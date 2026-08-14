# Payment endpoint

An HTTP endpoint that starts a card payment for a shopping cart, with the schema behind it.

Built with Python 3.12, Flask, SQLAlchemy 2.0, Alembic and PostgreSQL 18.

---

## Quick start

Everything runs in Docker; nothing else needs installing.

```bash
cp .env.example .env
docker compose up --build
```

That starts PostgreSQL, applies the migrations, loads the demo rows and serves the API on
`http://localhost:8000`. A database UI is available at `http://localhost:8081`, which is the
quickest way to read the `payments` and `payment_events` rows a request leaves behind.

```bash
curl http://localhost:8000/health      # {"status": "ok"}
```

### Try it

Alice's cart holds one kettle at 45.00 and two mugs at 12.50, so it costs 70.00 USD. Her
saved card authorises.

```bash
curl -i -X POST \
  http://localhost:8000/api/v1/carts/c1c1c1c1-c1c1-c1c1-c1c1-c1c1c1c1c1c1/payments \
  -H 'X-User-Id: 11111111-1111-1111-1111-111111111111' \
  -H 'Idempotency-Key: demo-key-1'
```

```
HTTP/1.1 201 CREATED
{
  "id": "9f1c…",
  "cart_id": "c1c1c1c1-c1c1-c1c1-c1c1-c1c1c1c1c1c1",
  "amount": "70.00",
  "currency": "USD",
  "status": "succeeded",
  "provider_reference": "ch_9f1c…",
  "failure_code": null,
  …
}
```

Send the **same request again** and it answers `200` with `Idempotent-Replay: true` and the same
payment. The card is not charged twice, and the answer is the same one the first call gave.

Send it again with a **different** `Idempotency-Key` — a new intent, not a retry — and it
answers `409` with the payment that already paid for the cart.

Bob's card declines, so his cart shows the failure path:

```bash
curl -i -X POST \
  http://localhost:8000/api/v1/carts/c2c2c2c2-c2c2-c2c2-c2c2-c2c2c2c2c2c2/payments \
  -H 'X-User-Id: 22222222-2222-2222-2222-222222222222' \
  -H 'Idempotency-Key: demo-key-2'
```

```
HTTP/1.1 402 PAYMENT REQUIRED
{ "status": "failed", "failure_code": "card_declined", … }
```

---

## The Docker setup

Two files, merged automatically by `docker compose up`:

| File | Role |
| --- | --- |
| `compose.yml` | The stack as it would run in production — one definition of each service |
| `compose.override.yml` | Development ergonomics only: published ports, code syncing, demo data, adminer |

```bash
docker compose up --build        # development (both files)
docker compose watch             # the same, syncing code as you save it
docker compose -f compose.yml up # production-shaped, without the override
```

Three details worth pointing at:

- **Migrations run in their own one-shot `migrate` service**, and the API waits for it with
  `condition: service_completed_successfully`. An application container that upgrades its own
  schema on boot races every other replica doing the same thing.
- **Required variables are declared `${VAR?Variable not set}`**, so a missing value stops the
  stack instead of quietly starting it with a guess.
- **The production image runs as a non-root user** and is built in two stages, so the runtime
  carries the virtualenv and nothing that was only needed to install it. `Dockerfile.dev` is
  separate: an editable install, dev dependencies, and Flask's reloader.

## Running it on the host

```bash
make install       # virtualenv + dependencies + .env
make db            # PostgreSQL only, published on localhost
make migrate       # flask db upgrade
make seed          # demo rows
make run           # http://localhost:5000
```

`make help` lists every target.

## Running the tests

With the stack already up, nothing needs installing:

```bash
docker compose up --build -d      # if it is not running
docker compose exec api pytest
```

Or from a host virtualenv, against the database Compose publishes:

```bash
make install       # needs python3-venv
make db
make test-host
```

The suite uses the separate `payments_test` database, which Compose creates on first start.
**It drops and rebuilds that schema on every run**, so `TEST_DATABASE_URL` must never point at a
database that matters.

Useful selections:

```bash
docker compose exec api pytest tests/test_concurrency.py -v   # the two-thread race
docker compose exec api pytest -k idempotency -v              # replay and double-charge rules
docker compose exec api pytest -x -q                          # stop at the first failure
```

| File | What it pins down |
| --- | --- |
| `test_payments_api.py` | Every response the endpoint can give, and that a rejected request charges nothing |
| `test_idempotency.py` | Retries return the original payment, charge once, and cannot be replayed by another caller |
| `test_concurrency.py` | Two simultaneous attempts on real connections produce exactly one payment |
| `test_totals.py` | What a cart costs, including the snapshotted line price |
| `test_gateway.py` | The mock provider is deterministic and never echoes the card token |
| `test_health.py` | The endpoint the container healthcheck depends on |

```bash
make lint          # ruff format --check + ruff check
```

---

## The endpoint

```
POST /api/v1/carts/{cart_id}/payments
```

| Header | Required | Meaning |
| --- | --- | --- |
| `X-User-Id` | yes | Who is paying. Stands in for authentication — see [Assumptions](#assumptions). |
| `Idempotency-Key` | yes | Identifies the attempt, so a retry is recognised rather than re-charged. |

Body (optional):

```json
{ "payment_method_id": "11111111-2222-3333-4444-555555555555" }
```

Without it, the user's default card is charged.

### Responses

Every response carries a payment, including the failures — a payment record exists from the
moment the attempt starts, whatever happens next.

| Situation | Status | Payment status |
| --- | --- | --- |
| The provider authorised the charge | `201` | `succeeded` |
| The provider declined the card | `402` | `failed` |
| The provider never answered | `202` | `pending` |
| A payment already owns the cart | `409` | the existing one |

`409` covers both ways a cart can already be spoken for — a payment still `pending` against an
active cart, and a `succeeded` payment that checked the cart out. They are the same situation
from the caller's side, so they get the same answer, and it carries the payment rather than an
error: that payment is the receipt the caller is missing.

`422 cart_not_payable` is left for a cart that cannot be paid for and has no payment to point
at — one that was abandoned, or closed by something other than a payment.

### Retries

Repeating a request with the same `Idempotency-Key` returns the original payment untouched and
never calls the provider again. The response carries `Idempotent-Replay: true` and repeats the
status code the first attempt gave, so a client can handle a retry with the branch it already
has. The single exception is `201`, which becomes `200`: the replay created nothing.

| First attempt | Replay |
| --- | --- |
| `201` succeeded | `200` + `Idempotent-Replay: true` |
| `402` declined | `402` + `Idempotent-Replay: true` |
| `202` pending | `202` + `Idempotent-Replay: true` |

A key is scoped to the caller who used it, and ownership of the cart is settled *before* the
replay is looked up. Answering a replay on the strength of the key alone would make the key a
bearer token: anyone naming a cart id and the key used against it would be handed that payment's
amount, card and provider reference.

**A replay is answered even after the cart has been checked out**, and that is the point of the
key rather than a hole in the validation. The alternative — re-checking the cart first — would
answer `422 cart_not_payable` to a client retrying after a dropped connection, reporting failure
for money that has already been taken. The key identifies one attempt and returns that attempt's
recorded outcome; only a request carrying a *new* key is a new intent and gets validated afresh.

A declined card is a **successful request that recorded a failed payment**. That is why the
status code describes the payment rather than the call.

Errors use one envelope:

```json
{ "error": { "code": "cart_not_payable", "message": "Cart … is abandoned, so it cannot be paid for." } }
```

| Code | Status | Meaning |
| --- | --- | --- |
| `invalid_request` | `400` | A header or body field is missing or malformed |
| `cart_not_found` | `404` | No such cart, or it belongs to someone else |
| `cart_not_payable` | `422` | The cart cannot be paid for and no payment owns it |
| `cart_empty` | `422` | Nothing to pay for |
| `mixed_currency_cart` | `422` | The cart's products are priced in different currencies |
| `payment_method_not_found` | `422` | No such card for this user, or no default card |
| `concurrent_payment_attempt` | `409` | A competing attempt held the cart; retry |

---

## How it works

`docs/payment-design.drawio` (open at [app.diagrams.net](https://app.diagrams.net) or with the
VS Code Draw.io extension) draws the four things described below.

### One request, two transactions

The obvious implementation wraps the whole endpoint in a single transaction. That is the
mistake this design exists to avoid: a single transaction holds a row lock and a database
connection for the entire round trip to the card provider, and if the process dies mid-call
the transaction rolls back — leaving a card that may have been charged and no record that we
ever tried.

So the write is split, in `app/payments/service.py`:

```
Transaction 1    lock the cart, validate it, insert the payment as `pending`, COMMIT
(no transaction) charge the card
Transaction 2    record the outcome, check the cart out, COMMIT
```

Two details make the split real rather than decorative:

- The values the charge needs are **copied into a `ChargeRequest` before the first commit**.
  After a commit the ORM object is expired, so reading `payment.amount` would silently open a
  second transaction that then stayed open across the network call — exactly what the split
  is meant to prevent.
- The provider is given **our `payment.id` as its idempotency key**, so a retried charge is
  recognised at the provider too, not only here.

If the process dies in the gap, the payment stays `pending`. That is a recoverable state, and
it exists only because the write was split.

### Nothing gets charged twice

Three mechanisms, doing three different jobs:

1. **`Idempotency-Key`** — a lookup before the insert. Handles the honest retry: same client,
   same intent, flaky network. Returns the original payment with `200`.
2. **`SELECT … FOR UPDATE` on the cart row** — orders two genuinely concurrent requests, so
   the second cannot read the cart while the first is claiming it.
3. **A partial unique index** — the one that makes a second live payment *impossible*:

   ```sql
   CREATE UNIQUE INDEX uq_payments_active_cart
       ON payments (cart_id)
       WHERE status IN ('pending', 'succeeded');
   ```

The third is the one that matters. A check-then-insert in application code is a read outside
the write's serialization: two workers can both read "no payment yet", both insert and both
charge. The rule has to be something the database evaluates at write time, and the code has
to handle it being violated — which is why the conflict is caught as an `IntegrityError` and
turned into an outcome, rather than pre-empted by an `if`.

`pending` counts as live on purpose. Its outcome is unknown, so it must block a second
attempt just as firmly as a success would.

### What a payment can be

```
                 ┌─ provider authorised ──▶ succeeded  (terminal)
INSERT ─▶ pending┤
                 └─ provider declined ────▶ failed     (terminal)
```

Terminal states never change again; `Payment.mark_succeeded` and `mark_failed` refuse to move
a settled payment. A payment left in `pending` means the provider never answered — the charge
may have gone through. The cart deliberately stays `active`, because it is not paid for until
we know it was.

### Money

`NUMERIC(12, 2)` in the schema, `Decimal` in Python, a **string** in JSON — a float anywhere
in this path eventually loses a cent. The amount is snapshotted onto the payment row when it
is created, exactly as `cart_items.unit_price` snapshots the price, so repricing a product can
never move a payment that has already settled.

### The provider

`app/gateway/` holds the interface (`PaymentGateway`) and the mock that implements it. The
mock decides from the card token, so every run is reproducible:

| Token | Result |
| --- | --- |
| anything else | authorised |
| ends with `_declined` | declined, `failure_code: card_declined` |
| ends with `_unreachable` | raises `PaymentGatewayError` — outcome unknown |

Nothing here is random. A suite that fails once in a hundred runs teaches you nothing.

The third case is the one worth having: **not knowing is different from being told no**, and
the two must never collapse into the same branch.

---

## Project structure

```
compose.yml             the stack as it would run in production
compose.override.yml    development ergonomics, merged in automatically
Dockerfile              two-stage production image, runs as a non-root user
Dockerfile.dev          editable install, dev dependencies, reloading server

app/
├── __init__.py         application factory
├── config.py           configuration read from the environment
├── extensions.py       SQLAlchemy and Migrate instances
├── errors.py           domain failures and the JSON envelope they produce
├── health.py           liveness endpoint behind the container healthcheck
├── cli.py              flask seed-demo
├── models/
│   ├── columns.py      column helpers and timestamp mixins
│   ├── shop.py         users, products, carts, cart items, saved cards
│   └── payment.py      payments, payment events, the state machine
├── gateway/
│   ├── base.py         ChargeRequest, ChargeResult, the PaymentGateway protocol
│   └── mock.py         the deterministic stand-in
└── payments/
    ├── routes.py       HTTP in, HTTP out
    ├── service.py      the two-transaction flow
    ├── schemas.py      request parsing and response shaping
    └── totals.py       what a cart costs

migrations/versions/
├── 0001_base_schema.py the supplied db.sql, as a migration
└── 0002_payments.py    payments, payment_events, the partial unique index

tests/
├── conftest.py         app, session and gateway fixtures
├── factories.py        row builders
├── api.py              how the endpoint is called
├── test_payments_api.py
├── test_idempotency.py
├── test_concurrency.py
├── test_gateway.py
└── test_totals.py
```

Dependencies point one way: `routes` knows HTTP and never touches SQLAlchemy; `service` knows
the domain and the session but never mentions a status code; `gateway` knows the provider and
nothing about the database.

There is no repository layer. The SQLAlchemy session already is one, and wrapping it would add
indirection without adding a seam.

### The schema

`db.sql` is kept exactly as supplied, for reference. The database itself is built by Alembic —
revision `0001` reproduces that file so `flask db upgrade` works from an empty database, and
`0002` adds the payment tables. **Alembic is the single source of truth for the schema**; the
models describe the Python side of it.

### Tests

The suite runs against a real PostgreSQL, because what is being tested is PostgreSQL's
behaviour: row locks, a partial unique index, and what two connections do when they race.
SQLite would pass while proving nothing.

The payment flow is allowed to **really commit** rather than being wrapped in a transaction
that is rolled back afterwards. Those commits are the design; a fixture that neutralised them
would be testing something the application never does. Isolation comes from emptying the
tables between tests instead.

`test_concurrency.py` runs two attempts on two threads with their own connections. Its
assertion — one payment row, one `created` and one `conflict` — holds whether or not the
operating system actually overlaps them, so the test cannot flake.

---

## Assumptions

The brief left these open, so they were decided as follows.

- **No authentication.** There is no auth layer in the base schema and building one is outside
  the task, so the caller identifies itself with an `X-User-Id` header. Everything else treats
  it as a trusted identity: a cart belonging to another user answers `404`, not `403`, so the
  endpoint cannot be used to discover which cart ids exist.
- **`Idempotency-Key` is required.** A payment endpoint should not accept a request it cannot
  recognise on retry. Reusing a key for a different cart is rejected rather than silently
  returning the wrong payment.
- **The total is calculated here.** The brief says the shop already has a total calculation
  service. `app/payments/totals.py` is the smallest stand-in — the sum of the line items,
  behind one function so the real service can replace it without touching the payment flow.
- **A cart cannot mix currencies.** The base schema prices each product separately, so this is
  possible; charging one card two currencies at once is not. It is rejected with `422`.
- **Stock is not decremented.** Reserving inventory is a separate concern with its own
  concurrency rules, and the brief does not ask for it.
- **The cart is checked out only on success.** A declined or unknown payment leaves it active
  so the user can try another card.
- **One payment per cart, not per attempt.** A failed payment frees the cart for a new attempt;
  a pending or succeeded one does not.

## Out of scope

Named rather than silently absent:

- **A reconciliation worker.** Payments left `pending` need something that re-queries the
  provider and settles them. The state that makes it possible is here; the worker is not.
- **Provider webhooks.** The real integration would confirm outcomes asynchronously; the
  `pending` state and `payment_events` are already shaped for it.
- **`GET /payments/{id}`.** The natural companion to the `202` response. The brief asks for
  the endpoint that *starts* a payment, so that is what is built.
- **Refunds, partial captures, multi-currency settlement.**
