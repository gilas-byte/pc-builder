Português: [../02-backend.md](../02-backend.md)

# Backend (Python)

**Objective:** an API consumed by the frontend. Scraped prices enter via a local command (see below).

**Technology:** FastAPI + Uvicorn, dependency management with `uv`. Python 3.11.

## Endpoints

| Method | Route | Description |
|---|---|---|
| GET | `/api/health` | status, date of last collection run, and total price count |
| GET | `/api/stores` | tracked stores |
| GET | `/api/parts?category=gpu` | parts list with lowest current price, store, and URL |
| GET | `/api/parts/{id}` | single part with price breakdown across stores |
| GET | `/api/parts/{id}/history` | historical prices for rendering charts |
| GET | `/api/deals` | today's deals (rules described in `01-banco-de-dados.md`) |
| GET | `/api/builds` | 2 builds with running totals |
| PUT | `/api/builds/{id}/items/{category}` | select a specific part for a category in a build |
| GET | `/api/current-pc` | active current PC (`current_pc` setting; falls back to example PC if unset) |
| GET | `/api/settings` | effective configuration + source for each (`default`, `banco`, `env`) + UI dropdown options |
| PUT | `/api/settings` | partial update; atomic all-or-nothing; 422 `{"detail": {"message", "fields": {key: msg}}}` |
| POST | `/api/settings/reset/{chave}` | resets key to default (deletes from db); unknown key = 404 |
| GET | `/api/channels` | configured channels: enabled state, origin, offers seen, last read, failures |
| POST | `/api/channels` | `{"handle"}`: `@name`, `name`, `t.me/name`, `t.me/s/name`; verifies web preview (201/409/422/503) |
| PUT | `/api/channels/{slug}` | `{"enabled": true/false}` |
| DELETE | `/api/channels/{slug}` | disables and hides; preserves past offers and history (204) |
| GET | `/api/secrets/telegram` | token and chat status only: `{configured, source: env\|file\|null, hint: "…1234", chat_id: {...}, ready}` |
| PUT | `/api/secrets/telegram` | `{token?, chat_id?}`; 422 without echoing value; 409 if value is provided via env var |
| DELETE | `/api/secrets/telegram` | deletes token and chat from `secrets.env` (env vars remain effective) |
| POST | `/api/secrets/telegram/detect-chat` | `getUpdates` using stored token: `{bot, chats: [{id, tipo, nome}], hint?}`; 409 if token missing |
| POST | `/api/notify/test` | sends "PC Builder: mensagem de teste" (`{"target"}` optional); 409 if unconfigured; rate limit 1/10s, 20/h |
| GET | `/api/scheduler` | scheduler status: enabled, running, last/next run, last error, game mode availability |
| POST | `/api/scheduler/run-now` | triggers 1 background run immediately (202); 409 if run lock is held; rate limit 1/min, 10/h |
| GET | `/api/ollama/status` | `{reachable, url, version, error, warning, classifier_mode, classifier_effective, models_selected, models_missing}`; `?url=` tests an address without saving |
| GET | `/api/ollama/models` | installed models (`{url}/api/tags`): name, size, quantization, parameter count; 503 if Ollama unreachable |
| GET | `/api/ollama/pull` | pull progress: `{model, state (idle/running/done/error/canceled), phase, completed, total, percent, error}` |
| POST | `/api/ollama/pull` | `{"model"}`; downloads model in background (202); one at a time (409); limit 5/h (429 + `Retry-After`) |
| DELETE | `/api/ollama/pull` | cancels ongoing pull: `{canceled}` |
| POST | `/api/classifier/test` | `{"text"}` (1 to 2000 chars): classified type, source (`ollama`/`rules`), model votes, and rule rationale; limit 1/s, 300/h |
| GET | `/api/classifier` | selected mode, effective mode, rule benchmark metrics (`app/tg/rules_metrics.json`), and offers by source |

**Classifier and Ollama:** rule-based classifier (`app/tg/rules.py`) as fallback for Ollama, selected
via the `classifier` setting (`auto` | `rules` | `ollama`; `app/tg/classifier.py`). The Ollama client
(`app/ollama.py`, httpx) uses the configured address; errors never repeat the address string. The `/api/ollama/*` and
`/api/classifier*` routes enforce Host and Origin validation **even on GET requests** (as they trigger external network calls from the server).

**Alerts and scheduler:** bot token is **write-only**. It resides in `secrets.env` (`app/secrets_store.py`) within
the data directory (`PCB_DATA_DIR`, default `data/`), mode 0600, atomic write; `PCB_TELEGRAM_TOKEN` /
`PCB_TELEGRAM_CHAT_ID` take precedence. Never written to database, logs, error payloads, or API responses. Alerts are sent via the notifier
(`app/notify.py`: `TelegramBot`, `Stdout`, `NoneNotifier`), selected by `notify_target`. The internal scheduler
(`app/scheduler.py`) is a server thread running only when `scheduler_enabled`/`PCB_SCHEDULER=1`; the file
lock (`app/runlock.py`, `data/rodada.lock`) is identical to the CLI lock, preventing concurrent runs with an external cron.

**Write guard and settings:** all mutation routes pass through the write guard (`write_guard`): `Host` must match
`127.0.0.1:8787`, `localhost:8787`, or `PCB_ALLOWED_HOSTS` (otherwise 403); `Origin`, if present, must match an allowed host
(otherwise 403; omitted Origin, like `curl`, is allowed); body must be `application/json` (415) and under 64 KB (413). GET requests do not require
these checks. Settings reside in `app/settings.py` (defaults, validation, `PCB_*`) and channels in `app/tg/channels.py`.

**Prices never enter over the network.** Price ingestion is handled by the local command `python -m app.ingest lote.json`, which
writes directly to SQLite. The API only reads data and edits builds. (See "Security Fix" below.)

## Compatibility (upgrade list)

Simple, practical rules without unnecessary complexity:
- CPU: socket must match current motherboard (in example PC, **AM4**; rejects AM5).
- RAM: memory type must match motherboard (in example PC, **DDR4**).
- Motherboard: excluded from upgrades (swapping motherboard constitutes a new build).
- GPU, storage, power supply, case, and cooler: no hard filters, only informational warnings (e.g., low wattage PSU).

Parts without populated `specs` display a "compatibility not verified" warning rather than disappearing.

## Serving the Frontend

The backend serves compiled static assets generated by `vite build` (directory `frontend/dist`). A single process, a single port.

## Execution

- Local: listens on `127.0.0.1:8787`.
- Always-on: systemd user service (template in `deploy/pc-builder.service`), with automatic restart.
  With `loginctl enable-linger`, it runs without an active graphical user session.
- **Other devices:** a local reverse proxy (e.g., `tailscale serve`) forwarding to `127.0.0.1:8787`. The app
  remains unexposed directly to the physical network.

## Why prices do not enter through the network

An early version ingested prices via `POST /api/snapshots`, protected by a **local IP check + token**. Behind
`tailscale serve` that protects nothing: the proxy runs on the same machine, so **every** forwarded request arrives
from `127.0.0.1`, the IP restriction no longer applies, and only the token (stored in a file on the machine) is left.

So the ingestion route does not exist. Prices enter only through the local `app.ingest` command (or the collector),
which writes directly to the database without any network involvement. Any POST/PUT/PATCH for prices returns 405,
and the OpenAPI schema lists no route that writes prices (tests cover this, including the local-proxy path with
identity headers).

Build editing (`PUT /api/builds/...`) stays open to whoever can reach the app, on purpose: it is the user choosing
parts, from the PC or another personal device. Like every write route, it requires an allowed Host/Origin and JSON,
so another site open in the browser cannot write (CSRF), not even through a domain pointing to 127.0.0.1
(DNS rebinding).

## Tests

`cd backend && uv run python -B -m pytest`. Tests use FastAPI's test client against a temporary database, with no
network and no real Ollama.
