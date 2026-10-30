"""Coleta diária: busca cada peça vigiada nas lojas que funcionam e grava pelo `app.ingest`.

    uv run python -m app.collect                 # coleta e grava no banco real
    uv run python -m app.collect --dry-run       # só mostra o que gravaria
    uv run python -m app.collect --notify        # saída = mensagem pro Telegram (vazia se nada a dizer)

Ritmo baixo: uma página por vez, pausa entre requisições, uma vez por dia. Bloqueio/captcha = a loja fica
de fora nesta coleta e entra no aviso; as outras continuam.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

from ..db import database as db
from ..ingest import IngestError, ingest_batch
from ..schemas import IngestBatch
from .stores import STORES, Offer, StoreBlocked
from .watchlist import WATCHLIST, Watch, load_watchlist

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/130.0 Safari/537.36")
PER_STORE_PER_PART = 3   # guarda só os 3 anúncios mais baratos de cada peça em cada loja
PAUSE_S = 4.0
ALERT_COOLDOWN_DAYS = 7
PANEL_URL = "http://127.0.0.1:8787"   # link no fim do aviso; PCB_PANEL_URL troca (ex.: endereço do proxy)

Fetch = Callable[[str], str]


def http_fetch() -> Fetch:
    import httpx

    client = httpx.Client(headers={"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9"},
                          follow_redirects=True, timeout=25)

    def fetch(url: str) -> str:
        r = client.get(url)
        if r.status_code in (403, 429, 503):
            raise StoreBlocked(f"HTTP {r.status_code}")
        r.raise_for_status()
        if "account-verification" in str(r.url) or "validateCaptcha" in str(r.url):
            raise StoreBlocked("página de verificação")
        return r.text

    return fetch


def collect(watchlist: list[Watch], fetch: Fetch, stores: list[str] | None = None,
            pause: float = PAUSE_S, log=print, registry: dict | None = None,
            ) -> tuple[list[tuple[Watch, Offer]], dict[str, str]]:
    """Devolve (pares peça→anúncio, erros por loja). registry: lojas → (url_da_busca, parser)."""
    registry = registry or STORES
    found: list[tuple[Watch, Offer]] = []
    errors: dict[str, str] = {}
    parsed_any: dict[str, int] = {}
    for store in stores or list(registry):
        url_for, parse = registry[store]
        parsed_any[store] = 0
        for w in watchlist:
            if store in errors:
                break                       # loja bloqueou: não insiste
            if w.stores and store not in w.stores:
                continue
            try:
                offers = parse(fetch(url_for(w.query)))
            except StoreBlocked as e:
                errors[store] = f"bloqueou ({e})"
                break
            except Exception as e:          # loja fora do ar, layout mudou...
                errors.setdefault(store, f"{type(e).__name__}: {e}"[:200])
                continue
            finally:
                if pause:
                    time.sleep(pause)
            parsed_any[store] += len(offers)
            # com estoque primeiro: indisponível com preço velho não pode tirar a vaga de quem vende
            hits = sorted((o for o in offers if w.matches(o.title, o.price_cash)),
                          key=lambda o: (not o.in_stock, o.price_cash))
            for o in hits[:PER_STORE_PER_PART]:
                found.append((w, o))
            log(f"[{store}] {w.name}: {len(offers)} na busca, {len(hits)} batem")
        if store not in errors and parsed_any[store] == 0:
            errors[store] = "nenhum produto lido em nenhuma busca (layout mudou?)"
    return found, errors


def to_batch(found: list[tuple[Watch, Offer]], collected_at: str) -> dict:
    seen, items = set(), []
    for w, o in found:
        if o.url in seen:      # o mesmo anúncio casou com 2 peças: fica com a 1ª
            continue
        seen.add(o.url)
        items.append({
            "store": o.store, "url": o.url, "title": o.title[:300], "category": w.category,
            "brand": w.brand, "model": w.model, "specs": w.specs, "image_url": o.image_url,
            "condition": o.condition, "seller": o.seller, "price_cash": o.price_cash,
            "price_installment": o.price_installment, "in_stock": o.in_stock,
        })
    return {"collected_at": collected_at, "items": items}


# --------------------------------------------------------------------------- avisos

def _ensure_alerts(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS alerts_sent (
        listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
        kind TEXT NOT NULL, sent_on TEXT NOT NULL, PRIMARY KEY (listing_id, kind))""")


def pending_alerts(conn: sqlite3.Connection, watchlist: list[Watch], today: date) -> list[dict]:
    """Promoções e preços abaixo do alvo que ainda não foram avisados nos últimos 7 dias."""
    _ensure_alerts(conn)
    since = (today - timedelta(days=ALERT_COOLDOWN_DAYS)).isoformat()

    def fresh(lid, kind):
        return conn.execute("SELECT 1 FROM alerts_sent WHERE listing_id=? AND kind=? AND sent_on>?",
                            (lid, kind, since)).fetchone() is None

    out = []
    for d in db.list_deals(conn):
        if fresh(d["listing_id"], "deal"):
            out.append({**d, "kind": "deal"})
    targets = {(w.category, w.brand, w.model): w.alert_below for w in watchlist if w.alert_below}
    for (cat, brand, model), limit in targets.items():
        row = conn.execute("SELECT id FROM parts WHERE category=? AND brand=? AND model=?", (cat, brand, model)).fetchone()
        best = db.best_price(conn, row["id"]) if row else None
        if best and best["price_cash"] <= limit * 100 and fresh(best["listing_id"], "target"):
            out.append({**best, "brand": brand, "model": model, "kind": "target", "limit": limit})
    return out


def mark_sent(conn: sqlite3.Connection, alerts: list[dict], today: date) -> None:
    _ensure_alerts(conn)
    with conn:
        conn.executemany("INSERT OR REPLACE INTO alerts_sent (listing_id, kind, sent_on) VALUES (?, ?, ?)",
                         [(a["listing_id"], a["kind"], today.isoformat()) for a in alerts])


def _brl(c: int) -> str:
    return f"R$ {c / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def format_message(alerts: list[dict], errors: dict[str, str], result: dict | None) -> str:
    """Mensagem curta pro Telegram. Vazia = dia normal, silêncio."""
    lines = []
    deals = [a for a in alerts if a["kind"] == "deal"]
    targets = [a for a in alerts if a["kind"] == "target"]
    if deals:
        lines.append("🛒 PC Builder — promoção")
        for a in deals:
            used = " (usado)" if a.get("condition") == "used" else ""
            lines.append(f"• {a['brand']} {a['model']}{used}: {_brl(a['price_cash'])} na {a['store_name']} "
                         f"(-{a['drop_pct']}% da mediana de 30 dias)\n  {a['url']}")
    if targets:
        lines.append("🎯 Abaixo do alvo")
        for a in targets:
            lines.append(f"• {a['brand']} {a['model']}: {_brl(a['price_cash'])} na {a['store_name']} "
                         f"(alvo {_brl(int(a['limit'] * 100))})\n  {a['url']}")
    if errors:
        lines.append("🧯 Coleta com problema")
        lines += [f"• {s}: {e}" for s, e in errors.items()]
    if lines:
        lines.append(f"Painel: {os.environ.get('PCB_PANEL_URL') or PANEL_URL}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- CLI

def main(argv: list[str] | None = None, db_path: str | Path = db.DEFAULT_DB, fetch: Fetch | None = None,
         pause: float = PAUSE_S, now: datetime | None = None, notifier=None, locked: bool = False,
         lock_wait: float | None = None) -> int:
    """--notify: a mensagem sai pelo notificador das Configurações (padrão `stdout`: imprime igual a antes). Toma a
    trava da rodada (app/runlock.py), a mesma do agendador interno; `locked=True` = quem chama já tem a trava.
    --dry-run não grava nada e não toma a trava."""
    ap = argparse.ArgumentParser(prog="python -m app.collect")
    ap.add_argument("--dry-run", action="store_true", help="não grava, só mostra")
    ap.add_argument("--notify", action="store_true", help="manda só a mensagem do aviso (destino: Configurações)")
    ap.add_argument("--stores", help="ex.: kabum,amazon")
    ap.add_argument("--only", help="só peças cujo nome contém este texto")
    ap.add_argument("--watchlist", default=str(WATCHLIST))
    args = ap.parse_args(argv)
    if locked or args.dry_run:
        return _main(args, db_path, fetch, pause, now, notifier)
    from ..runlock import LOCK_WAIT_S, round_lock
    with round_lock().hold(LOCK_WAIT_S if lock_wait is None else lock_wait) as got:
        if not got:
            print("outra rodada (coleta ou canais) em andamento: pulei esta", file=sys.stderr)
            return 0
        return _main(args, db_path, fetch, pause, now, notifier)


def _main(args, db_path, fetch, pause, now, notifier) -> int:
    now = (now or datetime.now()).replace(microsecond=0)
    watch = load_watchlist(args.watchlist)
    if args.only:
        watch = [w for w in watch if args.only.lower() in w.name.lower()]
    if args.stores:
        stores = args.stores.split(",")
    else:                           # sem --stores: as lojas ligadas nas Configurações (ou PCB_STORES)
        from .. import settings
        conn = db.connect(db_path) if Path(db_path).exists() else None   # --dry-run não cria banco
        try:
            on = settings.values(conn)["stores"]
        finally:
            if conn is not None:
                conn.close()
        stores = [s for s in STORES if on.get(s, True)]
    log = (lambda *_: None) if args.notify else (lambda m: print(m, file=sys.stderr))

    found, errors = collect(watch, fetch or http_fetch(), stores, pause, log)
    batch = to_batch(found, now.isoformat())

    if args.dry_run:
        print(json.dumps({"errors": errors, **batch}, ensure_ascii=False, indent=1))
        return 0

    result = None
    conn = db.init_db(db_path)
    try:
        if batch["items"]:
            try:
                result = ingest_batch(conn, IngestBatch.model_validate(batch))
            except IngestError as e:
                errors["banco"] = str(e)
        alerts = pending_alerts(conn, watch, now.date())
        msg = format_message(alerts, errors, result)
        if args.notify:
            from ..notify import deliver, from_config
            if msg:
                deliver(notifier or from_config(db_path), msg)
            mark_sent(conn, alerts, now.date())
        else:
            print(json.dumps({"ok": not errors, "errors": errors, "ingest": result,
                              "alerts": len(alerts)}, ensure_ascii=False))
    finally:
        conn.close()
    return 0 if not errors else 1
