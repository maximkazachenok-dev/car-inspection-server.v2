"""Проверка ИИ-помощника сайта: инструменты на поддельной базе, цикл разговора на поддельном ИИ."""
import io
import json
import os
import sys
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.update(API_TOKEN='test-token', SUPABASE_URL='http://fake', SUPABASE_KEY='sb_secret_x',
                  BOT_TOKEN='', CHAT_ID='', ANTHROPIC_KEY='', TELEGRAM_API='')

import assistant  # noqa: E402
import server  # noqa: E402
from assistant import Assistant, AssistantError  # noqa: E402

TZ = ZoneInfo('Europe/Minsk')


def jpeg():
    buf = io.BytesIO()
    Image.new('RGB', (40, 30), 'red').save(buf, format='JPEG')
    return buf.getvalue()


class FakeRest:
    """Имитация PostgREST с операторами eq, in, gte, lt, order, limit, offset."""

    def __init__(self):
        self.t = {k: [] for k in ['vehicles', 'drivers', 'inspections', 'inspection_photos', 'inspection_checks']}
        self.updates = []

    @staticmethod
    def _ok(value, cond):
        op, _, want = cond.partition('.')
        if op == 'eq':
            return str(value).lower() == want.lower()
        if op == 'in':
            return str(value) in want.strip('()').split(',')
        if op == 'gte':
            return value is not None and str(value) >= want
        if op == 'lt':
            return value is not None and str(value) < want
        raise AssertionError(cond)

    def _rows(self, table):
        if table == 'v_vehicles':
            return [{**v, 'open_session_id': None, 'last_mileage': None, 'last_inspection_at': None}
                    for v in self.t['vehicles']]
        if table == 'v_last_inspections':
            last = {}
            for i in sorted(self.t['inspections'], key=lambda i: i['inspected_at']):
                last[i['vehicle_id']] = i
            return list(last.values())
        return self.t[table]

    def select(self, table, params):
        rows = list(self._rows(table))
        for k, v in params.items():
            if k in ('order', 'limit', 'offset', 'select'):
                continue
            for cond in (v if isinstance(v, list) else [v]):
                rows = [r for r in rows if self._ok(r.get(k), cond)]
        if params.get('order', '').endswith('.desc'):
            rows.sort(key=lambda r: r[params['order'][:-5]], reverse=True)
        off = int(params.get('offset', 0))
        rows = rows[off:off + int(params['limit'])] if 'limit' in params else rows[off:]
        return [dict(r) for r in rows]

    def select_all(self, table, params, page=1000, max_rows=5000):
        return self.select(table, params)

    def update(self, table, params, values):
        self.updates.append((table, params, values))
        return []

    def download(self, path):
        return jpeg()


@pytest.fixture
def db():
    d = FakeRest()
    d.t['vehicles'] = [
        {'id': 'v1', 'plate': '3134КМ-2', 'plate_norm': '3134KM2', 'kind': 'truck', 'model': 'MAN', 'is_active': True},
        {'id': 'v2', 'plate': 'АХ5463-5', 'plate_norm': 'AX54635', 'kind': 'truck', 'model': 'DAF', 'is_active': True},
        {'id': 'v3', 'plate': 'А1234А-7', 'plate_norm': 'A1234A7', 'kind': 'trailer', 'model': None, 'is_active': True},
    ]
    d.t['drivers'] = [{'id': 'd1', 'full_name': 'Иванов Иван'}]
    d.t['inspections'] = [
        # v1: старый осмотр с критичным замечанием, последний — с «?» по документам
        {'id': 'i1', 'vehicle_id': 'v1', 'driver_id': 'd1', 'kind': 'acceptance', 'inspected_at': '2026-10-12T20:30:00Z',
         'mileage': 1000, 'doc_status': 'bad', 'doc_comment': 'нет страховки', 'voice_notes': None, 'ai_status': 'none'},
        {'id': 'i2', 'vehicle_id': 'v1', 'driver_id': 'd1', 'kind': 'return', 'inspected_at': '2026-10-13T21:30:00Z',
         'mileage': 1500, 'doc_status': 'warn', 'doc_comment': 'техосмотр до 20.10', 'voice_notes': None,
         'ai_status': 'done', 'ai_report': 'без повреждений'},
        # v2: всё хорошо, но ТМЦ с замечанием
        {'id': 'i3', 'vehicle_id': 'v2', 'driver_id': 'd1', 'kind': 'acceptance', 'inspected_at': '2026-10-13T08:00:00Z',
         'mileage': 5000, 'doc_status': 'ok', 'voice_notes': 'царапина на бампере', 'ai_status': 'none'},
        # v3: всё хорошо
        {'id': 'i4', 'vehicle_id': 'v3', 'driver_id': 'd1', 'kind': 'acceptance', 'inspected_at': '2026-10-13T09:00:00Z',
         'doc_status': 'ok', 'voice_notes': None, 'ai_status': 'none'},
    ]
    d.t['inspection_checks'] = [
        {'inspection_id': 'i3', 'label': 'Огнетушитель', 'status': 'warn', 'comment': 'просрочен'},
        {'inspection_id': 'i3', 'label': 'Аптечка', 'status': 'ok', 'comment': None},
    ]
    d.t['inspection_photos'] = [
        {'inspection_id': i, 'label': label, 'sort': n, 'path': f'{i}/{n}.jpg'}
        for i in ('i1', 'i2') for n, label in enumerate(['Спереди', 'Сзади'])
    ]
    return d


@pytest.fixture
def helper(db):
    return Assistant(db, 'key', TZ)


# ---------- инструменты ----------
def test_current_remarks_use_last_inspection(helper):
    r = helper.tool_find_remarks(scope='current')
    plates = {v['plate']: v for v in r['vehicles']}
    assert set(plates) == {'3134КМ-2', 'АХ5463-5'}
    docs = plates['3134КМ-2']['inspections'][0]['documents']
    assert docs['comment'] == 'техосмотр до 20.10' and '?' in docs['status']   # не старое «нет страховки»
    v2 = plates['АХ5463-5']['inspections'][0]
    assert v2['tmc'] == [{'item': 'Огнетушитель', 'status': 'некритичное замечание (?)', 'comment': 'просрочен'}]
    assert v2['driver_notes'] == 'царапина на бампере'
    assert plates['3134КМ-2']['card'] == '#/vehicle/v1'


def test_critical_only_and_documents_area(helper):
    assert helper.tool_find_remarks(scope='current', severity='critical')['vehicles'] == []
    period = helper.tool_find_remarks(scope='period', date_from='2026-10-01', date_to='2026-10-14',
                                      severity='critical', area='documents')
    assert [v['plate'] for v in period['vehicles']] == ['3134КМ-2']
    assert period['vehicles'][0]['inspections'][0]['documents']['comment'] == 'нет страховки'


def test_period_uses_minsk_days(helper):
    # i1 — 12.10 20:30 UTC = 12.10 23:30 Минск; i2 — 13.10 21:30 UTC = 14.10 00:30 Минск
    r = helper.tool_get_inspections('3134km2', date_from='2026-10-13', date_to='2026-10-13')
    assert r['count'] == 0
    r = helper.tool_get_inspections('3134 КМ 2', date_from='2026-10-14', date_to='2026-10-14')
    assert [i['inspection_id'] for i in r['inspections']] == ['i2']
    assert r['inspections'][0]['date'] == '14.10.2026 00:30'
    assert r['inspections'][0]['photos'] == ['Спереди', 'Сзади']
    assert r['inspections'][0]['ai_analysis'] == 'без повреждений'


def test_unknown_plate_suggests_similar(helper):
    with pytest.raises(AssistantError, match='3134КМ-2'):
        helper.tool_get_inspections('3134КМ-3')
    with pytest.raises(AssistantError, match='ГГГГ-ММ-ДД'):
        helper.tool_get_inspections('3134КМ-2', date_from='13.10.26')


def test_find_vehicles_filters(helper):
    r = helper.tool_find_vehicles(kind='trailer')
    assert [v['plate'] for v in r['vehicles']] == ['А1234А-7']
    assert helper.tool_find_vehicles(query='ax5463')['count'] == 1


def test_view_photos_returns_images(helper):
    content, is_error = helper.run_tool('view_photos', {'inspection_ids': ['i2', 'i1'], 'labels': ['спереди']})
    assert not is_error
    images = [c for c in content if c['type'] == 'image']
    texts = [c['text'] for c in content if c['type'] == 'text']
    assert len(images) == 2 and '14.10.2026' in texts[0] and '12.10.2026 23:30' in texts[1]


def test_run_tool_reports_errors(helper):
    content, is_error = helper.run_tool('get_inspections', {'plate': 'нет такого'})
    assert is_error and 'нет в справочнике' in content
    content, is_error = helper.run_tool('get_inspections', {'wrong': 1})
    assert is_error


def test_damage_analysis_saves_report(helper, db, monkeypatch):
    monkeypatch.setattr(assistant, 'analyze_photos_with_ai', lambda key, photos: f'{len(photos)} фото: ✅')
    content, is_error = helper.run_tool('run_damage_analysis', {'inspection_id': 'i2'})
    assert not is_error and json.loads(content)['saved_to_card'] is True
    assert db.updates[-1] == ('inspections', {'id': 'eq.i2'}, {'ai_status': 'done', 'ai_report': '2 фото: ✅'})


# ---------- разговор ----------
def test_clean_history():
    msgs = Assistant.clean_history([
        {'role': 'assistant', 'content': 'Здравствуйте'}, {'role': 'user', 'content': ' a '},
        {'role': 'user', 'content': 'b'}, {'role': 'system', 'content': 'x'}])
    assert msgs == [{'role': 'user', 'content': 'a\n\nb'}]
    with pytest.raises(AssistantError):
        Assistant.clean_history([{'role': 'user', 'content': 'q'}, {'role': 'assistant', 'content': 'a'}])


def block(**kw):
    return SimpleNamespace(**kw)


def reply(content, stop='end_turn'):
    return SimpleNamespace(content=content, stop_reason=stop,
                           usage=SimpleNamespace(input_tokens=10, output_tokens=5, cache_read_input_tokens=0))


class FakeClient:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kw):
        self.calls.append({**kw, 'messages': list(kw['messages'])})
        return self.replies.pop(0)


def test_chat_runs_tools_and_answers(helper, monkeypatch):
    fake = FakeClient([
        reply([block(type='thinking', thinking=''),
               block(type='tool_use', id='t1', name='find_remarks', input={'scope': 'current'})], 'tool_use'),
        reply([block(type='text', text='С замечаниями: **3134КМ-2**')]),
    ])
    monkeypatch.setattr(assistant.anthropic, 'Anthropic', lambda **kw: fake)
    out = helper.chat([{'role': 'user', 'content': 'Выдели авто с замечаниями'}])
    assert out['answer'] == 'С замечаниями: **3134КМ-2**'
    assert out['steps'] == ['Поиск замечаний (текущее состояние)']
    second = fake.calls[1]
    assert second['model'] == 'claude-opus-5-5' and second['fallbacks'] == 'default'
    assert second['messages'][1]['role'] == 'assistant'                 # ответ ИИ вместе с thinking передан назад
    result = second['messages'][2]['content'][0]
    assert result['tool_use_id'] == 't1' and not result['is_error'] and 'техосмотр до 20.10' in result['content']


def test_chat_stops_after_step_limit(helper, monkeypatch):
    monkeypatch.setattr(assistant, 'MAX_STEPS', 2)
    loop = [reply([block(type='tool_use', id=f't{n}', name='find_vehicles', input={})], 'tool_use') for n in range(2)]
    fake = FakeClient(loop + [reply([block(type='text', text='Итог по собранному')])])
    monkeypatch.setattr(assistant.anthropic, 'Anthropic', lambda **kw: fake)
    out = helper.chat([{'role': 'user', 'content': 'Список'}])
    assert out['answer'] == 'Итог по собранному'
    last = fake.calls[-1]
    assert last['tool_choice'] == {'type': 'none'} and last['messages'][-1]['role'] == 'system'


def test_chat_refusal(helper, monkeypatch):
    fake = FakeClient([reply([], 'refusal')])
    monkeypatch.setattr(assistant.anthropic, 'Anthropic', lambda **kw: fake)
    assert 'отказался' in helper.chat([{'role': 'user', 'content': '?'}])['answer']


# ---------- адреса сервера ----------
@pytest.fixture
def client(monkeypatch):
    server.app.config['TESTING'] = True
    server.limiter.enabled = False
    monkeypatch.setattr(server.db, 'auth_user', lambda token: {'email': 'a@b.c'} if token == 'good' else None)
    return server.app.test_client()


def test_chat_endpoint_requires_login(client, monkeypatch):
    monkeypatch.setattr(server, 'ANTHROPIC_KEY', 'key')
    r = client.post('/api/assistant/chat', json={'messages': [{'role': 'user', 'content': 'q'}]})
    assert r.status_code == 401
    r = client.post('/api/assistant/chat', json={}, headers={'Authorization': 'Bearer bad'})
    assert r.status_code == 401


def test_chat_endpoint_without_ai_key(client):
    r = client.post('/api/assistant/chat', json={'messages': [{'role': 'user', 'content': 'q'}]},
                    headers={'Authorization': 'Bearer good'})
    assert r.status_code == 503 and 'ANTHROPIC_KEY' in r.get_json()['error']


def test_chat_endpoint_answers(client, monkeypatch):
    monkeypatch.setattr(server, 'ANTHROPIC_KEY', 'key')
    monkeypatch.setattr(Assistant, 'chat', lambda self, history: {'answer': 'ok', 'steps': [], 'usage': {}})
    r = client.post('/api/assistant/chat', json={'messages': [{'role': 'user', 'content': 'q'}]},
                    headers={'Authorization': 'Bearer good'})
    assert r.status_code == 200 and r.get_json()['answer'] == 'ok'


def test_chat_endpoint_bad_request(client, monkeypatch):
    monkeypatch.setattr(server, 'ANTHROPIC_KEY', 'key')
    r = client.post('/api/assistant/chat', json={'messages': []}, headers={'Authorization': 'Bearer good'})
    assert r.status_code == 400 and r.get_json()['error'] == 'Напишите вопрос'


# ---------- выбор модели (ASSISTANT_MODEL) ----------
def test_pick_model():
    assert assistant.pick_model('') == ('claude-opus-5-5', None)
    assert assistant.pick_model(' claude-sonnet-5-5 ') == ('claude-sonnet-5-5', None)
    model, warning = assistant.pick_model('claude-sonet-5-5')       # опечатка не ломает чат
    assert model == 'claude-opus-5-5' and 'не поддерживается' in warning


@pytest.mark.parametrize('model, with_fallback', [('claude-sonnet-5-5', True), ('claude-haiku-5-5', False)])
def test_chat_uses_selected_model(db, monkeypatch, model, with_fallback):
    fake = FakeClient([reply([block(type='text', text='ok')])])
    monkeypatch.setattr(assistant.anthropic, 'Anthropic', lambda **kw: fake)
    out = Assistant(db, 'key', TZ, model).chat([{'role': 'user', 'content': 'q'}])
    call = fake.calls[0]
    assert call['model'] == model and out['model'] == model
    assert ('fallbacks' in call) is with_fallback          # у Haiku 5.5 запасной модели нет


def test_server_passes_model_and_health_shows_it(client, monkeypatch):
    seen = {}
    monkeypatch.setattr(server, 'ANTHROPIC_KEY', 'key')
    monkeypatch.setattr(server, 'ASSISTANT_MODEL', 'claude-sonnet-5-5')
    monkeypatch.setattr(Assistant, 'chat', lambda self, history: seen.setdefault('model', self.model) and {
        'answer': 'ok', 'steps': [], 'usage': {}, 'model': self.model})
    r = client.post('/api/assistant/chat', json={'messages': [{'role': 'user', 'content': 'q'}]},
                    headers={'Authorization': 'Bearer good'})
    assert r.get_json()['model'] == 'claude-sonnet-5-5' and seen['model'] == 'claude-sonnet-5-5'
    monkeypatch.setattr(server, 'SUPABASE_URL', '')
    assert client.get('/api/health').get_json()['модель помощника'] == 'claude-sonnet-5-5'
