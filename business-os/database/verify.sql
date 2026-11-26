-- Run only against the isolated Business OS Supabase project after applying
-- reference-schema.sql as a reviewed migration. These checks are read-only.

-- 1) All expected tables exist and RLS is enabled.
SELECT
  n.nspname AS schema_name,
  c.relname AS table_name,
  c.relrowsecurity AS rls_enabled,
  has_table_privilege('anon', c.oid, 'SELECT') AS anon_can_select,
  has_table_privilege('authenticated', c.oid, 'SELECT') AS authenticated_can_select,
  has_table_privilege('service_role', c.oid, 'SELECT') AS service_role_can_select
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'business_os'
  AND c.relkind = 'r'
ORDER BY c.relname;

-- 2) The schema itself must not be usable by browser-facing roles.
SELECT
  has_schema_privilege('anon', 'business_os', 'USAGE') AS anon_schema_usage,
  has_schema_privilege('authenticated', 'business_os', 'USAGE') AS authenticated_schema_usage,
  has_schema_privilege('service_role', 'business_os', 'USAGE') AS service_role_schema_usage;

-- 3) The schema should not be included in PostgREST exposed schemas.
-- This is a dashboard/API-settings check, not fully inferable from SQL alone.
-- Verify manually in Supabase API settings; business_os must not be listed.

-- Expected:
-- - Every listed table has rls_enabled = true.
-- - anon_can_select and authenticated_can_select = false.
-- - service_role_can_select = true.
-- - anon_schema_usage and authenticated_schema_usage = false.
-- - service_role_schema_usage = true.
