import * as api from './api.js';

const app = document.getElementById('app');
const state = { session: null, drivers: null, threshold: 0, vehFilter: { q: '', kind: 'all', inactive: false }, drvQ: '' };

// ---------- Иконки ----------
const svg = (p, cls = 'ico') => `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${p}</svg>`;
const I = {
  logo: svg('<rect width="8" height="4" x="8" y="2" rx="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><path d="m9 14 2 2 4-4"/>', ''),
  truck: svg('<path d="M14 18V6a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v11a1 1 0 0 0 1 1h2"/><path d="M15 18H9"/><path d="M19 18h2a1 1 0 0 0 1-1v-3.65a1 1 0 0 0-.22-.624l-3.48-4.35A1 1 0 0 0 17.52 8H14"/><circle cx="17" cy="18" r="2"/><circle cx="7" cy="18" r="2"/>'),
  users: svg('<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>'),
  gear: svg('<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>'),
  search: svg('<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>'),
  plus: svg('<path d="M5 12h14"/><path d="M12 5v14"/>'),
  upload: svg('<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" x2="12" y1="3" y2="15"/>'),
  back: svg('<path d="m15 18-6-6 6-6"/>'),
  chev: svg('<path d="m9 18 6-6-6-6"/>', 'chev'),
  edit: svg('<path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/>'),
  alert: svg('<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>'),
  lock: svg('<rect width="18" height="11" x="3" y="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>'),
  logout: svg('<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" x2="9" y1="12" y2="12"/>'),
};

// ---------- Форматирование ----------
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const num = n => (n == null || n === '' ? '—' : Number(n).toLocaleString('ru'));
function fmtDate(iso) { if (!iso) return '—'; const d = new Date(iso); return d.toLocaleDateString('ru', { day: '2-digit', month: '2-digit', year: 'numeric' }); }
function fmtDay(iso) { if (!iso) return ''; return new Date(iso).toLocaleDateString('ru', { day: '2-digit', month: '2-digit' }); }
function fmtTime(iso) { if (!iso) return ''; return new Date(iso).toLocaleTimeString('ru', { hour: '2-digit', minute: '2-digit' }); }
function daysBetween(a, b) {
  if (!a) return null;
  const ms = (b ? new Date(b) : new Date()) - new Date(a);
  return Math.max(1, Math.ceil(ms / 86400000));
}
const KIND = { truck: 'Автомобиль', trailer: 'Прицеп' };
const STATUS_LABEL = { ok: 'Всё хорошо', warn: 'Замечание', bad: 'Критично' };

// ---------- Уведомления и модальные окна ----------
function toast(message, isError = false) {
  const el = document.createElement('div');
  el.className = 'toast' + (isError ? ' error' : '');
  el.textContent = message;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), isError ? 5000 : 2600);
}

function openModal(html, { className = 'modal', onClose } = {}) {
  const overlay = document.createElement('div');
  overlay.className = 'overlay';
  overlay.innerHTML = `<div class="${className}" role="dialog" aria-modal="true">${html}</div>`;
  const close = () => { overlay.remove(); document.removeEventListener('keydown', onKey); onClose && onClose(); };
  const onKey = e => { if (e.key === 'Escape') close(); };
  overlay.addEventListener('click', e => { if (e.target === overlay || e.target.closest('[data-close]')) close(); });
  document.addEventListener('keydown', onKey);
  document.body.appendChild(overlay);
  return { el: overlay, close };
}

function confirmDialog(title, text, okLabel = 'Подтвердить', danger = false) {
  return new Promise(resolve => {
    let done = false;
    const m = openModal(`
      <div class="modal-title">${esc(title)}</div>
      <div class="modal-text">${esc(text)}</div>
      <div class="modal-foot">
        <button class="btn" data-close>Отмена</button>
        <button class="btn ${danger ? 'btn-danger' : 'btn-primary'}" data-ok>${esc(okLabel)}</button>
      </div>`, { onClose: () => { if (!done) resolve(false); } });
    m.el.querySelector('[data-ok]').addEventListener('click', () => { done = true; m.close(); resolve(true); });
  });
}

function loadingHtml(text = 'Загружаем…') { return `<div class="loading"><div class="spinner"></div>${esc(text)}</div>`; }

async function guarded(fn, errorTarget) {
  try { return await fn(); } catch (e) {
    console.error(e);
    if (errorTarget) errorTarget.textContent = e.message; else toast(e.message, true);
    return undefined;
  }
}

// ---------- Каркас и навигация ----------
function layout(active, content) {
  const email = state.session && state.session.user ? state.session.user.email : '';
  app.innerHTML = `
    <header class="topbar">
      <a class="brand" href="#/vehicles"><span class="brand-logo">${I.logo}</span>Карточки ТС</a>
      <nav class="nav">
        <a href="#/vehicles" class="${active === 'vehicles' ? 'active' : ''}">${I.truck}Транспорт</a>
        <a href="#/drivers" class="${active === 'drivers' ? 'active' : ''}">${I.users}Водители</a>
        <a href="#/settings" class="${active === 'settings' ? 'active' : ''}">${I.gear}Настройки</a>
      </nav>
      <div class="topbar-right">
        <span class="user-email">${esc(email)}</span>
        <button class="btn btn-sm btn-ghost" id="logout">${I.logout}Выйти</button>
      </div>
    </header>
    <main class="page" id="page">${content}</main>`;
  document.getElementById('logout').addEventListener('click', async () => { await api.signOut(); location.hash = '#/login'; route(); });
  return document.getElementById('page');
}

async function route() {
  if (!api.configured) return notConfiguredView();
  if (!state.session) state.session = await api.getSession();
  const hash = location.hash.replace(/^#\/?/, '');
  const [name, id] = hash.split('/');
  if (!state.session) return loginView();
  if (name === 'login' || !name) { location.hash = '#/vehicles'; return; }
  if (name === 'vehicle' && id) return vehicleView(id);
  if (name === 'drivers') return driversView();
  if (name === 'settings') return settingsView();
  return vehiclesView();
}

function notConfiguredView() {
  app.innerHTML = `<div class="login-wrap"><div class="card login">
    <div class="brand"><span class="brand-logo">${I.logo}</span>Карточки ТС</div>
    <p class="login-sub">Сайт ещё не подключён к базе данных.<br>Заполните адрес и ключ Supabase в файле <b>portal/config.js</b>.</p>
  </div></div>`;
}

function loginView() {
  app.innerHTML = `<div class="login-wrap"><form class="card login" id="login-form" autocomplete="on">
    <div class="brand"><span class="brand-logo">${I.logo}</span>Карточки ТС</div>
    <p class="login-sub">Войдите, чтобы открыть историю осмотров</p>
    <label class="field" for="email">Email</label>
    <input type="email" id="email" required autocomplete="username">
    <label class="field" for="password">Пароль</label>
    <input type="password" id="password" required autocomplete="current-password">
    <div class="form-error" id="login-error"></div>
    <button class="btn btn-primary btn-block" style="margin-top:20px" type="submit">${I.lock}Войти</button>
  </form></div>`;
  const form = document.getElementById('login-form');
  form.addEventListener('submit', async e => {
    e.preventDefault();
    const btn = form.querySelector('button'); btn.disabled = true;
    const err = document.getElementById('login-error'); err.textContent = '';
    const data = await guarded(() => api.signIn(form.email.value.trim(), form.password.value), err);
    btn.disabled = false;
    if (data) { state.session = data.session; location.hash = '#/vehicles'; route(); }
  });
}

async function driversMap(force = false) {
  if (!state.drivers || force) state.drivers = await api.listDrivers();
  const map = {};
  for (const d of state.drivers) map[d.id] = d;
  return map;
}

// ---------- Транспорт ----------
async function vehiclesView() {
  const page = layout('vehicles', `
    <div class="page-head">
      <div><div class="page-title">Транспорт</div><div class="page-sub">Карточки ТС и текущий статус</div></div>
      <div class="actions">
        <button class="btn" id="import-veh">${I.upload}Импорт из Excel</button>
        <button class="btn btn-primary" id="add-veh">${I.plus}Добавить ТС</button>
      </div>
    </div>
    <div class="card">
      <div class="toolbar">
        <div class="search">${I.search}<input type="text" id="veh-q" placeholder="Поиск по номеру или модели" value="${esc(state.vehFilter.q)}"></div>
        <div class="seg" id="veh-kind">
          <button data-kind="all">Все</button><button data-kind="truck">Автомобили</button><button data-kind="trailer">Прицепы</button>
        </div>
        <label class="check"><input type="checkbox" id="veh-inactive" ${state.vehFilter.inactive ? 'checked' : ''}> Показать неактивные</label>
      </div>
      <div id="veh-list">${loadingHtml()}</div>
    </div>`);
  page.querySelector('#add-veh').addEventListener('click', () => vehicleForm(null, vehiclesView));
  page.querySelector('#import-veh').addEventListener('click', () => importDialog('vehicles', vehiclesView));
  const vehicles = await guarded(() => api.listVehicles());
  if (!vehicles) { page.querySelector('#veh-list').innerHTML = '<div class="empty">Не удалось загрузить список</div>'; return; }

  const render = () => {
    const f = state.vehFilter;
    page.querySelectorAll('#veh-kind button').forEach(b => b.classList.toggle('active', b.dataset.kind === f.kind));
    const nq = api.normPlate(f.q), lq = f.q.toLowerCase();
    const rows = vehicles.filter(v => (f.inactive || v.is_active) && (f.kind === 'all' || v.kind === f.kind) &&
      (!f.q || v.plate_norm.includes(nq) || String(v.model || '').toLowerCase().includes(lq)));
    const list = page.querySelector('#veh-list');
    if (!vehicles.length) {
      list.innerHTML = `<div class="empty"><strong>Список пуст</strong>Добавьте ТС вручную или загрузите список из Excel.</div>`;
      return;
    }
    if (!rows.length) { list.innerHTML = '<div class="empty">Ничего не найдено</div>'; return; }
    list.innerHTML = `<div class="table-wrap"><table class="tbl">
      <thead><tr><th>Номер</th><th>Тип</th><th>Статус</th><th class="r">Последний пробег</th><th>Последний осмотр</th></tr></thead>
      <tbody>${rows.map(v => `
        <tr class="clickable ${v.is_active ? '' : 'inactive'}" data-id="${v.id}">
          <td><div class="cell-main">${esc(v.plate)}</div>${v.model ? `<div class="cell-sub">${esc(v.model)}</div>` : ''}</td>
          <td>${KIND[v.kind] || v.kind}</td>
          <td>${!v.is_active ? '<span class="badge b-grey">Неактивно</span>' : v.open_session_id
              ? `<span class="badge b-line">На линии</span><div class="cell-sub">${esc(v.open_driver_name || '')}${v.open_since ? ' с ' + fmtDay(v.open_since) : ''}</div>`
              : '<span class="badge b-free">Свободно</span>'}</td>
          <td class="r num">${v.kind === 'truck' ? (v.last_mileage != null ? num(v.last_mileage) + ' км' : '—') : '—'}</td>
          <td>${v.last_inspection_at ? fmtDate(v.last_inspection_at) : '<span class="muted">—</span>'}</td>
        </tr>`).join('')}</tbody></table></div>`;
    list.querySelectorAll('tr[data-id]').forEach(tr => tr.addEventListener('click', () => { location.hash = '#/vehicle/' + tr.dataset.id; }));
  };
  page.querySelector('#veh-q').addEventListener('input', e => { state.vehFilter.q = e.target.value; render(); });
  page.querySelectorAll('#veh-kind button').forEach(b => b.addEventListener('click', () => { state.vehFilter.kind = b.dataset.kind; render(); }));
  page.querySelector('#veh-inactive').addEventListener('change', e => { state.vehFilter.inactive = e.target.checked; render(); });
  render();
}

function vehicleForm(v, after) {
  const m = openModal(`
    <form id="vf">
      <div class="modal-title">${v ? 'Изменить ТС' : 'Новое ТС'}</div>
      <label class="field" for="vf-plate">Гос. номер</label>
      <input type="text" id="vf-plate" required placeholder="АХ5463-5" value="${esc(v ? v.plate : '')}" style="text-transform:uppercase">
      <label class="field" for="vf-kind">Тип</label>
      <select id="vf-kind"><option value="truck">Автомобиль</option><option value="trailer">Прицеп / полуприцеп</option></select>
      <label class="field" for="vf-model">Марка, модель</label>
      <input type="text" id="vf-model" placeholder="MAN TGX" value="${esc(v && v.model || '')}">
      <label class="field" for="vf-note">Примечание</label>
      <input type="text" id="vf-note" value="${esc(v && v.note || '')}">
      ${v ? `<label class="check" style="margin-top:16px"><input type="checkbox" id="vf-active" ${v.is_active ? 'checked' : ''}> Активно (показывается водителям в приложении)</label>` : ''}
      <div class="form-error" id="vf-err"></div>
      <div class="modal-foot"><button type="button" class="btn" data-close>Отмена</button><button class="btn btn-primary" type="submit">Сохранить</button></div>
    </form>`);
  const f = m.el.querySelector('#vf');
  f.querySelector('#vf-kind').value = v ? v.kind : 'truck';
  f.addEventListener('submit', async e => {
    e.preventDefault();
    const saved = await guarded(() => api.saveVehicle({
      id: v && v.id, plate: f.querySelector('#vf-plate').value.toUpperCase(), kind: f.querySelector('#vf-kind').value,
      model: f.querySelector('#vf-model').value, note: f.querySelector('#vf-note').value,
      is_active: v ? f.querySelector('#vf-active').checked : true,
    }), f.querySelector('#vf-err'));
    if (saved) { m.close(); toast('Сохранено'); after(); }
  });
}

// ---------- Импорт из Excel ----------
function readSheet(file) {
  return new Promise((resolve, reject) => {
    if (!window.XLSX) { reject(new Error('Не загрузилась библиотека Excel. Проверьте интернет.')); return; }
    const reader = new FileReader();
    reader.onload = e => {
      try {
        const wb = window.XLSX.read(new Uint8Array(e.target.result), { type: 'array' });
        resolve(window.XLSX.utils.sheet_to_json(wb.Sheets[wb.SheetNames[0]], { header: 1, raw: false }));
      } catch (err) { reject(new Error('Не удалось прочитать файл: ' + err.message)); }
    };
    reader.onerror = () => reject(new Error('Не удалось прочитать файл'));
    reader.readAsArrayBuffer(file);
  });
}

function parseKind(s) { return /приц|п\/п|trailer/i.test(String(s || '')) ? 'trailer' : 'truck'; }

function importDialog(kind, after) {
  const isVeh = kind === 'vehicles';
  const m = openModal(`
    <div class="modal-title">Импорт ${isVeh ? 'транспорта' : 'водителей'} из Excel</div>
    <div class="modal-text">${isVeh
      ? 'Первый лист файла: столбец A — гос. номер, B — тип («авто» или «прицеп»), C — марка и модель.'
      : 'Первый лист файла: столбец A — ФИО, B — телефон (необязательно).'}
      Строка заголовков пропускается автоматически. Записи, которые уже есть в списке, не дублируются.</div>
    <input type="file" id="imp-file" accept=".xlsx,.xls,.csv">
    <div class="modal-text" id="imp-info" style="margin-top:12px"></div>
    <div class="form-error" id="imp-err"></div>
    <div class="modal-foot"><button class="btn" data-close>Отмена</button><button class="btn btn-primary" id="imp-go" disabled>Загрузить</button></div>`);
  let rows = [];
  m.el.querySelector('#imp-file').addEventListener('change', async e => {
    const err = m.el.querySelector('#imp-err'); err.textContent = '';
    const data = await guarded(() => readSheet(e.target.files[0]), err);
    if (!data) return;
    const body = data.filter(r => r && String(r[0] || '').trim());
    if (body.length && /номер|гос|фио|водит|name|plate/i.test(String(body[0][0]))) body.shift();
    rows = isVeh ? body.map(r => ({ plate: String(r[0]).toUpperCase(), kind: parseKind(r[1]), model: r[2] ? String(r[2]) : '' }))
                 : body.map(r => ({ full_name: String(r[0]), phone: r[1] ? String(r[1]) : '' }));
    m.el.querySelector('#imp-info').textContent = `Найдено строк: ${rows.length}`;
    m.el.querySelector('#imp-go').disabled = !rows.length;
  });
  m.el.querySelector('#imp-go').addEventListener('click', async () => {
    const btn = m.el.querySelector('#imp-go'); btn.disabled = true;
    const added = await guarded(() => (isVeh ? api.importVehicles(rows) : api.importDrivers(rows)), m.el.querySelector('#imp-err'));
    btn.disabled = false;
    if (added !== undefined) {
      m.close();
      toast(`Добавлено: ${added}. Уже были в списке: ${rows.length - added}`);
      if (!isVeh) state.drivers = null;
      after();
    }
  });
}

// ---------- Карточка ТС ----------
async function vehicleView(id) {
  const page = layout('vehicles', loadingHtml());
  const [vehicle, sessions, dmap, threshold] = await Promise.all([
    guarded(() => api.getVehicle(id)), guarded(() => api.listSessions(id)),
    guarded(() => driversMap(true)), guarded(() => api.getSetting('unaccounted_threshold_km', 0)),
  ]);
  if (!vehicle) { page.innerHTML = `<div class="empty"><strong>ТС не найдено</strong><a href="#/vehicles">Вернуться к списку</a></div>`; return; }
  state.threshold = Number(threshold) || 0;
  const isTruck = vehicle.kind === 'truck';
  const unit = isTruck ? 'км' : 'м/ч';
  const startVal = s => (isTruck ? s.start_mileage : s.start_moto);
  const endVal = s => (isTruck ? s.end_mileage : s.end_moto);
  const dname = did => (did && dmap[did] ? dmap[did].full_name : null);
  const list = sessions || [];

  // Неучтённый пробег между строками (список отсортирован от новых к старым)
  const gaps = {};
  let gapTotal = 0;
  for (let i = 0; i < list.length - 1; i++) {
    const newer = list[i], older = list[i + 1];
    const a = endVal(older), b = startVal(newer);
    if (a == null || b == null) continue;
    const diff = b - a;
    if (diff > state.threshold) { gaps[newer.id] = { diff, from: older.ended_at, to: newer.started_at }; gapTotal += diff; }
    else if (diff < 0) gaps[newer.id] = { diff, from: older.ended_at, to: newer.started_at };
  }
  const totalDist = list.reduce((sum, s) => sum + (startVal(s) != null && endVal(s) != null ? endVal(s) - startVal(s) : 0), 0);

  const statusBadges = s => {
    const b = [];
    if (s.status === 'open') b.push('<span class="badge b-line">На линии</span>');
    if (s.status === 'closed') b.push('<span class="badge b-done">Сдан</span>');
    if (s.status === 'closed_by_admin') b.push('<span class="badge b-admin">Закрыт админом</span>');
    if ((s.flags || []).includes('other_driver')) b.push('<span class="badge b-info">Сдал другой водитель</span>');
    if ((s.flags || []).includes('no_acceptance')) b.push('<span class="badge b-grey">Без приёмки</span>');
    return `<div class="badges">${b.join('')}</div>`;
  };
  const gapRow = s => {
    const g = gaps[s.id];
    if (!g) return '';
    const period = `${g.from ? 'сдача ' + fmtDay(g.from) : ''}${g.to ? ' → приёмка ' + fmtDay(g.to) : ''}`;
    return g.diff > 0
      ? `<tr class="gap"><td colspan="7"><div class="gap-note warn">${I.alert}Неучтённый ${isTruck ? 'пробег' : 'наработка'}: ${num(g.diff)} ${unit} <span style="font-weight:500">(${period})</span></div></td></tr>`
      : `<tr class="gap"><td colspan="7"><div class="gap-note bad">${I.alert}При приёмке на ${num(-g.diff)} ${unit} меньше, чем при предыдущей сдаче — проверьте показания <span style="font-weight:500">(${period})</span></div></td></tr>`;
  };
  const row = s => {
    const start = startVal(s), end = endVal(s);
    const dist = start != null && end != null ? end - start : null;
    const acceptName = dname(s.driver_id);
    const returnName = dname(s.return_driver_id);
    const mainName = acceptName || returnName || '—';
    return `
      <tr class="srow ${s.status === 'open' ? 'open' : ''}" data-sid="${s.id}">
        <td style="width:28px">${I.chev}</td>
        <td><div class="cell-main">${esc(mainName)}</div></td>
        <td>${s.started_at ? `<div class="cell-main nowrap">${fmtDate(s.started_at)} <span class="muted">${fmtTime(s.started_at)}</span></div>
            <div class="cell-sub num">${start != null ? num(start) + ' ' + unit : ''}</div>` : '<span class="muted">—</span>'}</td>
        <td>${s.ended_at ? `<div class="cell-main nowrap">${fmtDate(s.ended_at)} <span class="muted">${fmtTime(s.ended_at)}</span></div>
            <div class="cell-sub num">${end != null ? num(end) + ' ' + unit : ''}${returnName && s.driver_id && s.return_driver_id !== s.driver_id ? ' · сдал: ' + esc(returnName) : ''}</div>`
            : '<span class="muted">—</span>'}</td>
        <td class="r num">${dist != null ? `<span class="dist">${num(dist)}</span> ${unit}` : '<span class="muted">—</span>'}</td>
        <td class="r num">${s.started_at ? daysBetween(s.started_at, s.ended_at) : '<span class="muted">—</span>'}</td>
        <td>${statusBadges(s)}</td>
      </tr>${gapRow(s)}`;
  };

  page.innerHTML = `
    <div class="crumbs"><a href="#/vehicles">${I.back}Транспорт</a></div>
    <div class="page-head">
      <div class="vh">
        <div class="vh-icon">${I.truck}</div>
        <div><div class="vh-title">${esc(vehicle.plate)}</div>
          <div class="page-sub">${KIND[vehicle.kind]}${vehicle.model ? ' · ' + esc(vehicle.model) : ''}${vehicle.is_active ? '' : ' · <b>неактивно</b>'}</div></div>
      </div>
      <div class="actions"><button class="btn" id="edit-veh">${I.edit}Изменить</button></div>
    </div>
    <div class="stats">
      <div class="stat"><div class="stat-label">Статус</div><div class="stat-value">${vehicle.open_session_id
        ? `<span class="badge b-line">На линии</span>` : '<span class="badge b-free">Свободно</span>'}</div>
        ${vehicle.open_session_id ? `<div class="cell-sub">${esc(vehicle.open_driver_name || '')} с ${fmtDate(vehicle.open_since)}</div>` : ''}</div>
      <div class="stat"><div class="stat-label">${isTruck ? 'Последний пробег' : 'Последние моточасы'}</div><div class="stat-value num">${
        isTruck ? (vehicle.last_mileage != null ? num(vehicle.last_mileage) + ' км' : '—') : (vehicle.last_return_moto != null ? num(vehicle.last_return_moto) + ' м/ч' : '—')}</div></div>
      <div class="stat"><div class="stat-label">Периодов использования</div><div class="stat-value num">${list.length}</div></div>
      <div class="stat"><div class="stat-label">${isTruck ? 'Пройдено за периоды' : 'Наработка за периоды'}</div><div class="stat-value num">${num(totalDist)} ${unit}</div></div>
      <div class="stat"><div class="stat-label">Неучтённый ${isTruck ? 'пробег' : 'наработка'}</div><div class="stat-value num" style="color:${gapTotal ? 'var(--warn)' : 'inherit'}">${num(gapTotal)} ${unit}</div></div>
    </div>
    <div class="card">
      ${list.length ? `<div class="table-wrap"><table class="tbl sessions">
        <thead><tr><th></th><th>Водитель</th><th>Приёмка</th><th>Сдача</th><th class="r">${isTruck ? 'Пройдено' : 'Наработка'}</th><th class="r">Дней</th><th>Статус</th></tr></thead>
        <tbody>${list.map(row).join('')}</tbody></table></div>`
        : `<div class="empty"><strong>Осмотров пока нет</strong>Строка появится, когда водитель оформит приёмку или сдачу в приложении.</div>`}
    </div>`;

  page.querySelector('#edit-veh').addEventListener('click', () => vehicleForm(vehicle, () => vehicleView(id)));
  page.querySelectorAll('tr.srow').forEach(tr => tr.addEventListener('click', () => {
    const s = list.find(x => x.id === tr.dataset.sid);
    toggleDetail(tr, s, vehicle, dmap, () => vehicleView(id));
  }));
}

async function toggleDetail(tr, s, vehicle, dmap, reload) {
  const next = tr.nextElementSibling;
  if (next && next.classList.contains('detail')) { next.remove(); tr.classList.remove('expanded'); return; }
  tr.classList.add('expanded');
  const detail = document.createElement('tr');
  detail.className = 'detail';
  detail.innerHTML = `<td colspan="7">${loadingHtml('Загружаем осмотры…')}</td>`;
  tr.after(detail);
  const details = await guarded(() => api.getInspectionDetails([s.start_inspection_id, s.end_inspection_id]));
  if (!details) { detail.firstElementChild.innerHTML = '<div class="empty">Не удалось загрузить</div>'; return; }
  const a = details[s.start_inspection_id] || null, b = details[s.end_inspection_id] || null;
  const paths = [a, b].filter(Boolean).flatMap(x => x.photos.flatMap(p => [p.thumb_path, p.path]));
  const urls = (await guarded(() => api.signedUrls(paths))) || {};
  detail.firstElementChild.innerHTML = renderDetail(s, vehicle, a, b, dmap, urls);
  detail.querySelectorAll('[data-full]').forEach(btn => btn.addEventListener('click', e => {
    e.stopPropagation();
    const url = urls[btn.dataset.full];
    if (!url) return;
    const lb = openModal(`<img src="${url}" alt=""><div class="lightbox-cap">${esc(btn.dataset.cap)}</div>`, { className: 'lightbox' });
    lb.el.querySelector('.lightbox').addEventListener('click', lb.close);
  }));
  const closeBtn = detail.querySelector('[data-act="close"]');
  if (closeBtn) closeBtn.addEventListener('click', () => closeSessionDialog(s, vehicle, reload));
  const delBtn = detail.querySelector('[data-act="delete"]');
  if (delBtn) delBtn.addEventListener('click', async () => {
    const ok = await confirmDialog('Удалить приёмку?',
      'Строка, осмотр и все его фото будут удалены без возможности восстановления. ТС снова станет свободным.', 'Удалить', true);
    if (!ok) return;
    if (await guarded(() => api.deleteAcceptance(s.id))) { toast('Приёмка удалена'); reload(); }
  });
}

function renderDetail(s, vehicle, a, b, dmap, urls) {
  const isTruck = vehicle.kind === 'truck';
  const who = insp => (insp && dmap[insp.driver_id] ? dmap[insp.driver_id].full_name : '');
  const head = (title, insp) => `<div class="h">${title}<strong>${insp ? `${fmtDate(insp.inspected_at)} ${fmtTime(insp.inspected_at)} · ${esc(who(insp))}` : '—'}</strong></div>`;
  const cell = (html, changed) => `<div class="${changed ? 'changed' : ''}">${html == null || html === '' ? '<span class="none">—</span>' : html}</div>`;
  const status = (st, comment) => st ? `<span class="st ${st}"><span class="dot"></span>${STATUS_LABEL[st]}</span>${comment ? `<div class="cmt">${esc(comment)}</div>` : ''}` : '';
  const thumb = (p) => p ? `<button class="thumb" data-full="${esc(p.path)}" data-cap="${esc(p.label)}">${urls[p.thumb_path] || urls[p.path] ? `<img src="${urls[p.thumb_path] || urls[p.path]}" alt="${esc(p.label)}" loading="lazy">` : ''}</button>` : '';
  const out = [`<div></div>`, head('Приёмка', a), head('Сдача', b)];
  const section = t => out.push(`<div class="sec">${t}</div>`);
  const line = (label, l, r, changed) => out.push(`<div class="lbl">${esc(label)}</div>`, cell(l, changed), cell(r, changed));

  section('Показания');
  if (isTruck) line('Пробег', a && a.mileage != null ? num(a.mileage) + ' км' : '', b && b.mileage != null ? num(b.mileage) + ' км' : '');
  else {
    line('Тип прицепа', a && esc(a.trailer_type), b && esc(b.trailer_type));
    line('Моточасы', a && a.moto_hours != null ? num(a.moto_hours) + ' м/ч' : '', b && b.moto_hours != null ? num(b.moto_hours) + ' м/ч' : '');
  }

  const labels = [];
  for (const insp of [a, b]) if (insp) for (const p of insp.photos) if (!labels.includes(p.label)) labels.push(p.label);
  if (labels.length) {
    section('Фото');
    for (const label of labels) {
      line(label, thumb(a && a.photos.find(p => p.label === label)), thumb(b && b.photos.find(p => p.label === label)));
    }
  }

  section('Документы');
  line('Проверка документов', a && status(a.doc_status, a.doc_comment), b && status(b.doc_status, b.doc_comment),
       a && b && a.doc_status && b.doc_status && a.doc_status !== b.doc_status);

  const items = [];
  for (const insp of [a, b]) if (insp) for (const c of insp.checks) if (!items.find(x => x.key === c.item_key)) items.push({ key: c.item_key, label: c.label });
  if (items.length) {
    section('ТМЦ');
    for (const it of items) {
      const ca = a && a.checks.find(c => c.item_key === it.key), cb = b && b.checks.find(c => c.item_key === it.key);
      line(it.label, ca && status(ca.status, ca.comment), cb && status(cb.status, cb.comment), ca && cb && ca.status !== cb.status);
    }
  }

  const extraKeys = [...new Set([a, b].filter(Boolean).flatMap(x => Object.keys(x.extra || {})))];
  if (extraKeys.length) {
    section('Дополнительно');
    for (const k of extraKeys) line(k, a && esc((a.extra || {})[k]), b && esc((b.extra || {})[k]));
  }

  section('Замечания водителя');
  line('Голосом / текстом', a && a.voice_notes ? `<div class="cmt">${esc(a.voice_notes)}</div>` : '', b && b.voice_notes ? `<div class="cmt">${esc(b.voice_notes)}</div>` : '');

  const ai = insp => !insp ? '' : insp.ai_status === 'done' ? `<div class="ai">${esc(insp.ai_report)}</div>`
    : insp.ai_status === 'pending' ? '<span class="muted">Анализ выполняется…</span>'
    : insp.ai_status === 'error' ? '<span class="muted">Анализ не удался</span>' : '<span class="muted">Не подключён</span>';
  section('Анализ ИИ');
  line('Повреждения по фото', ai(a), ai(b));

  if (s.status === 'closed_by_admin') {
    section('Закрыто администратором');
    out.push(`<div class="lbl">Причина</div><div style="grid-column: span 2">${esc(s.admin_note || '—')}</div>`);
  }

  const actions = [];
  if (s.status === 'open') actions.push(`<button class="btn" data-act="close">Закрыть вручную</button>`);
  if (s.status === 'open' && !s.end_inspection_id && s.start_inspection_id) actions.push(`<button class="btn btn-danger" data-act="delete">Удалить приёмку</button>`);
  return `<div class="detail-body">${actions.length ? `<div class="detail-actions">${actions.join('')}</div>` : ''}<div class="cmp">${out.join('')}</div></div>`;
}

function closeSessionDialog(s, vehicle, reload) {
  const isTruck = vehicle.kind === 'truck';
  const start = isTruck ? s.start_mileage : s.start_moto;
  const m = openModal(`
    <form id="cs">
      <div class="modal-title">Закрыть строку вручную</div>
      <div class="modal-text">Используйте, если водитель не оформил сдачу в приложении. Строка получит статус «Закрыт админом», ТС станет свободным.</div>
      <label class="field" for="cs-val">${isTruck ? 'Пробег при сдаче, км' : 'Моточасы при сдаче (если есть)'}</label>
      <input type="number" id="cs-val" min="0" ${isTruck ? 'required' : ''} placeholder="${start != null ? 'не меньше ' + start : ''}">
      <label class="field" for="cs-note">Причина</label>
      <textarea id="cs-note" required placeholder="Водитель забыл оформить сдачу, машина на стоянке"></textarea>
      <div class="form-error" id="cs-err"></div>
      <div class="modal-foot"><button type="button" class="btn" data-close>Отмена</button><button class="btn btn-primary" type="submit">Закрыть строку</button></div>
    </form>`);
  const f = m.el.querySelector('#cs');
  f.addEventListener('submit', async e => {
    e.preventDefault();
    const err = f.querySelector('#cs-err');
    const raw = f.querySelector('#cs-val').value.trim();
    const val = raw === '' ? null : parseInt(raw, 10);
    if (val != null && start != null && val < start) { err.textContent = `Значение меньше, чем при приёмке (${num(start)})`; return; }
    const note = f.querySelector('#cs-note').value.trim();
    if (!note) { err.textContent = 'Укажите причину'; return; }
    const done = await guarded(() => api.closeSession(s.id, isTruck ? val : null, isTruck ? null : val, note).then(() => true), err);
    if (done) { m.close(); toast('Строка закрыта'); reload(); }
  });
}

// ---------- Водители ----------
async function driversView() {
  const page = layout('drivers', `
    <div class="page-head">
      <div><div class="page-title">Водители</div><div class="page-sub">Список, из которого водитель выбирает себя в приложении</div></div>
      <div class="actions">
        <button class="btn" id="import-drv">${I.upload}Импорт из Excel</button>
        <button class="btn btn-primary" id="add-drv">${I.plus}Добавить водителя</button>
      </div>
    </div>
    <div class="card">
      <div class="toolbar"><div class="search">${I.search}<input type="text" id="drv-q" placeholder="Поиск по ФИО" value="${esc(state.drvQ)}"></div></div>
      <div id="drv-list">${loadingHtml()}</div>
    </div>`);
  page.querySelector('#add-drv').addEventListener('click', () => driverForm(null));
  page.querySelector('#import-drv').addEventListener('click', () => importDialog('drivers', driversView));
  const map = await guarded(() => driversMap(true));
  if (!map) return;
  const render = () => {
    const q = api.normName(state.drvQ);
    const rows = state.drivers.filter(d => !q || d.name_norm.includes(q));
    const list = page.querySelector('#drv-list');
    if (!state.drivers.length) { list.innerHTML = `<div class="empty"><strong>Список пуст</strong>Добавьте водителей вручную или загрузите из Excel.</div>`; return; }
    if (!rows.length) { list.innerHTML = '<div class="empty">Ничего не найдено</div>'; return; }
    list.innerHTML = `<div class="table-wrap"><table class="tbl"><thead><tr><th>ФИО</th><th>Телефон</th><th>Статус</th></tr></thead><tbody>
      ${rows.map(d => `<tr class="clickable ${d.is_active ? '' : 'inactive'}" data-id="${d.id}">
        <td class="cell-main">${esc(d.full_name)}</td><td>${esc(d.phone || '—')}</td>
        <td>${d.is_active ? '<span class="badge b-free">Активен</span>' : '<span class="badge b-grey">Неактивен</span>'}</td></tr>`).join('')}
      </tbody></table></div>`;
    list.querySelectorAll('tr[data-id]').forEach(tr => tr.addEventListener('click', () => driverForm(state.drivers.find(d => d.id === tr.dataset.id))));
  };
  page.querySelector('#drv-q').addEventListener('input', e => { state.drvQ = e.target.value; render(); });
  render();
}

function driverForm(d) {
  const m = openModal(`
    <form id="df">
      <div class="modal-title">${d ? 'Изменить водителя' : 'Новый водитель'}</div>
      <label class="field" for="df-name">ФИО</label>
      <input type="text" id="df-name" required placeholder="Иванов Иван Иванович" value="${esc(d ? d.full_name : '')}">
      <label class="field" for="df-phone">Телефон</label>
      <input type="text" id="df-phone" placeholder="+375 29 000-00-00" value="${esc(d && d.phone || '')}">
      ${d ? `<label class="check" style="margin-top:16px"><input type="checkbox" id="df-active" ${d.is_active ? 'checked' : ''}> Активен (показывается в приложении)</label>` : ''}
      <div class="form-error" id="df-err"></div>
      <div class="modal-foot"><button type="button" class="btn" data-close>Отмена</button><button class="btn btn-primary" type="submit">Сохранить</button></div>
    </form>`);
  const f = m.el.querySelector('#df');
  f.addEventListener('submit', async e => {
    e.preventDefault();
    const saved = await guarded(() => api.saveDriver({
      id: d && d.id, full_name: f.querySelector('#df-name').value, phone: f.querySelector('#df-phone').value,
      is_active: d ? f.querySelector('#df-active').checked : true,
    }), f.querySelector('#df-err'));
    if (saved) { m.close(); toast('Сохранено'); driversView(); }
  });
}

// ---------- Настройки ----------
async function settingsView() {
  const page = layout('settings', loadingHtml());
  const threshold = await guarded(() => api.getSetting('unaccounted_threshold_km', 0));
  page.innerHTML = `
    <div class="page-head"><div><div class="page-title">Настройки</div></div></div>
    <form class="card card-pad" id="sf" style="max-width:560px">
      <label class="field" for="sf-thr">Порог неучтённого пробега, км</label>
      <input type="number" id="sf-thr" min="0" value="${Number(threshold) || 0}">
      <div class="cell-sub" style="margin-top:6px">Разница между сдачей одного водителя и приёмкой следующего меньше или равная порогу не показывается (например, перегон на стоянку или мойку). 0 — показывать любую разницу.</div>
      <div class="form-error" id="sf-err"></div>
      <div class="modal-foot" style="justify-content:flex-start"><button class="btn btn-primary" type="submit">Сохранить</button></div>
    </form>`;
  const f = page.querySelector('#sf');
  f.addEventListener('submit', async e => {
    e.preventDefault();
    const v = Math.max(0, parseInt(f.querySelector('#sf-thr').value || '0', 10));
    const ok = await guarded(() => api.setSetting('unaccounted_threshold_km', v).then(() => true), f.querySelector('#sf-err'));
    if (ok) toast('Сохранено');
  });
}

// ---------- Запуск ----------
api.onAuthChange(session => {
  const had = Boolean(state.session);
  state.session = session;
  if (had && !session) route();
});
window.addEventListener('hashchange', route);
route();
