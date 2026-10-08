"""Правила строк карточки ТС: приёмка открывает строку, сдача закрывает.

Чистая логика без обращения к сети — её проверяют тесты (tests/test_sessions.py).
"""
from dataclasses import dataclass, field
from datetime import datetime

# Кириллические буквы, которые на номерах выглядят как латинские
_PLATE_LOOKALIKES = str.maketrans({
    'А': 'A', 'В': 'B', 'Е': 'E', 'Ё': 'E', 'К': 'K', 'М': 'M', 'Н': 'H', 'О': 'O',
    'Р': 'P', 'С': 'C', 'Т': 'T', 'У': 'Y', 'Х': 'X', 'І': 'I',
})


def normalize_plate(plate):
    """«ах 5463-5» и «AX5463-5» → «AX54635»: один и тот же номер."""
    s = (plate or '').upper().translate(_PLATE_LOOKALIKES)
    return ''.join(ch for ch in s if ch.isalnum())


def normalize_name(name):
    """«  Иванов  Иван ИВАНОВИЧ» → «иванов иван иванович»."""
    return ' '.join((name or '').lower().replace('ё', 'е').split())


def short_date(iso):
    try:
        return datetime.fromisoformat(str(iso).replace('Z', '+00:00')).strftime('%d.%m')
    except (TypeError, ValueError):
        return ''


def fmt_km(value):
    return f'{value:,}'.replace(',', ' ')


@dataclass
class Decision:
    action: str                    # open | close | closed_no_acceptance | reject
    flags: list = field(default_factory=list)
    message: str = ''
    http_status: int = 200
    distance: int | None = None    # пройдено, км (для тягача)
    moto_delta: int | None = None  # отработано моточасов (для рефа)


def decide(kind, vehicle_kind, open_session, driver_id, mileage, moto_hours):
    """Что сделать со строкой карточки при новом осмотре.

    open_session — открытая строка этого ТС (или None):
      {'driver_id', 'driver_name', 'started_at', 'start_mileage', 'start_moto'}
    """
    if kind not in ('acceptance', 'return'):
        return Decision('reject', message='Не выбран тип осмотра', http_status=400)
    if vehicle_kind == 'truck' and mileage is None:
        return Decision('reject', message='Введите пробег', http_status=400)

    if kind == 'acceptance':
        if open_session:
            since = short_date(open_session.get('started_at'))
            who = open_session.get('driver_name') or 'другим водителем'
            return Decision(
                'reject', http_status=409,
                message=f'ТС числится за: {who}' + (f' с {since}' if since else '') +
                        '. Сдача не оформлена — обратитесь к администратору.')
        return Decision('open')

    # Сдача
    if not open_session:
        return Decision('closed_no_acceptance', flags=['no_acceptance'])

    flags = []
    if open_session.get('driver_id') and driver_id != open_session.get('driver_id'):
        flags.append('other_driver')

    start_km = open_session.get('start_mileage')
    distance = None
    if mileage is not None and start_km is not None:
        if mileage < start_km:
            return Decision(
                'reject', http_status=400,
                message=f'Пробег при сдаче ({fmt_km(mileage)} км) меньше, чем при приёмке '
                        f'({fmt_km(start_km)} км). Проверьте показания одометра.')
        distance = mileage - start_km

    start_moto = open_session.get('start_moto')
    moto_delta = None
    if moto_hours is not None and start_moto is not None:
        if moto_hours < start_moto:
            return Decision(
                'reject', http_status=400,
                message=f'Моточасы при сдаче ({moto_hours}) меньше, чем при приёмке ({start_moto}).')
        moto_delta = moto_hours - start_moto

    return Decision('close', flags=flags, distance=distance, moto_delta=moto_delta)
