Português: [../03-frontend.md](../03-frontend.md)

# Frontend (React)

**Objective:** the web interface where users view prices, deals, and builds.

**Technology:** React + Vite, plain JavaScript (no TypeScript, keeping maintenance lightweight). Price
history charts are hand-written inline SVG (no charting library).

## Design Decisions

- **Navigation:** fixed sidebar on the left (collapses to bottom bar on mobile screens).
- **Full build:** the app automatically assembles the cheapest **compatible** build, and the user can swap parts individually.
  The upgrade list remains manual (the "cheapest" standalone part would likely be inferior to existing hardware).
- **Until collection is active:** sample data with an **EXEMPLO** banner always visible. Sample data lives in
  a separate database (`data/demo.db`), regenerated on every service startup. This allows core application logic
  (deals, assembly, compatibility) to run against realistic data. When real scraped parts exist, sample mode disappears automatically.
- **Large part cards with product images and glow effect** circling the image container.
- **Extra features:** responsive mobile design and **part favoriting**.

### Backend Support

- `parts.image_url` (restricted to `https://`) and optional `image_url` field in `app.ingest` payload. Images are scraped
  from stores during collection. When missing (including demo mode to avoid fabricated photos), a category icon is displayed.
- `favorites` table and routes `GET /api/favorites`, `PUT`/`DELETE /api/favorites/{id}`.
- Automated build assembly (`POST /api/builds/{id}/auto`) and category options with compatibility metadata
  (`GET /api/builds/{id}/options/{category}`).
- Full build compatibility logic: CPU/motherboard socket, RAM/motherboard type, motherboard/case form factor,
  cooler sockets, and power supply wattage vs. GPU recommendations.

## Visual Design

- **Black background** (`#0a0a0a`), deep gray cards (`#141414`), borders `#262626`.
- **Yellow accents** only: `#ffea00`.
  Applied to discounted prices, primary action buttons, active navigation items, and links.
- Primary text `#f5f5f5`, secondary text `#a3a3a3`. Checked for accessible contrast.
- Inter font with standard system font fallbacks.
- Strictly dark mode; light theme is unsupported.

## Screens and Views

1. **Deals** (landing view): parts priced below the 30-day median, sorted by steepest drop.
   Cards display cash price, savings amount, store name, and store link.
2. **Parts:** categorized catalog (tabs: CPU, Motherboard, RAM, GPU...). Search filter.
   List items: model, lowest price, store, stock status, URL, and a 30-day sparkline.
3. **Part Detail:** side-by-side store prices, 90-day price history chart, and direct links.
4. **Builds:** two tabs, "Full build" and "Upgrades for current PC". Each category shows selected part
   and price, with running total at the top. Upgrade view includes compatibility warnings.

5. **Settings** (`#/config`, gear icon in navigation; labeled "Ajustes" / "Settings" on mobile):
   Telegram channels (toggle, remove with confirmation, add with live preview check and API error handling),
   Stores, Collection (frequency), My PC (selectors for socket, memory, form factor, and RAM capacity; short text for CPU, motherboard, and GPU),
   Price range, Game mode, Notification, Local AI (below), and
   Language. Each section identifies its configuration source (`default` / `banco` / `env`, with environment variables locking inputs),
   includes "Save" and "Restore defaults" actions, and displays validation errors from the API. Touch targets meet 44 px standards.
   Deals and Parts screens display notifications when price filters or store toggles restrict output, with links to Settings.

   **Alerts and scheduler:**
   - **Notification:** alert target (Telegram bot / Script output (cron or Hermes Agent) / None) and the "Telegram bot" card:
     4-step setup tutorial (@BotFather and `/newbot`; copy token; send `/start` to bot; "Find my chat"),
     `type=password` token input **without React state** (managed strictly via `ref`; cleared immediately after submission,
     including on error; never stored in DOM attributes or console logs), "configured (ends in …1234)" state with "Change" and "Remove"
     actions (with confirmation), "Find my chat" (interactive conversation picker; empty state explains `/start`), manual chat ID
     (optional, collapsible under `<details>`), "Send test message" with live API response feedback. Environment variable token:
     input hidden, informational badge displayed.
   - **Collection:** "Internal scheduler" card with instant-toggle switch (`scheduler_enabled`), warning note "leave disabled
     if using external cron (or Hermes Agent) to prevent duplicate runs", runtime status (enabled/disabled/running,
     last run outcome, next scheduled run, error message), and "Run now" trigger. `PCB_SCHEDULER` locks the toggle.
   - **Game mode:** displays "Unavailable in Docker" when `/api/scheduler` reports `game_mode_available: false`.

   **Local AI** (`src/pages/OllamaSection.jsx`), "Local AI (Ollama)" section:
   - 3-option mode selector with concise explanations (Automatic / Rules only / Ollama only), saved instantly;
     `PCB_CLASSIFIER` locks the setting.
   - "No Ollama installed? The app uses rules, achieving X% accuracy on benchmark samples": X dynamically rendered from `GET /api/classifier`
     (never hardcoded); omitted if benchmark data is unavailable.
   - Health status: green/red indicator + "Ollama responds" / "does not respond", failure reason, active classification engine,
     missing selected models, remote host badge, and offer tally by classification source.
   - Host address field with "Test" (`?url=`, does not persist) and "Save"; installed model cards displaying size/quantization, selecting 1 to 3
     (selecting 3 disables remaining checkboxes), VRAM/RAM advisory badges; empty states ("no models installed", "unable to query tags").
   - "Download another model" (recommendations in `datalist`) with progress bar (`role=progressbar` + `aria-valuenow`) and "Cancel";
     download errors display root cause. 1-second polling runs **only** during active downloads; stops on completion or view unmount.
   - Quick test sandbox: paste title (up to 2000 chars), view predicted type, classification source, and rule match rationale.

Fixed footer: "Last collected: dd/mm at hh:mm" to communicate data freshness.

## External Links

Every price snapshot links to the store product page, opening in a new tab (`target="_blank"` with `rel="noopener noreferrer"`).
Store names are explicitly displayed alongside URLs.

## How it works today

- **Access:** `http://127.0.0.1:8787` on the host; other devices through the local proxy address (e.g., `tailscale serve`).
- **Views:** Deals (home), Parts (category tabs + search), Favorites, Part Detail (store comparison,
  90-day SVG price history per store), Builds (full build and upgrade list). Hash-based routing (`#/pecas/12`),
  so browser navigation and reload work without a routing library.
- **Large cards** with product images and a yellow radial glow animation on hover (always on for discounted items). When photos
  are missing, category icons render with the same glow. Respects `prefers-reduced-motion`.
- **Mobile:** below 820 px the sidebar becomes a bottom bar; horizontally scrollable tabs; single-column cards.
- **Full build:** assembled on load (cheapest compatible combination, evaluating each motherboard as the platform baseline).
  The "Build cheapest" button recalculates. "Swap" opens a drawer with compatibility notes per candidate;
  incompatible items sort to the bottom but remain selectable (red warning on the card).
- **Demo mode:** `data/demo.db` (20 parts, 30 days of history, 4 simulated deals), regenerated on each service start.
  Sample links point to store search pages. A yellow diagonal-striped "EXEMPLO" banner is shown across the top.
- Custom inline SVG charts: final bundle 245 kB (77 kB gzip).

## Tests and updating

- Frontend: `cd frontend && npx vitest run`; clean build with no errors or warnings: `npm run build`.
- Tests cover rendering of the views with mock data (including empty states and API failure), `noopener` on every
  external link, and the static file server against path traversal.
- Visual styling needs a human eye: tests do not check appearance.
- After changing the frontend: `cd frontend && npm run build && systemctl --user restart pc-builder`.
