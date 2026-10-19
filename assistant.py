"""ИИ-помощник сайта «Карточки ТС»: отвечает на вопросы администратора по данным осмотров.

ИИ сам ничего не знает о базе: он вызывает инструменты (поиск ТС, осмотров, замечаний, просмотр фото),
сервер выполняет их и возвращает данные, ИИ составляет ответ. Доступ к базе — только на чтение,
кроме сохранения анализа ИИ по фото в осмотр.
"""
import json
import time
from datetime import date, datetime, timedelta, timezone

import anthropic

from notify import analyze_photos_with_ai, image_block
from sessions import normalize_plate

DEFAULT_MODEL = 'claude-opus-5-5'
# Модели, с которыми помощник работает: они понимают все части запроса (инструменты, effort,
# системные сообщения посреди разговора). Выбирается переменной ASSISTANT_MODEL в Railway.
SUPPORTED_MODELS = ('claude-opus-5-5', 'claude-sonnet-5-5', 'claude-haiku-5-5', 'claude-opus-5', 'claude-fable-5-1')
# У этих моделей сервис ИИ сам повторяет вопрос на запасной модели, если основная отказалась отвечать
FALLBACK_MODELS = ('claude-opus-5-5', 'claude-sonnet-5-5', 'claude-opus-5', 'claude-fable-5-1')
MAX_STEPS = 10           # обращений к ИИ на один вопрос
DEADLINE_S = 100         # после этого ИИ отвечает по уже собранным данным (gunicorn ждёт 180 с)
MAX_HISTORY = 20         # сообщений переписки, которые сайт присылает вместе с вопросом
MAX_MESSAGE_CHARS = 8000
MAX_PHOTOS = 12          # фото за один вызов view_photos

KIND_RU = {'acceptance': 'приёмка', 'return': 'сдача'}
VEHICLE_KIND_RU = {'truck': 'автомобиль', 'trailer': 'прицеп'}
STATUS_RU = {'ok': 'всё хорошо', 'warn': 'некритичное замечание (?)', 'bad': 'критичное замечание (!)'}
WEEKDAYS = ['понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота', 'воскресенье']


class AssistantError(Exception):
    """Ошибка в запросе к помощнику, которую можно показать пользователю."""


def pick_model(value):
    """Модель из настройки ASSISTANT_MODEL: (модель, предупреждение или None). Ошибка в названии не ломает чат."""
    value = (value or '').strip()
    if not value:
        return DEFAULT_MODEL, None
    if value in SUPPORTED_MODELS:
        return value, None
    return DEFAULT_MODEL, f'«{value}» не поддерживается, работает {DEFAULT_MODEL}. Можно: {", ".join(SUPPORTED_MODELS)}'


SYSTEM_PROMPT = """Ты — ИИ-помощник администратора сайта «Карточки ТС» транспортной компании. Администратор \
спрашивает об осмотрах машин и прицепов; данные бери только из инструментов и не выдумывай того, чего в них нет.

Как устроены данные:
- ТС бывают двух типов: автомобиль (тягач, пробег в км) и прицеп (тип: тент, изотерма или реф; у рефа моточасы).
- Осмотр — приёмка (водитель забирает ТС) или сдача (возвращает). Период от приёмки до сдачи — строка карточки ТС.
- В осмотре водитель оценивает «Проверку документов» и пункты ТМЦ (огнетушитель, аптечка, знак аварийной \
остановки и др.) одной из трёх оценок: ok — «всё хорошо» (галочка), warn — «некритичное замечание» (в приложении \
значок «?», администраторы называют это «стоит вопрос»), bad — «критичное замечание» (значок «!»). \
К оценке можно добавить комментарий.
- Замечание по документам обычно значит, что скоро заканчивается техосмотр, страховка или другой документ; \
подробности — в комментарии. Если комментария нет, прямо скажи, что причина не указана.
- «Замечания водителя» — свободный текст, надиктованный или набранный при осмотре.
- «Анализ ИИ» — отчёт о видимых повреждениях по фото, сохранённый в осмотре (если его запускали).
- Текущее состояние ТС определяется по его последнему осмотру.

Даты: пользователь пишет ДД.ММ.ГГ или ДД.ММ.ГГГГ («13.10.26» — 13 октября 2026). В инструменты передавай даты \
в виде ГГГГ-ММ-ДД. Время — по Минску. Номера ТС можно писать кириллицей или латиницей, с пробелами и без.

Как работать:
- Сравнение осмотров: найди осмотры за указанные даты (get_inspections), сравни показания, документы, ТМЦ и \
замечания, затем посмотри фото обоих осмотров (view_photos) и по каждому ракурсу скажи, что изменилось: новые \
повреждения, исчезнувшие, без изменений. Если за дату несколько осмотров, выбери подходящие и скажи, какие взял. \
Отличай повреждения от бликов, грязи, снега и другого ракурса; если не уверен — так и напиши.
- Списки ТС с замечаниями — find_remarks. Для вопросов о текущем положении бери scope=current.
- Если ТС не найдено, предложи похожие номера из ответа инструмента.
- run_damage_analysis вызывай, только когда пользователь просит запустить или сохранить анализ ИИ по фото: \
результат записывается в карточку ТС.

Формат ответа: Markdown — короткие абзацы, списки, **жирный**, таблицы для списков ТС. Номер ТС оформляй \
ссылкой на карточку из поля card: [3134КМ-2](#/vehicle/…). Даты пиши как ДД.ММ.ГГГГ. Внутренние \
идентификаторы осмотров не показывай. Отвечай по-русски, по делу, без вступлений."""


TOOLS = [
    {
        'name': 'find_vehicles',
        'description': 'Список ТС из справочника с текущим статусом (на линии у водителя или свободно), '
                       'последним пробегом и датой последнего осмотра. Можно искать по части номера или модели.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'query': {'type': 'string', 'description': 'Часть номера или модели; пусто — все ТС'},
                'kind': {'type': 'string', 'enum': ['all', 'truck', 'trailer']},
                'status': {'type': 'string', 'enum': ['all', 'on_line', 'free']},
                'include_inactive': {'type': 'boolean', 'description': 'Показывать отключённые ТС'},
            },
            'additionalProperties': False,
        },
    },
    {
        'name': 'get_inspections',
        'description': 'Осмотры одного ТС с полными данными: тип, водитель, пробег, моточасы, документы, ТМЦ, '
                       'замечания водителя, анализ ИИ, список фото. Новые сверху. Без дат — последние осмотры.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'plate': {'type': 'string', 'description': 'Гос. номер ТС'},
                'date_from': {'type': 'string', 'description': 'ГГГГ-ММ-ДД, включительно'},
                'date_to': {'type': 'string', 'description': 'ГГГГ-ММ-ДД, включительно'},
                'kind': {'type': 'string', 'enum': ['any', 'acceptance', 'return']},
                'limit': {'type': 'integer', 'minimum': 1, 'maximum': 20, 'description': 'По умолчанию 10'},
            },
            'required': ['plate'],
            'additionalProperties': False,
        },
    },
    {
        'name': 'find_remarks',
        'description': 'ТС, у которых в осмотрах есть замечания: по документам, по ТМЦ, замечания водителя. '
                       'scope=current — только последний осмотр каждого ТС (текущее состояние); '
                       'scope=period — все осмотры за даты date_from..date_to.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'scope': {'type': 'string', 'enum': ['current', 'period']},
                'date_from': {'type': 'string', 'description': 'ГГГГ-ММ-ДД, для scope=period'},
                'date_to': {'type': 'string', 'description': 'ГГГГ-ММ-ДД, для scope=period'},
                'severity': {'type': 'string', 'enum': ['any', 'critical'],
                             'description': 'any — некритичные и критичные, critical — только критичные'},
                'area': {'type': 'string', 'enum': ['all', 'documents', 'tmc', 'driver_notes']},
            },
            'required': ['scope'],
            'additionalProperties': False,
        },
    },
    {
        'name': 'view_photos',
        'description': 'Показывает фото осмотров, чтобы ты сам их рассмотрел (например, для сравнения состояния). '
                       'До 4 осмотров и до 12 фото за раз. Идентификаторы осмотров бери из get_inspections.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'inspection_ids': {'type': 'array', 'items': {'type': 'string'}, 'minItems': 1, 'maxItems': 4},
                'labels': {'type': 'array', 'items': {'type': 'string'},
                           'description': 'Только эти ракурсы (например «Спереди»); пусто — все'},
            },
            'required': ['inspection_ids'],
            'additionalProperties': False,
        },
    },
    {
        'name': 'run_damage_analysis',
        'description': 'Запускает анализ повреждений по фото одного осмотра и сохраняет отчёт в карточку ТС. '
                       'Только по просьбе пользователя.',
        'input_schema': {
            'type': 'object',
            'properties': {'inspection_id': {'type': 'string'}},
            'required': ['inspection_id'],
            'additionalProperties': False,
        },
    },
]


def analyze_inspection(db, api_key, inspection_id):
    """Анализ ИИ по фото осмотра с сохранением в базу. Возвращает (статус, отчёт)."""
    if not db.select('inspections', {'id': f'eq.{inspection_id}', 'select': 'id'}):
        raise AssistantError('Осмотр не найден')
    rows = db.select('inspection_photos', {'inspection_id': f'eq.{inspection_id}', 'order': 'sort'})
    photos = [(r['label'], db.download(r['path'])) for r in rows]
    if not photos:
        raise AssistantError('У осмотра нет фото')
    db.update('inspections', {'id': f'eq.{inspection_id}'}, {'ai_status': 'pending'})
    report = analyze_photos_with_ai(api_key, photos)
    status = 'done' if report else 'error'
    db.update('inspections', {'id': f'eq.{inspection_id}'}, {'ai_status': status, 'ai_report': report})
    return status, report


class Assistant:
    def __init__(self, db, api_key, tz, model=DEFAULT_MODEL):
        self.db = db
        self.api_key = api_key
        self.tz = tz
        self.model = model
        self._drivers = None
        self._vehicles = None

    # ---------- вспомогательное ----------
    def local(self, iso):
        return datetime.fromisoformat(str(iso).replace('Z', '+00:00')).astimezone(self.tz)

    def fmt_dt(self, iso):
        return self.local(iso).strftime('%d.%m.%Y %H:%M') if iso else None

    def day_bounds(self, date_from, date_to):
        """Границы периода по местному времени → UTC для запроса к базе."""
        def parse(s, name):
            try:
                return date.fromisoformat(str(s).strip())
            except ValueError:
                raise AssistantError(f'{name}: дата должна быть в виде ГГГГ-ММ-ДД, получено «{s}»')
        start = parse(date_from, 'date_from') if date_from else None
        end = parse(date_to, 'date_to') if date_to else None
        to_utc = lambda d: datetime.combine(d, datetime.min.time(), self.tz).astimezone(timezone.utc).strftime(
            '%Y-%m-%dT%H:%M:%SZ')
        filters = []
        if start:
            filters.append(f'gte.{to_utc(start)}')
        if end:
            filters.append(f'lt.{to_utc(end + timedelta(days=1))}')
        return filters

    def drivers(self):
        if self._drivers is None:
            self._drivers = {d['id']: d['full_name'] for d in self.db.select('drivers', {'select': 'id,full_name'})}
        return self._drivers

    def vehicles(self):
        if self._vehicles is None:
            self._vehicles = {v['id']: v for v in self.db.select('v_vehicles', {'order': 'plate'})}
        return self._vehicles

    @staticmethod
    def card(vehicle_id):
        return f'#/vehicle/{vehicle_id}'

    def find_vehicle(self, plate):
        """ТС по номеру; если точного совпадения нет — AssistantError со списком похожих."""
        norm = normalize_plate(plate)
        if not norm:
            raise AssistantError('Не указан номер ТС')
        exact = [v for v in self.vehicles().values() if v['plate_norm'] == norm]
        if exact:
            return exact[0]
        similar = [v['plate'] for v in self.vehicles().values()
                   if norm in v['plate_norm'] or v['plate_norm'] in norm or norm[:4] == v['plate_norm'][:4]]
        hint = f' Похожие номера: {", ".join(similar[:10])}.' if similar else ' Похожих номеров нет.'
        raise AssistantError(f'ТС «{plate}» нет в справочнике.{hint}')

    def checks_for(self, inspection_ids, statuses=None):
        """Пункты ТМЦ по осмотрам: {inspection_id: [check, ...]}."""
        out = {}
        ids = list(inspection_ids)
        for i in range(0, len(ids), 100):  # длина адреса запроса ограничена
            params = {'inspection_id': f'in.({",".join(ids[i:i + 100])})'}
            if statuses:
                params['status'] = f'in.({",".join(statuses)})'
            for c in self.db.select_all('inspection_checks', params):
                out.setdefault(c['inspection_id'], []).append(c)
        return out

    def describe(self, insp, checks, full=True):
        """Осмотр в виде, понятном ИИ."""
        d = {
            'inspection_id': insp['id'],
            'date': self.fmt_dt(insp['inspected_at']),
            'kind': KIND_RU.get(insp['kind'], insp['kind']),
            'driver': self.drivers().get(insp.get('driver_id')),
        }
        if insp.get('mileage') is not None:
            d['mileage_km'] = insp['mileage']
        if insp.get('moto_hours') is not None:
            d['moto_hours'] = insp['moto_hours']
        if insp.get('trailer_type'):
            d['trailer_type'] = insp['trailer_type']
        if insp.get('doc_status'):
            d['documents'] = {'status': STATUS_RU[insp['doc_status']], 'comment': insp.get('doc_comment')}
        if checks:
            d['tmc'] = [{'item': c['label'], 'status': STATUS_RU.get(c['status'], c['status']),
                         'comment': c.get('comment')} for c in checks]
        if insp.get('voice_notes'):
            d['driver_notes'] = insp['voice_notes']
        if full:
            if insp.get('extra'):
                d['extra_fields'] = insp['extra']
            d['ai_analysis'] = {'none': 'не запускался', 'pending': 'выполняется', 'error': 'не удался',
                                'done': insp.get('ai_report')}.get(insp.get('ai_status'), insp.get('ai_status'))
        return d

    # ---------- инструменты ----------
    def tool_find_vehicles(self, query='', kind='all', status='all', include_inactive=False):
        q, nq = (query or '').strip().lower(), normalize_plate(query or '')
        out = []
        for v in self.vehicles().values():
            if not include_inactive and not v.get('is_active'):
                continue
            if kind in ('truck', 'trailer') and v['kind'] != kind:
                continue
            on_line = bool(v.get('open_session_id'))
            if (status == 'on_line' and not on_line) or (status == 'free' and on_line):
                continue
            if q and not ((nq and nq in v['plate_norm']) or q in str(v.get('model') or '').lower()):
                continue
            item = {'plate': v['plate'], 'card': self.card(v['id']), 'type': VEHICLE_KIND_RU.get(v['kind']),
                    'model': v.get('model'), 'status': 'на линии' if on_line else 'свободно'}
            if on_line:
                item['driver'] = v.get('open_driver_name')
                item['since'] = self.fmt_dt(v.get('open_since'))
            if v.get('last_mileage') is not None:
                item['last_mileage_km'] = v['last_mileage']
            item['last_inspection'] = self.fmt_dt(v.get('last_inspection_at'))
            if not v.get('is_active'):
                item['inactive'] = True
            out.append(item)
        return {'count': len(out), 'vehicles': out[:300]}

    def tool_get_inspections(self, plate, date_from=None, date_to=None, kind='any', limit=10):
        v = self.find_vehicle(plate)
        limit = max(1, min(int(limit or 10), 20))
        params = {'vehicle_id': f'eq.{v["id"]}', 'order': 'inspected_at.desc', 'limit': str(limit)}
        period = self.day_bounds(date_from, date_to)
        if period:
            params['inspected_at'] = period
        if kind in ('acceptance', 'return'):
            params['kind'] = f'eq.{kind}'
        insps = self.db.select('inspections', params)
        checks = self.checks_for([i['id'] for i in insps]) if insps else {}
        labels = {}
        if insps:
            for p in self.db.select('inspection_photos', {
                    'inspection_id': f'in.({",".join(i["id"] for i in insps)})', 'order': 'sort',
                    'select': 'inspection_id,label'}):
                labels.setdefault(p['inspection_id'], []).append(p['label'])
        result = []
        for i in insps:
            d = self.describe(i, checks.get(i['id']))
            d['photos'] = labels.get(i['id'], [])
            result.append(d)
        return {'vehicle': {'plate': v['plate'], 'card': self.card(v['id']), 'type': VEHICLE_KIND_RU.get(v['kind']),
                            'model': v.get('model')},
                'count': len(result), 'inspections': result,
                'note': None if result else 'За указанный период осмотров нет'}

    def tool_find_remarks(self, scope='current', date_from=None, date_to=None, severity='any', area='all'):
        statuses = ['bad'] if severity == 'critical' else ['warn', 'bad']
        if scope == 'period':
            period = self.day_bounds(date_from, date_to)
            if not period:
                raise AssistantError('Для scope=period укажите date_from и/или date_to')
            insps = self.db.select_all('inspections', {'inspected_at': period, 'order': 'inspected_at.desc'})
        else:
            insps = self.db.select_all('v_last_inspections', {'order': 'inspected_at.desc'})
        checks = self.checks_for([i['id'] for i in insps], statuses) if area in ('all', 'tmc') and insps else {}

        by_vehicle = {}
        for i in insps:
            docs = area in ('all', 'documents') and i.get('doc_status') in statuses
            tmc = checks.get(i['id'], []) if area in ('all', 'tmc') else []
            notes = area in ('all', 'driver_notes') and severity == 'any' and bool(i.get('voice_notes'))
            if not (docs or tmc or notes):
                continue
            d = {'inspection_id': i['id'], 'date': self.fmt_dt(i['inspected_at']),
                 'kind': KIND_RU.get(i['kind']), 'driver': self.drivers().get(i.get('driver_id'))}
            if docs:
                d['documents'] = {'status': STATUS_RU[i['doc_status']], 'comment': i.get('doc_comment')}
            if tmc:
                d['tmc'] = [{'item': c['label'], 'status': STATUS_RU[c['status']], 'comment': c.get('comment')}
                            for c in tmc]
            if notes:
                d['driver_notes'] = i['voice_notes']
            by_vehicle.setdefault(i['vehicle_id'], []).append(d)

        vehicles = []
        for vid, items in by_vehicle.items():
            v = self.vehicles().get(vid, {})
            vehicles.append({'plate': v.get('plate'), 'card': self.card(vid), 'type': VEHICLE_KIND_RU.get(v.get('kind')),
                             'inactive': not v.get('is_active', True) or None, 'inspections': items})
        vehicles.sort(key=lambda x: x['plate'] or '')
        return {'scope': 'последний осмотр каждого ТС' if scope != 'period' else 'осмотры за период',
                'inspections_checked': len(insps), 'vehicles_with_remarks': len(vehicles), 'vehicles': vehicles}

    def tool_view_photos(self, inspection_ids, labels=None):
        ids = [str(x) for x in inspection_ids][:4]
        insps = {i['id']: i for i in self.db.select('inspections', {'id': f'in.({",".join(ids)})'})}
        if not insps:
            raise AssistantError('Осмотры не найдены')
        rows = self.db.select('inspection_photos', {'inspection_id': f'in.({",".join(insps)})', 'order': 'sort'})
        wanted = {l.strip().lower() for l in (labels or []) if l.strip()}
        if wanted:
            rows = [r for r in rows if r['label'].strip().lower() in wanted]
        rows.sort(key=lambda r: (ids.index(r['inspection_id']) if r['inspection_id'] in ids else 9, r['sort']))
        skipped = max(0, len(rows) - MAX_PHOTOS)
        content = []
        for r in rows[:MAX_PHOTOS]:
            i = insps[r['inspection_id']]
            v = self.vehicles().get(i['vehicle_id'], {})
            content.append({'type': 'text', 'text': f'{v.get("plate", "")} · {KIND_RU.get(i["kind"])} '
                                                    f'{self.fmt_dt(i["inspected_at"])} · ракурс «{r["label"]}»'})
            content.append(image_block(self.db.download(r['path']), max_dimension=1280, max_size_kb=700))
        if not content:
            return [{'type': 'text', 'text': 'У этих осмотров нет фото с такими ракурсами.'}]
        if skipped:
            content.append({'type': 'text', 'text': f'Ещё {skipped} фото не показаны: запросите их отдельно.'})
        return content

    def tool_run_damage_analysis(self, inspection_id):
        status, report = analyze_inspection(self.db, self.api_key, inspection_id)
        return {'saved_to_card': status == 'done', 'report': report or 'ИИ не вернул отчёт'}

    def run_tool(self, name, args):
        """Возвращает (содержимое результата, ошибка ли это)."""
        fn = getattr(self, f'tool_{name}', None)
        if not fn:
            return f'Неизвестный инструмент {name}', True
        try:
            result = fn(**(args or {}))
        except AssistantError as e:
            return str(e), True
        except TypeError as e:
            return f'Неверные параметры: {e}', True
        if isinstance(result, list):
            return result, False
        return json.dumps(result, ensure_ascii=False, default=str), False

    # ---------- разговор ----------
    def system(self):
        now = datetime.now(self.tz)
        return [{'type': 'text', 'text': SYSTEM_PROMPT},
                {'type': 'text', 'text': f'Сегодня {now:%d.%m.%Y}, {WEEKDAYS[now.weekday()]}, {now:%H:%M} по Минску.'}]

    @staticmethod
    def clean_history(history):
        """Переписка с сайта: только текст, роли чередуются, первое и последнее — от пользователя."""
        if not isinstance(history, list):
            raise AssistantError('Пустой запрос')
        msgs = []
        for m in history[-MAX_HISTORY:]:
            if not isinstance(m, dict) or m.get('role') not in ('user', 'assistant'):
                continue
            text = str(m.get('content') or '').strip()[:MAX_MESSAGE_CHARS]
            if not text:
                continue
            if msgs and msgs[-1]['role'] == m['role']:
                msgs[-1]['content'] += '\n\n' + text
            else:
                msgs.append({'role': m['role'], 'content': text})
        while msgs and msgs[0]['role'] != 'user':
            msgs.pop(0)
        if not msgs or msgs[-1]['role'] != 'user':
            raise AssistantError('Напишите вопрос')
        return msgs

    def chat(self, history):
        messages = self.clean_history(history)
        client = anthropic.Anthropic(api_key=self.api_key, timeout=75, max_retries=1)
        started = time.monotonic()
        steps, usage = [], {'input': 0, 'output': 0, 'cache_read': 0}
        finish = False
        fallback = ({'betas': ['server-side-fallback-2026-07-01'], 'fallbacks': 'default'}
                    if self.model in FALLBACK_MODELS else {})
        for step in range(MAX_STEPS + 1):
            resp = client.beta.messages.create(
                model=self.model, max_tokens=16000, system=self.system(), tools=TOOLS, messages=messages,
                tool_choice={'type': 'none'} if finish else {'type': 'auto'},
                output_config={'effort': 'medium'}, cache_control={'type': 'ephemeral'}, **fallback)
            usage['input'] += resp.usage.input_tokens or 0
            usage['output'] += resp.usage.output_tokens or 0
            usage['cache_read'] += getattr(resp.usage, 'cache_read_input_tokens', 0) or 0
            if resp.stop_reason == 'refusal':
                return {'answer': 'ИИ отказался отвечать на этот запрос. Попробуйте сформулировать его иначе.',
                        'steps': steps, 'usage': usage, 'model': self.model}
            tool_uses = [b for b in resp.content if b.type == 'tool_use']
            if not tool_uses or finish:
                break
            messages.append({'role': 'assistant', 'content': resp.content})
            results = []
            for t in tool_uses:
                steps.append(step_label(t.name, t.input))
                content, is_error = self.run_tool(t.name, t.input)
                results.append({'type': 'tool_result', 'tool_use_id': t.id, 'content': content, 'is_error': is_error})
            messages.append({'role': 'user', 'content': results})
            if step + 1 >= MAX_STEPS or time.monotonic() - started > DEADLINE_S:
                finish = True
                messages.append({'role': 'system', 'content': 'Время на поиск закончилось. Ответь по уже '
                                 'собранным данным и скажи, чего не успел проверить.'})
        answer = '\n\n'.join(b.text for b in resp.content if b.type == 'text').strip()
        if resp.stop_reason == 'max_tokens':
            answer += '\n\n_(Ответ оборвался: слишком длинный. Уточните вопрос.)_'
        print(f'Assistant ({self.model}): {len(steps)} steps, usage {usage}, {time.monotonic() - started:.1f}s')
        return {'answer': answer or 'Пустой ответ ИИ. Повторите вопрос.', 'steps': steps, 'usage': usage,
                'model': self.model}


def step_label(name, args):
    """Что делал помощник — показывается на сайте под ответом."""
    args = args or {}
    period = ' – '.join(x for x in (args.get('date_from'), args.get('date_to')) if x)
    if name == 'find_vehicles':
        return 'Список ТС' + (f' «{args["query"]}»' if args.get('query') else '')
    if name == 'get_inspections':
        return f'Осмотры {args.get("plate", "")}' + (f' за {period}' if period else '')
    if name == 'find_remarks':
        return 'Поиск замечаний' + (f' за {period}' if period else ' (текущее состояние)')
    if name == 'view_photos':
        return f'Просмотр фото ({len(args.get("inspection_ids") or [])} осм.)'
    if name == 'run_damage_analysis':
        return 'Анализ повреждений по фото'
    return name
