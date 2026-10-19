// Все обращения сайта к Supabase. Доступ к данным — только после входа (правила RLS в базе).
const cfg = window.PORTAL_CONFIG || {};
const BUCKET = 'inspection-photos';

export const configured = Boolean(cfg.SUPABASE_URL && cfg.SUPABASE_KEY &&
  !String(cfg.SUPABASE_URL).includes('ВАШ') && !String(cfg.SUPABASE_KEY).includes('ВСТАВЬТЕ'));

const sb = configured ? window.supabase.createClient(cfg.SUPABASE_URL, cfg.SUPABASE_KEY, {
  auth: { persistSession: true, autoRefreshToken: true },
}) : null;

function check({ data, error }) {
  if (error) throw new Error(humanError(error));
  return data;
}

function humanError(error) {
  const msg = String(error.message || error);
  if (error.code === '23505' || /duplicate key/i.test(msg)) return 'Такая запись уже есть';
  if (/Invalid login credentials/i.test(msg)) return 'Неверный email или пароль';
  if (/Failed to fetch|NetworkError/i.test(msg)) return 'Нет связи с сервером. Проверьте интернет.';
  if (/JWT|not authorized|permission denied/i.test(msg)) return 'Нет доступа. Войдите заново.';
  return msg;
}

// ---------- Нормализация (так же, как на сервере) ----------
const LOOKALIKES = { 'А':'A','В':'B','Е':'E','Ё':'E','К':'K','М':'M','Н':'H','О':'O','Р':'P','С':'C','Т':'T','У':'Y','Х':'X','І':'I' };
export function normPlate(s) {
  return String(s || '').toUpperCase().split('').map(ch => LOOKALIKES[ch] || ch).join('')
    .split('').filter(ch => /[0-9A-ZА-ЯЁ]/.test(ch)).join('');
}
export function normName(s) {
  return String(s || '').toLowerCase().replace(/ё/g, 'е').split(/\s+/).filter(Boolean).join(' ');
}

// ---------- Вход ----------
export async function getSession() {
  if (!sb) return null;
  const { data } = await sb.auth.getSession();
  return data.session;
}
export async function signIn(email, password) {
  return check(await sb.auth.signInWithPassword({ email, password }));
}
export async function signOut() { await sb.auth.signOut(); }
export function onAuthChange(cb) { if (sb) sb.auth.onAuthStateChange((_e, session) => cb(session)); }

// ---------- Транспорт ----------
export async function listVehicles() {
  return check(await sb.from('v_vehicles').select('*').order('plate'));
}
export async function getVehicle(id) {
  const rows = check(await sb.from('v_vehicles').select('*').eq('id', id));
  return rows[0] || null;
}
export async function saveVehicle(v) {
  const row = { plate: v.plate.trim(), plate_norm: normPlate(v.plate), kind: v.kind,
                model: (v.model || '').trim() || null, note: (v.note || '').trim() || null,
                is_active: v.is_active !== false };
  if (!row.plate_norm) throw new Error('Введите гос. номер');
  const q = v.id ? sb.from('vehicles').update(row).eq('id', v.id) : sb.from('vehicles').insert(row);
  try {
    return check(await q.select())[0];
  } catch (e) {
    if (e.message === 'Такая запись уже есть') throw new Error('ТС с таким номером уже есть в списке');
    throw e;
  }
}
export async function importVehicles(rows) {
  const clean = dedupe(rows.map(r => ({ plate: r.plate.trim(), plate_norm: normPlate(r.plate), kind: r.kind,
                                        model: (r.model || '').trim() || null, is_active: true }))
                          .filter(r => r.plate_norm), 'plate_norm');
  if (!clean.length) return 0;
  const data = check(await sb.from('vehicles').upsert(clean, { onConflict: 'plate_norm', ignoreDuplicates: true }).select());
  return data.length;
}

// ---------- Водители ----------
export async function listDrivers() {
  return check(await sb.from('drivers').select('*').order('full_name'));
}
export async function saveDriver(d) {
  const row = { full_name: d.full_name.trim().replace(/\s+/g, ' '), name_norm: normName(d.full_name),
                phone: (d.phone || '').trim() || null, is_active: d.is_active !== false };
  if (!row.name_norm) throw new Error('Введите ФИО');
  const q = d.id ? sb.from('drivers').update(row).eq('id', d.id) : sb.from('drivers').insert(row);
  try {
    return check(await q.select())[0];
  } catch (e) {
    if (e.message === 'Такая запись уже есть') throw new Error('Водитель с таким ФИО уже есть в списке');
    throw e;
  }
}
export async function importDrivers(rows) {
  const clean = dedupe(rows.map(r => ({ full_name: r.full_name.trim().replace(/\s+/g, ' '), name_norm: normName(r.full_name),
                                        phone: (r.phone || '').trim() || null, is_active: true }))
                          .filter(r => r.name_norm), 'name_norm');
  if (!clean.length) return 0;
  const data = check(await sb.from('drivers').upsert(clean, { onConflict: 'name_norm', ignoreDuplicates: true }).select());
  return data.length;
}

function dedupe(rows, key) {
  const seen = new Set();
  return rows.filter(r => !seen.has(r[key]) && seen.add(r[key]));
}

// ---------- Строки карточки ТС ----------
export async function listSessions(vehicleId) {
  const rows = check(await sb.from('usage_sessions').select('*').eq('vehicle_id', vehicleId));
  const key = s => s.started_at || s.ended_at || s.created_at;
  return rows.sort((a, b) => String(key(b)).localeCompare(String(key(a))));
}
// Замечания строк карточки ТС: {session_id: {remark_inspections, unresolved, remarks_resolved_at, ...}}.
// null — в базе ещё не выполнен скрипт 003_remarks.sql.
export async function listSessionRemarks(vehicleId) {
  const { data, error } = await sb.from('v_session_remarks').select('*').eq('vehicle_id', vehicleId);
  if (error) { console.warn('Замечания недоступны:', error.message); return null; }
  const out = {};
  for (const r of data) out[r.session_id] = r;
  return out;
}
export async function setRemarksResolved(sessionId, resolved) {
  check(await sb.rpc('set_remarks_resolved', { p_session_id: sessionId, p_resolved: resolved }));
}
export async function getInspectionDetails(ids) {
  ids = ids.filter(Boolean);
  if (!ids.length) return {};
  const [insps, photos, checks] = await Promise.all([
    sb.from('inspections').select('*').in('id', ids).then(check),
    sb.from('inspection_photos').select('*').in('inspection_id', ids).order('sort').then(check),
    sb.from('inspection_checks').select('*').in('inspection_id', ids).then(check),
  ]);
  const out = {};
  for (const i of insps) out[i.id] = { ...i, photos: [], checks: [] };
  for (const p of photos) out[p.inspection_id] && out[p.inspection_id].photos.push(p);
  for (const c of checks) out[c.inspection_id] && out[c.inspection_id].checks.push(c);
  return out;
}
export async function signedUrls(paths) {
  paths = [...new Set(paths.filter(Boolean))];
  if (!paths.length) return {};
  const data = check(await sb.storage.from(BUCKET).createSignedUrls(paths, 3600));
  const out = {};
  for (const item of data) if (item.signedUrl) out[item.path] = item.signedUrl;
  return out;
}

// ---------- Действия администратора ----------
export async function closeSession(sessionId, endMileage, endMoto, note) {
  check(await sb.rpc('admin_close_session', {
    p_session_id: sessionId, p_end_mileage: endMileage, p_end_moto: endMoto, p_note: note }));
}
export async function deleteAcceptance(sessionId) {
  const paths = check(await sb.rpc('admin_delete_acceptance', { p_session_id: sessionId })) || [];
  const list = paths.map(p => (typeof p === 'string' ? p : Object.values(p)[0])).filter(Boolean);
  if (list.length) await sb.storage.from(BUCKET).remove(list);
  return true;
}

// ---------- ИИ-помощник (через сервер на Railway: ключ ИИ хранится только там) ----------
const SERVER_URL = String(cfg.SERVER_URL || '').trim().replace(/\/+$/, '').replace(/\/submit$/, '');
export const assistantConfigured = Boolean(SERVER_URL && !SERVER_URL.includes('ВАШ'));

async function serverPost(path, body) {
  if (!assistantConfigured) throw new Error('Не указан адрес сервера: добавьте SERVER_URL в файл portal/config.js');
  const session = await getSession();
  if (!session) throw new Error('Сеанс входа истёк. Войдите заново.');
  let resp;
  try {
    resp = await fetch(SERVER_URL + path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + session.access_token },
      body: JSON.stringify(body),
    });
  } catch (e) {
    throw new Error('Нет связи с сервером. Проверьте интернет и повторите.');
  }
  let data = null;
  try { data = await resp.json(); } catch (e) { /* ответ не JSON */ }
  if (resp.ok && data && data.ok) return data;
  if (data && data.error) throw new Error(data.error);
  if (resp.status === 429) throw new Error('Слишком много запросов подряд. Подождите несколько минут.');
  if (resp.status === 502 || resp.status === 504) throw new Error('Сервер не успел ответить. Повторите или упростите вопрос.');
  throw new Error(`Сервер ответил с ошибкой ${resp.status}`);
}
export function askAssistant(messages) { return serverPost('/api/assistant/chat', { messages }); }
export function analyzeInspection(inspectionId) { return serverPost('/api/assistant/analyze', { inspection_id: inspectionId }); }

// ---------- Настройки ----------
export async function getSetting(key, fallback) {
  const rows = check(await sb.from('settings').select('*').eq('key', key));
  return rows.length ? rows[0].value : fallback;
}
export async function setSetting(key, value) {
  check(await sb.from('settings').upsert({ key, value }, { onConflict: 'key' }).select());
}
