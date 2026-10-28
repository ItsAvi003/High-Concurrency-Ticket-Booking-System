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
