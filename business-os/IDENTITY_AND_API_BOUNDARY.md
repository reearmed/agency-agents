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

## Cryptographic Auth0 verifier component

`control_plane/auth0_jwt_verifier.py` now provides a concrete RS256 verifier backed by **PyJWT[crypto] 2.15.1**, pinned in `requirements-auth.txt`. It:
- accepts only an operator-configured HTTPS issuer origin and API audience;
- derives the JWKS URL from that exact issuer; no token or request can select a key URL;
- pins the accepted JWT algorithm to RS256 and requires a bounded `kid`;
- uses PyJWT's JWKS client with a 5-second fetch timeout, 5-minute JWKS cache and bounded 16-key signing-key LRU cache;
- requires RFC 9068 `at+jwt` type plus issuer, audience, expiry, issued-at, subject, client ID and token ID;
- rejects unsigned tokens, algorithm confusion, wrong signatures, wrong issuer/audience and malformed or oversized tokens.

PyJWT 2.15.1 is selected because its release includes the 2.14.0 security fixes for JWKS redirects and key handling, and the 2.15.0 parser-hardening fix. See [PyJWT 2.15.1 release metadata](https://pypi.org/project/PyJWT/2.15.1/), [PyJWT security changelog](https://pyjwt.readthedocs.io/en/stable/changelog.html) and [JWKS redirect advisory](https://github.com/advisories/GHSA-9v7f-9g4p-ffgj). The exact dependency must still be included in a future fully hash-locked deployment lockfile and scanned at release time.

Offline tests generate RSA keys and exercise real signature verification; they do not make network requests. The verifier is now suitable to inject into `IdentityBoundary`, but no Auth0 tenant, live JWKS fetch, API server, TLS endpoint, secret store, revocation integration or deployment exists. This does not close the production-authentication blocker.

