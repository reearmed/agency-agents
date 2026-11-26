-- Reference schema for a NEW, isolated Business OS Supabase project.
-- NOT a migration. Do not execute against NOREVYO production.
-- Keep this schema private: do not add business_os to Data API exposed schemas.
BEGIN;

CREATE SCHEMA IF NOT EXISTS business_os;
REVOKE ALL ON SCHEMA business_os FROM PUBLIC, anon, authenticated;
GRANT USAGE ON SCHEMA business_os TO service_role;

CREATE TABLE business_os.business_units (
  unit_key text PRIMARY KEY CHECK (unit_key IN ('norevyo','automation_services','digital_products','shared')),
  display_name text NOT NULL,
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','paused','archived')),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE business_os.projects (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  unit_key text NOT NULL REFERENCES business_os.business_units(unit_key) ON DELETE RESTRICT,
  slug text NOT NULL,
  name text NOT NULL,
  objective text NOT NULL,
  status text NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed','active','paused','completed','cancelled')),
  priority integer NOT NULL DEFAULT 3 CHECK (priority BETWEEN 1 AND 5),
  monthly_budget_usd numeric(14,2) CHECK (monthly_budget_usd IS NULL OR monthly_budget_usd >= 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (unit_key, slug)
);

CREATE TABLE business_os.tasks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid REFERENCES business_os.projects(id) ON DELETE RESTRICT,
  unit_key text NOT NULL REFERENCES business_os.business_units(unit_key) ON DELETE RESTRICT,
  parent_task_id uuid REFERENCES business_os.tasks(id) ON DELETE RESTRICT,
  title text NOT NULL,
  objective text NOT NULL,
  status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','triaged','planned','running','review','staged','awaiting_approval','approved','executed','verified','closed','rejected','cancelled','failed','expired','blocked')),
  risk_tier text NOT NULL CHECK (risk_tier IN ('R0','R1','R2','R3','R4')),
  data_classification text NOT NULL CHECK (data_classification IN ('public','internal','confidential','restricted')),
  assigned_agent text,
  allowed_tools text[] NOT NULL DEFAULT '{}',
  forbidden_actions text[] NOT NULL DEFAULT '{}',
  input jsonb NOT NULL DEFAULT '{}'::jsonb,
  output jsonb,
  budget_limit_usd numeric(14,4) CHECK (budget_limit_usd IS NULL OR budget_limit_usd >= 0),
  actual_cost_usd numeric(14,4) NOT NULL DEFAULT 0 CHECK (actual_cost_usd >= 0),
  idempotency_key text UNIQUE,
  deadline timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX tasks_status_created_idx ON business_os.tasks(status, created_at);
CREATE INDEX tasks_unit_status_idx ON business_os.tasks(unit_key, status);
CREATE INDEX tasks_project_idx ON business_os.tasks(project_id);

CREATE TABLE business_os.task_events (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  task_id uuid NOT NULL REFERENCES business_os.tasks(id) ON DELETE RESTRICT,
  event_type text NOT NULL,
  actor_type text NOT NULL CHECK (actor_type IN ('operator','orchestrator','agent','system','integration')),
  actor_id text,
  details jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX task_events_task_created_idx ON business_os.task_events(task_id, created_at);

CREATE TABLE business_os.approvals (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  task_id uuid NOT NULL REFERENCES business_os.tasks(id) ON DELETE RESTRICT,
  action text NOT NULL,
  target text NOT NULL,
  payload_sha256 char(64) NOT NULL CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
  amount numeric(14,2) CHECK (amount IS NULL OR amount >= 0),
  currency char(3),
  risk_tier text NOT NULL CHECK (risk_tier IN ('R3','R4')),
  rollback_plan text NOT NULL,
  decision text NOT NULL DEFAULT 'pending' CHECK (decision IN ('pending','approved','rejected','expired')),
  approver text,
  decided_at timestamptz,
  expires_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK ((decision = 'pending' AND approver IS NULL AND decided_at IS NULL) OR (decision <> 'pending' AND approver IS NOT NULL AND decided_at IS NOT NULL))
);

CREATE INDEX approvals_pending_expiry_idx ON business_os.approvals(decision, expires_at);

CREATE TABLE business_os.artifacts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  task_id uuid NOT NULL REFERENCES business_os.tasks(id) ON DELETE RESTRICT,
  storage_uri text NOT NULL,
  sha256 char(64) CHECK (sha256 IS NULL OR sha256 ~ '^[0-9a-f]{64}$'),
  mime_type text,
  data_classification text NOT NULL CHECK (data_classification IN ('public','internal','confidential','restricted')),
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE business_os.experiments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  unit_key text NOT NULL REFERENCES business_os.business_units(unit_key) ON DELETE RESTRICT,
  project_id uuid REFERENCES business_os.projects(id) ON DELETE RESTRICT,
  name text NOT NULL,
  hypothesis text NOT NULL,
  primary_metric text NOT NULL,
  guardrails jsonb NOT NULL DEFAULT '{}'::jsonb,
  status text NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed','approved','running','paused','completed','stopped')),
  starts_at timestamptz,
  ends_at timestamptz,
  result jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE business_os.cost_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  task_id uuid REFERENCES business_os.tasks(id) ON DELETE RESTRICT,
  unit_key text NOT NULL REFERENCES business_os.business_units(unit_key) ON DELETE RESTRICT,
  provider text NOT NULL,
  model text,
  quantity numeric(18,6),
  unit text,
  amount numeric(14,6) NOT NULL CHECK (amount >= 0),
  currency char(3) NOT NULL DEFAULT 'USD',
  occurred_at timestamptz NOT NULL DEFAULT now(),
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX cost_events_unit_date_idx ON business_os.cost_events(unit_key, occurred_at);

-- Contact/lead records are intentionally metadata-minimal. Keep outreach disabled
-- until lawful basis, source, retention and suppression checks are implemented.
CREATE TABLE business_os.prospect_records (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  unit_key text NOT NULL REFERENCES business_os.business_units(unit_key) ON DELETE RESTRICT,
  organization_name text NOT NULL,
  contact_name text,
  contact_address text,
  source_url text NOT NULL,
  collected_at timestamptz NOT NULL DEFAULT now(),
  purpose text NOT NULL,
  lawful_basis text NOT NULL,
  consent_evidence text,
  suppression_status text NOT NULL DEFAULT 'not_suppressed' CHECK (suppression_status IN ('not_suppressed','suppressed','unknown')),
  retention_until timestamptz NOT NULL,
  notes text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX prospect_suppression_retention_idx ON business_os.prospect_records(suppression_status, retention_until);

-- Store grant metadata only. Secret values live in a dedicated secret manager.
CREATE TABLE business_os.integration_grants (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  integration text NOT NULL,
  environment text NOT NULL CHECK (environment IN ('development','staging','production')),
  scopes text[] NOT NULL DEFAULT '{}',
  status text NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed','active','revoked','expired')),
  granted_by text,
  expires_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- Private-schema, backend-only access. No anon/authenticated policies are created.
ALTER TABLE business_os.business_units ENABLE ROW LEVEL SECURITY;
ALTER TABLE business_os.projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE business_os.tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE business_os.task_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE business_os.approvals ENABLE ROW LEVEL SECURITY;
ALTER TABLE business_os.artifacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE business_os.experiments ENABLE ROW LEVEL SECURITY;
ALTER TABLE business_os.cost_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE business_os.prospect_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE business_os.integration_grants ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON ALL TABLES IN SCHEMA business_os FROM PUBLIC, anon, authenticated;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA business_os FROM PUBLIC, anon, authenticated;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA business_os TO service_role;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA business_os TO service_role;

ALTER DEFAULT PRIVILEGES IN SCHEMA business_os
  REVOKE ALL ON TABLES FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA business_os
  GRANT ALL ON TABLES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA business_os
  REVOKE ALL ON SEQUENCES FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA business_os
  GRANT ALL ON SEQUENCES TO service_role;

COMMIT;
