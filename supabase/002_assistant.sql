-- =====================================================================
--  Осмотр ТС v2 — дополнение для ИИ-помощника на сайте
--  Выполнить один раз после 001_init.sql: SQL Editor → New query → Run.
--  Скрипт можно запускать повторно.
-- =====================================================================

-- Последний осмотр каждого ТС: «текущее состояние» машины для вопросов
-- вроде «у каких ТС сейчас замечания по документам»
create or replace view public.v_last_inspections with (security_invoker = on) as
select distinct on (i.vehicle_id) i.*
from public.inspections i
order by i.vehicle_id, i.inspected_at desc;

grant select on public.v_last_inspections to authenticated, service_role;

-- Поиск осмотров за период и замечаний ТМЦ по оценке
create index if not exists inspections_inspected_at_idx on public.inspections (inspected_at desc);
create index if not exists inspection_checks_status_idx on public.inspection_checks (status) where status <> 'ok';
