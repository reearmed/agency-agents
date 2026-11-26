# Business OS database — isolated project only

This directory contains a **reference schema**, not an executable migration.

## Non-negotiable boundary

- Create a separate Supabase project for Business OS.
- Do not apply this SQL to the existing NOREVYO production project.
- Keep `business_os` out of the Data API exposed schemas.
- Keep `anon` and `authenticated` without schema/table privileges.
- Access this database only from a private server-side worker using a dedicated secret held in a secret manager.
- Never expose a Supabase `service_role` or secret key to a browser or commit it to Git.

## Why private schema + RLS

Supabase distinguishes grants (whether a role can access an object) from RLS (which rows a role can access). The reference SQL creates a non-public schema, revokes access from `PUBLIC`, `anon` and `authenticated`, grants server-side access to `service_role`, and enables RLS on every table as defense in depth. No public-facing policies are created.

Do not add this schema to the project's exposed Data API schemas. New Supabase projects no longer automatically expose tables by default, but the design must not rely on that default.

## Tables

- `business_units`, `projects`: portfolio separation and budget ownership.
- `tasks`, `task_events`: durable task state and audit history.
- `approvals`: exact payload-hash-bound approval records.
- `artifacts`: report and output provenance.
- `experiments`: hypotheses, metrics and outcomes.
- `cost_events`: per-provider, model and task spend.
- `prospect_records`: minimized prospect data with source, purpose, lawful basis, suppression and retention metadata.
- `integration_grants`: metadata only; never secret values.

## Apply later

1. Create a new isolated Supabase project after the owner selects the organization and reviews the quoted cost.
2. Check the project is healthy.
3. Use the Supabase CLI to create a properly named migration in a local checkout, following the current CLI help and Supabase skill workflow.
4. Review this reference SQL, create the migration, and run it only against the new Business OS project.
5. Run Supabase security/performance advisors and database tests; verify grants, RLS, and that the schema is not exposed through Data API.
6. Test service-side access and confirm anonymous/authenticated access is denied.

The connected account currently exposes an existing NOREVYO production project. It has not been modified, and it is not a valid target for this schema.
