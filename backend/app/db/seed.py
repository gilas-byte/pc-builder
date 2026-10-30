"""Dados iniciais: as 3 lojas, as 2 builds e as configurações. Pode rodar várias vezes sem duplicar."""

import sqlite3

from ..settings import DEFAULT_CHANNELS

CATEGORIES = ("cpu", "motherboard", "ram", "gpu", "storage", "psu", "case", "cooler")
# Placa-mãe não entra em upgrades: trocar a placa é montar outra build.
UPGRADE_CATEGORIES = tuple(c for c in CATEGORIES if c != "motherboard")

# (slug, nome, site, motivo de NÃO coletar — None = a coleta automática lê a loja)
# Teste de 09/10/2026: Pichau, Mercado Livre e Shopee bloqueiam robô; regra do projeto = não contornar.
STORES = (
    ("kabum", "KaBuM!", "https://www.kabum.com.br", None),
    ("pichau", "Pichau", "https://www.pichau.com.br", "bloqueia robô (HTTP 403)"),
    ("terabyte", "Terabyte", "https://www.terabyteshop.com.br", None),
    ("amazon", "Amazon", "https://www.amazon.com.br", None),
    ("mercadolivre", "Mercado Livre", "https://www.mercadolivre.com.br",
     "bloqueia robô (busca pública fechada, site pede verificação)"),
    ("shopee", "Shopee", "https://shopee.com.br", "bloqueia robô (exige login)"),
)

BUILDS = (
    ("Build completa", "full", CATEGORIES),
    ("Upgrades do PC atual", "upgrade", UPGRADE_CATEGORIES),
)

SETTINGS = {
    "promo_threshold": "0.10",   # promoção = pelo menos 10% abaixo da mediana
    "promo_window_days": "30",   # janela da mediana
    "promo_min_days": "7",       # menos que isso = "histórico curto"
}


def seed(conn: sqlite3.Connection) -> None:
    with conn:
        for slug, name, url, note in STORES:
            conn.execute("INSERT OR IGNORE INTO stores (slug, name, base_url) VALUES (?, ?, ?)", (slug, name, url))
            conn.execute("UPDATE stores SET status_note = ? WHERE slug = ?", (note, slug))
        for name, kind, cats in BUILDS:
            conn.execute("INSERT OR IGNORE INTO builds (name, kind) VALUES (?, ?)", (name, kind))
            build_id = conn.execute("SELECT id FROM builds WHERE name = ?", (name,)).fetchone()[0]
            conn.executemany(
                "INSERT OR IGNORE INTO build_items (build_id, category) VALUES (?, ?)",
                [(build_id, c) for c in cats],
            )
        conn.executemany(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", SETTINGS.items()
        )
        # os 9 canais de fábrica: INSERT OR IGNORE não ressuscita canal que a pessoa removeu (fica escondido)
        conn.executemany(
            "INSERT OR IGNORE INTO tg_channels (slug, source, added_at) "
            "VALUES (?, 'padrao', strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime'))",
            [(c,) for c in DEFAULT_CHANNELS],
        )
