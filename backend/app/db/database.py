"""Acesso ao banco SQLite do PC Builder.

Preços sempre em centavos (int). Datas em ISO local 'AAAA-MM-DDTHH:MM:SS'.
"""

from __future__ import annotations

import json
import sqlite3
import statistics
from datetime import datetime, timedelta
from pathlib import Path

from ..secrets_store import data_dir
from .seed import seed

SCHEMA = Path(__file__).with_name("schema.sql")
DEFAULT_DB = data_dir() / "pcbuilder.db"   # PCB_DATA_DIR (Docker: o volume) ou a pasta data/ do projeto


# --------------------------------------------------------------------------- conexão

def connect(path: str | Path = DEFAULT_DB) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Uma conexão por requisição; o servidor pode abrir numa thread e usar em outra.
    conn = sqlite3.connect(path, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(path: str | Path = DEFAULT_DB) -> sqlite3.Connection:
    """Cria as tabelas (se faltarem) e insere os dados iniciais. Seguro de rodar sempre."""
    conn = connect(path)
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    _migrate(conn)
    seed(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Colunas novas em bancos criados antes delas (CREATE TABLE IF NOT EXISTS não altera tabela velha)."""
    def cols(table):
        return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}

    adds = [
        ("parts", "image_url", "TEXT CHECK (image_url IS NULL OR image_url LIKE 'https://%')"),
        ("stores", "status_note", "TEXT"),
        ("listings", "condition", "TEXT NOT NULL DEFAULT 'new' CHECK (condition IN ('new', 'used'))"),
        ("listings", "seller", "TEXT"),
        # peça vista só nos canais do Telegram (source='canal'), agrupada por tg_key
        ("parts", "source", "TEXT NOT NULL DEFAULT 'loja' CHECK (source IN ('loja', 'canal'))"),
        ("parts", "tg_key", "TEXT"),
        # foto da oferta do canal (o link remoto vence em ~1 dia → cópia local em data/tg_img)
        ("tg_offers", "image_src", "TEXT"),
        ("tg_offers", "image_path", "TEXT"),
        ("tg_offers", "image_tries", "INTEGER NOT NULL DEFAULT 0"),
        # configurações pela tela. `tg_channels.active` já é o liga/desliga; removido = escondido
        # (removed_at), nunca apagado, pra não perder o histórico das ofertas.
        ("settings", "updated_at", "TEXT"),
        ("tg_channels", "added_at", "TEXT"),
        ("tg_channels", "source", "TEXT CHECK (source IS NULL OR source IN ('padrao', 'usuario'))"),
        ("tg_channels", "removed_at", "TEXT"),
    ]
    with conn:
        for table, col, ddl in adds:
            if col not in cols(table):
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
        # de onde veio o tipo da oferta. Antes dela, todo tipo veio da votação (só na criação da coluna).
        if "kind_source" not in cols("tg_offers"):
            conn.execute("ALTER TABLE tg_offers ADD COLUMN kind_source TEXT "
                         "CHECK (kind_source IS NULL OR kind_source IN ('ollama', 'rules'))")
            conn.execute("UPDATE tg_offers SET kind_source = 'ollama' WHERE kind IS NOT NULL")
        # canais de antes do cadastro pela tela: os 9 de fábrica viram 'padrao', o resto 'usuario'
        from ..settings import DEFAULT_CHANNELS
        conn.execute(f"UPDATE tg_channels SET source = CASE WHEN slug IN ({','.join('?' * len(DEFAULT_CHANNELS))}) "
                     "THEN 'padrao' ELSE 'usuario' END WHERE source IS NULL", DEFAULT_CHANNELS)
        conn.execute("UPDATE tg_channels SET added_at = strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime') "
                     "WHERE added_at IS NULL")


def get_setting(conn: sqlite3.Connection, key: str, default: str) -> str:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


# --------------------------------------------------------------------------- escrita

class ListingConflict(ValueError):
    """O link já existe, mas aponta pra outra peça."""


def upsert_part(conn: sqlite3.Connection, category: str, brand: str, model: str, specs: dict,
                image_url: str | None = None) -> tuple[int, bool]:
    """Acha a peça por (categoria, marca, modelo) ou cria. Specs novos completam os antigos.
    Imagem nova substitui a antiga; sem imagem nova, a antiga fica.

    Retorna (id, criada?). Não faz commit: quem chama controla a transação.
    """
    row = conn.execute(
        "SELECT id, specs FROM parts WHERE category = ? AND brand = ? AND model = ?",
        (category, brand, model),
    ).fetchone()
    if row is None:
        cur = conn.execute(
            "INSERT INTO parts (category, brand, model, specs, image_url) VALUES (?, ?, ?, ?, ?)",
            (category, brand, model, json.dumps(specs, ensure_ascii=False), image_url),
        )
        return cur.lastrowid, True
    if specs:
        merged = {**json.loads(row["specs"]), **specs}
        conn.execute("UPDATE parts SET specs = ? WHERE id = ?",
                     (json.dumps(merged, ensure_ascii=False), row["id"]))
    if image_url:
        conn.execute("UPDATE parts SET image_url = ? WHERE id = ?", (image_url, row["id"]))
    return row["id"], False


def upsert_listing(conn: sqlite3.Connection, part_id: int, store_id: int, url: str, title: str | None,
                   condition: str = "new", seller: str | None = None) -> tuple[int, bool]:
    """Acha o link pela URL ou cria. Retorna (id, criado?). Não faz commit.

    condition: 'new' ou 'used'. Cada link tem o próprio histórico, então a promoção de um usado
    é calculada só com preços daquele anúncio usado (não puxa a mediana do novo).
    """
    row = conn.execute("SELECT id, part_id FROM listings WHERE url = ?", (url,)).fetchone()
    if row is None:
        cur = conn.execute(
            "INSERT INTO listings (part_id, store_id, url, title, condition, seller) VALUES (?, ?, ?, ?, ?, ?)",
            (part_id, store_id, url, title, condition, seller),
        )
        return cur.lastrowid, True
    if row["part_id"] != part_id:
        raise ListingConflict(f"o link {url} já pertence a outra peça (id {row['part_id']})")
    conn.execute("UPDATE listings SET title = COALESCE(?, title), condition = ?, seller = COALESCE(?, seller) "
                 "WHERE id = ?", (title, condition, seller, row["id"]))
    return row["id"], False


def insert_snapshot(
    conn: sqlite3.Connection,
    listing_id: int,
    price_cash: int,
    in_stock: bool,
    collected_at: str,
    price_installment: int | None = None,
) -> int:
    """Grava o preço de um link SEM commit. No mesmo dia, substitui o registro anterior."""
    datetime.fromisoformat(collected_at)  # recusa data mal formatada
    cur = conn.execute(
        """INSERT OR REPLACE INTO price_snapshots
           (listing_id, price_cash, price_installment, in_stock, collected_at)
           VALUES (?, ?, ?, ?, ?)""",
        (listing_id, int(price_cash), price_installment, int(bool(in_stock)), collected_at),
    )
    return cur.lastrowid


def record_snapshot(
    conn: sqlite3.Connection,
    listing_id: int,
    price_cash: int,
    in_stock: bool,
    collected_at: str,
    price_installment: int | None = None,
) -> int:
    """Igual ao insert_snapshot, mas já faz o commit."""
    with conn:
        return insert_snapshot(conn, listing_id, price_cash, in_stock, collected_at, price_installment)


# --------------------------------------------------------------------------- leitura

def latest_prices(conn: sqlite3.Connection, part_id: int) -> list[dict]:
    """Preço mais recente de cada loja ativa para uma peça."""
    rows = conn.execute(
        """SELECT l.id AS listing_id, l.url, l.title, l.condition, l.seller,
                  st.slug AS store, st.name AS store_name,
                  v.price_cash, v.price_installment, v.in_stock, v.collected_at
           FROM listings l
           JOIN stores st ON st.id = l.store_id
           JOIN v_latest_price v ON v.listing_id = l.id
           WHERE l.part_id = ? AND l.active = 1 AND st.active = 1
           ORDER BY v.price_cash""",
        (part_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def best_price(conn: sqlite3.Connection, part_id: int) -> dict | None:
    """Menor preço à vista entre as lojas, só com estoque. None se não houver."""
    for p in latest_prices(conn, part_id):
        if p["in_stock"]:
            return p
    return None


def last_known_price(conn: sqlite3.Connection, part_id: int) -> dict | None:
    """Menor preço mais recente SEM estoque (só pra mostrar referência apagada na tela; build e promoção não usam)."""
    for p in latest_prices(conn, part_id):
        if not p["in_stock"]:
            return p
    return None


def price_history(conn: sqlite3.Connection, part_id: int, days: int | None = None) -> list[dict]:
    sql = """SELECT st.slug AS store, s.price_cash, s.price_installment, s.in_stock, s.collected_at
             FROM price_snapshots s
             JOIN listings l ON l.id = s.listing_id
             JOIN stores st ON st.id = l.store_id
             WHERE l.part_id = ?"""
    args: list = [part_id]
    if days is not None:
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
        sql += " AND s.collected_at >= ?"
        args.append(since)
    sql += " ORDER BY s.collected_at, st.slug"
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def deal_status(conn: sqlite3.Connection, listing_id: int) -> dict:
    """Compara o preço mais recente com a mediana dos dias ANTERIORES dentro da janela.

    status: 'deal' (promoção), 'normal', 'short_history' (poucos dias) ou 'no_data'.
    """
    threshold = float(get_setting(conn, "promo_threshold", "0.10"))
    window = int(get_setting(conn, "promo_window_days", "30"))
    min_days = int(get_setting(conn, "promo_min_days", "7"))

    latest = conn.execute(
        "SELECT * FROM v_latest_price WHERE listing_id = ?", (listing_id,)
    ).fetchone()
    if latest is None:
        return {"status": "no_data"}

    latest_day = datetime.fromisoformat(latest["collected_at"]).date()
    since = (latest_day - timedelta(days=window)).isoformat()
    previous = [
        r["price_cash"]
        for r in conn.execute(
            """SELECT price_cash FROM price_snapshots
               WHERE listing_id = ? AND substr(collected_at, 1, 10) >= ?
                 AND substr(collected_at, 1, 10) < ?""",
            (listing_id, since, latest_day.isoformat()),
        )
    ]
    base = {"price_cash": latest["price_cash"], "days_of_history": len(previous)}
    if len(previous) < min_days:
        return {**base, "status": "short_history"}

    median = statistics.median(previous)
    drop = (median - latest["price_cash"]) / median
    return {
        **base,
        "median_cash": round(median),
        "drop_pct": round(drop * 100, 1),
        "status": "deal" if drop >= threshold else "normal",
    }


def list_deals(conn: sqlite3.Connection) -> list[dict]:
    """Links em promoção hoje, com estoque, maior queda primeiro."""
    rows = conn.execute(
        """SELECT l.id AS listing_id, l.url, l.part_id, l.condition, l.seller, p.category, p.brand, p.model,
                  st.slug AS store, st.name AS store_name, v.in_stock
           FROM listings l
           JOIN parts p ON p.id = l.part_id
           JOIN stores st ON st.id = l.store_id
           JOIN v_latest_price v ON v.listing_id = l.id
           WHERE l.active = 1 AND st.active = 1 AND v.in_stock = 1"""
    ).fetchall()
    deals = []
    for r in rows:
        d = deal_status(conn, r["listing_id"])
        if d["status"] == "deal":
            deals.append({**dict(r), **d})
    return sorted(deals, key=lambda d: d["drop_pct"], reverse=True)


def build_total(conn: sqlite3.Connection, build_id: int) -> dict:
    """Soma o melhor preço de cada peça escolhida e lista o que falta."""
    items = conn.execute(
        """SELECT bi.category, bi.part_id, p.brand, p.model
           FROM build_items bi LEFT JOIN parts p ON p.id = bi.part_id
           WHERE bi.build_id = ? ORDER BY bi.category""",
        (build_id,),
    ).fetchall()
    total, out, missing, unavailable = 0, [], [], []
    for it in items:
        entry = dict(it)
        if it["part_id"] is None:
            missing.append(it["category"])
            entry["best"] = None
        else:
            best = best_price(conn, it["part_id"])
            entry["best"] = best
            if best is None:
                unavailable.append(it["category"])
            else:
                total += best["price_cash"]
        out.append(entry)
    return {
        "build_id": build_id,
        "total_cash": total,
        "items": out,
        "missing": missing,
        "unavailable": unavailable,
    }
