# Security and deployment boundary

**v0.1 is a single-user local authoring application, not a hardened multi-tenant SaaS.**
The server binds to 127.0.0.1 and refuses other addresses. Do not expose it through a
public tunnel or unauthenticated reverse proxy. A hosted product needs authentication,
per-user workspaces, real secret custody, authorization, concurrency/isolation, request
quotas, production HTTP serving, audits and network egress policy.

## What this release does

- Exact Host and same-origin checks, session token on writes and private project reads,
  request-size limits, restrictive page CSP and no cross-origin API policy.
- No model API credentials in drafts, browser storage, exports, or logs. A remote key
  saved with Save key is sealed outside the app for this user and loaded back into
  process memory only when that provider is selected.
- No execution of imported business APIs, remote refs or model-generated code.
- Whitelisted output paths, deterministic exports and checksum verification.
- Root HTTPS URLs for imported business APIs; explicitly opted-in loopback model access.
- No credential forwarding on redirects. Provider failures do not trigger automatic retries.
- Heuristic detection of common credential formats in briefs and exports.

These are not complete DLP or formal security guarantees. Arbitrary secret formats can
escape regex detection. Private data can occur in names and descriptions. Review every
public export. On Windows the saved key is sealed with DPAPI for the current user and the
secrets folder is limited to that user. On other systems it is sealed with a user-only
key file. Process memory, that folder, and environment variables are not protected from
the local owner or administrator by this application.

## Trust boundaries

The compiler owns its fixed control-loop requirements. Imported summaries and model
output are treated as draft data, but semantic prompt injection is not solved by a regex
or JSON schema. A future agent reading a malicious draft still needs a separate policy
boundary. Never execute third-party skill code just because its manifest validates.

The reference Controller's signatures authenticate host-issued statements, not external
truth. A compromised verifier can sign a false claim. Someone who can modify the database
or read the signing key can bypass in-process gates. Keep these outside the agent's
privileges in a real harness. Browser export approval covers a local artifact only.

DNS checks are not pinned-IP connections and do not constitute a full SSRF defense for
hosted deployments. The local application ignores ambient proxies; use approved outbound
firewall policy and a vetted transport when broader network access is required.

## Reporting

Do not publish secrets, exploit traffic or private project exports in an issue. For a
sensitive issue, use the repository owner's private security-reporting channel when a
remote repository is configured. No contact address or hosted reporting channel is
invented by this package.
