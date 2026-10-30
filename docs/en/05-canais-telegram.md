Português: [../05-canais-telegram.md](../05-canais-telegram.md)

# Telegram Channel Deals

Scheduled every 45 min → `deploy/canais-telegram.sh` →
`python -m app.tg --notify`.
UI: **Channels** menu (`#/canais`).
Local Ollama (optional; address configured in Settings, default `127.0.0.1:11434`). Without Ollama, uses rule-based classifier
(see "Rule-based Classifier and Modes" section below).

## Rationale

Stores with aggressive bot blocking (Pichau, Mercado Livre, Shopee) appear constantly in public Telegram deal channels.
Scraping these channels retrieves those prices without bypassing anti-bot systems and populates the database with price references.

## Design Decisions

1. **Channels:** 9 public channels that offer web previews (listed below). The 2 Canaltech channels are excluded:
   they are public, but web previews are disabled, requiring user account login (out of scope).
2. **No history pruning.** Neither channels nor stores purge past data. Sizing calculation: ~1,100 posts/day across 9 channels
   = ~400,000/year, ~240 MB/year stored in full; SQLite handles this easily.
3. **Scope:** curated deals for **tech products** (PC parts, monitors, peripherals, laptops/MacBooks,
   audio, gaming consoles...). Home goods, fashion, food, etc., are ignored. MacBooks are now in scope.
4. **Scraping interval every 45 min**, without remote AI models in the loop (script handles end-to-end execution).
5. **Telegram alerts** dispatched when a deal for the **exact same product** is:
   - **7% or more below** reference price, **or**
   - **the lowest price ever recorded** (even if under 7% drop).
   Reference = lowest previously recorded price for the exact product across both channels and tracked PC Builder stores.
   Requires at least 3 previous sightings (ensuring a reliable historical baseline). 1 alert per product per day.
6. **Local AI** (Ollama on local host, lightweight model such as `qwen2.5:3b`) used solely to classify product **category**
   when heuristics are inconclusive. AI **never** evaluates price calculations or product identity matching (strictly rule-governed and tested).

## Channels

| Channel | Posts/day (measured) | Notes |
|---|---|---|
| OPromoFacil | ~530 | General variety; heavy Shopee presence |
| descontoemgames | ~160 | Focused on games and consoles |
| grupo_promocoes | ~115 | General deals, "por R$ X no pix" patterns |
| EconomizandocomJP | ~70 | PC hardware and laptops, "POR: 279" without currency sign |
| especialistaemti | ~60 | Laptops |
| ToptechPROMO | ~55 | "💸 R$ 229" pattern |
| gpcrpromo | ~55 | Desktop hardware |
| escolhasegura | ~40 | Broad tech and gadgets |
| lipeofertas | ~12 | Laptops and tech, "De/Por" format |

Live sample dataset (1,077 posts, 1,011 with prices): Mercado Livre 383, Shopee 291, Amazon 267, Magalu 32.
PC components / monitors ~180, non-component tech ~300 (keyword match), remainder ~530 (home/lifestyle + complex tech → local AI).

## Pipeline Design

- **Ingestion:** public web preview `t.me/s/<channel>`, crawling backwards to last seen message ID (max ~10
  pages per channel per run, throttle delay between requests). Single channel failure does not halt others; error surfaces as alert.
- **Extraction:** promo price ("por" / first currency occurrence excluding "De:" or coupons); retailer inferred from link domain;
  inflated list prices ("De:") are ignored.
- **Classification:** heuristic parser (hardware keywords + tech catalog); ambiguities → local AI; if Ollama is unreachable,
  unclassified offers remain "untyped" without data loss (re-evaluated on subsequent runs).
- **Product Normalization (tg_key):** category-specific canonical keys (GPU = chipset + VRAM; CPU = model; RAM = DDR + capacity + MHz;
  SSD = interface + capacity + brand/model; PSU = brand + wattage + 80-Plus rating; motherboard = brand + chipset; cooler/case = model code;
  monitor = brand + size + resolution + refresh rate; MacBook = chip + RAM + SSD). Unmatched items appear in UI catalog but omit alert notifications.
- **Database:** new tables `tg_channels`, `tg_offers` (unique constraint on channel + message ID), `tg_alerts_sent`.
  Preserves existing retail store tables intact.
- **UI:** dedicated "Channels" view in PC Builder (filters by category, store, channel; discount badge). Integrates with builds/upgrades.

## Category Classifier with Local Models

No model fine-tuning: "training" consisted of prompt iteration and few-shot examples evaluated against real, human-labeled
posts (measured before publication; the benchmark data is not part of this repository). The best prompt was the 2-stage one
("is it tech?" then "which category?"), with appliances, air conditioners and tools = no, headset = audio, and game ≠ coupon.

Ensemble validation with 3 models (`qwen2.5:3b`, `llama3.2:3b`, `gemma3:4b`) on a held-out set: **unanimous on 84% of posts
with 98.4% accuracy**; 2/3 majority vote = 92.5%. Inference speed per post: GPU qwen 0.15 s, gemma 0.47 s, llama 1.7 s;
CPU (no GPU) qwen ~2 s, gemma ~7 s. Remaining edge-case errors: car battery chargers, LEGO sets, kitchen containers, washing
machines with "Inverter" motor branding (electronic terminology applied to non-tech items), and tablet vs. laptop confusion.

## Implementation

- Codebase: `backend/app/tg/` — `parse.py` (DOM scraping, price extraction, store normalization), `classify.py` (title parsing, hardware detection, product key generation),
  `vote.py` (3-model voting harness), `run.py` (crawl orchestrator, reference pricing, alert dispatch). Read-only endpoints: `/api/tg/offers`, `/api/tg/meta`.
- **Model Execution:** one model at a time on GPU (all 3 together exceed 8 GB VRAM: 3rd model spilled to CPU) and each is
  unloaded immediately after inference (`keep_alive 0`). VRAM stays free between runs. Measured overhead: ~2 s warm-up per model +
  qwen 0.12 / llama 0.15 / gemma 0.39 s per post. Typical run (10–40 new items): 15–40 s.
- **Canonical Key Validation:** heuristic parser and AI voting must agree on product category (a laptop title containing "RTX" never
  classifies as GPU). Cooler and case color/edition variants are preserved (AK400 ≠ AK400 Zero Dark ≠ AK400 WH ≠ AK400 RD: real bug
  caught during first run where median blended R$ 150 and R$ 237). Monitors index by exact model code when present (24GS60F).
- **Network Resilience:** t.me drops connections intermittently → 2 retries with exponential backoff (5 s, 10 s). Channel health alerts
  trigger only after 3 consecutive failed runs. Unreachable Ollama → store as unclassified and dispatch warning.

## Channel Parts = Real Inventory

All parts from every source appear in a single unified catalog; only the card color differs (subtle blue accent = Telegram), and the
builder incorporates channel parts.
- `app/tg/sync.py` (runs at end of collection and during `reclassify`): registers pseudo-store `canal` ("Canais do Telegram");
  each hardware offer = 1 listing (URL = post link, seller = "Shopee via @canal", price timestamped to post).
  Matching canonical key with an existing retail part → attaches to existing catalog entry and competes on price; otherwise → creates new
  part entry with `parts.source = 'canal'` grouped by `tg_key`. Hardware specs extracted from post text (socket from chipset/CPU generation,
  memory generation, form factors, PSU wattage, cooler mounts); missing values flagged as "unverified" in build validator.
- Posts older than 14 days transition to "out of stock" (pruned from automatic builds, struck through in lists). Reclassified non-hardware items are pruned;
  channel parts with zero active listings are purged.
- Price reference calculation excludes the `canal` pseudo-store (posts are already factored through `tg_offers`, avoiding double-counting).
- UI: `.is-tg` card styling (light blue border) when part originates from a channel OR current lowest price is from a channel;
  active promotion highlight (yellow) supersedes blue styling. Direct "View on Telegram" button provided. Identical rendering in build drawers and detail views.
- A laptop post titled "🔥 RYZEN 5 COM BOM PREÇO" used to be misclassified as a desktop CPU, so the title parser strips clickbait prefixes
  and voting reads title + first specification line (`vote_text`).

## Rule-based Classifier and Modes

Users running without Ollama can classify channel offers via `backend/app/tg/rules.py` (`rules_kind`), which leverages the rules
from `classify.py` to identify hardware, monitors, "non-hardware", or None (ambiguous). Ambiguities never become hardware listings.
Only items with complete specification sheets (including canonical product key) enter price comparisons and alert checks.

| Mode (`classifier`, `PCB_CLASSIFIER`) | Behavior |
|---|---|
| `auto` (default) | Probes Ollama (`/api/version`, 3 s timeout). If responsive → uses AI voting. If unreachable or drops mid-run → falls back to rules with **one** notice per incident ("Ollama did not respond; using rules. Offers will be re-evaluated when online"). On recovery, re-votes rules-classified and untyped items. |
| `rules` | Rules-only classification. Never contacts Ollama. |
| `ollama` | AI voting only. If unreachable → preserves untyped offers (legacy behavior) and reports error in alert; never falls back to rules. |

Voting engine supports 1 to 3 models: 1 model acts solo, 2 require consensus, 3 follows majority rule (3 default models produce
identical output to initial implementation; verified by regression tests). Each offer records classification provenance in `tg_offers.kind_source`
(`ollama` | `rules`). Offers classified by rules as "non-hardware" are excluded from the Channels tab (rules do not differentiate general tech from everyday household items).

Rule accuracy on real public-channel offers labeled by hand (measured before publication; the number shown in the UI comes from
`backend/app/tg/rules_metrics.json`):

| Dataset | Correct | Ambiguous | Hallucinated Part |
|---|---|---|---|
| tuning (148) | 148/148 = 100% | 0 | 0 |
| held-out (147) | 146/147 = 99.3% | 1 | 0 |
| **Combined** | **294/295 = 99.7%** | 1 | 0 |

Accuracy breakdown by category (combined): GPU 2/2, SSD/HDD 3/3, Case 3/3, Cooler 4/4, Monitor 26/26, Non-hardware 256/257
(single miss: "MEMÓRIA RAM DDR5 8GB 4800MHZ" lacking explicit desktop markers, which the rule safely marks ambiguous).
Note on evaluation: datasets contain only 38 hardware/monitor items, zero CPUs, motherboards, desktop RAM, or power supplies, and rules were
refined examining error cases from both sets (the held-out set no longer serves as an unobserved blind test). Pre-adjustment baseline: 289/295 =
98.0% with 1 false positive hardware part (laptop "HP 200 G2i ... 256GB SSD" misclassified as SSD).

## Tests

Parsers tested with saved real pages (`backend/tests/fixtures/`), multi-format price strings across all 9 channels, exclusion filters against
real-world false positives (blenders, smartphones "with octa-core processor", monitor arms, pre-assembled systems), canonical key generation,
7% / lowest-price rules, minimum 3 sighting requirement, idempotent re-runs, once-daily alert rate limits, channel outages, and Ollama failure modes.
Run: `cd backend && uv run python -B -m pytest`.
