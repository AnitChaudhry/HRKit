# Roadmap

This document tracks features that have been **explicitly considered and deferred** rather than silently dropped. Each entry says *why* it was deferred, so the next person to look at it (or future-you) can judge whether the constraint still holds.

The bar for inclusion in HR-Kit is the project's stated moat:

1. **Single Python process** — no Docker, no Redis, no external services required to run.
2. **SQLite-backed** — one file you can copy / back up / inspect.
3. **BYOK / local-first** — your data stays on your machine; AI keys are user-supplied.
4. **One file per module** — `hrkit/modules/<name>.py` + an entry in the registry.

Anything that materially fights one of those four moats lives here, not in `hrkit/modules/`.

---

## Tier D — deferred (architecture-level)

### Mobile app (Android / iOS)

- **What it is:** Native or React-Native client for leave/attendance/timesheet on a phone.
- **Why deferred:** Not a Python module — needs a separate codebase (RN/Flutter/Swift+Kotlin), separate build pipeline, separate distribution (App Store / Play Store), and an authenticated REST surface that HR-Kit doesn't have today (the server is localhost-bound by design).
- **Smallest path forward:** A PWA wrapper around the existing HTML UI, served over Tailscale or a tunnel. Possible without breaking the moat — but still a separate workstream.
- **Revisit when:** A customer with >50 mobile-only employees asks. Until then, the desktop browser experience covers the use cases.

### LDAP / SSO / SAML

- **What it is:** Enterprise auth (Active Directory, Okta, Google Workspace SAML).
- **Why deferred:** HR-Kit is single-tenant local-first today — there is no auth at all (server binds to `127.0.0.1`). Adding LDAP/SSO requires designing the auth model first (sessions? JWT? per-employee access scopes?), which is its own design doc and meaningfully changes the threat model.
- **Smallest path forward:** Reverse-proxy auth (Caddy + Authelia or Tailscale identity headers) — push the problem to the proxy and keep HR-Kit auth-free. Document this in `docs/INSTALL.md` as a deployment recipe.
- **Revisit when:** A customer needs HR-Kit on a non-local-only deployment.

### Biometric / face-ID attendance

- **What it is:** Anti-fraud check-in via fingerprint reader, USB biometric pad, or webcam face match.
- **Why deferred:** Hardware integration. Each device family (ZKTeco, ESSL, Suprema, etc.) has its own SDK; webcam face-match needs a vision model and on-device inference. Neither fits "stdlib only" or "single Python process".
- **Smallest path forward:** A separate `hrkit-biometric` companion package that POSTs check-ins to the existing attendance API. Zero changes to core HR-Kit.
- **Revisit when:** Manufacturing/retail customers ask. Office-knowledge-worker customers don't need it.

### Geofencing / GPS-tagged check-in

- **What it is:** Check-in only valid inside a configured geofence.
- **Why deferred:** GPS only meaningfully exists on mobile. Without a mobile client, geofencing is theatre — browsers don't reliably expose accurate geolocation, and laptop-based check-in is by definition stationary.
- **Coupled to:** Mobile app (above). Build mobile first, then this.

### Multi-language UI (i18n)

- **What it is:** Translated UI strings (en/hi/es/fr/...).
- **Why deferred:** Cross-cutting refactor — every existing module's HTML rendering would need to be wrapped in a translation function. Adds runtime overhead and a string-extraction toolchain. Better done as a single dedicated phase later, not interleaved with feature work.
- **Smallest path forward:** Add a `_t("key")` helper and a `locale.json` bundle, migrate one module at a time.
- **Revisit when:** A non-English market deploy is in scope.

### ERPNext accounting hook

- **What it is:** Auto-post payroll runs to ERPNext as journal entries.
- **Why deferred:** Couples HR-Kit to a specific external ERP. Frappe HRMS does this because it lives inside Frappe. HR-Kit's BYOK philosophy says: emit a generic JSON/CSV ledger export, let the user wire it to whatever accounting system they use.
- **Smallest path forward:** Add a "Ledger export" button on payroll runs that produces a generic double-entry JSON. ERPNext-specific shim is then a 50-line glue script outside the package.
- **Revisit when:** Multiple customers request a specific accounting system. Pick the most-asked one and ship a Composio-style integration.

### Scheduled / automated database backups

- **What it is:** Cron-style nightly DB snapshots.
- **Why deferred:** A scheduler in-process means the server has to stay up, which fights "single Python process you start when you need it". OS-level cron + `cp hrkit.db backups/$(date +%F).db` is the right answer for a SQLite-backed app.
- **Smallest path forward:** Document the one-line cron recipe in `docs/INSTALL.md`. Optionally add `hrkit backup --to <path>` CLI command (no scheduler — just a one-shot copy).
- **Revisit when:** Customers ask for an in-app "Backup now" button (cheap to add) or scheduled (still defer to OS cron / Task Scheduler).

---

## How to graduate a Tier D item

1. Open an issue describing which moat constraint has changed.
2. Write a one-page design doc: data model, threat model (if auth-touching), and how it stays out of the four-moat hot path.
3. Move the entry from this file into `CHANGELOG.md` under the release that ships it.

If a constraint hasn't changed, the entry stays here. **Quietly building a Tier D item without revisiting the moat is the failure mode this document exists to prevent.**
