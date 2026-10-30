"""Peças vistas nos canais viram peças DE VERDADE (tabela parts), pra aparecerem em Peças, Builds, favoritos e
detalhe igual às das lojas (decisão do projeto, 12/10/2026: "todas as peças juntas, só muda a cor do cartão").

Como: uma "loja" `canal` (Canais do Telegram). Cada post de peça = um anúncio (listing) dessa loja, URL = link
do post, vendedor = "<loja real> via @canal", 1 preço na data do post.
- Mesma chave de produto de uma peça das lojas → o anúncio entra NESSA peça (concorre pelo menor preço).
- Senão → peça nova com `source = 'canal'`, agrupada pela chave (ou pelo título, sem chave).
- Post com mais de EXPIRE_DAYS dias ganha um preço "sem estoque" (oferta relâmpago não fica fingindo que vale).
- Post que deixou de ser peça (revotação) sai; peça de canal sem anúncio nenhum some.
Specs (socket, DDR, formato, watts) saem do texto quando dá; o que faltar vira "não verificado" na build.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timedelta

from ..collect.watchlist import norm
from .classify import _brand, product_key

STORE = ("canal", "Canais do Telegram", "https://t.me")
EXPIRE_DAYS = 14
KIND2CAT = {f"peca:{c}": c for c in ("cpu", "motherboard", "ram", "gpu", "storage", "psu", "case", "cooler")}
STORE_LABEL = {"amazon": "Amazon", "mercadolivre": "Mercado Livre", "shopee": "Shopee", "kabum": "KaBuM!",
               "terabyte": "Terabyte", "pichau": "Pichau", "magalu": "Magalu", "aliexpress": "AliExpress"}

# chipset → (socket, memória). Formato sai do "M" no fim (B550M = mATX) ou do texto.
CHIPSET = {
    "a320": ("AM4", "DDR4"), "a520": ("AM4", "DDR4"), "b450": ("AM4", "DDR4"), "b550": ("AM4", "DDR4"),
    "x570": ("AM4", "DDR4"), "a620": ("AM5", "DDR5"), "b650": ("AM5", "DDR5"), "b650e": ("AM5", "DDR5"),
    "x670": ("AM5", "DDR5"), "x670e": ("AM5", "DDR5"), "b840": ("AM5", "DDR5"), "b850": ("AM5", "DDR5"),
    "x870": ("AM5", "DDR5"), "x870e": ("AM5", "DDR5"), "h610": ("LGA1700", None), "b660": ("LGA1700", None),
    "b760": ("LGA1700", None), "h770": ("LGA1700", None), "z690": ("LGA1700", None), "z790": ("LGA1700", None),
    "b860": ("LGA1851", "DDR5"), "h810": ("LGA1851", "DDR5"), "z890": ("LGA1851", "DDR5"),
}


def _cpu_socket(h: str) -> str | None:
    m = re.search(r" ryzen [3579] (\d)(\d{3})", h)
    if m:
        gen = int(m.group(1))
        return "AM5" if gen >= 7 else "AM4"
    m = re.search(r" (?:core )?i[3579] ?(\d{2})\d{3}", h)
    if m:
        return "LGA1700" if int(m.group(1)) in (12, 13, 14) else None
    if re.search(r" core ultra [579] 2\d\d", h):
        return "LGA1851"
    return None


def specs_from_text(category: str, text: str) -> dict:
    h = norm(text)
    s: dict = {}
    if category == "cpu":
        sock = _cpu_socket(h)
        if sock:
            s["socket"] = sock
    elif category == "motherboard":
        m = re.search(r" (a320|a520|b450|b550|x570|a620|b650e?|x670e?|b840|b850|x870e?|h610|b660|b760|h770|z690|"
                      r"z790|b860|h810|z890)(m?)", h)
        if m:
            sock, mem = CHIPSET[m.group(1)]
            s["socket"] = sock
            ddr = re.search(r" ddr([45]) ", h)
            if ddr:
                s["memory_type"] = f"DDR{ddr.group(1)}"
            elif mem:
                s["memory_type"] = mem
            if m.group(2) == "m" or re.search(r" (matx|micro atx|m atx) ", h):
                s["form_factor"] = "mATX"
            elif re.search(r" (itx|mini itx) ", h):
                s["form_factor"] = "ITX"
            elif re.search(r" atx ", h):
                s["form_factor"] = "ATX"
    elif category == "ram":
        ddr = re.search(r" ddr([45]) ", h)
        if ddr:
            s["memory_type"] = f"DDR{ddr.group(1)}"
    elif category == "psu":
        w = re.search(r" (\d{3,4})w ", h)
        if w:
            s["wattage_w"] = int(w.group(1))
    elif category == "case":
        # micro/mini primeiro: "M-ATX" normaliza pra "m atx", que também contém " atx "
        if re.search(r" (matx|m atx|micro atx|mini tower) ", h):
            s["motherboard_support"] = ["mATX", "ITX"]
        elif re.search(r" (e atx|eatx|mid tower|full tower|atx) ", h):
            s["motherboard_support"] = ["ATX", "mATX", "ITX"]
    elif category == "cooler":
        socks = set()
        if re.search(r" am4 ", h):
            socks.add("AM4")
        if re.search(r" am5 ", h):
            socks.add("AM5")
        if re.search(r" (lga ?1700|1700) ", h):
            socks.add("LGA1700")
        if re.search(r" (lga ?1851|1851) ", h):
            socks.add("LGA1851")
        if socks:
            s["sockets"] = sorted(socks)
    return s


def _group_key(row) -> str:
    return row["product_key"] or "t:" + norm(row["title"]).strip()[:120]


def _store_part_keys(conn) -> dict[str, int]:
    """chave do produto → peça das LOJAS (pelos títulos dos anúncios das lojas, não dos canais)."""
    out = {}
    for r in conn.execute(
            "SELECT p.id, p.category, l.title FROM listings l JOIN parts p ON p.id = l.part_id "
            "JOIN stores st ON st.id = l.store_id WHERE st.slug != 'canal' AND p.source = 'loja' "
            "AND l.condition = 'new' AND l.title IS NOT NULL ORDER BY p.id"):
        k = product_key(r["title"], r["category"])
        if k:
            out.setdefault(k, r["id"])
    return out


GENERIC_WORDS = re.compile(r"^(placa[- ]m[ãa]e|placa de v[íi]deo|processador|mem[óo]ria( ram)?|ssd|hd( interno)?|"
                           r"fonte( gamer)?|gabinete( gamer)?( aqu[áa]rio)?|air cooler|water ?cooler|cooler( para "
                           r"processador)?|gpu)\s+", re.I)
BRAND_FIX = {"amd": "AMD", "msi": "MSI", "tgt": "TGT", "nzxt": "NZXT", "pny": "PNY", "xfx": "XFX", "asl": "ASL",
             "pcyes": "PCYes", "xpg": "XPG", "wd": "WD", "lg": "LG", "aoc": "AOC", "hp": "HP"}


def _brand_model(title: str) -> tuple[str, str]:
    """("Gabinete Gamer TGT Jester V2, Rainbow" → ("TGT", "Jester V2, Rainbow")). Tira o "(Amazon)" do fim,
    a palavra genérica do começo e a marca repetida."""
    t = re.sub(r"[\s-]*\((?:amazon|shopee|mercado livre|kabum|magalu)\)\s*$", "", title, flags=re.I).strip()
    t = GENERIC_WORDS.sub("", t).strip()
    b = _brand(norm(t), skip=("fury", "vengeance")) or _brand(norm(title), skip=("fury", "vengeance"))
    if not b:
        return "—", t[:120]
    brand = BRAND_FIX.get(b, b.title())
    t = re.sub(r"^" + re.escape(b) + r"\b\s*", "", t, flags=re.I).strip()
    t = re.sub(r"\s+" + re.escape(b) + r"\b", "", t, count=1, flags=re.I).strip() if t.lower().count(b) > 0 else t
    return brand, (t or title)[:120]


def sync(conn: sqlite3.Connection, now: datetime | None = None) -> dict:
    """Deixa parts/listings/price_snapshots em dia com tg_offers. Idempotente. Não faz commit fora do `with`."""
    now = (now or datetime.now()).replace(microsecond=0)
    with conn:
        conn.execute("INSERT OR IGNORE INTO stores (slug, name, base_url) VALUES (?, ?, ?)", STORE)
        store_id = conn.execute("SELECT id FROM stores WHERE slug = 'canal'").fetchone()[0]
        offers = conn.execute("SELECT * FROM tg_offers WHERE kind LIKE 'peca:%' ORDER BY posted_at").fetchall()
        keep_urls, created, attached = set(), 0, 0
        store_keys = _store_part_keys(conn)
        for o in offers:
            cat = KIND2CAT.get(o["kind"])
            if not cat:
                continue
            keep_urls.add(o["link"])
            existing = conn.execute("SELECT id FROM listings WHERE url = ?", (o["link"],)).fetchone()
            if existing:
                continue
            gkey = _group_key(o)
            pid = store_keys.get(o["product_key"]) if o["product_key"] else None
            if pid is None:
                row = conn.execute("SELECT id FROM parts WHERE tg_key = ? AND category = ?", (gkey, cat)).fetchone()
                if row:
                    pid = row["id"]
                else:
                    brand, model = _brand_model(o["title"])
                    specs = specs_from_text(cat, o["text"])
                    for suffix in ("", f" ({o['channel']}/{o['msg_id']})"):
                        try:
                            pid = conn.execute(
                                "INSERT INTO parts (category, brand, model, specs, source, tg_key) "
                                "VALUES (?, ?, ?, ?, 'canal', ?)",
                                (cat, brand, model + suffix, json.dumps(specs), gkey)).lastrowid
                            break
                        except sqlite3.IntegrityError:
                            continue
                    created += 1
            else:
                attached += 1
            seller = f"{STORE_LABEL.get(o['store'], o['store'] or 'loja ?')} via @{o['channel']}"
            lid = conn.execute(
                "INSERT INTO listings (part_id, store_id, url, title, condition, seller) VALUES (?, ?, ?, ?, 'new', ?)",
                (pid, store_id, o["link"], o["title"], seller)).lastrowid
            conn.execute("INSERT OR IGNORE INTO price_snapshots (listing_id, price_cash, in_stock, collected_at) "
                         "VALUES (?, ?, 1, ?)", (lid, o["price_cash"], o["posted_at"]))

        # post que deixou de ser peça: sai
        removed = 0
        for r in conn.execute("SELECT id, url FROM listings WHERE store_id = ?", (store_id,)).fetchall():
            if r["url"] not in keep_urls:
                conn.execute("DELETE FROM listings WHERE id = ?", (r["id"],))
                removed += 1
        # oferta relâmpago velha: preço "sem estoque" (uma vez só)
        cutoff = (now - timedelta(days=EXPIRE_DAYS)).isoformat()
        expired = 0
        for r in conn.execute(
                "SELECT l.id, v.price_cash FROM listings l JOIN v_latest_price v ON v.listing_id = l.id "
                "WHERE l.store_id = ? AND v.in_stock = 1 AND v.collected_at < ?", (store_id, cutoff)).fetchall():
            conn.execute("INSERT OR IGNORE INTO price_snapshots (listing_id, price_cash, in_stock, collected_at) "
                         "VALUES (?, ?, 0, ?)", (r["id"], r["price_cash"], now.isoformat()))
            expired += 1
        # peça de canal que ficou sem anúncio: some (build/favorito liberam a vaga pelas FKs)
        gone = conn.execute("DELETE FROM parts WHERE source = 'canal' AND id NOT IN "
                            "(SELECT DISTINCT part_id FROM listings)").rowcount
    return {"created": created, "attached": attached, "removed": removed, "expired": expired, "parts_gone": gone}


if __name__ == "__main__":
    from ..db import database as db
    c = db.init_db()
    print(sync(c))
