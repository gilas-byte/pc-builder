Português: [../01-banco-de-dados.md](../01-banco-de-dados.md)

# Database

**Objective:** store parts, stores, listings, and price history in a way that allows the backend to quickly
answer "what is today's lowest price" and "is this price really a deal?".

**Technology:** SQLite, database file `data/pcbuilder.db`. Accessed via Python's built-in `sqlite3` module,
without an ORM, keeping queries simple and readable.

## Tables

### `stores` — stores
| column | type | example |
|---|---|---|
| id | INTEGER PK | 1 |
| slug | TEXT UNIQUE | `kabum` |
| name | TEXT | `KaBuM!` |
| base_url | TEXT | `https://www.kabum.com.br` |
| active | INTEGER (0/1) | 1 |

Starts with 3 rows: Kabum, Pichau, and Terabyte.

### `parts` — the part itself (store-independent)
| column | type | example |
|---|---|---|
| id | INTEGER PK | 7 |
| category | TEXT | `gpu` |
| brand | TEXT | `NVIDIA` |
| model | TEXT | `GeForce RTX 4060 8GB` |
| specs | TEXT (JSON) | `{"socket": "AM4", "memory_type": "DDR4"}` |
| created_at | TEXT (ISO) | `2026-10-09T09:00:00` |

Fixed categories: `cpu`, `motherboard`, `ram`, `gpu`, `storage`, `psu`, `case`, `cooler`.
The `specs` field stores details needed to evaluate compatibility (socket, memory type, wattage, form factor).

### `listings` — a part at a specific store (the product link)
| column | type | example |
|---|---|---|
| id | INTEGER PK | 12 |
| part_id | FK → parts | 7 |
| store_id | FK → stores | 1 |
| url | TEXT UNIQUE | product link |
| title | TEXT | product title as formatted by store |
| active | INTEGER | 1 |

A single part can have one listing per store. This is the link users click.

### `price_snapshots` — historical prices (one row per collection run)
| column | type | notes |
|---|---|---|
| id | INTEGER PK | |
| listing_id | FK → listings | |
| price_cash | INTEGER | **cash / PIX price, in cents** |
| price_installment | INTEGER | total installment price, in cents, nullable |
| in_stock | INTEGER | 1 in stock, 0 out of stock |
| collected_at | TEXT (ISO) | timestamp when price was scraped |

Prices are stored in **integer cents** to prevent floating-point rounding issues (R$ 1,299.90 becomes `129990`).

### `builds` and `build_items` — full build and upgrade list
| table | columns |
|---|---|
| `builds` | id, name, kind (`full` or `upgrade`), created_at |
| `build_items` | build_id, category, part_id (nullable until selected) |

Starts with 2 builds: "Build completa" (`full`) and "Upgrades do PC atual" (`upgrade`).

## Queries Needed by the Backend (implemented as views or helper functions)

1. **Current price per listing:** the most recent snapshot for each `listing`.
2. **Best price per part:** the lowest current `price_cash` across stores where `in_stock = 1`.
3. **History:** all snapshots for a given part grouped by store, for rendering charts.
4. **Deal detector:** today's price compared to the **median of the past 30 days**.
   A deal is defined as today being at least 10% below the median. The 10% threshold is configurable.
   With fewer than 7 days of history, the app displays "short history" instead of flagging a deal.
5. **Build total:** sum of the best prices for each selected part.

## Files

- `backend/app/db/schema.sql` — tables, indexes, and views creation.
- `backend/app/db/database.py` — connection management, schema initialization if file does not exist.
- `backend/app/db/seed.py` — seeding initial 3 stores and 2 empty builds.
- `backend/tests/test_db.py` — unit tests.

## Design rules

- Collecting twice on the same day **replaces** that day's price instead of duplicating it (unique index on listing and date). Re-running collection does not corrupt history.
- The median considers only days **prior** to today. Including today's price would make a steep drop lower the baseline median itself.
- Deal settings (10%, 30 days, 7-day minimum) live in the `settings` table rather than in code.
- `data/` is excluded from git.
- Tests: `cd backend && uv run python -B -m pytest` (the database ones are in `backend/tests/test_db.py`).
