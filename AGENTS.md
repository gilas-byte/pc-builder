# PC Builder: notes for contributors and coding agents

Applies to any coding agent (Claude Code, Codex, Antigravity...) and to human contributors.

Local dashboard that tracks PC part prices from stores and from public Telegram deal channels. Dark UI, black with
yellow `#ffea00`; interface in Portuguese and English. Read [README.md](README.md) first, then the doc for the area you
are touching in [`docs/en/`](docs/en/) (or [`docs/`](docs/) in Portuguese). The real state is in `git log` and the tests.

## How to work

- Tests first (TDD). Don't report "done" without running the tests and looking at the real output. If something fails,
  say what and why. Never invent output, data or tests.
- Doubt about the request: ask one short question. Extras are welcome as proposals; ask before doing them.
- Small commits with descriptive messages.

## Stack and commands

- Backend: Python 3.11, FastAPI, SQLite (`data/pcbuilder.db`, outside git).
  Tests: `cd backend && uv run python -B -m pytest`.
- Frontend: React + Vite in `frontend/`; the backend serves `dist`. Tests: `cd frontend && npx vitest run`;
  build: `npm run build`.
- Public hygiene: `python3 tools/check_public.py` must report 0 findings before any commit.
- The server listens on `127.0.0.1:8787` (never `0.0.0.0` outside the Docker image). Another device reaches it through a
  local reverse proxy.

## Rules that must not break

- **Prices do NOT enter through the API.** Only the local command (`uv run python -m app.ingest batch.json`) or the
  collectors write prices. Don't add an HTTP route that writes prices: behind a local proxy (e.g. `tailscale serve`)
  every request arrives from `127.0.0.1`, so an IP check means nothing.
- **Write guard** (`write_guard` in `backend/app/main.py`): every POST/PUT/PATCH/DELETE under `/api/*` needs an allowed
  `Host` (`127.0.0.1:8787`, `localhost:8787` and `PCB_ALLOWED_HOSTS`), an `Origin` (if present) whose host is allowed
  (else 403), a JSON body only (else 415) and at most 64 KB (else 413). GET doesn't need Origin. A new route that
  writes inherits the guard and goes in the allowed-routes list in the OpenAPI test. In tests, `TestClient` uses
  `base_url="http://127.0.0.1:8787"`.
- **Settings** (`backend/app/settings.py`, the only place for defaults): default < database (`settings` table, JSON) <
  `PCB_*` environment. Everything is validated on the server. No secrets there.
- **Write-only secret** (`backend/app/secrets_store.py`): the bot token and chat id live in `secrets.env` in the data
  directory (`PCB_DATA_DIR`, default `data/`), mode 0600, atomic write, no symlinks; `PCB_TELEGRAM_*` wins. The token
  **never** goes to the database, `settings`, logs, error messages, API responses, the browser console or tests (in tests
  only a fake token built in pieces, so `check_public` doesn't flag it). The API returns only
  `{configured, source, hint: "…1234"}`.
- **Alerts** (`backend/app/notify.py`): `TelegramBot`, `Stdout` or none. With `stdout` (default) `--notify` prints
  exactly what it always printed, for an external cron or Hermes Agent.
- **Internal scheduler** (`backend/app/scheduler.py`): a thread of `app.serve`, only with `scheduler_enabled` or
  `PCB_SCHEDULER=1`. It shares a file lock (`data/rodada.lock`) with the CLI so two rounds never overlap.
- **Telegram channels** (`backend/app/tg/channels.py`): adding a channel checks the `t.me/s/<name>` preview first
  (injectable fetcher, never real network in tests). DELETE only hides (`removed_at`); offers stay.
- **Classifier** (`backend/app/tg/classifier.py`): setting `classifier` = `auto` | `rules` | `ollama`. The AI only says
  the TYPE of an offer; price and "same product" are plain, tested rules. Ollama is reached only through
  `backend/app/ollama.py` (httpx, saved address, errors never echo the address); tests use `httpx.MockTransport` and
  `conftest.py` forbids a real client.
- **Docker** (`Dockerfile` + `docker-compose.yml`): `docker compose up -d --build`. The container listens on `0.0.0.0`
  (`PCB_HOST`, set by the image only) but the host publishes only `127.0.0.1:8787`: never `8787:8787`. Non-root user
  (UID 10001), `read_only` + `tmpfs /tmp`, `cap_drop: [ALL]`, `no-new-privileges`, data in the `pcb-data` volume.
  Base images always have a version tag (no `latest`). Never `up` the `ollama` profile in a test (big image).
- Parts and Telegram: a laptop's RAM (SO-DIMM) is **not a part** (`adjust_kind` only accepts desktop RAM with evidence in
  the text). When in doubt, it is not a part. Not a part: laptop, phone, console, peripheral, appliance. When you find a
  classification error, write the test with the real post text first.

## Test style

- `pytest` with a temporary database (`tmp_path`); saved real pages in `backend/tests/fixtures/`; no network in tests.
- Prove a test catches its bug with a manual mutation: apply the change from Python (`assert old in s; s.replace(...)`),
  not with `sed`, and always revert.

## Never

- Don't use `sudo`; don't touch schedulers (cron), system systemd, firewall or network. Say the command and stop.
- No secrets, tokens, real hostnames, e-mails or absolute home paths in code, tests or docs; use environment variables
  (see `.env.example`).
- Before committing, check that no `.db`, photo from `data/tg_img`, `.env` or secret got in.
