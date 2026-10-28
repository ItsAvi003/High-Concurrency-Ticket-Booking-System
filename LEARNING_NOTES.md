# Learning Notes

Condensed revision notes, one section per phase.

---

## Phase 0: Project foundation

### What exists
- Docker Compose stack: `web` (Django dev server), `db` (Postgres 17), `redis` (Redis 7).
  `web` starts only after the `db` and `redis` healthchecks pass.
- Settings split: `base.py` (shared, reads env vars) -> `dev.py` / `prod.py` / `test.py`.
- Custom `accounts.User`: email login, no username, emails stored lowercase.
- `/health/live/` (process up) and `/health/ready/` (Postgres + Redis reachable, else 503).
- `RequestIdMiddleware` + `RequestIdFilter`: every log line and response carries `X-Request-ID`.
- Logs go to stdout; JSON in prod (`LOG_JSON=true`), readable text in dev.

### Concepts
- **12-factor config**: code is the same everywhere; environment variables change behaviour.
  Secrets never live in git (`.env` is gitignored, `.env.example` is the template).
- **Settings inheritance**: `from .base import *`, then override. Which file loads is chosen by
  `DJANGO_SETTINGS_MODULE`. `manage.py` defaults to dev, `wsgi.py` defaults to prod.
- **Custom user model first**: `AUTH_USER_MODEL` must be set before the first migration. Every
  FK to users points at that table; switching later means hand-written migrations on live data.
- **Manager vs model**: the manager (`User.objects`) owns table-level operations like
  `create_user`; the model owns row behaviour like `save()`.
- **`get_by_natural_key`**: what Django's auth backend calls at login. Overridden so login is
  case-insensitive.
- **Liveness vs readiness**: liveness failure means "restart me"; readiness failure means "stop
  sending me traffic". Liveness must not check dependencies, or a Redis blip restarts every pod.
- **ContextVar**: like a global, but each thread / async task sees its own value. Used to
  carry the request id to every log call without passing it around.
- **Logging filter vs formatter**: a filter can modify a record (we add `request_id`); a
  formatter turns the record into text or JSON.
- **Structured logging**: one JSON object per line, so you can query `status=503` instead of grepping.

### Decisions and tradeoffs
- Email-only login (custom manager) rather than keeping `username`: one identifier, no confusion.
- Lowercase the whole email, not just the domain. The RFC technically allows case-sensitive
  local parts, but no real provider uses that, and duplicate accounts are worse.
- Plain Django views for health checks, not DRF: probes should skip auth, throttling and content negotiation.
- Health checks have short timeouts: a hanging probe is worse than a failed one.
- Health response hides error details; full traceback goes to logs only.
- Request id is reset on the `request_finished` signal, not in the middleware, because Django
  writes its 4xx/5xx log lines after the middleware chain returns.
- Incoming `X-Request-ID` is accepted only if it matches `[A-Za-z0-9-_.]{1,64}` (prevents log injection).
- Django 5.2 LTS (security support to April 2028) over 6.0.

### Shortcuts (and the real-world version)
- Dev container runs `migrate` on start. In production, migrations run as a separate one-off
  job before the rollout, so several replicas don't race to migrate.
- Dev server (`runserver`) is used; gunicorn behind Nginx comes in Phase 8.
- Postgres/Redis passwords are trivial and in `.env`. Real deployments use a secrets manager.
- Redis readiness check opens a new connection per probe. Fine at probe frequency; app code
  will use a shared pool.
- Known gap: the Redis socket timeout (1s) does not cover DNS lookup. With the Redis container
  stopped, `/health/ready/` took ~4s to fail. Orchestrator probe timeouts must allow for it.

### Interview Q&A
1. **Why a custom user model on day one?** Changing `AUTH_USER_MODEL` after migrations exist
   breaks every FK to the user table and needs manual data migration. Django's docs recommend
   it for every new project, even if it starts identical to the default.
2. **Liveness vs readiness?** Liveness asks "is the process alive" and triggers a restart on
   failure; it must not depend on Postgres/Redis or an outage restarts everything in a loop.
   Readiness asks "can I serve traffic"; failure removes the instance from the load balancer.
3. **How do you trace one request through logs?** A request id is generated (or accepted from
   Nginx), stored in a ContextVar, added to every record by a logging filter, and returned in
   `X-Request-ID`. A user can quote that id and you search logs for it.
4. **Why ContextVar, not a global or thread-local?** A global is shared by all threads, so concurrent
   requests overwrite each other. Thread-locals break under async. ContextVar works for both.
5. **How are secrets handled?** Read from environment variables via django-environ. `.env` is
   gitignored and dockerignored; `.env.example` documents the keys. `DJANGO_SECRET_KEY` has no
   default, so a misconfigured deploy fails at startup instead of running with a weak key.

---

## Phase 1: Auth and roles

### What exists
- `User.role`: `user` | `organizer` | `admin` (TextChoices, default `user`). Migration 0002 adds
  it; data migration 0003 promotes existing superusers to `admin` (reversible).
- SimpleJWT: login `/auth/token/`, refresh `/auth/token/refresh/` (rotation + blacklist),
  logout `/auth/logout/` (blacklists refresh). Access 15 min, refresh 7 days.
- `/auth/register/` (always role `user`), `/auth/me/`, admin-only `/users/` and `/users/<id>/role/`.
- Permissions in `apps/accounts/permissions.py`: `HasRole` base, `IsOrganizer` (organizer or
  admin), `IsAdminRole`, object-level `IsOwnerOrAdminRole` (for bookings later).
- DRF defaults: JWT auth only, `IsAuthenticated` everywhere unless a view opts out, JSON only,
  page-number pagination (20).

### Concepts
- **Authentication vs authorization**: authN = who are you (JWT check, 401 if it fails);
  authZ = what may you do (permission classes, 403 if denied).
- **401 vs 403**: 401 = no or invalid credentials (with `WWW-Authenticate: Bearer`); 403 = we know
  who you are, and the answer is no.
- **JWT**: `header.payload.signature`, base64url-encoded. The payload is *readable by anyone*,
  only *tamper-proof* (HMAC-SHA256 with SECRET_KEY). Never put secrets in it.
- **Access vs refresh token**: access is short-lived and sent on every request; refresh is
  long-lived and only sent to `/token/refresh/` to get new access tokens.
- **Stateless vs stateful**: access tokens are verified without a DB lookup of the token
  (stateless), so they can't be revoked before expiry. Refresh tokens are tracked in the
  `token_blacklist` tables (stateful), which is what makes logout possible.
- **Rotation**: each refresh issues a new refresh token and blacklists the old one. A stolen
  refresh token dies as soon as either party uses it, and replay is detectable.
- **Permission classes**: `has_permission` runs for every request; `has_object_permission`
  runs only when the view calls `get_object()`. All listed classes must pass (AND).
- **Secure by default**: global `IsAuthenticated`; public views opt out with `AllowAny`.
- **Mass assignment / privilege escalation**: `RegisterSerializer.fields` omits `role`, so
  `{"role": "admin"}` in the body is silently ignored.
- **Data migration**: `RunPython` with `apps.get_model()` (the historical model), plus a
  reverse function so the migration can be rolled back.
- **HS256 key length**: the HMAC key must be at least 32 bytes (RFC 7518). pytest turns
  `InsecureKeyLengthWarning` into an error.

### Decisions and tradeoffs
- Role is **not** in the JWT. `JWTAuthentication` loads the user from the DB on each request,
  and permissions read `request.user.role`, so demotion is immediate (tested). Cost: one
  indexed PK lookup per request. A claim would only save that lookup, and it would go stale
  for up to 15 minutes.
- Role separate from `is_staff`: the API admin role and Django-admin-site access are different
  concerns. `createsuperuser` sets both.
- Admins can't change their own role, to avoid locking out the last admin.
- Admin implies organizer (`IsOrganizer` allows admin), so there's no separate admin-only copy of organizer views.
- Registration returns the user, not tokens; the client logs in next. Simpler, and the
  signup and login flows stay separate (e.g. to add email verification later).
- The duplicate-email race is handled by the DB unique index + `IntegrityError` -> 400 inside
  `transaction.atomic()` (savepoint). The `exists()` check alone is not enough.
- Same 401 message for wrong password and unknown email (no user enumeration via login).

### Shortcuts (and the real-world version)
- **No rate limiting on login/register yet**, so brute force is possible. Added in Phase 6
  (Redis-backed throttling, stricter scope on auth endpoints).
- Blacklist tables grow forever. Real: run `manage.py flushexpiredtokens` daily (Celery beat, Phase 6).
- Tokens are returned in the JSON body. A browser SPA would ideally keep the refresh token in
  an httpOnly, Secure, SameSite cookie to protect it from XSS. That brings CSRF back into scope.
- HS256 with SECRET_KEY. With many services verifying tokens, use RS256 (private key signs,
  public key verifies) so verifiers can't mint tokens.
- No email verification or password reset yet.
- Registration still reveals that an email exists ("already exists"). Real systems often return
  the same response either way and send an email instead.

### Interview Q&A
1. **How does JWT auth work in your project?** Login posts email + password to `/auth/token/`;
   Django's ModelBackend checks the PBKDF2 hash and SimpleJWT returns a 15-min access and 7-day
   refresh token signed with HS256. Clients send `Authorization: Bearer <access>`.
   `JWTAuthentication` verifies the signature and expiry, then loads the user by id.
2. **How do you log out with stateless JWTs?** You can't revoke the access token. It expires in
   15 minutes, which is why it's short. Logout blacklists the *refresh* token in the DB, so no
   new access tokens can be minted. Rotation also blacklists every used refresh token.
3. **Why not put the role in the token?** Because permission checks would trust a value that
   can be up to 15 minutes stale. A demoted admin would keep admin powers. We read role from the
   DB-loaded user, and a test proves a demotion takes effect on the very next request with the
   old token.
4. **401 vs 403?** 401: authentication missing or failed (no token, expired, tampered), with a
   `WWW-Authenticate` header. 403: authenticated, but the permission class says no
   (a `user` calling `/users/`).
5. **How do you stop someone registering as admin?** The serializer's `fields` doesn't include
   `role`, so the input is ignored and the model default (`user`) applies. Roles only change via
   `PATCH /users/<id>/role/`, guarded by `IsAdminRole`. There's a test that posts `role=admin,
   is_staff=true` and asserts a plain user is created.
