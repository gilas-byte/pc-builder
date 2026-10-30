PRAGMA foreign_keys = ON;

-- Lojas onde a coleta procura preço.
CREATE TABLE IF NOT EXISTS stores (
    id        INTEGER PRIMARY KEY,
    slug      TEXT    NOT NULL UNIQUE,
    name      TEXT    NOT NULL,
    base_url  TEXT    NOT NULL,
    active    INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    status_note TEXT  -- NULL = a coleta automática lê esta loja; texto = por que não (bloqueio etc.)
);

-- A peça em si, independente de loja.
CREATE TABLE IF NOT EXISTS parts (
    id          INTEGER PRIMARY KEY,
    category    TEXT NOT NULL CHECK (category IN
                    ('cpu', 'motherboard', 'ram', 'gpu', 'storage', 'psu', 'case', 'cooler')),
    brand       TEXT NOT NULL,
    model       TEXT NOT NULL,
    specs       TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(specs)),
    image_url   TEXT CHECK (image_url IS NULL OR image_url LIKE 'https://%'),
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime')),
    UNIQUE (category, brand, model)
);

-- Peças que o usuário marcou pra acompanhar.
CREATE TABLE IF NOT EXISTS favorites (
    part_id     INTEGER PRIMARY KEY REFERENCES parts(id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime'))
);

-- A peça numa loja: é aqui que fica o link.
CREATE TABLE IF NOT EXISTS listings (
    id        INTEGER PRIMARY KEY,
    part_id   INTEGER NOT NULL REFERENCES parts(id) ON DELETE CASCADE,
    store_id  INTEGER NOT NULL REFERENCES stores(id),
    url       TEXT    NOT NULL UNIQUE,
    title     TEXT,
    active    INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    condition TEXT    NOT NULL DEFAULT 'new' CHECK (condition IN ('new', 'used')),
    seller    TEXT
);
CREATE INDEX IF NOT EXISTS idx_listings_part ON listings(part_id);

-- Histórico de preço. Valores em CENTAVOS (R$ 1.299,90 = 129990).
CREATE TABLE IF NOT EXISTS price_snapshots (
    id                 INTEGER PRIMARY KEY,
    listing_id         INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    price_cash         INTEGER NOT NULL CHECK (price_cash > 0),
    price_installment  INTEGER CHECK (price_installment IS NULL OR price_installment > 0),
    in_stock           INTEGER NOT NULL CHECK (in_stock IN (0, 1)),
    collected_at       TEXT    NOT NULL
);
-- Um registro por link por dia: coletar duas vezes no mesmo dia substitui, não duplica.
CREATE UNIQUE INDEX IF NOT EXISTS uq_snap_listing_day
    ON price_snapshots(listing_id, substr(collected_at, 1, 10));
CREATE INDEX IF NOT EXISTS idx_snap_listing_time
    ON price_snapshots(listing_id, collected_at);

-- Build completa e lista de upgrades.
CREATE TABLE IF NOT EXISTS builds (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    kind        TEXT NOT NULL CHECK (kind IN ('full', 'upgrade')),
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS build_items (
    build_id  INTEGER NOT NULL REFERENCES builds(id) ON DELETE CASCADE,
    category  TEXT    NOT NULL CHECK (category IN
                  ('cpu', 'motherboard', 'ram', 'gpu', 'storage', 'psu', 'case', 'cooler')),
    part_id   INTEGER REFERENCES parts(id) ON DELETE SET NULL,
    PRIMARY KEY (build_id, category)
);

-- Configurações simples (limite de promoção etc.).
CREATE TABLE IF NOT EXISTS settings (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);

-- Preço mais recente de cada link.
CREATE VIEW IF NOT EXISTS v_latest_price AS
SELECT s.*
FROM price_snapshots s
WHERE s.id = (
    SELECT s2.id FROM price_snapshots s2
    WHERE s2.listing_id = s.listing_id
    ORDER BY s2.collected_at DESC, s2.id DESC
    LIMIT 1
);

-- ---------------------------------------------------------------- canais do Telegram
-- Canais públicos lidos pela página t.me/s/<canal> (sem login). last_msg_id = até onde já li.
CREATE TABLE IF NOT EXISTS tg_channels (
    slug         TEXT PRIMARY KEY,
    title        TEXT,
    active       INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    last_msg_id  INTEGER NOT NULL DEFAULT 0,
    last_ok_at   TEXT,
    fail_count   INTEGER NOT NULL DEFAULT 0,
    last_error   TEXT
);

-- Ofertas de tecnologia vistas nos canais. Casa/moda/comida e cupom não são guardados.
-- kind NULL = ainda não classificado (Ollama fora do ar); 'duvidoso' = os 3 modelos discordaram.
-- product_key só existe quando dá pra afirmar que é o MESMO produto (script e IA concordam no tipo).
CREATE TABLE IF NOT EXISTS tg_offers (
    id           INTEGER PRIMARY KEY,
    channel      TEXT    NOT NULL REFERENCES tg_channels(slug),
    msg_id       INTEGER NOT NULL,
    posted_at    TEXT    NOT NULL,
    seen_at      TEXT    NOT NULL,
    title        TEXT    NOT NULL,
    text         TEXT    NOT NULL,
    price_cash   INTEGER NOT NULL CHECK (price_cash > 0),
    store        TEXT,
    link         TEXT,
    kind         TEXT,
    kind_votes   TEXT CHECK (kind_votes IS NULL OR json_valid(kind_votes)),
    kind_agree   INTEGER CHECK (kind_agree IS NULL OR kind_agree BETWEEN 0 AND 3),
    product_key  TEXT,
    UNIQUE (channel, msg_id)
);
CREATE INDEX IF NOT EXISTS idx_tg_offers_key    ON tg_offers(product_key, posted_at);
CREATE INDEX IF NOT EXISTS idx_tg_offers_posted ON tg_offers(posted_at);
CREATE INDEX IF NOT EXISTS idx_tg_offers_kind   ON tg_offers(kind);

-- 1 aviso por produto por dia.
CREATE TABLE IF NOT EXISTS tg_alerts_sent (
    product_key  TEXT NOT NULL,
    day          TEXT NOT NULL,
    offer_id     INTEGER REFERENCES tg_offers(id) ON DELETE CASCADE,
    PRIMARY KEY (product_key, day)
);
