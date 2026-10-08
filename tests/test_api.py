"""Проверка /submit и /api/directory с поддельной базой в памяти (без сети)."""
import io
import os
import sys
import uuid

import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.update(API_TOKEN='test-token', SUPABASE_URL='http://fake', SUPABASE_KEY='sb_secret_x',
                  BOT_TOKEN='', CHAT_ID='', ANTHROPIC_KEY='', TELEGRAM_API='',
                  PORTAL_URL='https://example.github.io/car-inspection-v2/portal')

import server  # noqa: E402
from supa import SupaError  # noqa: E402


class FakeSupa:
    """Минимальная имитация PostgREST: фильтры eq., order, limit; уникальная открытая строка."""

    def __init__(self):
        self.t = {k: [] for k in ['vehicles', 'drivers', 'inspections', 'inspection_photos',
                                  'inspection_checks', 'usage_sessions']}
        self.files = {}
        self.fail_session_insert = False

    def _match(self, row, params):
        for k, v in params.items():
            if k in ('order', 'limit', 'select'):
                continue
            want = v[3:]
            got = row.get(k)
            if str(got).lower() != want.lower():
                return False
        return True

    def select(self, table, params):
        if table == 'v_vehicles':
            rows = []
            for v in self.t['vehicles']:
                ss = [s for s in self.t['usage_sessions'] if s['vehicle_id'] == v['id']]
                o = next((s for s in ss if s['status'] == 'open'), None)
                done = sorted((s for s in ss if s['status'] != 'open'), key=lambda s: s.get('ended_at') or '')
                lr = done[-1] if done else {}
                drv = next((d for d in self.t['drivers'] if o and d['id'] == o.get('driver_id')), {})
                rows.append({**v, 'open_session_id': o and o['id'], 'open_driver_id': o and o.get('driver_id'),
                             'open_driver_name': drv.get('full_name'), 'open_since': o and o.get('started_at'),
                             'open_start_mileage': o and o.get('start_mileage'), 'open_start_moto': o and o.get('start_moto'),
                             'last_return_mileage': lr.get('end_mileage'), 'last_return_moto': lr.get('end_moto')})
            return [r for r in rows if self._match(r, params)]
        rows = [r for r in self.t[table] if self._match(r, params)]
        if 'limit' in params:
            rows = rows[:int(params['limit'])]
        return [dict(r) for r in rows]

    def insert(self, table, rows):
        rows = rows if isinstance(rows, list) else [rows]
        out = []
        for r in rows:
            r = {'id': str(uuid.uuid4()), 'flags': [], **r}
            if table == 'usage_sessions':
                if self.fail_session_insert:
                    raise SupaError(409, '{"code":"23505"}')
                if r.get('status') == 'open' and any(
                        s['vehicle_id'] == r['vehicle_id'] and s['status'] == 'open' for s in self.t[table]):
                    raise SupaError(409, '{"code":"23505"}')
            self.t[table].append(r)
            out.append(dict(r))
        return out

    def update(self, table, params, values):
        out = []
        for r in self.t[table]:
            if self._match(r, params):
                r.update(values)
                out.append(dict(r))
        return out

    def delete(self, table, params):
        before = [r for r in self.t[table] if self._match(r, params)]
        self.t[table] = [r for r in self.t[table] if not self._match(r, params)]
        if table == 'inspections':  # каскад
            ids = {r['id'] for r in before}
            for child in ('inspection_photos', 'inspection_checks'):
                self.t[child] = [r for r in self.t[child] if r['inspection_id'] not in ids]

    def upload(self, path, data, content_type='image/jpeg'):
        self.files[path] = data
        return path

    def remove(self, paths):
        for p in paths:
            self.files.pop(p, None)

    def download(self, path):
        return self.files[path]


@pytest.fixture
def env(monkeypatch):
    fake = FakeSupa()
    monkeypatch.setattr(server, 'db', fake)
    monkeypatch.setattr(server, 'notify_background', lambda **kw: None)
    server.limiter.enabled = False
    truck = fake.insert('vehicles', {'plate': 'АХ5463-5', 'plate_norm': 'AX54635', 'kind': 'truck', 'is_active': True})[0]
    trailer = fake.insert('vehicles', {'plate': 'А1234А-7', 'plate_norm': 'A1234A7', 'kind': 'trailer', 'is_active': True})[0]
    ivanov = fake.insert('drivers', {'full_name': 'Иванов Иван', 'name_norm': 'иванов иван', 'is_active': True})[0]
    petrov = fake.insert('drivers', {'full_name': 'Петров Пётр', 'name_norm': 'петров петр', 'is_active': True})[0]
    return dict(db=fake, client=server.app.test_client(), truck=truck, trailer=trailer, ivanov=ivanov, petrov=petrov)


def jpeg():
    buf = io.BytesIO()
    Image.new('RGB', (800, 600), (120, 140, 170)).save(buf, 'JPEG')
    return buf.getvalue()


def submit(env, vehicle, driver, kind, mileage='', moto='', token='test-token', photos=2, **extra):
    data = {'vehicle_id': vehicle['id'], 'driver_id': driver['id'], 'kind': kind, 'mileage': mileage,
            'moto_hours': moto, 'inspected_at': '2026-10-08T09:30:00+03:00', 'photo_count': str(photos),
            'checks': '[{"key":"fire","label":"Огнетушитель","status":"warn","comment":"просрочен"}]',
            'extra': '{"Путевой лист": "123"}', **extra}
    for i in range(photos):
        data[f'photo_{i}'] = (io.BytesIO(jpeg()), f'{i}.jpg')
        data[f'photo_label_{i}'] = ['Спереди', 'Сзади', 'Салон'][i % 3]
    return env['client'].post('/submit', data=data, headers={'X-App-Token': token},
                              content_type='multipart/form-data')


def test_requires_token(env):
    assert env['client'].get('/api/directory').status_code == 401
    assert submit(env, env['truck'], env['ivanov'], 'acceptance', '1000', token='bad').status_code == 401


def test_directory_lists_vehicles_and_drivers(env):
    r = env['client'].get('/api/directory', headers={'X-App-Token': 'test-token'})
    body = r.get_json()
    assert r.status_code == 200 and len(body['vehicles']) == 2 and len(body['drivers']) == 2


def test_full_cycle_acceptance_then_return(env):
    db = env['db']
    r = submit(env, env['truck'], env['ivanov'], 'acceptance', '214400')
    assert r.status_code == 200, r.get_json()
    [s] = db.t['usage_sessions']
    assert s['status'] == 'open' and s['start_mileage'] == 214400 and s['driver_id'] == env['ivanov']['id']
    [insp] = db.t['inspections']
    assert insp['session_id'] == s['id'] and insp['extra'] == {'Путевой лист': '123'}
    assert len(db.t['inspection_photos']) == 2 and db.t['inspection_checks'][0]['comment'] == 'просрочен'
    assert len(db.files) == 4  # 2 фото + 2 превью

    r = submit(env, env['truck'], env['ivanov'], 'return', '215990')
    body = r.get_json()
    assert r.status_code == 200 and body['distance'] == 1590 and body['flags'] == []
    assert s['id'] == body['session_id']
    s = db.t['usage_sessions'][0]
    assert s['status'] == 'closed' and s['end_mileage'] == 215990 and s['return_driver_id'] == env['ivanov']['id']


def test_second_acceptance_is_blocked_without_uploads(env):
    submit(env, env['truck'], env['ivanov'], 'acceptance', '214400')
    files_before = dict(env['db'].files)
    r = submit(env, env['truck'], env['petrov'], 'acceptance', '214500')
    assert r.status_code == 409 and 'Иванов Иван' in r.get_json()['error']
    assert env['db'].files == files_before and len(env['db'].t['inspections']) == 1


def test_return_by_other_driver_is_flagged(env):
    submit(env, env['truck'], env['ivanov'], 'acceptance', '214400')
    r = submit(env, env['truck'], env['petrov'], 'return', '215000')
    assert r.status_code == 200 and r.get_json()['flags'] == ['other_driver']


def test_return_with_lower_mileage_is_rejected(env):
    submit(env, env['truck'], env['ivanov'], 'acceptance', '214400')
    r = submit(env, env['truck'], env['ivanov'], 'return', '214000')
    assert r.status_code == 400 and 'меньше' in r.get_json()['error']
    assert len(env['db'].t['inspections']) == 1


def test_return_without_acceptance(env):
    r = submit(env, env['truck'], env['ivanov'], 'return', '215000')
    assert r.status_code == 200 and r.get_json()['flags'] == ['no_acceptance']
    [s] = env['db'].t['usage_sessions']
    assert s['status'] == 'closed' and s.get('driver_id') is None and s['return_driver_id'] == env['ivanov']['id']


def test_race_on_open_rolls_back(env):
    env['db'].fail_session_insert = True
    r = submit(env, env['truck'], env['ivanov'], 'acceptance', '214400')
    assert r.status_code == 409
    assert env['db'].t['inspections'] == [] and env['db'].t['inspection_photos'] == [] and env['db'].files == {}


def test_trailer_uses_moto_hours_and_ignores_mileage(env):
    r = submit(env, env['trailer'], env['ivanov'], 'acceptance', '999', moto='1200', trailer_type='реф')
    assert r.status_code == 200
    r = submit(env, env['trailer'], env['ivanov'], 'return', '', moto='1250', trailer_type='реф')
    assert r.get_json()['moto_delta'] == 50 and r.get_json()['distance'] is None
    assert all(i['mileage'] is None for i in env['db'].t['inspections'])


def test_requires_ids_and_photos(env):
    r = env['client'].post('/submit', data={'kind': 'acceptance'}, headers={'X-App-Token': 'test-token'})
    assert r.status_code == 400 and 'обновите приложение' in r.get_json()['error'].lower()
    r = submit(env, env['truck'], env['ivanov'], 'acceptance', '214400', photos=0)
    assert r.status_code == 400 and r.get_json()['error'] == 'Нет фотографий'


def test_caption_contains_card_link_and_distance(env):
    from sessions import Decision
    from datetime import datetime
    cap = server.build_caption(env['truck'], env['ivanov'], 'return', datetime.fromisoformat('2026-10-08T09:30:00+03:00'),
                               215990, None, Decision('close', distance=1590), [], {}, None, {})
    assert 'Пройдено: 1 590 км' in cap and '#/vehicle/' + env['truck']['id'] in cap and 'СДАЧА' in cap
