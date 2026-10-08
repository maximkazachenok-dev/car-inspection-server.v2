"""Telegram-уведомления и ИИ-анализ фото (перенесено из прежнего server.py)."""
import base64
import json
from io import BytesIO

import requests
from PIL import Image


def escape_markdown(text):
    """Экранирует спецсимволы Markdown в пользовательском вводе."""
    for ch in ['_', '*', '`', '[']:
        text = text.replace(ch, '\\' + ch)
    return text


def compress_image(img_bytes, max_size_kb=3000, max_dimension=1920):
    try:
        img = Image.open(BytesIO(img_bytes))
        if img.mode not in ('RGB', 'L'):
            img = img.convert('RGB')
        w, h = img.size
        if w > max_dimension or h > max_dimension:
            ratio = min(max_dimension / w, max_dimension / h)
            img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
        quality = 85
        while quality >= 40:
            buf = BytesIO()
            img.save(buf, format='JPEG', quality=quality, optimize=True)
            if buf.tell() <= max_size_kb * 1024:
                return buf.getvalue()
            quality -= 10
        return buf.getvalue()
    except Exception as e:
        print(f'Compress error: {e}')
        return img_bytes


def is_valid_image(fb):
    try:
        Image.open(BytesIO(fb)).verify()
        return True
    except Exception:
        return False


# ---------- Telegram ----------
class Telegram:
    def __init__(self, bot_token, chat_id, api_base=None):
        self.chat_id = chat_id
        self.api = api_base or f'https://api.telegram.org/bot{bot_token}'

    def send_message(self, chat_id, text, markdown=True):
        max_len = 4000
        chunks, chunk = [], ''
        for line in text.split('\n'):
            if chunk and len(chunk) + len(line) + 1 > max_len:
                chunks.append(chunk)
                chunk = line
            else:
                chunk = chunk + '\n' + line if chunk else line
        if chunk:
            chunks.append(chunk)
        for part in chunks:
            try:
                payload = {'chat_id': chat_id, 'text': part}
                if markdown:
                    payload['parse_mode'] = 'Markdown'
                r = requests.post(f'{self.api}/sendMessage', json=payload, timeout=15)
                if r.status_code != 200 and markdown:
                    # Не удалось разобрать Markdown — отправляем как обычный текст
                    requests.post(f'{self.api}/sendMessage', json={'chat_id': chat_id, 'text': part}, timeout=15)
            except Exception as e:
                print(f'Telegram message error: {e}')

    def send_album(self, photos, caption):
        """photos: список (подпись, байты). Первое фото несёт подпись акта."""
        media, files = [], {}
        for i, (_label, fb) in enumerate(photos[:10]):  # Telegram: не больше 10 фото в альбоме
            name = f'photo_{i}'
            files[name] = (f'{name}.jpg', fb, 'image/jpeg')
            item = {'type': 'photo', 'media': f'attach://{name}'}
            if i == 0:
                item['caption'] = caption[:1024]
                item['parse_mode'] = 'Markdown'
            media.append(item)
        if not media:
            return None
        r = requests.post(f'{self.api}/sendMediaGroup',
                          data={'chat_id': self.chat_id, 'media': json.dumps(media)},
                          files=files, timeout=90)
        print(f'Telegram: {r.status_code}')
        return r.status_code


# ---------- ИИ (Anthropic) ----------
def _claude(api_key, model, content, max_tokens, timeout):
    resp = requests.post(
        'https://api.anthropic.com/v1/messages',
        headers={'x-api-key': api_key, 'anthropic-version': '2023-06-01', 'content-type': 'application/json'},
        json={'model': model, 'max_tokens': max_tokens, 'messages': [{'role': 'user', 'content': content}]},
        timeout=timeout,
    )
    if resp.status_code == 200:
        return resp.json()['content'][0]['text']
    print(f'Claude API error: {resp.status_code} {resp.text}')
    return None


def _image_block(fb):
    data = base64.standard_b64encode(compress_image(fb)).decode('utf-8')
    return {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/jpeg', 'data': data}}


def analyze_photos_with_ai(api_key, photos):
    """photos: список (подпись, байты). Возвращает текст отчёта или None."""
    if not api_key or not photos:
        return None
    zones_format = '\n'.join(f'{label}: [повреждения или "✅ без повреждений"]' for label, _ in photos)
    prompt_text = (
        'Ты эксперт по осмотру транспортных средств. '
        'Осмотри каждое фото и выяви ТОЛЬКО видимые повреждения: вмятины, царапины, трещины, сколы краски, сломанные элементы. '
        'Формат ответа — строго следующий:\n'
        '🔍 АНАЛИЗ ПОВРЕЖДЕНИЙ\n'
        + zones_format + '\n'
        'Итог: [1-2 предложения]\n\n'
        'Правила:\n'
        '- Каждая зона — одна строка, максимум 10 слов\n'
        '- Пиши только факты, никаких рассуждений\n'
        '- Если зоны нет на фото — пропусти её\n'
        'Отвечай только на русском языке.'
    )
    content = [{'type': 'text', 'text': prompt_text}]
    for label, fb in photos:
        content.append({'type': 'text', 'text': f'Зона: {label}'})
        content.append(_image_block(fb))
    try:
        return _claude(api_key, 'claude-sonnet-4-6', content, 1024, 90)
    except Exception as e:
        print(f'Claude API exception: {e}')
        return None


def compare_inspections_with_ai(api_key, plate, older, newer):
    """older/newer: {'date': 'ДД.ММ.ГГГГ', 'photos': [(подпись, байты), ...]}"""
    if not api_key:
        return 'ИИ-анализ не подключён (нет ключа ANTHROPIC_KEY).'
    content = [{'type': 'text', 'text': (
        f'Сравни два осмотра {plate}.\n'
        f'Осмотр 1 (старый): {older["date"]}\n'
        f'Осмотр 2 (новый): {newer["date"]}\n\n'
        'Для каждой зоны определи: появились ли новые повреждения или изменений нет. '
        'В конце дай общий вывод. Отвечай на русском языке.'
    )}]
    newer_by_label = dict(newer['photos'])
    for label, fb_old in older['photos']:
        fb_new = newer_by_label.get(label)
        if fb_new is None:
            continue
        content.append({'type': 'text', 'text': f'\n--- {label} ---'})
        content.append({'type': 'text', 'text': f'Осмотр {older["date"]}'})
        content.append(_image_block(fb_old))
        content.append({'type': 'text', 'text': f'Осмотр {newer["date"]}'})
        content.append(_image_block(fb_new))
    try:
        return _claude(api_key, 'claude-haiku-4-5-20251001', content, 2048, 120) or 'Ошибка при обращении к ИИ.'
    except Exception as e:
        return f'Ошибка: {e}'
