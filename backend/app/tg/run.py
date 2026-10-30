"""Rodada dos canais do Telegram. Roda pelo cron a cada 45 min: `python -m app.tg`.

1. Lê cada canal público (t.me/s/<canal>) de trás pra frente até a última mensagem já vista.
2. Fica só com post que tem preço. O tipo vem da votação (1 a 3 modelos do Ollama) ou das regras, conforme a
   configuração `classifier` (tg/classifier.py); nao_tech e cupom são descartados.
3. Chave do produto (script) só quando o tipo do script BATE com o da votação (ou com ficha completa nas regras).
4. Aviso quando, pro mesmo produto (com pelo menos MIN_SEEN preços anteriores, canais + lojas):
   - preço <= mediana anterior × (1 − 7%), ou
   - preço < menor preço anterior (menor já visto).
   1 aviso por produto por dia. Saída vazia = nada a avisar (cron fica quieto).
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import datetime
from typing import Callable

from ..db import database as db
from . import classifier as C
from .classify import product_key, title_of
from .parse import Post, has_preview, parse_page, price_cents, store_of
from .. import settings as S
from ..settings import DEFAULT_CHANNELS

# os canais de fábrica moram em app/settings.py (entram no banco no 1º init); a rodada lê os ATIVOS do banco
CHANNELS = list(DEFAULT_CHANNELS)
DROP_PCT = 0.07
MIN_SEEN = 3
MAX_PAGES = 10          # por canal por rodada
FIRST_PAGES = 1         # canal novo: só a página mais recente
PAUSE_S = 1.5
CAT2KIND = C.CAT2KIND

Fetch = Callable[[str], str]


def http_fetch() -> Fetch:
    import httpx
    client = httpx.Client(headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)", "Accept-Language": "pt-BR"},
                          timeout=20, follow_redirects=True)

    def fetch(url: str) -> str:
        # o t.me às vezes derruba a conexão (ReadTimeout / "Server disconnected"): 2 novas tentativas com pausa
        for attempt in range(3):
            try:
                r = client.get(url)
                r.raise_for_status()
                return r.text
            except (httpx.TransportError, httpx.HTTPStatusError) as e:
                if attempt == 2 or (isinstance(e, httpx.HTTPStatusError) and e.response.status_code < 500
                                    and e.response.status_code != 429):
                    raise
                time.sleep(5 * (attempt + 1))
        raise RuntimeError("inalcançável")
    return fetch


# --------------------------------------------------------------------------- leitura

def read_channel(slug: str, last_id: int, fetch: Fetch, pause: float = PAUSE_S) -> list[Post]:
    """Posts novos (id > last_id), do mais antigo pro mais novo."""
    url, got, pages = f"https://t.me/s/{slug}", {}, (FIRST_PAGES if last_id == 0 else MAX_PAGES)
    for n in range(pages):
        page = fetch(url)
        if n == 0 and not has_preview(page):
            raise RuntimeError("sem prévia web (canal fechado pra leitura sem login)")
        posts = parse_page(page)
        if not posts:
            break
        for p in posts:
            if p.msg_id > last_id:
                got[p.msg_id] = p
        oldest = min(p.msg_id for p in posts)
        if oldest <= last_id:
            break
        url = f"https://t.me/s/{slug}?before={oldest}"
        if pause:
            time.sleep(pause)
    return [got[k] for k in sorted(got)]


# --------------------------------------------------------------------------- referência e aviso

def _store_prices(conn, key: str, before: str) -> list[int]:
    """Preços das lojas (KaBuM/Terabyte/Amazon) do mesmo produto, pela mesma chave aplicada ao título."""
    out = []
    rows = conn.execute(
        "SELECT p.category, l.title, ps.price_cash FROM price_snapshots ps JOIN listings l ON l.id = ps.listing_id "
        "JOIN parts p ON p.id = l.part_id JOIN stores st ON st.id = l.store_id "
        "WHERE l.condition = 'new' AND st.slug != 'canal' AND ps.collected_at < ?", (before,))
    for r in rows:
        if product_key(r["title"], r["category"]) == key:
            out.append(r["price_cash"])
    return out


def reference(conn, key: str, before: str, exclude_id: int | None = None) -> dict | None:
    prev = [r["price_cash"] for r in conn.execute(
        "SELECT price_cash FROM tg_offers WHERE product_key = ? AND posted_at < ? AND id IS NOT ?",
        (key, before, exclude_id))]
    prev += _store_prices(conn, key, before)
    if len(prev) < MIN_SEEN:
        return None
    return {"n": len(prev), "min": min(prev), "median": int(statistics.median(prev))}


def judge(price: int, ref: dict | None) -> str | None:
    if not ref:
        return None
    if price < ref["min"]:
        return "menor_ja_visto"
    if price <= ref["median"] * (1 - DROP_PCT):
        return "abaixo_7"
    return None


def brl(cents: int) -> str:
    return f"R$ {cents / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# --------------------------------------------------------------------------- rodada

def run_round(conn, fetch: Fetch, chat=None, now: datetime | None = None,
              channels: list[str] | None = None, pause: float = PAUSE_S, log=print, probe=None,
              state_path=None, ollama_client=None) -> dict:
    """chat: votação injetada (testes; sem ele, o Ollama do endereço salvo). probe: teste de presença injetado.
    state_path: onde lembrar a queda do Ollama (padrão: diretório de dados)."""
    now = (now or datetime.now()).replace(microsecond=0)
    seen_at = now.isoformat()
    if channels:                    # --channels: lê só estes (canal novo entra como cadastrado pela pessoa)
        with conn:
            conn.executemany("INSERT OR IGNORE INTO tg_channels (slug, source, added_at) VALUES (?, 'usuario', ?)",
                             [(c, seen_at) for c in channels])

    fresh, errors = [], {}
    for ch in channels or [r["slug"] for r in conn.execute(
            "SELECT slug FROM tg_channels WHERE active = 1 AND removed_at IS NULL ORDER BY rowid")]:
        last = conn.execute("SELECT last_msg_id FROM tg_channels WHERE slug = ?", (ch,)).fetchone()["last_msg_id"]
        try:
            posts = read_channel(ch, last, fetch, pause)
        except Exception as e:
            errors[ch] = f"{type(e).__name__}: {e}"[:160]
            with conn:
                conn.execute("UPDATE tg_channels SET fail_count = fail_count + 1, last_error = ? WHERE slug = ?",
                             (errors[ch], ch))
            continue
        with conn:
            conn.execute("UPDATE tg_channels SET fail_count = 0, last_error = NULL, last_ok_at = ?, "
                         "last_msg_id = MAX(last_msg_id, ?) WHERE slug = ?",
                         (seen_at, max([p.msg_id for p in posts], default=last), ch))
        fresh += [p for p in posts if price_cents(p.text)]
        log(f"[{ch}] {len(posts)} novos, {sum(1 for p in posts if price_cents(p.text))} com preço")

    titles = [title_of(p.text) for p in fresh]
    cfg = S.values(conn)
    ollama, alive = C.ollama_backend(cfg, chat, ollama_client, probe)
    again = []

    def to_reeval() -> list[str]:                       # só é chamado se o Ollama vai ser usado
        again.extend(C.reeval_rows(conn))
        return [r["text"] for r in again]
    out = C.classify_round(cfg["classifier"], [p.text for p in fresh], to_reeval, ollama, alive,
                           C.FallbackState(state_path))
    if out.error:
        errors["ollama"] = out.error                    # modo "só Ollama": guarda sem tipo; reavalia quando voltar

    with conn:
        for r, v in zip(again, out.extra):
            C.update_offer(conn, r["id"], r["text"], v, ollama.quorum)

    kept, alerts = 0, []
    for p, title, v in zip(fresh, titles, out.fresh):
        f = C.fields(p.text, v, ollama.quorum)
        if f is None:
            continue
        key = f["product_key"]
        with conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO tg_offers (channel, msg_id, posted_at, seen_at, title, text, price_cash, store, "
                "link, kind, kind_votes, kind_agree, kind_source, product_key, image_src) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (p.channel, p.msg_id, p.posted_at, seen_at, title, p.text, price_cents(p.text), store_of(p),
                 p.url, f["kind"], f["kind_votes"], f["kind_agree"], f["kind_source"], key, p.image))
        if not cur.rowcount:
            continue
        kept += 1
        if key:
            oid, price = cur.lastrowid, int(price_cents(p.text) or 0)
            ref = reference(conn, key, p.posted_at, oid)
            why = judge(price, ref)
            if why:
                alerts.append(dict(id=oid, key=key, title=title, price=price, ref=ref, why=why, store=store_of(p),
                                   link=p.url, channel=p.channel))
    return {"read": len(fresh), "kept": kept, "alerts": alerts, "errors": errors, "classifier": out.effective,
            "reevaluated": len(out.extra), "notices": out.notices}


def pending(conn, alerts: list[dict], day: str) -> list[dict]:
    out = []
    for a in alerts:
        if conn.execute("SELECT 1 FROM tg_alerts_sent WHERE product_key = ? AND day = ?", (a["key"], day)).fetchone():
            continue
        if any(o["key"] == a["key"] for o in out):        # mesmo produto 2x na rodada: fica o mais barato
            prev = next(o for o in out if o["key"] == a["key"])
            if a["price"] < prev["price"]:
                out[out.index(prev)] = a
            continue
        out.append(a)
    return out


def mark_sent(conn, alerts: list[dict], day: str) -> None:
    with conn:
        conn.executemany("INSERT OR IGNORE INTO tg_alerts_sent (product_key, day, offer_id) VALUES (?, ?, ?)",
                         [(a["key"], day, a["id"]) for a in alerts])


def format_message(alerts: list[dict], errors: dict, fail_counts: dict) -> str:
    lines = []
    if alerts:
        lines.append("🛰 Promoção nos canais")
        for a in alerts:
            r = a["ref"]
            tag = "menor preço já visto" if a["why"] == "menor_ja_visto" else \
                f"{round(100 * (1 - a['price'] / r['median']))}% abaixo do típico"
            lines.append(f"• {a['title'][:90]}\n  {brl(a['price'])} ({a['store'] or '?'}) — {tag}; "
                         f"típico {brl(r['median'])}, menor antes {brl(r['min'])} ({r['n']} preços)\n  {a['link']}")
    # canal com erro só vira aviso depois de 3 rodadas seguidas falhando (evita alarme por instabilidade)
    bad = {c: e for c, e in errors.items() if c == "ollama" or fail_counts.get(c, 0) >= 3}
    if bad:
        lines.append("🧯 Canais com problema: " + "; ".join(f"{c}: {e}" for c, e in bad.items()))
    return "\n".join(lines)


def main(argv: list[str] | None = None, db_path=db.DEFAULT_DB, fetch: Fetch | None = None,
         chat=None, now: datetime | None = None, pause: float = PAUSE_S,
         img_get=None, img_dir=None, notifier=None, locked: bool = False, lock_wait: float | None = None,
         ollama_client=None) -> int:
    """--notify: a mensagem sai pelo notificador das Configurações (padrão `stdout`: imprime igual a antes, para o
    cron entregar). Toma a trava da rodada (app/runlock.py), a mesma do agendador interno; `locked=True` = quem
    chama já tem a trava."""
    ap = argparse.ArgumentParser(prog="python -m app.tg")
    ap.add_argument("--notify", action="store_true", help="manda só a mensagem do aviso (destino: Configurações)")
    ap.add_argument("--channels", help="ex.: OPromoFacil,gpcrpromo")
    ap.add_argument("--backfill-images", action="store_true",
                    help="relê as páginas recentes e pega o link da foto de ofertas já guardadas (uso único)")
    args = ap.parse_args(argv)
    if locked:
        return _main(args, db_path, fetch, chat, now, pause, img_get, img_dir, notifier, ollama_client)
    from ..runlock import LOCK_WAIT_S, round_lock
    with round_lock().hold(LOCK_WAIT_S if lock_wait is None else lock_wait) as got:
        if not got:
            print("outra rodada (coleta ou canais) em andamento: pulei esta", file=sys.stderr)
            return 0
        return _main(args, db_path, fetch, chat, now, pause, img_get, img_dir, notifier, ollama_client)


def _main(args, db_path, fetch, chat, now, pause, img_get, img_dir, notifier, ollama_client=None) -> int:
    now = (now or datetime.now()).replace(microsecond=0)
    log = (lambda *_: None) if args.notify else (lambda m: print(m, file=sys.stderr))

    conn = db.init_db(db_path)
    try:
        res = run_round(conn, fetch or http_fetch(), chat, now,
                        args.channels.split(",") if args.channels else None, pause, log,
                        ollama_client=ollama_client)
        from . import images             # baixa a foto na hora (o link vence em ~1 dia)
        try:
            if args.backfill_images:
                log(f"fotos: link preenchido em {images.backfill(conn, fetch or http_fetch(), pause=pause)} ofertas")
            log(f"fotos: {images.fetch_pending(conn, img_get or images.http_get(), img_dir or images.IMG_DIR)}")
        except Exception as e:           # foto nunca derruba a rodada nem o aviso de promoção
            log(f"fotos: falhou ({type(e).__name__}: {e})"[:200])
        from .sync import sync           # peças dos canais viram peças de verdade (aba Peças, Builds)
        log(f"sync peças: {sync(conn, now)}")
        day = now.date().isoformat()
        alerts = pending(conn, res["alerts"], day)
        fails = {r["slug"]: r["fail_count"] for r in conn.execute("SELECT slug, fail_count FROM tg_channels")}
        # aviso de queda do Ollama (modo automático): uma vez por queda, depois dos avisos de promoção
        msg = "\n".join(x for x in (format_message(alerts, res["errors"], fails), *res["notices"]) if x)
        if args.notify:
            from ..notify import deliver, from_config
            if msg:
                deliver(notifier or from_config(db_path), msg)
            mark_sent(conn, alerts, day)
        else:
            print(json.dumps({k: v for k, v in res.items() if k != "alerts"} | {"alerts": alerts},
                             ensure_ascii=False, indent=1, default=str))
    finally:
        conn.close()
    return 0
