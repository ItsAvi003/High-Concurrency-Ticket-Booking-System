# High-Concurrency Ticket Booking System

Django + DRF + PostgreSQL + Redis + Celery backend that sells the last seat exactly once.
See [PROJECT_SPEC.md](PROJECT_SPEC.md) for the goals and [LEARNING_NOTES.md](LEARNING_NOTES.md)
for per-phase design notes.

## Quick start

Requires Docker Desktop.

```bash
cp .env.example .env
docker compose up --build          # web on http://localhost:8000
curl http://localhost:8000/health/ready/
docker compose run --rm web pytest # test suite against real Postgres + Redis
docker compose exec web python manage.py createsuperuser   # gets role=admin
```

Roles: `user` books tickets, `organizer` manages events, `admin` manages the platform.
Send the access token as `Authorization: Bearer <token>`.

## Endpoints so far

| Method | Path             | Purpose                                         |
|--------|------------------|-------------------------------------------------|
| GET    | `/health/live/`  | Liveness: process is up, no dependency checks   |
| GET    | `/health/ready/` | Readiness: Postgres and Redis reachable, or 503 |
| -      | `/admin/`        | Django admin                                    |
| POST   | `/api/v1/auth/register/`      | Sign up (always role `user`)        |
| POST   | `/api/v1/auth/token/`         | Login: email + password -> access + refresh JWT |
| POST   | `/api/v1/auth/token/refresh/` | New access + rotated refresh token  |
| POST   | `/api/v1/auth/logout/`        | Blacklist a refresh token           |
| GET    | `/api/v1/auth/me/`            | Current user (any role)             |
| GET    | `/api/v1/users/`              | List users (admin role)             |
| PATCH  | `/api/v1/users/<id>/role/`    | Change a user's role (admin role)   |

## Progress

- [x] Phase 0: Project foundation
- [x] Phase 1: Auth and roles
- [ ] Phase 2: Core domain models and read APIs
- [ ] Phase 3: Concurrency-safe booking
- [ ] Phase 4: Seat hold with expiry
- [ ] Phase 5: Idempotent payment flow (Razorpay)
- [ ] Phase 6: Async work and reliability
- [ ] Phase 7: Performance
- [ ] Phase 8: Production readiness
