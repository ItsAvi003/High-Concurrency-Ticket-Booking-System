# High-Concurrency Ticket Booking System (Django + DRF + PostgreSQL + Redis + Celery)

A portfolio backend project for a Django fresher, built to hold up under deep interview questioning.

Not a todo app, blog, or e-commerce clone. Anyone can build those by following a tutorial. This project forces you
to deal with problems that real backends have, and interviewers can dig into it for 30+ minutes.

## The core problem

Two users try to book the last seat at the same moment. A naive Django app sells it twice. Your project solves this
properly and proves it.

## What to build

### 1. Concurrency-safe booking

- `select_for_update()` inside `transaction.atomic()` for pessimistic locking
- Also implement optimistic locking (a version field) and compare the two
- Write a test that fires 100 parallel requests at 10 seats and asserts exactly 10 succeed

### 2. Seat hold with expiry

- User selects a seat, it's held for 10 minutes using Redis keys with TTL
- If payment isn't completed, a Celery task releases the seat
- Be ready to explain what happens if Redis dies, and how the DB stays the source of truth

### 3. Idempotent payment flow

- Integrate Razorpay/Stripe test mode
- Webhook handler with signature verification
- Idempotency keys so a retried webhook or double-click never creates two bookings

### 4. Auth and permissions

- JWT (SimpleJWT) with refresh tokens
- Roles: user, organizer, admin, with custom DRF permission classes

### 5. Performance work you can show with numbers

- Use `django-debug-toolbar` or `assertNumQueries` to find and fix N+1 queries (`select_related`, `prefetch_related`)
- Add proper DB indexes, and show `EXPLAIN ANALYZE` before and after
- Cache event listings in Redis with invalidation on change
- Cursor pagination instead of offset for large lists

### 6. Async work and reliability

- Celery for confirmation emails and ticket PDF generation
- Retries with exponential backoff
- Rate limiting on booking endpoints (DRF throttling or Redis-based)

### 7. Production readiness

- Dockerize it (Django, Postgres, Redis, Celery worker, Nginx via docker-compose)
- Structured logging, environment-based settings
- pytest with a CI pipeline (GitHub Actions)
- Swagger docs via drf-spectacular
- Load test with Locust and put the results in your README

## Questions it prepares you for

- What's the difference between pessimistic and optimistic locking, and when would you use each?
- What isolation level does Postgres use by default, and what anomalies can still happen?
- How do you make an API idempotent?
- Why Redis for holds but Postgres for final state?
- How would you scale this to 10x traffic?
- What happens if the Celery worker crashes mid-task?

If you can answer these from your own code, you stand out from almost every other fresher.

## Alternatives if this doesn't appeal

- **Rate-limited URL shortener with analytics:** smaller scope, but covers hashing, caching, and async click tracking
- **Multi-tenant SaaS backend:** tenant isolation, per-tenant permissions, and background billing jobs

## Tips

- Put an architecture diagram and a "design decisions and tradeoffs" section in the README
- Don't copy a tutorial, because interviewers can tell instantly
- Only list what you can explain line by line

## Next steps

A week-by-week build plan or the database schema design would be good follow-ups to this document.
See [BUILD_PLAN.md](BUILD_PLAN.md).
