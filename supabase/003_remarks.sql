-- =====================================================================
--  Осмотр ТС v2 — раздел «Замечания» и отметка «Замечания устранены»
--  Выполнить один раз после 002_assistant.sql: SQL Editor → New query → Run.
--  Скрипт можно запускать повторно.
-- =====================================================================

-- Отметка «Замечания устранены» у строки карточки ТС: когда и кто отметил
alter table public.usage_sessions add column if not exists remarks_resolved_at timestamptz;
alter table public.usage_sessions add column if not exists remarks_resolved_by text;

create index if not exists inspections_session_idx on public.inspections (session_id);

-- Текст водителя — замечание, если это не «всё хорошо», «нет» и т.п.
-- Регистр приводится вручную (translate), чтобы не зависеть от языковых настроек базы.
create or replace function public.is_driver_remark(t text) returns boolean
language sql immutable as $$
  select coalesce(
    btrim(regexp_replace(
      translate(t, 'АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯёABCDEFGHIJKLMNOPQRSTUVWXYZ',
                   'абвгдеежзийклмнопрстуфхцчшщъыьэюяеabcdefghijklmnopqrstuvwxyz'),
      '[^0-9a-zа-я]+', ' ', 'g')) not in (
      '', 'все хорошо', 'все в порядке', 'все нормально', 'все норм', 'все ок', 'все ok', 'все исправно',
      'хорошо', 'нормально', 'норм', 'ок', 'ok', 'нет', 'нету', 'в порядке', 'исправно',
      'замечаний нет', 'нет замечаний', 'без замечаний', 'претензий нет', 'нет претензий'),
    false)
$$;

-- Замечания каждого осмотра: оценки «?» и «!» по документам и ТМЦ, текст водителя
create or replace view public.v_inspection_remarks with (security_invoker = on) as
select i.id as inspection_id, i.vehicle_id, i.session_id, i.received_at,
       coalesce(i.doc_status in ('warn', 'bad'), false) as doc_remark,
       exists (select 1 from public.inspection_checks c
               where c.inspection_id = i.id and c.status in ('warn', 'bad')) as tmc_remark,
       public.is_driver_remark(i.voice_notes) as notes_remark
from public.inspections i;

-- Замечания строки карточки ТС. Неустранённые — те, что пришли после отметки «устранены» или без неё.
create or replace view public.v_session_remarks with (security_invoker = on) as
select s.id as session_id, s.vehicle_id, s.remarks_resolved_at, s.remarks_resolved_by,
       count(r.inspection_id) filter (where r.doc_remark or r.tmc_remark or r.notes_remark) as remark_inspections,
       count(r.inspection_id) filter (where (r.doc_remark or r.tmc_remark or r.notes_remark)
                                        and (s.remarks_resolved_at is null or r.received_at > s.remarks_resolved_at))
         as unresolved
from public.usage_sessions s
left join public.v_inspection_remarks r on r.session_id = s.id
group by s.id, s.vehicle_id, s.remarks_resolved_at, s.remarks_resolved_by;

-- Список ТС: тот же, что в 001_init.sql, плюс число осмотров с неустранёнными замечаниями
create or replace view public.v_vehicles with (security_invoker = on) as
select
  v.*,
  o.id             as open_session_id,
  o.driver_id      as open_driver_id,
  od.full_name     as open_driver_name,
  o.started_at     as open_since,
  o.start_mileage  as open_start_mileage,
  o.start_moto     as open_start_moto,
  lr.end_mileage   as last_return_mileage,
  lr.end_moto      as last_return_moto,
  li.inspected_at  as last_inspection_at,
  greatest(li.mileage, lr.end_mileage, o.start_mileage) as last_mileage,
  (select coalesce(sum(sr.unresolved), 0)::integer from public.v_session_remarks sr
    where sr.vehicle_id = v.id) as unresolved_remarks
from public.vehicles v
left join public.usage_sessions o on o.vehicle_id = v.id and o.status = 'open'
left join public.drivers od on od.id = o.driver_id
left join lateral (
  select s.end_mileage, s.end_moto from public.usage_sessions s
  where s.vehicle_id = v.id and s.status <> 'open'
  order by s.ended_at desc nulls last limit 1
) lr on true
left join lateral (
  select i.inspected_at, i.mileage from public.inspections i
  where i.vehicle_id = v.id
  order by i.inspected_at desc limit 1
) li on true;

-- Поставить или снять отметку «Замечания устранены». Время — по часам базы, автор — из входа на сайт.
create or replace function public.set_remarks_resolved(p_session_id uuid, p_resolved boolean)
returns void language plpgsql security invoker as $$
begin
  update public.usage_sessions
     set remarks_resolved_at = case when p_resolved then now() end,
         remarks_resolved_by = case when p_resolved then coalesce(auth.jwt() ->> 'email', 'сайт') end
   where id = p_session_id;
  if not found then raise exception 'Строка не найдена'; end if;
end $$;

grant select on public.v_inspection_remarks, public.v_session_remarks, public.v_vehicles to authenticated, service_role;
grant execute on function public.is_driver_remark(text) to authenticated, service_role;
revoke all on function public.set_remarks_resolved(uuid, boolean) from anon, public;
grant execute on function public.set_remarks_resolved(uuid, boolean) to authenticated;
