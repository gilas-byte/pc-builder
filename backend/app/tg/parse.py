"""Leitura das páginas públicas t.me/s/<canal> e extração de ofertas (sem login, sem conta)."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import datetime


@dataclass
class Post:
    channel: str
    msg_id: int
    posted_at: str          # ISO local, sem fuso
    text: str               # texto puro, linhas separadas por \n
    links: list[str]
    image: str | None = None   # 1ª foto da mensagem (https, vence em ~1 dia: baixar na hora)

    @property
    def url(self) -> str:
        return f"https://t.me/{self.channel}/{self.msg_id}"


def _local_iso(dt: str) -> str:
    return datetime.fromisoformat(dt).astimezone().replace(tzinfo=None).isoformat(timespec="seconds")


def _photo_of(block: str) -> str | None:
    """Foto da mensagem: `tgme_widget_message_photo_wrap ... background-image:url('https://...')`.
    Só https. Link-preview (miniatura de site) e capa de vídeo têm outras classes e ficam de fora."""
    m = re.search(r"tgme_widget_message_photo_wrap[^>]*?background-image:url\('(https://[^']+)'\)", block)
    return html.unescape(m.group(1)) if m else None


def parse_page(page: str) -> list[Post]:
    """Posts com texto de uma página t.me/s/. Ordem: mais antigo → mais novo."""
    out = []
    for b in re.split(r'(?=<div class="tgme_widget_message_wrap)', page)[1:]:
        pid = re.search(r'data-post="([^"/]+)/(\d+)"', b)
        m = re.search(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', b, re.S)
        dt = re.search(r'<time[^>]*datetime="([^"]+)"', b)
        if not (pid and m and dt):
            continue
        raw = re.sub(r"<br\s*/?>", "\n", m.group(1))
        text = html.unescape(re.sub(r"<[^>]+>", "", raw))
        text = "\n".join(" ".join(l.split()) for l in text.split("\n"))
        links = [html.unescape(u) for u in re.findall(r'href="(https?://[^"]+)"', m.group(1))
                 if "t.me/" not in u]
        out.append(Post(pid.group(1), int(pid.group(2)), _local_iso(dt.group(1)), text.strip(), links,
                        _photo_of(b)))
    return out


def has_preview(page: str) -> bool:
    """Canal com a prévia web desligada não mostra mensagem nenhuma (só o botão 'View in Telegram')."""
    return "tgme_widget_message_wrap" in page


# --------------------------------------------------------------------------- preço

NUM = r"(\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:,\d{1,2})?)"


def to_cents(num: str) -> int:
    return round(float(num.replace(".", "").replace(",", ".")) * 100)


def price_cents(text: str) -> int | None:
    """Preço anunciado, em ordem de confiança:
    1. número logo depois de "por" ("Por: R$ 148", "POR: 404 REAIS", "por R$ 237 no pix");
    2. linha cujo conteúdo é praticamente só o preço ("💲R$2.206,16", "💸 R$ 229 em até 6x");
    3. primeiro "R$" que não está numa linha de cupom/desconto nem é o "De:".
    O "De:" do canal é ignorado (costuma ser inflado). Linha de cupom ("20% OFF max R$ 50") nunca é preço."""
    low = text.lower()
    m = re.search(r"\bpor\s*:?\s*(?:r\$\s*)?" + NUM + r"(?!\s*(?:x\b|%|off))", low)
    if m:
        return to_cents(m.group(1))
    lines = [l.strip() for l in low.split("\n") if l.strip()]
    coupon = re.compile(r"cupom|off\b|desconto|max |limite|acima de|cashback|resgat")
    for l in lines:
        m = re.fullmatch(r"\W*r\$\s*" + NUM + r"(?:\s*(?:no pix|à vista|a vista|pix|em até.*|em ate.*|\(.*\)))?\W*", l)
        if m and not coupon.search(l):
            return to_cents(m.group(1))
    for l in lines:
        if coupon.search(l) or re.match(r"\W*de\s*:", l) or "sozinho" in l or "custa" in l:
            continue
        m = re.search(r"r\$\s*" + NUM, l)
        if m:
            return to_cents(m.group(1))
    return None


# --------------------------------------------------------------------------- loja

DOMAINS = [
    (r"amzn\.to|amazon\.|link\.amazon|amzlink", "amazon"),
    (r"meli\.la|mercadolivre\.|mercadolibre\.", "mercadolivre"),
    (r"shopee\.", "shopee"),
    (r"kabum\.", "kabum"),
    (r"terabyteshop\.", "terabyte"),
    (r"pichau\.", "pichau"),
    (r"magazineluiza\.|magalu\.", "magalu"),
    (r"aliexpress\.|a\.aliexpress", "aliexpress"),
]
TEXT_STORES = [("mercado livre", "mercadolivre"), ("mercadolivre", "mercadolivre"), ("amazon", "amazon"),
               ("shopee", "shopee"), ("kabum", "kabum"), ("terabyte", "terabyte"), ("pichau", "pichau"),
               ("magalu", "magalu"), ("aliexpress", "aliexpress")]


def store_of(post: Post) -> str | None:
    for u in post.links:
        for rx, store in DOMAINS:
            if re.search(rx, u):
                return store
    t = post.text.lower()
    for name, store in TEXT_STORES:
        if name in t:
            return store
    return None
