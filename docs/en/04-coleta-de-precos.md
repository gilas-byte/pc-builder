Português: [../04-coleta-de-precos.md](../04-coleta-de-precos.md)

# Price Collection (Scheduled)

**Objective:** run daily automated scraping across online retailers and persist prices to the database.

## How Collection Works

1. **Watchlist:** the database tracks target products (table `listings`). Starts empty. The initial watchlist
   (`backend/watchlist.json`, editable) targets AM4 and GPU price-to-performance.
2. **Scraping:** for each listing URL, parse the page and extract cash price, installment price, and stock status.
3. **Storage:** local command `uv run python -m app.ingest lote.json` (no network access; the HTTP API cannot write prices).
4. **Discovery:** in addition to tracked URLs, execute category search queries on each store to discover new promotions.
   Discovered items enter as candidates rather than direct additions to the active watchlist.

## Tested Stores

Each store was tested before joining the collector:

Test with 1 search query per store ("rtx 4060"), `httpx` with standard browser User-Agent, 3 s throttle.

| Store | Outcome | Method | Notes |
|---|---|---|---|
| KaBuM! | **works** | `__NEXT_DATA__` (Next.js hydrated JSON) | `price`, `priceWithDiscount` (cash), `image`, `sellerName`, `code`. Search includes laptops: filter by `category` |
| Terabyte | **works** | HTML parsing: `data-tss-price`, `data-tss-estoque`, `.product-item__new-price` ("à vista no Pix") | reCAPTCHA present on checkout/forms only; catalog listings fully accessible. "Open Box" in title = used/open-box |
| Amazon | **works** | HTML parsing: `data-asin`, `a-offscreen`, `s-image` | 48 search results. Mixes sponsored items and third-party sellers; requires strict filtering |
| Pichau | **blocks** | HTTP 403 (anti-bot challenge) | Inaccessible without full browser automation |
| Mercado Livre | **blocks** | Public search API returns 403 (ML closed open search API). Website redirects to `account-verification` | Third-party bypasses circumvent Cloudflare: violates project safety guidelines |
| Shopee | **blocks** | Internal API: error 90309999 (requires auth). Website: verification challenge | Same as above |

Full headless browser automation: not tested. Even with headless browsers, verification challenges / captchas = retailer excluded (core project rule).

Order of preference, lightest to heaviest:
1. Structured page metadata (JSON-LD with `offers.price`, standard for SEO).
2. Clean HTML parsing via `httpx`.
3. Headless browser automation.

**No anti-bot evasion.** Stores with captchas, anti-bot protection, or mandatory authentication are excluded
and flagged in the UI. Low request rate: one page at a time, throttled pauses, once or twice daily.

## Scheduling

- External scheduler (cron, systemd timer, or agent) invokes `deploy/coleta-diaria.sh`. No LLM in the loop:
  the shell script and Python collector handle everything.
- Alerts: triggered only on new deals or collection failures. Routine runs operate in silence (empty stdout).

## What the App Does Not Do

No checkout automation, shopping carts, or store account logins. The app reads public prices only.

## Accepted Stores and Listings

- **Collected stores:** KaBuM!, Terabyte, and Amazon. Pichau, Mercado Livre, and Shopee block bots: they show in the UI as "excluded (blocking bots)" (`stores.status_note`).
- **Used items permitted.** The UI stores and shows the `condition` (new/used) per listing; deals are calculated independently per condition (used items do not pull down the 30-day median for new parts).
- **Seller reputation:** accept **official stores OR sellers with a high rating**. The cutoff is defined per marketplace when testing the source.
- Every source is tested before it is added; no anti-bot evasion, and blocking stores stay excluded.

## Collector Details

- `backend/watchlist.json`: 24 monitored parts (initial proposal, customizable). `must`/`exclude` keywords enforce whole-word matching;
  category price floors and anti-combo rules eliminate accessory traps and pre-builts. `alert_below` sets per-part price targets
  (e.g., GPUs up to R$ 1,000, 2 TB HDDs up to R$ 350).
- `app/collect/stores.py`: store-specific scrapers. KaBuM! = `__NEXT_DATA__` (sold directly by KaBuM! or manufacturer official store;
  flash deals accepted only within the active promotion window). Terabyte = `data-tss-*` attributes (decimal point parsing handled). Amazon = search URL
  pre-filtered by "ships from and sold by Amazon" (`rh=p_6:A1ZZFT5FULY4LN`), sponsored results skipped; captcha triggers `StoreBlocked`.
- Used items: titles containing Open Box / used / refurbished / showcase → `condition='used'`. Each listing keeps its own snapshot history,
  so used price drops are evaluated strictly against used baselines.
- Up to 3 listings per part per retailer, prioritizing **in-stock items first** (otherwise cheap out-of-stock listings take all 3 slots).
- Execution command: `uv run python -m app.collect [--dry-run|--notify] [--only X] [--stores a,b]`. One search query at a time, 4 s sleep
  (~6 min total run). Retailers returning blocks: 1 attempt and skip; remaining stores continue.
- Alert triggers: verified deals (≥10% below the 30-day median, ≥7 days of history) or prices dropping below a fixed target, rate-limited to 1 alert per week per listing (`alerts_sent`); store collection failure; script crashes. Normal runs remain silent.
- `deploy/coleta-diaria.sh`: runner for schedulers (stdout becomes the message). Exit code 3 (crashes) is **never** suppressed.
- Suggested schedule: **08:00 and 21:00** (`0 8,21 * * *`). The second collection of the day replaces the first (one record per listing per day,
  unique listing+date index), so history is not duplicated; deal alerts remain limited to once per week per listing.

**Known limits**
- Parts that are out of stock at all 3 stores, or sold only by third parties (which are filtered), do not show up. Used listings on
  marketplaces that block bots (Mercado Livre, Shopee) cannot be collected.
- Amazon search results omit installment totals (`price_installment` empty).

**Tests:** `cd backend && uv run python -B -m pytest`, using saved real pages in `tests/fixtures/` (no network).
