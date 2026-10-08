"""Сервер «Осмотр ТС» v2: принимает осмотры, ведёт строки карточек ТС, шлёт уведомления."""
import json
import os
import threading
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from sessions import decide, normalize_plate, fmt_km
from supa import Supa, SupaError, make_thumbnail
from notify import (Telegram, escape_markdown, compress_image, is_valid_image,
                    analyze_photos_with_ai, compare_inspections_with_ai)

BOT_TOKEN = os.environ.get('BOT_TOKEN', '')
CHAT_ID = os.environ.get('CHAT_ID', '')
SUPABASE_URL = os.environ.get('SUPABASE_URL', '')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', '')
ANTHROPIC_KEY = os.environ.get('ANTHROPIC_KEY', '')
API_TOKEN = os.environ.get('API_TOKEN', '')
TELEGRAM_WEBHOOK_SECRET = os.environ.get('TELEGRAM_WEBHOOK_SECRET', '')
TELEGRAM_API = os.environ.get('TELEGRAM_API', '')          # только для тестов: подмена адреса Telegram
PORTAL_URL = os.environ.get('PORTAL_URL', '').rstrip('/')    # адрес сайта, например https://логин.github.io/car-inspection-v2/portal
APP_TZ = ZoneInfo(os.environ.get('APP_TIMEZONE', 'Europe/Minsk'))
ALLOWED_ORIGINS = [o.strip().rstrip('/').lower() for o in
                   os.environ.get('ALLOWED_ORIGINS', 'https://maximkazachenok-dev.github.io').split(',')
                   if o.strip()]

app = Flask(__name__)
CORS(app, origins=ALLOWED_ORIGINS)
limiter = Limiter(app=app, key_func=get_remote_address, default_limits=['2000 per day'])

db = Supa(SUPABASE_URL, SUPABASE_KEY)
tg = Telegram(BOT_TOKEN, CHAT_ID, api_base=TELEGRAM_API or None)

KIND_LABELS = {'acceptance': 'приёмка', 'return': 'сдача'}
CHECK_ICONS = {'ok': '✅', 'warn': '⚠️', 'bad': '🔴'}
CHECK_LABELS = {'ok': 'всё хорошо', 'warn': 'некритичные замечания', 'bad': 'критичные замечания'}


class SessionChanged(Exception):
    """Открытую строку успели закрыть, пока водитель оформлял сдачу."""


def authorized():
    return API_TOKEN and request.headers.get('X-App-Token', '') == API_TOKEN


def fail(message, status):
    return jsonify({'ok': False, 'error': message}), status


def to_int(value):
    value = (value or '').strip().replace(' ', '')
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def parse_json(value, default):
    try:
        return json.loads(value) if value else default
    except (TypeError, ValueError):
        return default


def local_dt(iso):
    return datetime.fromisoformat(str(iso).replace('Z', '+00:00')).astimezone(APP_TZ)


def card_link(vehicle_id):
    return f'{PORTAL_URL}/#/vehicle/{vehicle_id}' if PORTAL_URL else ''


def open_session_for(vehicle_id):
    rows = db.select('usage_sessions', {'vehicle_id': f'eq.{vehicle_id}', 'status': 'eq.open', 'limit': '1'})
    if not rows:
        return None
    s = rows[0]
    if s.get('driver_id'):
        d = db.select('drivers', {'id': f'eq.{s["driver_id"]}', 'select': 'full_name'})
        s['driver_name'] = d[0]['full_name'] if d else None
    return s


# ---------------------------------------------------------------------
@app.route('/', methods=['GET'])
def health():
    return 'OK', 200


@app.route('/api/directory', methods=['GET'])
@limiter.limit('600 per hour')
def directory():
    """Справочник для приложения водителя: ТС с текущим статусом и водители."""
    if not authorized():
        return fail('Unauthorized', 401)
    try:
        vehicles = db.select('v_vehicles', {
            'is_active': 'eq.true', 'order': 'plate',
            'select': 'id,plate,kind,model,open_session_id,open_driver_id,open_driver_name,open_since,'
                      'open_start_mileage,open_start_moto,last_return_mileage,last_return_moto'})
        drivers = db.select('drivers', {'is_active': 'eq.true', 'order': 'full_name', 'select': 'id,full_name'})
    except SupaError as e:
        print(f'Directory error: {e}')
        return fail('Не удалось загрузить справочник', 502)
    return jsonify({'ok': True, 'vehicles': vehicles, 'drivers': drivers})


@app.route('/submit', methods=['POST'])
@limiter.limit('60 per hour')
def submit():
    if not authorized():
        return fail('Unauthorized', 401)
    f = request.form
    vehicle_id = f.get('vehicle_id', '').strip()
    driver_id = f.get('driver_id', '').strip()
    kind = f.get('kind', '').strip()
    if not vehicle_id or not driver_id:
        return fail('Выберите ТС и водителя из списка. Если списка нет — обновите приложение.', 400)

    try:
        vehicle = (db.select('vehicles', {'id': f'eq.{vehicle_id}', 'is_active': 'eq.true'}) or [None])[0]
        driver = (db.select('drivers', {'id': f'eq.{driver_id}', 'is_active': 'eq.true'}) or [None])[0]
        if not vehicle:
            return fail('ТС не найдено в справочнике. Обновите список и выберите снова.', 400)
        if not driver:
            return fail('Водитель не найден в справочнике. Выберите себя снова.', 400)
        open_session = open_session_for(vehicle_id)
    except SupaError as e:
        print(f'Submit lookup error: {e}')
        return fail('База данных недоступна. Попробуйте позже.', 502)

    mileage = to_int(f.get('mileage')) if vehicle['kind'] == 'truck' else None
    moto_hours = to_int(f.get('moto_hours'))
    decision = decide(kind, vehicle['kind'], open_session, driver_id, mileage, moto_hours)
    if decision.action == 'reject':
        return fail(decision.message, decision.http_status)

    # Время осмотра — с телефона; если его нет или оно некорректно — время сервера
    try:
        inspected_at = datetime.fromisoformat(f.get('inspected_at', '').replace('Z', '+00:00'))
        if inspected_at.tzinfo is None:
            inspected_at = inspected_at.replace(tzinfo=APP_TZ)
    except ValueError:
        inspected_at = datetime.now(timezone.utc)
    inspected_iso = inspected_at.isoformat()

    # Фото
    photos = []  # (подпись, байты)
    for i in range(to_int(f.get('photo_count')) or 0):
        file = request.files.get(f'photo_{i}')
        if not file:
            continue
        fb = file.read()
        if fb and len(fb) >= 100 and is_valid_image(fb):
            if len(fb) > 1500 * 1024:
                fb = compress_image(fb)
            photos.append((f.get(f'photo_label_{i}', f'Фото {i + 1}').strip() or f'Фото {i + 1}', fb))
    if not photos:
        return fail('Нет фотографий', 400)

    checks = [c for c in parse_json(f.get('checks'), []) if isinstance(c, dict) and c.get('status') in CHECK_ICONS]
    extra = parse_json(f.get('extra'), {})
    if not isinstance(extra, dict):
        extra = {}
    doc_status = f.get('doc_status', '').strip() or None
    if doc_status not in CHECK_ICONS:
        doc_status = None

    inspection_id = str(uuid.uuid4())
    uploaded = []
    try:
        photo_rows = []
        for i, (label, fb) in enumerate(photos):
            base = f'{vehicle_id}/{inspection_id}/{i:02d}'
            path = db.upload(f'{base}.jpg', fb)
            uploaded.append(path)
            thumb = db.upload(f'{base}_thumb.jpg', make_thumbnail(fb))
            uploaded.append(thumb)
            photo_rows.append({'inspection_id': inspection_id, 'label': label, 'sort': i,
                               'path': path, 'thumb_path': thumb})

        db.insert('inspections', {
            'id': inspection_id, 'vehicle_id': vehicle_id, 'driver_id': driver_id, 'kind': kind,
            'inspected_at': inspected_iso, 'mileage': mileage, 'moto_hours': moto_hours,
            'trailer_type': f.get('trailer_type', '').strip() or None,
            'doc_status': doc_status, 'doc_comment': f.get('doc_comment', '').strip() or None,
            'voice_notes': f.get('voice_notes', '').strip() or None, 'extra': extra,
            'ai_status': 'pending' if ANTHROPIC_KEY else 'none',
        })
        db.insert('inspection_photos', photo_rows)
        if checks:
            db.insert('inspection_checks', [{
                'inspection_id': inspection_id, 'item_key': str(c.get('key', ''))[:100],
                'label': str(c.get('label', ''))[:200], 'status': c['status'],
                'comment': (str(c.get('comment') or '').strip() or None)} for c in checks])

        # Строка карточки ТС
        if decision.action == 'open':
            session = db.insert('usage_sessions', {
                'vehicle_id': vehicle_id, 'driver_id': driver_id, 'start_inspection_id': inspection_id,
                'started_at': inspected_iso, 'start_mileage': mileage, 'start_moto': moto_hours,
                'status': 'open'})[0]
        elif decision.action == 'close':
            updated = db.update('usage_sessions',
                                {'id': f'eq.{open_session["id"]}', 'status': 'eq.open'},
                                {'return_driver_id': driver_id, 'end_inspection_id': inspection_id,
                                 'ended_at': inspected_iso, 'end_mileage': mileage, 'end_moto': moto_hours,
                                 'status': 'closed', 'flags': decision.flags})
            if not updated:
                raise SessionChanged()
            session = updated[0]
        else:  # closed_no_acceptance
            session = db.insert('usage_sessions', {
                'vehicle_id': vehicle_id, 'return_driver_id': driver_id, 'end_inspection_id': inspection_id,
                'ended_at': inspected_iso, 'end_mileage': mileage, 'end_moto': moto_hours,
                'status': 'closed', 'flags': decision.flags})[0]
        db.update('inspections', {'id': f'eq.{inspection_id}'}, {'session_id': session['id']})

    except (SupaError, SessionChanged) as e:
        print(f'Submit save error: {e}')
        # Откат: осмотр (вместе с фото и ТМЦ в базе) и файлы фото удаляются
        try:
            db.delete('inspections', {'id': f'eq.{inspection_id}'})
            db.remove(uploaded)
        except Exception as cleanup_error:
            print(f'Rollback error: {cleanup_error}')
        if isinstance(e, SessionChanged):
            return fail('Строка этого ТС изменилась (её мог закрыть администратор). '
                        'Обновите список и отправьте осмотр снова.', 409)
        if e.is_unique_violation:
            return fail('Это ТС только что принял другой водитель. Обновите список и проверьте статус.', 409)
        return fail('Не удалось сохранить осмотр. Попробуйте ещё раз.', 502)

    threading.Thread(target=notify_background, daemon=True, kwargs=dict(
        inspection_id=inspection_id, vehicle=vehicle, driver=driver, kind=kind, inspected_at=inspected_at,
        mileage=mileage, moto_hours=moto_hours, decision=decision, photos=photos, checks=checks,
        extra=extra, doc_status=doc_status, form=f.to_dict())).start()

    return jsonify({'ok': True, 'session_id': session['id'], 'distance': decision.distance,
                    'moto_delta': decision.moto_delta, 'flags': decision.flags})


def build_caption(vehicle, driver, kind, inspected_at, mileage, moto_hours, decision, checks, extra,
                  doc_status, form):
    lines = [
        f'🚛 *ОСМОТР ТРАНСПОРТНОГО СРЕДСТВА*', '',
        f'👤 {escape_markdown(driver["full_name"])}',
        f'🔢 {escape_markdown(vehicle["plate"])}',
        f'📋 {KIND_LABELS.get(kind, kind).upper()}',
        f'📅 {local_dt(inspected_at.isoformat()).strftime("%d.%m.%Y %H:%M")}',
    ]
    if mileage is not None:
        lines.append(f'🛣 Пробег: {fmt_km(mileage)} км')
    if decision.distance is not None:
        lines.append(f'➡️ Пройдено: {fmt_km(decision.distance)} км')
    if form.get('trailer_type'):
        lines.append(f'🚚 Тип прицепа: {escape_markdown(form["trailer_type"]).upper()}')
    if moto_hours is not None:
        lines.append(f'⏱ Мото-часы ДВС: {moto_hours} м/ч')
    if 'other_driver' in decision.flags:
        lines.append('⚠️ Сдал другой водитель')
    if 'no_acceptance' in decision.flags:
        lines.append('⚠️ Сдача без приёмки')
    for label, value in extra.items():
        lines.append(f'{escape_markdown(str(label))}: {escape_markdown(str(value))}')
    if doc_status:
        doc = f'📋 Документы: {CHECK_ICONS[doc_status]} {CHECK_LABELS[doc_status]}'
        if form.get('doc_comment'):
            doc += f' — {escape_markdown(form["doc_comment"])}'
        lines.append(doc)
    if checks:
        lines += ['', '📦 *ТМЦ:*'] + [
            f'{CHECK_ICONS[c["status"]]} {escape_markdown(str(c.get("label", "")))}' +
            (f' — {escape_markdown(str(c["comment"]))}' if c.get('comment') else '') for c in checks]
    if form.get('voice_notes'):
        lines += ['', f'🗣 *Замечания:* {escape_markdown(form["voice_notes"])}']
    link = card_link(vehicle['id'])
    if link:
        lines += ['', f'🔗 Карточка ТС: {link}']
    return '\n'.join(lines)


def notify_background(inspection_id, vehicle, driver, kind, inspected_at, mileage, moto_hours, decision,
                      photos, checks, extra, doc_status, form):
    try:
        caption = build_caption(vehicle, driver, kind, inspected_at, mileage, moto_hours, decision,
                                checks, extra, doc_status, form)
        if (BOT_TOKEN and CHAT_ID) or TELEGRAM_API:
            tg.send_album(photos, caption)
        if ANTHROPIC_KEY:
            report = analyze_photos_with_ai(ANTHROPIC_KEY, photos)
            db.update('inspections', {'id': f'eq.{inspection_id}'},
                      {'ai_status': 'done' if report else 'error', 'ai_report': report})
            if report and ((BOT_TOKEN and CHAT_ID) or TELEGRAM_API):
                clean = '\n'.join(l for l in report.split('\n') if l.strip())
                header = (f'🤖 *АНАЛИЗ AI-ПОМОЩНИКА* — {escape_markdown(vehicle["plate"])} • '
                          f'{KIND_LABELS.get(kind, kind)} • {local_dt(inspected_at.isoformat()).strftime("%d.%m.%Y")}')
                tg.send_message(CHAT_ID, header + '\n\n' + clean)
    except Exception as e:
        print(f'Background error: {e}')
        import traceback
        traceback.print_exc()


# ---------------------------------------------------------------------
def find_inspection(vehicle_id, date_str):
    """Последний осмотр ТС за дату ДД.ММ.ГГГГ (по местному времени)."""
    try:
        day = datetime.strptime(date_str, '%d.%m.%Y').date()
    except ValueError:
        return None
    rows = db.select('inspections', {'vehicle_id': f'eq.{vehicle_id}', 'order': 'inspected_at.desc',
                                     'limit': '200', 'select': 'id,inspected_at'})
    for r in rows:
        if local_dt(r['inspected_at']).date() == day:
            return r
    return None


def inspection_photos(inspection_id):
    rows = db.select('inspection_photos', {'inspection_id': f'eq.{inspection_id}', 'order': 'sort'})
    return [(r['label'], db.download(r['path'])) for r in rows]


@app.route('/webhook', methods=['POST'])
@limiter.limit('60 per hour')
def webhook():
    if TELEGRAM_WEBHOOK_SECRET and request.headers.get('X-Telegram-Bot-Api-Secret-Token', '') != TELEGRAM_WEBHOOK_SECRET:
        return jsonify({'ok': False}), 401
    try:
        message = (request.json or {}).get('message', {})
        text = message.get('text', '').strip()
        chat_id = message.get('chat', {}).get('id')
        if not text or not chat_id or not text.lower().startswith('сравни'):
            return jsonify({'ok': True})
        usage = '⚠️ Формат: `сравни АХ5463-5 01.05.2026 и 01.04.2026`'
        parts = text.split()
        if len(parts) < 5 or 'и' not in parts:
            tg.send_message(chat_id, usage)
            return jsonify({'ok': True})
        plate, idx = parts[1], parts.index('и')
        date1 = parts[2] if idx > 2 else None
        date2 = parts[idx + 1] if idx + 1 < len(parts) else None
        if not date1 or not date2:
            tg.send_message(chat_id, usage)
            return jsonify({'ok': True})
        vehicles = db.select('vehicles', {'plate_norm': f'eq.{normalize_plate(plate)}'})
        if not vehicles:
            tg.send_message(chat_id, f'❌ ТС {escape_markdown(plate)} не найдено в справочнике.')
            return jsonify({'ok': True})
        vehicle = vehicles[0]
        tg.send_message(chat_id, f'🔍 Ищу осмотры {escape_markdown(vehicle["plate"])}...')
        insp1, insp2 = find_inspection(vehicle['id'], date1), find_inspection(vehicle['id'], date2)
        for insp, d in ((insp1, date1), (insp2, date2)):
            if not insp:
                tg.send_message(chat_id, f'❌ Осмотр {escape_markdown(vehicle["plate"])} от {d} не найден.')
                return jsonify({'ok': True})
        tg.send_message(chat_id, '🤖 Анализирую фото, подождите...')
        older, newer = sorted([(insp1, date1), (insp2, date2)], key=lambda x: x[0]['inspected_at'])
        result = compare_inspections_with_ai(
            ANTHROPIC_KEY, vehicle['plate'],
            {'date': older[1], 'photos': inspection_photos(older[0]['id'])},
            {'date': newer[1], 'photos': inspection_photos(newer[0]['id'])})
        tg.send_message(chat_id, f'🔄 *СРАВНЕНИЕ {escape_markdown(vehicle["plate"])}*\n'
                                 f'📅 {older[1]} → {newer[1]}\n\n{result}')
        link = card_link(vehicle['id'])
        if link:
            tg.send_message(chat_id, f'🔗 Карточка ТС: {link}', markdown=False)
    except Exception as e:
        print(f'Webhook error: {e}')
    return jsonify({'ok': True})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
