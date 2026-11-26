# Identity and API boundary

**Status: local identity-validation component and contract only. No HTTP API, identity provider, or production authentication is deployed.**

## Trust model

Agents and retrieved content are untrusted. A model-supplied actor name, role, approval flag, bearer claim, or JSON field is never proof of identity. The future API must authenticate every request before it reaches the task, approval, budget, or execution services.

The local `control_plane/identity_boundary.py` component provides:
- strict bounded Bearer-header parsing;
- an injected token-verifier seam;
- issuer and audience pinning;
- required subject and token identifier claims;
- expiry, not-before, issued-at, clock-skew and maximum-lifetime checks;
- normalized scopes and roles, filtered through an explicit Business OS scope/role allowlist; unknown scopes and roles are discarded;
- a minimal immutable principal that does not retain the bearer token;
- exact-scope authorization and a human-approver callback suitable for the existing approval-grant authority.

The component deliberately does not parse or verify JWT signatures itself. The injected verifier must be backed by a real identity provider and must validate the signature using a pinned algorithm allowlist, trusted issuer metadata/JWKS, key rotation and revocation policy. A test lambda or caller-provided claims object is not an authenticator.

## Expected token claims

| Claim | Requirement |
|---|---|
| `iss` | Exact configured issuer |
| `sub` | Non-empty stable principal identifier |
| `aud` | Contains the Business OS API audience |
| `jti` | Non-empty token identifier |
| `iat`, `exp` | Finite numeric timestamps; expiry and maximum lifetime enforced |
| `nbf` | Optional numeric not-before timestamp |
| `scope` | Space-delimited OAuth scopes |
| `roles` | Array of role strings |

The OpenAPI route scope/role extensions are tested against the same allowlist so a new route cannot silently introduce an unsupported permission. The internal independent-verifier service uses the separate `business-os:verification:record` scope and `business-os:independent-verifier` role; its subject must differ from requester and executor. The human approval callback requires all three: the verified principal subject matches the approver ID, scope includes `business-os:approval:decide`, and role includes `business-os:human-approver`. Agent identities cannot satisfy the human role by setting a request field.

## Machine-readable API contract

`business-os/api/openapi.yaml` defines the intended authenticated API surface. It includes task proposals, safe task reads, internal artifact staging, approval requests/decisions, immutable period-budget configuration and kill-switch activation. It intentionally exposes no execution or adapter route. The API contract has static CI checks for required bearer security, route scopes, sensitive-operation roles, strict request schemas and unique operation IDs. The server URL is a placeholder and no server is deployed.\n\n## Candidate identity provider (not provisioned)

**Preferred managed candidate: Auth0 Public Cloud Canada, Essentials.** Auth0 documents a Canadian public-cloud region, selectable when creating a tenant; the resulting issuer uses the `.ca.auth0.com` domain. The current pricing page lists Essentials at **US$35/month**, up to 500 monthly active users, with Pro MFA and role-based access control. The pricing comparison lists 1,000 machine-to-machine authentications on Essentials, but the unit/quota semantics and expected service-token refresh rate must be confirmed before relying on it. Professional is listed at US$240/month and includes an M2M-token add-on; do not upgrade without a separate cost review.

Why this is the leading candidate:
- Canadian public-cloud tenant region is explicitly available, supporting a Canadian data-residency target.
- Essentials includes MFA and RBAC; Auth0 Free's higher 25,000-MAU allowance does not include Pro MFA.
- Auth0 supports the OIDC client-credentials flow for backend service identities. Cache short-lived service tokens securely and avoid a token request per agent tool call.
- The API's issuer/audience, scopes and role claims can be pinned to the selected tenant and resource server.

Alternatives reviewed:
- ZITADEL Cloud Free is US$0 but its listed residency options are EU, US, Switzerland and Australia—not Canada. Self-hosted ZITADEL can run in a chosen Canadian region, but adds deployment, patching, backup and availability responsibility.
- Clerk's current security page says regional data residency is not offered and data is US-hosted; it is not suitable if Canadian residency is a hard requirement.
- WorkOS AuthKit advertises a free tier, but its security review says customer data is hosted in AWS us-east-1 with backups in us-west-2; not suitable for a strict Canadian-only data boundary.

For the Auth0 candidate, the planned integration is: register a custom API with the exact Business OS scopes; enable RBAC and the **Add Permissions in the Access Token** setting; use the RFC 9068 JWT access-token profile and verify that issued tokens contain the required `jti`; add human roles as a namespaced access-token claim and configure `IdentityBoundary(role_claim="https://norevyo.com/claims/roles")`. The documented Auth0 Post-Login Action pattern is:

```javascript
exports.onExecutePostLogin = async (event, api) => {
  if (event.authorization) {
    api.accessToken.setCustomClaim(
      'https://norevyo.com/claims/roles',
      event.authorization.roles,
    );
  }
};
```

Machine identities must use separate client-credentials applications and service-specific scopes/roles; they must never receive the human-approver role. Configure and test the exact machine-token claim mapping separately. No real token or Auth0 Action has been created.

This is a research recommendation, not a selected provider or purchase. Before selection, confirm Canadian tenant availability for the exact plan, DPA/subprocessors, backup/log location, M2M quotas, token lifetime/rotation, revocation behavior and any restrictions on machine identities. No tenant has been created and no credentials are stored.

Sources:
- [Auth0 pricing](https://auth0.com/pricing)
- [Auth0 Public Cloud in Canada announcement](https://auth0.com/changelog?version=v202631)
- [Auth0 Client Credentials Flow](https://auth0.com/docs/get-started/authentication-and-authorization-flow/client-credentials-flow)
- [ZITADEL pricing and cloud residency](https://zitadel.com/pricing)
- [Clerk security and residency](https://clerk.com/security)
- [WorkOS security review and hosting regions](https://workos.com/blog/workos-security-review)

## Minimum API middleware sequence

1. Enforce TLS at the edge; reject oversized headers and request bodies.
2. Extract one Bearer token and validate it through the trusted identity provider verifier.
3. Construct a `VerifiedPrincipal`; never accept a principal or claims object from the request body.
4. Authorize the exact route scope and resource ownership server-side.
5. Apply tenant/account/environment scoping to every database lookup.
6. Validate request schemas with unknown fields rejected.
7. Persist an audit event for the authenticated actor, request ID, policy version and payload hash; redact credentials and unnecessary personal data.
8. For consequential writes, freeze the exact payload and scope, request human approval, issue a short-lived one-use grant, and send only that grant to a narrow adapter service.
9. Require independent target-system verification before terminal success or budget settlement.
10. Return non-sensitive status only; never expose signing keys, provider tokens, database paths, or raw adapter credentials.

## Required scopes

Suggested route scopes (the API implementation must enforce these server-side):

- `business-os:read`: read safe operational summaries;
- `business-os:task:submit`: submit a task proposal;
- `business-os:artifact:write`: stage an internal draft/artifact;
- `business-os:approval:request`: request human review;
- `business-os:approval:decide`: approve or reject a frozen action as a human approver;
- `business-os:budget:configure`: configure an immutable period cap;
- `business-os:kill-switch:activate`: engage the emergency stop.

There is intentionally no agent scope for approving, settling, releasing budgets, clearing the kill switch, or invoking external integrations. There is no kill-switch clear operation in the current prototype.

## Production gates still open

- Select an identity provider and confirm its Canadian data residency and contractual terms.
- Implement a cryptographic OIDC/JWT verifier with issuer pinning, algorithm allowlisting, JWKS rotation, revocation and key-compromise response.
- Deploy an authenticated API with CSRF protections where cookies are used, rate limits, request-size limits, tenant isolation and server-side authorization.
- Separate human approver, runtime worker, adapter and verifier service identities.
- Add independently administered signing-key storage/rotation and grant revocation.
- Move durable coordination to a supported multi-host transactional service/queue with tested recovery.
- Move audit copies and encrypted backups off-host; test restore and incident response.
- Complete threat modelling, dependency review, penetration testing and privacy/legal review.

Until these gates are independently implemented and tested, this module is a tested local reference boundary only. Do not connect real adapters, customer data, payment systems, publishing, email, or production infrastructure.
