"""Fotos das ofertas dos canais.

O link da foto no t.me vence em menos de 1 dia (cdn*.telesco.pe), então a rodada BAIXA a foto e guarda uma
cópia em data/tg_img/. O link vem de HTML de terceiro: nada aqui confia nele.
- só https e só host `*.telesco.pe` (nunca endereço de rede local nem outro site);
- o nome do arquivo sai de canal + id da mensagem (validados), nunca da URL;
- tipo conferido pelos primeiros bytes (JPEG/PNG/WEBP), tamanho máximo MAX_BYTES, gravação atômica;
- falha numa foto não derruba a rodada; MAX_TRIES tentativas e desiste.
"""

from __future__ import annotations

import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from ..secrets_store import data_dir
from .parse import parse_page

IMG_DIR = data_dir() / "tg_img"   # PCB_DATA_DIR (Docker: o volume) ou a pasta data/ do projeto
MAX_BYTES = 2 * 1024 * 1024
MIN_BYTES = 100
MAX_TRIES = 3
PER_ROUND = 150
HOST_RX = re.compile(r"^(?:[a-z0-9-]+\.)*telesco\.pe$")
CHANNEL_RX = re.compile(r"^[A-Za-z0-9_]{3,64}$")
NAME_RX = re.compile(r"^[A-Za-z0-9_]{3,64}_\d{1,12}\.(?:jpg|png|webp)$")

Get = Callable[[str], bytes]


def allowed(url: str | None) -> bool:
    if not url:
        return False
    try:
        u = urlsplit(url)
    except ValueError:
        return False
    # "@" ou porta na URL = tentativa de enganar o host; sem credencial, sem porta
    return (u.scheme == "https" and bool(u.hostname) and HOST_RX.match(u.hostname) is not None
            and "@" not in u.netloc and u.port is None and ".." not in u.path)


def kind_of(data: bytes) -> str | None:
    if len(data) < MIN_BYTES or len(data) > MAX_BYTES:
        return None
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def http_get() -> Get:
    import httpx
    client = httpx.Client(headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"}, timeout=20,
                          follow_redirects=False)

    def get(url: str) -> bytes:
        with client.stream("GET", url) as r:
            r.raise_for_status()
            buf = bytearray()
            for chunk in r.iter_bytes():
                buf += chunk
                if len(buf) > MAX_BYTES:        # não puxa arquivo gigante inteiro
                    break
            return bytes(buf)
    return get


def _save(directory: Path, name: str, data: bytes) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    tmp = directory / (name + ".part")
    tmp.write_bytes(data)
    os.replace(tmp, directory / name)


def fetch_pending(conn: sqlite3.Connection, get: Get, directory: Path = IMG_DIR, limit: int = PER_ROUND) -> dict:
    """Baixa a foto das ofertas que têm link e ainda não têm cópia. Mais novas primeiro."""
    saved = failed = 0
    rows = conn.execute(
        "SELECT id, channel, msg_id, image_src FROM tg_offers WHERE image_src IS NOT NULL AND image_path IS NULL "
        "AND image_tries < ? ORDER BY posted_at DESC LIMIT ?", (MAX_TRIES, limit)).fetchall()
    for r in rows:
        if not allowed(r["image_src"]) or not CHANNEL_RX.match(r["channel"]):
            with conn:                      # nunca vai poder baixar: não tenta mais
                conn.execute("UPDATE tg_offers SET image_tries = ? WHERE id = ?", (MAX_TRIES, r["id"]))
            continue
        try:
            data = get(r["image_src"])
            ext = kind_of(data)
            if ext is None:
                raise ValueError("não é imagem (ou tamanho fora do limite)")
            name = f"{r['channel']}_{r['msg_id']}.{ext}"
            _save(directory, name, data)
        except Exception:
            failed += 1
            with conn:
                conn.execute("UPDATE tg_offers SET image_tries = image_tries + 1 WHERE id = ?", (r["id"],))
            continue
        saved += 1
        with conn:
            conn.execute("UPDATE tg_offers SET image_path = ? WHERE id = ?", (name, r["id"]))
    return {"saved": saved, "failed": failed}


def backfill(conn: sqlite3.Connection, fetch: Callable[[str], str], channels: list[str] | None = None,
             pages: int = 5, pause: float = 1.5) -> int:
    """Relê as páginas recentes e preenche o link da foto de ofertas que já estavam no banco.
    Não mexe em oferta que já tem cópia local."""
    n = 0
    for ch in channels or [r["slug"] for r in conn.execute("SELECT slug FROM tg_channels WHERE active = 1")]:
        url = f"https://t.me/s/{ch}"
        for _ in range(pages):
            posts = parse_page(fetch(url))
            if not posts:
                break
            for p in posts:
                if not p.image:
                    continue
                with conn:
                    cur = conn.execute(
                        "UPDATE tg_offers SET image_src = ? WHERE channel = ? AND msg_id = ? AND image_path IS NULL "
                        "AND image_src IS NOT ?", (p.image, p.channel, p.msg_id, p.image))
                n += cur.rowcount
            url = f"https://t.me/s/{ch}?before={min(p.msg_id for p in posts)}"
            if pause:
                time.sleep(pause)
    return n
