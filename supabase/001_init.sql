-- =====================================================================
--  Осмотр ТС v2 — структура базы данных
--  Выполнить один раз в Supabase: SQL Editor → New query → Run.
--  Скрипт можно запускать повторно: уже созданное не пострадает.
-- =====================================================================

-- ---------- Справочники ----------
create table if not exists public.vehicles (
  id          uuid primary key default gen_random_uuid(),
  plate       text not null,                       -- номер как его видит человек: «АХ5463-5»
  plate_norm  text not null unique,                -- для поиска: верхний регистр, латиница, без пробелов
  kind        text not null default 'truck' check (kind in ('truck', 'trailer')),
  model       text,
  note        text,
  is_active   boolean not null default true,
  created_at  timestamptz not null default now()
);

create table if not exists public.drivers (
  id          uuid primary key default gen_random_uuid(),
  full_name   text not null,
  name_norm   text not null unique,
  phone       text,
  is_active   boolean not null default true,
  created_at  timestamptz not null default now()
);

-- ---------- Осмотры ----------
create table if not exists public.inspections (
  id            uuid primary key default gen_random_uuid(),
  vehicle_id    uuid not null references public.vehicles(id),
  driver_id     uuid references public.drivers(id),
  kind          text not null check (kind in ('acceptance', 'return')),
  inspected_at  timestamptz not null,              -- время осмотра с телефона
  received_at   timestamptz not null default now(),-- время получения сервером
  mileage       integer,
  moto_hours    integer,
  trailer_type  text,
  doc_status    text check (doc_status in ('ok', 'warn', 'bad')),
  doc_comment   text,
  voice_notes   text,
  extra         jsonb not null default '{}'::jsonb, -- доп. поля: {"Название поля": "значение"}
  ai_status     text not null default 'none' check (ai_status in ('none', 'pending', 'done', 'error')),
  ai_report     text,
  session_id    uuid
);
create index if not exists inspections_vehicle_idx on public.inspections (vehicle_id, inspected_at desc);

create table if not exists public.inspection_photos (
  id             uuid primary key default gen_random_uuid(),
  inspection_id  uuid not null references public.inspections(id) on delete cascade,
  label          text not null,
  sort           integer not null default 0,
  path           text not null,                   -- путь в хранилище inspection-photos
  thumb_path     text
);
create index if not exists inspection_photos_insp_idx on public.inspection_photos (inspection_id, sort);

create table if not exists public.inspection_checks (
  id             uuid primary key default gen_random_uuid(),
  inspection_id  uuid not null references public.inspections(id) on delete cascade,
  item_key       text not null,
  label          text not null,
  status         text not null check (status in ('ok', 'warn', 'bad')),
  comment        text
);
create index if not exists inspection_checks_insp_idx on public.inspection_checks (inspection_id);

-- ---------- Строки карточки ТС: период «приёмка → сдача» ----------
create table if not exists public.usage_sessions (
  id                   uuid primary key default gen_random_uuid(),
  vehicle_id           uuid not null references public.vehicles(id),
  driver_id            uuid references public.drivers(id),          -- кто принял
  return_driver_id     uuid references public.drivers(id),          -- кто сдал
  start_inspection_id  uuid references public.inspections(id) on delete set null,
  end_inspection_id    uuid references public.inspections(id) on delete set null,
  started_at           timestamptz,
  ended_at             timestamptz,
  start_mileage        integer,
  end_mileage          integer,
  start_moto           integer,
  end_moto             integer,
  status               text not null default 'open' check (status in ('open', 'closed', 'closed_by_admin')),
  flags                text[] not null default '{}',               -- other_driver, no_acceptance
  admin_note           text,
  created_at           timestamptz not null default now()
);
-- Главное правило: у одного ТС не может быть двух открытых строк
create unique index if not exists usage_sessions_one_open_per_vehicle
  on public.usage_sessions (vehicle_id) where status = 'open';
create index if not exists usage_sessions_vehicle_idx
  on public.usage_sessions (vehicle_id, coalesce(started_at, ended_at) desc);

do $$ begin
  alter table public.inspections
    add constraint inspections_session_fk foreign key (session_id)
    references public.usage_sessions(id) on delete set null;
exception when duplicate_object then null; end $$;

-- ---------- Настройки сайта ----------
create table if not exists public.settings (
  key    text primary key,
  value  jsonb not null
);
insert into public.settings (key, value) values ('unaccounted_threshold_km', '0'::jsonb)
on conflict (key) do nothing;

-- ---------- Список ТС с текущим статусом ----------
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
  -- одометр не уменьшается: берём наибольшее из последнего осмотра, сдачи и открытой приёмки
  greatest(li.mileage, lr.end_mileage, o.start_mileage) as last_mileage
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

-- ---------- Действия администратора ----------
-- Закрыть строку вручную (водитель не оформил сдачу)
create or replace function public.admin_close_session(
  p_session_id uuid, p_end_mileage integer, p_end_moto integer, p_note text
) returns void language plpgsql security invoker as $$
begin
  update public.usage_sessions
     set status = 'closed_by_admin', ended_at = now(),
         end_mileage = p_end_mileage, end_moto = p_end_moto, admin_note = p_note
   where id = p_session_id and status = 'open';
  if not found then raise exception 'Строка не найдена или уже закрыта'; end if;
end $$;

-- Удалить ошибочную приёмку (строка без сдачи). Возвращает пути фото для удаления из хранилища.
create or replace function public.admin_delete_acceptance(p_session_id uuid)
returns setof text language plpgsql security invoker as $$
declare v_insp uuid;
begin
  select start_inspection_id into v_insp from public.usage_sessions
   where id = p_session_id and end_inspection_id is null;
  if not found then raise exception 'Можно удалить только строку без сдачи'; end if;
  return query
    select unnest(array[p.path, p.thumb_path]) from public.inspection_photos p
     where p.inspection_id = v_insp;
  delete from public.usage_sessions where id = p_session_id;
  delete from public.inspections where id = v_insp;
end $$;

-- ---------- Доступ ----------
alter table public.vehicles          enable row level security;
alter table public.drivers           enable row level security;
alter table public.inspections       enable row level security;
alter table public.inspection_photos enable row level security;
alter table public.inspection_checks enable row level security;
alter table public.usage_sessions    enable row level security;
alter table public.settings          enable row level security;

-- Сайт: всё доступно только вошедшим пользователям (1–2 сотрудника, без ролей)
do $$
declare t text;
begin
  foreach t in array array['vehicles','drivers','inspections','inspection_photos',
                           'inspection_checks','usage_sessions','settings'] loop
    execute format('drop policy if exists "portal_all" on public.%I', t);
    execute format('create policy "portal_all" on public.%I for all to authenticated using (true) with check (true)', t);
    execute format('grant select, insert, update, delete on public.%I to authenticated, service_role', t);
  end loop;
end $$;
grant select on public.v_vehicles to authenticated, service_role;
grant execute on function public.admin_close_session(uuid, integer, integer, text) to authenticated;
grant execute on function public.admin_delete_acceptance(uuid) to authenticated;
revoke all on function public.admin_close_session(uuid, integer, integer, text) from anon, public;
revoke all on function public.admin_delete_acceptance(uuid) from anon, public;

-- ---------- Хранилище фото (закрытое: фото видны только вошедшим на сайт) ----------
insert into storage.buckets (id, name, public)
values ('inspection-photos', 'inspection-photos', false)
on conflict (id) do update set public = false;

drop policy if exists "portal_read_photos" on storage.objects;
create policy "portal_read_photos" on storage.objects
  for select to authenticated using (bucket_id = 'inspection-photos');
drop policy if exists "portal_delete_photos" on storage.objects;
create policy "portal_delete_photos" on storage.objects
  for delete to authenticated using (bucket_id = 'inspection-photos');
