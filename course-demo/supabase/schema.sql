-- הרץ את הקובץ הזה ב-Supabase: SQL Editor → New query → Run
-- פרויקט הגשה: אתר בית ספר + עוזר AI
-- קודם טבלאות, אחר כך אינדקס / טריגר / הרשאות.

create table if not exists school_state (
  id text primary key,
  payload jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

create table if not exists ai_logs (
  id uuid primary key default gen_random_uuid(),
  school_id text not null default 'default',
  user_message text not null default '',
  assistant_message text,
  change_type text,
  applied boolean default false,
  created_at timestamptz not null default now()
);

create index if not exists ai_logs_created_at_idx on ai_logs (created_at desc);

create or replace function set_school_state_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

do $$
begin
  if exists (
    select 1 from information_schema.tables
    where table_schema = 'public' and table_name = 'school_state'
  ) then
    drop trigger if exists school_state_updated_at on school_state;
  end if;
end $$;

create trigger school_state_updated_at
before update on school_state
for each row execute procedure set_school_state_updated_at();

alter table school_state enable row level security;
alter table ai_logs enable row level security;

do $$
begin
  if not exists (
    select 1 from pg_policies
    where schemaname = 'public'
      and tablename = 'school_state'
      and policyname = 'public read school_state'
  ) then
    create policy "public read school_state"
      on school_state for select
      using (true);
  end if;
end $$;

-- ===== מערכת משתמשים, פיצ'רים והגדרות גישה =====

create table if not exists users (
  id uuid primary key default gen_random_uuid(),
  school_id text not null default 'default',
  name text not null,
  role text not null check (role in ('teacher', 'staff', 'student')),
  class_id text,
  access_code text unique not null,
  created_at timestamptz not null default now()
);

create index if not exists users_code_idx on users (access_code);
create index if not exists users_class_idx on users (class_id);

create table if not exists features (
  id uuid primary key default gen_random_uuid(),
  school_id text not null default 'default',
  creator_name text not null default '',
  title text not null,
  description text not null default '',
  feature_type text not null,
  config jsonb not null default '{}'::jsonb,
  target_class text,
  status text not null default 'pending' check (status in ('pending', 'active', 'disabled')),
  created_at timestamptz not null default now(),
  approved_at timestamptz,
  approved_by text
);

create index if not exists features_status_idx on features (status);
create index if not exists features_class_idx on features (target_class);

create table if not exists access_settings (
  school_id text primary key default 'default',
  mode text not null default 'code' check (mode in ('code', 'per_user', 'open')),
  updated_at timestamptz not null default now()
);

insert into access_settings (school_id, mode)
values ('default', 'code')
on conflict (school_id) do nothing;

alter table users enable row level security;
alter table features enable row level security;
alter table access_settings enable row level security;

create policy "service role full access users"
  on users for all using (true);

create policy "service role full access features"
  on features for all using (true);

create policy "service role full access access_settings"
  on access_settings for all using (true);

-- ===== הרחבות אבטחה =====
ALTER TABLE access_settings ADD COLUMN IF NOT EXISTS site_protected BOOLEAN DEFAULT FALSE;
ALTER TABLE access_settings ADD COLUMN IF NOT EXISTS site_code TEXT DEFAULT '';
ALTER TABLE features ADD COLUMN IF NOT EXISTS access_level TEXT DEFAULT 'public' CHECK (access_level IN ('public', 'protected'));
ALTER TABLE features ADD COLUMN IF NOT EXISTS feature_code TEXT DEFAULT '';
ALTER TABLE users ADD COLUMN IF NOT EXISTS class_protected BOOLEAN DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS class_code TEXT DEFAULT '';
