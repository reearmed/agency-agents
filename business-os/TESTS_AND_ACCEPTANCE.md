# Tests and acceptance criteria

**No production systems or live customer data are required.** Tests use synthetic fixtures and isolated mock destinations only.

## Historical GitHub Actions audit

The complete feature-branch Actions run list was retrieved through the GitHub REST API: **327 workflow runs** were returned across four pages. **301 succeeded and 26 failed**. The failures cluster around intermediate commits during rapid incremental development; the current branch later moved beyond those broken intermediate states.

| Failed run(s) | Root cause found in job logs | Disposition |
|---|---|---|
| 45891310364 (run 300) | Auth0 test imported PyJWT before the dependency-installation step existed | Dependency installation was added to CI |
| 45891329453 (301), 45891332610 (302), 45891335000 (303), 45891339682 (304), 45891387917 (305) | Duplicate `max_cached_keys` keyword caused a Python SyntaxError in an intermediate verifier revision | Corrected in subsequent verifier commit |
| 45891391746 (306), 45891408404 (307), 45891429255 (308), 45891440184 (309), 45891467213 (310), 45891517452 (311) | Expiry-negative test depended on a module-import timestamp and did not remain outside the verifier's clock leeway in the actual test run | Test now derives expiry/issued-at timestamps at execution time and places expiry 120 seconds in the past |
| 45885368491 (run 247) | Identity-to-approval integration used a fixed identity clock but the grant authority's real wall clock | Test now passes the same explicit UTC instant to grant issuance and consumption |
| 45876023214 (150) | Budget settlement test attempted settlement before independent terminal reconciliation | Test and evidence-gated settlement flow were updated |
| 45876736008 (173), 45876746865 (174), 45876752008 (175), 45876784218 (176) | Intermediate budget fixture changes: required budget object was missing, then JSON fixture syntax was malformed | Fixture and schema were corrected |
| 45877138043 (189) | Durable destination tests had not yet supplied an approved execution intent after the destination boundary was hardened | Tests and gateway intent binding were updated |
| 45874973038 (120) | Backup test omitted the standard-library `stat` import | Test import was corrected |
| 45874652682 (103) | Durable gateway tests used the earlier constructor contract after the implementation began requiring an explicit SQLite mock destination and verifier | Tests and implementation contract were brought into alignment |
| 45874349452 (91) | Intermediate durable execution test file had a syntax error | Corrected in the next revision |
| 45873958820 (76), 45873912362 (75), 45873865211 (74) | SQLite row access expected named columns before the connection row factory was configured | Row-factory setup was corrected |
| 45873263806 (62) | Approval grant test fixtures used inconsistent timestamps, so grants were expired at verification | Deterministic clock handling was added |

The latest pre-audit successful run was [45891971022](https://github.com/reearmed/agency-agents/actions/runs/45891971022), with 176 Python tests and the synthetic durable E2E passing. The current audit adds two more tests (178 expected) and corrects the two time-dependent test defects above. The workflow now cancels superseded runs on the same ref so rapid pushes do not leave a queue of stale test runs. Hosted verification of these latest changes is still pending.

## Critical security tests

| Test | Expected result |
|---|---|
| Agent attempts direct email, payment, publishing, browser or shell action | Denied; no credential or route available |
| Agent attempts to approve its own proposal | Denied |
| Proposal payload or target changes after approval | Hash/scope mismatch; denied |
| Approval expires or is replayed | Denied |
| Two workers claim the same intent | Exactly one claim |
| Two requests reuse an idempotency key for different payloads | Denied |
| Budget service or audit store is unavailable | Paid/external action denied |
| Kill switch is active or unavailable | New execution denied |
| Adapter times out after destination acceptance | State becomes UNKNOWN; reconcile before retry |
| Independent verifier cannot confirm target state | No success claim |
| Malformed or oversized approval token | Rejected before grant verification; no parser exception |
| Bearer token has wrong signature, issuer, audience, time or identity claims | Authentication denied |
| OpenAPI protected route offers an anonymous or weaker alternative in its security array | Rejected; only the single supported bearerAuth requirement is accepted |
| Runtime modules are imported through the documented `control_plane` package path | All control-plane runtime modules import without relying on the current working directory |
| Human approval is attempted without exact subject, scope and human role | Denied |
| Agent-supplied role/approval field is present | Ignored; authorization comes from verified principal only |
| Retrieved content contains prompt injection | Treated as untrusted; no policy or tool permission change |
| Independent verifier is the requester or executor | Denied |
| Destination evidence has wrong target, payload hash or idempotency key | Denied |
| Destination evidence source is untrusted or authentication fails | No terminal outcome |
| Destination evidence is stale, future-dated or inconclusive | No terminal outcome |

## Functional acceptance

- [ ] Nine agent workspaces are isolated and each has only its declared tools.
- [ ] Agent-to-agent messaging is disabled except the orchestrator's explicit delegation path.
- [ ] All child sessions require sandboxing and fail closed when unavailable.
- [ ] Task state transitions are enforced server-side.
- [ ] Approval records bind to canonical payload hash, adapter, action, target, requester and idempotency key.
- [ ] Budget is reserved before paid work and reconciled afterward.
- [ ] Monthly and per-task caps stop work at the configured ceiling.
- [ ] Kill switches work at the business, agent and integration boundaries.
- [ ] Audit events survive restart and tampering is detected.
- [ ] Independent verification is required for every external side effect.
- [ ] Synthetic end-to-end tests pass with external integrations disabled.
- [ ] Backup restore and incident recovery are tested before pilot.
- [ ] Production identity provider, authenticated API, authorization and tenant isolation are independently reviewed.
- [ ] Off-host encrypted backup and multi-host recovery are proven before continuous operation.

## Pilot exit criteria

Run a 7-day internal-only pilot using synthetic or explicitly approved low-risk internal data. Require zero unauthorized writes, zero production access, complete audit traceability, no duplicate side effects, exact approval enforcement, spend within the approved cap, and a documented pause/recovery drill. Any failed critical security test blocks activation of external integrations.

## Current prototype evidence (26 November 2026)

Latest feature-branch CI run: [45891848185](https://github.com/reearmed/agency-agents/actions/runs/45891848185), on commit `81b6d76971e91d9f48ecc7e4c576f819e906f4ba`.

Verified by hosted CI:
- **176 Python unit tests passed** (`Ran 176 tests ... OK`), including real offline RSA signature verification through the Auth0 RS256 verifier and server-side OpenAPI route authorization.
- Six JSON Schema fixtures passed.
- JSON, YAML and JSON5 configuration parsing passed.
- OpenClaw example policy assertions passed, including explicit deny/allow lists, disabled cross-agent access, tree session visibility, disabled elevated/cron/restart, Docker network/root/capability controls and orchestrator-only delegation.
- Synthetic bootstrap safety harness passed.
- Budget-enabled synthetic durable control-plane E2E passed, including restart recovery, destination reconciliation, budget settlement, private backup verification and kill-switch enforcement.

The latest changes also add strict bounded approval-token routing parsing, identity-boundary and identity-to-approval integration tests, a machine-readable OpenAPI contract, a separate independent destination-evidence verifier contract, and a pinned PyJWT 2.15.1 Auth0 RS256/JWKS verifier and fail-closed OpenAPI route-authorization helper.

### Follow-up security audit (26 November 2026)

The hosted run above was inspected at job-log level: all seven configured workflow steps completed successfully, 176 tests passed in 2.495 seconds, and the synthetic durable E2E passed. This is evidence for that run only; the available GitHub connector exposes commit-associated pull-request runs rather than the complete push-run history, so it cannot establish the cause or count of every failed run visible in the Actions UI.

A code review found that the route authorizer accepted a protected OpenAPI security array if it contained any `bearerAuth` entry. OpenAPI security arrays express OR alternatives, so a second empty-object alternative could advertise anonymous access even though the helper still required a verified principal. The helper now accepts only one exact `bearerAuth: []` requirement and rejects anonymous, additional-scheme and malformed alternatives. A regression test covers these cases. A second portability review found that several runtime modules used top-level-only imports, which would fail when the future API imports them as `control_plane.*` from the repository root. The runtime modules now support both package imports and direct script/test imports, and a subprocess smoke test imports the full runtime module set as a package. The latest pre-fix hosted evidence remains 176 tests; the two new regression tests bring the expected suite count to 178, pending hosted CI verification. Do not count either new test as passed until a new run completes.
 The verifier pins issuer/audience and RS256, derives the JWKS URL from a trusted HTTPS issuer, bounds key fetch/cache, requires RFC 9068 `at+jwt` tokens with `jti` and `client_id`, and is integrated with the identity boundary in offline RSA tests. Route authorization evaluates server-owned OpenAPI policies, requires all declared scopes/roles and rejects missing or unsupported policies; CI walks every route. Tests bind verifier identity separately from requester/executor, require exact destination evidence, reject unauthenticated, stale, mismatched or inconclusive outcomes, and exercise namespaced Auth0-style role claims. API scope/role extensions are checked against the identity allowlist.

These results validate local reference code only. They do not constitute production acceptance. No deployed HTTP API, Auth0 tenant, live JWKS verification, production revocation/session service, independent external verifier, real adapter, hosted queue, multi-host coordination, provider invoice metering, off-host backup automation, OpenClaw runtime validation or 7-day pilot exists yet. The OpenClaw configuration remains an example, not an installed or runtime-validated system. No user Mac install, database creation, production access, paid provisioning or deployment has occurred.

## Remaining activation blockers

1. Configure and verify the concrete RS256/JWKS component against a real Auth0 Canada tenant; add production-grade revocation/session strategy, dependency lockfile hashes, key-rotation drill and live JWKS failure tests.
2. Authenticated API with server-side route scopes, tenant/resource isolation, request limits, rate limits and secure session handling.
3. Independently administered signing-key storage, rotation and grant revocation.
4. Independent destination verifier and evidence retrieval for every real adapter.
5. Multi-host durable queue/coordination and externally managed emergency control.
6. Encrypted off-host backup, retention, restore drills and incident alerting.
7. Pinned OpenClaw schema/runtime validation and sandbox smoke tests.
8. Threat model, dependency review, privacy/legal review and security testing.
9. Approved infrastructure, model provider and hard spend ceilings.


## HTTP transport boundary addition (26 November 2026)

A guarded stdlib HTTP transport shell now exists at
`control_plane/http_api.py`. It loads the server-owned OpenAPI contract,
matches documented method/path pairs, authenticates protected routes through
the existing identity boundary, applies route-level scope/role authorization,
limits JSON request bodies to 64 KiB, rejects transfer-encoding requests,
avoids logging request data, and emits no-store JSON responses. It binds only
to loopback when started through its `serve` entry point.

The only implemented operation is public `GET /healthz`. Every other
documented operation returns 501 after authentication and authorization.
There is no task persistence wiring, tenant-scoped data access, artifact
storage, approval workflow HTTP handler, budget handler, kill-switch handler,
TLS, rate limiting, reverse proxy, or deployed server. This is transport
scaffolding, not a usable production API.

Nine synthetic loopback tests were added for health, missing/invalid
credentials, insufficient scopes, protected-but-unimplemented routes,
request-size enforcement, unknown routes, and query rejection. The expected
suite count is now **187 Python tests**, pending a new hosted Actions run. Do
not count these tests as passing until the workflow completes successfully.
PyYAML is pinned alongside the JWT verifier dependency because the transport
loads the trusted YAML OpenAPI contract.
