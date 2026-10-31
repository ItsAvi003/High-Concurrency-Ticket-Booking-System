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
| GET    | `/api/v1/venues/`             | List venues (public); POST/PATCH/DELETE admin role |
| GET    | `/api/v1/events/`             | Published upcoming events (public). Filters: `city`, `starts_after`, `starts_before` |
| GET    | `/api/v1/events/<id>/`        | Event detail (public)               |
| GET    | `/api/v1/events/<id>/seats/`  | Seat map (public). Filter: `status`; `page_size` up to 1000 |
| CRUD   | `/api/v1/organizer/events/`   | Organizer's own events (admin sees all). Only drafts can be deleted |
| POST   | `/api/v1/bookings/`           | `{"seat": id}` -> 201, 409 if taken, 400 if event not bookable |
| GET    | `/api/v1/bookings/`           | Your bookings (admin: all)          |
| POST   | `/api/v1/bookings/<id>/cancel/` | Cancel a pending booking, freeing the seat (idempotent) |

## Concurrency: selling the last seat exactly once

Two strategies in [apps/bookings/services.py](apps/bookings/services.py), chosen by
`BOOKING_LOCK_STRATEGY`:

- **pessimistic** (default): `SELECT ... FOR UPDATE OF "events_seat"`, then check and write.
- **optimistic**: read `version`, then `UPDATE ... WHERE version = <read>`; on 0 rows re-read
  (up to 3 attempts).

Underneath both, a partial unique index (`seat_id WHERE status IN ('pending','confirmed')`)
makes a double booking impossible even if the application logic were wrong.

Proof: `test_100_parallel_requests_for_10_seats_sell_exactly_10` fires 100 parallel HTTP
requests (100 threads, 100 DB connections) at 10 seats: exactly 10 x 201 and 90 x 409, for both
strategies. A deliberately naive check-then-act version in the same file lets 19 of 20
requests pass the availability check for a single seat; only the DB index stops it.

`python manage.py compare_locking --requests 100 --rounds 5` (median of 5, local Docker):

| scenario      | strategy    | booked | 409s | retries | wall ms | p50 ms | p95 ms |
|---------------|-------------|-------:|-----:|--------:|--------:|-------:|-------:|
| hot seat      | pessimistic |      1 |   99 |       0 |     485 |    394 |    436 |
| hot seat      | optimistic  |      1 |   99 |      99 |     731 |    526 |    637 |
| 10 seats      | pessimistic |     10 |   90 |       0 |     516 |    406 |    472 |
| 10 seats      | optimistic  |     10 |   90 |      90 |     753 |    567 |    675 |
| no contention | pessimistic |    100 |    0 |       0 |     765 |    663 |    721 |
| no contention | optimistic  |    100 |    0 |       0 |     793 |    654 |    740 |

Pessimistic wins under contention here: an optimistic loser's UPDATE still waits for the
winner's row lock, then needs a second read to learn the seat is gone. Latencies include
100 Python threads opening fresh connections at once, so compare rows, not absolutes.

## Data model

```
Venue (rows x seats_per_row)
  └── Event (organizer, status: draft -> published -> cancelled)
        └── Seat (row_number, number, price, status)   one row per seat per event
              └── Booking (user, status, amount)        at most one active booking per seat
```

## Progress

- [x] Phase 0: Project foundation
- [x] Phase 1: Auth and roles
- [x] Phase 2: Core domain models and read APIs
- [x] Phase 3: Concurrency-safe booking
- [ ] Phase 4: Seat hold with expiry
- [ ] Phase 5: Idempotent payment flow (Razorpay)
- [ ] Phase 6: Async work and reliability
- [ ] Phase 7: Performance
- [ ] Phase 8: Production readiness
