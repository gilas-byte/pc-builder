"""Canais do Telegram cadastrados pela tela. Tabela `tg_channels`.

- Só canal PÚBLICO com prévia web (`t.me/s/<nome>`). Ao adicionar, o servidor abre a prévia uma vez (timeout curto);
  sem a estrutura de mensagens = recusado; sem rede = não grava.
- `active` = ligado/desligado (a rodada só lê os ligados). Remover NÃO apaga: desliga e esconde (`removed_at`), para
  as ofertas antigas continuarem com o histórico de preço (tg_offers.channel aponta para o canal). Adicionar de novo
  um canal removido traz ele de volta, com o histórico.
"""

from __future__ import annotations

import html
import re
import sqlite3
from datetime import datetime
from typing import Callable
from urllib.parse import urlsplit

from ..settings import MAX_CHANNELS
from .parse import has_preview, parse_page

SLUG_RX = re.compile(r"[A-Za-z0-9_]{4,32}")
HOSTS = ("t.me", "telegram.me")
PREVIEW_TIMEOUT_S = 8.0

Fetch = Callable[[str], str]


class ChannelUnreachable(RuntimeError):
    """Não deu para abrir t.me agora (sem rede, timeout, t.me fora do ar)."""


class ChannelExists(ValueError):
    pass


class ChannelLimit(ValueError):
    pass


class NoPreview(ValueError):
    pass


def normalize_handle(text) -> str:
    """`@nome`, `nome`, `https://t.me/nome`, `t.me/s/nome` → `nome`. Qualquer outra coisa: ValueError."""
    if not isinstance(text, str) or len(text) > 200:
        raise ValueError("mande o @nome do canal")
    s = text.strip(" ")
    if s.startswith("@"):
        s = s[1:]
    elif "/" in s or ":" in s:
        u = urlsplit(s if re.match(r"https?://", s) else "https://" + s)
        if u.scheme not in ("http", "https") or u.netloc.lower() not in HOSTS or u.query or u.fragment:
            raise ValueError("link de canal tem que ser t.me/<nome> ou t.me/s/<nome>")
        parts = u.path.strip("/").split("/")
        if len(parts) == 2 and parts[0] == "s":
            parts = parts[1:]
        if len(parts) != 1:
            raise ValueError("link de canal tem que ser t.me/<nome> ou t.me/s/<nome>")
        s = parts[0]
    if not SLUG_RX.fullmatch(s):
        raise ValueError("nome de canal: 4 a 32 letras sem acento, números ou _")
    return s


def preview_fetch(url: str) -> str:
    """GET da prévia pública: 1 tentativa, timeout curto. 4xx = página sem prévia (""); rede/5xx/429 = erro."""
    import httpx
    try:
        with httpx.Client(timeout=PREVIEW_TIMEOUT_S, follow_redirects=True,
                          headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"}) as client:
            r = client.get(url)
    except httpx.HTTPError as e:
        raise ChannelUnreachable(type(e).__name__) from None
    if r.status_code == 429 or r.status_code >= 500:
        raise ChannelUnreachable(f"HTTP {r.status_code}")
    return r.text if r.status_code < 400 else ""


def _row(conn: sqlite3.Connection, slug: str, visible_only: bool = True):
    sql = "SELECT * FROM tg_channels WHERE lower(slug) = lower(?)"
    if visible_only:
        sql += " AND removed_at IS NULL"
    return conn.execute(sql, (slug,)).fetchone()


def _public(conn: sqlite3.Connection, r: sqlite3.Row) -> dict:
    n, last = conn.execute("SELECT COUNT(*), MAX(posted_at) FROM tg_offers WHERE channel = ?", (r["slug"],)).fetchone()
    return {"slug": r["slug"], "title": r["title"], "enabled": bool(r["active"]), "source": r["source"],
            "added_at": r["added_at"], "posts": n, "last_post_at": last, "last_ok_at": r["last_ok_at"],
            "fail_count": r["fail_count"], "last_error": r["last_error"]}


def list_channels(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM tg_channels WHERE removed_at IS NULL ORDER BY lower(slug)").fetchall()
    return [_public(conn, r) for r in rows]


def _title(page: str) -> str | None:
    m = re.search(r'<meta property="og:title" content="([^"]{1,300})"', page)
    return html.unescape(m.group(1)).strip()[:120] or None if m else None


def add_channel(conn: sqlite3.Connection, handle, fetch: Fetch = preview_fetch) -> dict:
    slug = normalize_handle(handle)
    old = _row(conn, slug, visible_only=False)
    if old is not None and old["removed_at"] is None:
        raise ChannelExists(f"o canal @{old['slug']} já está na lista")
    visible = conn.execute("SELECT COUNT(*) FROM tg_channels WHERE removed_at IS NULL").fetchone()[0]
    if visible >= MAX_CHANNELS:
        raise ChannelLimit(f"limite de {MAX_CHANNELS} canais; remova um antes")
    page = fetch(f"https://t.me/s/{slug}")
    if not page or not has_preview(page):
        raise NoPreview("este canal não tem prévia pública (t.me/s/<nome>); só canal público com prévia funciona")
    for p in parse_page(page):                     # grafia oficial do nome, se a página mostrar
        if p.channel.lower() == slug.lower() and SLUG_RX.fullmatch(p.channel):
            slug = p.channel
            break
    now = datetime.now().replace(microsecond=0).isoformat()
    with conn:
        if old is not None:                        # removido antes: volta com o histórico
            conn.execute("UPDATE tg_channels SET active = 1, removed_at = NULL, fail_count = 0, last_error = NULL, "
                         "title = COALESCE(?, title) WHERE slug = ?", (_title(page), old["slug"]))
            slug = old["slug"]
        else:
            conn.execute("INSERT INTO tg_channels (slug, title, active, added_at, source) VALUES (?, ?, 1, ?, 'usuario')",
                         (slug, _title(page), now))
    return _public(conn, _row(conn, slug))


def set_enabled(conn: sqlite3.Connection, slug: str, enabled: bool) -> dict | None:
    r = _row(conn, slug)
    if r is None:
        return None
    with conn:
        conn.execute("UPDATE tg_channels SET active = ? WHERE slug = ?", (int(enabled), r["slug"]))
    return _public(conn, _row(conn, r["slug"]))


def remove_channel(conn: sqlite3.Connection, slug: str) -> bool:
    """Desliga e esconde. As ofertas e o histórico ficam."""
    r = _row(conn, slug)
    if r is None:
        return False
    now = datetime.now().replace(microsecond=0).isoformat()
    with conn:
        conn.execute("UPDATE tg_channels SET active = 0, removed_at = ? WHERE slug = ?", (now, r["slug"]))
    return True
