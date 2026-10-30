"""Parsers das lojas que deixam ler a busca sem navegador (teste de 09/10/2026).

Cada parser recebe o HTML da página de busca e devolve uma lista de `Offer`. Sem rede aqui:
quem baixa é o `fetch` em `run.py`. Assim os parsers são testados com páginas salvas.

Regras de vendedor (decisão do projeto: loja oficial OU boa reputação):
- KaBuM!: só vendido pelo próprio KaBuM! ou pela loja oficial do fabricante. A reputação dos outros
  vendedores do marketplace não aparece na busca, então ficam de fora.
- Terabyte: só vende ela mesma.
- Amazon: a busca já vem filtrada por "vendido pela Amazon" (rh=p_6:A1ZZFT5FULY4LN).
"""

from __future__ import annotations

import html
import json
import re
import time
from dataclasses import dataclass, field
from urllib.parse import quote, quote_plus


@dataclass
class Offer:
    store: str
    url: str
    title: str
    price_cash: int                      # centavos, à vista/PIX
    in_stock: bool
    price_installment: int | None = None  # centavos, total parcelado
    image_url: str | None = None
    seller: str | None = None
    condition: str = "new"               # 'new' | 'used'
    extra: dict = field(default_factory=dict)


class StoreBlocked(RuntimeError):
    """A loja respondeu com bloqueio/captcha. Não contornamos: a loja fica de fora nesta coleta."""


USED_WORDS = re.compile(r"\b(open box|usad[oa]|recondicionad[oa]|seminov[oa]|vitrine)\b", re.I)


def _cents(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return round(float(value) * 100) if value > 0 else None
    s = html.unescape(str(value)).replace("R$", "").replace("\xa0", " ").strip()
    if re.fullmatch(r"\d+(\.\d{1,2})?", s):        # "4980.27" (atributo de máquina, ponto decimal)
        v = float(s)
        return round(v * 100) if v > 0 else None
    s = s.replace(".", "").replace(",", ".")       # "4.980,27" (texto pra gente)
    try:
        v = float(re.sub(r"[^\d.]", "", s))
    except ValueError:
        return None
    return round(v * 100) if v > 0 else None


def _https(url: str | None) -> str | None:
    return url if url and url.startswith("https://") else None


def condition_from_title(title: str) -> str:
    return "used" if USED_WORDS.search(title or "") else "new"


# --------------------------------------------------------------------------- KaBuM!

def kabum_search_url(query: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")
    return f"https://www.kabum.com.br/busca/{quote(slug)}"


def parse_kabum(page: str, now: float | None = None) -> list[Offer]:
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', page, re.S)
    if not m:
        raise ValueError("KaBuM!: página sem __NEXT_DATA__ (layout mudou?)")
    data = json.loads(m.group(1))["props"]["pageProps"]["data"]
    if isinstance(data, str):
        data = json.loads(data)
    if "catalogServer" not in data:
        return []          # busca sem resultado: a página vem sem catálogo
    items = data["catalogServer"]["data"]
    now = time.time() if now is None else now
    out = []
    for it in items:
        seller = (it.get("sellerName") or "").strip()
        maker = ((it.get("manufacturer") or {}).get("name") or "").strip()
        if seller != "KaBuM!" and (not maker or seller.lower() != maker.lower()):
            continue  # marketplace sem reputação visível
        cash, inst = it.get("priceWithDiscount"), it.get("price")
        offer = it.get("offer")
        # oferta relâmpago ativa: o site mostra o preço da oferta
        if offer and offer.get("priceWithDiscount") and (offer.get("startsAt") or 0) <= now <= (offer.get("endsAt") or 0):
            cash, inst = offer["priceWithDiscount"], offer.get("price") or inst
        cash_c = _cents(cash)
        if not cash_c:
            continue
        title = it.get("name") or ""
        out.append(Offer(
            store="kabum",
            url=f"https://www.kabum.com.br/produto/{it['code']}/{it.get('friendlyName') or ''}".rstrip("/"),
            title=title, price_cash=cash_c, price_installment=_cents(inst),
            in_stock=bool(it.get("available")), image_url=_https(it.get("image")),
            seller=seller, condition=condition_from_title(title),
            extra={"category": it.get("category")},
        ))
    return out


# --------------------------------------------------------------------------- Terabyte

def terabyte_search_url(query: str) -> str:
    return f"https://www.terabyteshop.com.br/busca?str={quote_plus(query)}"


def parse_terabyte(page: str) -> list[Offer]:
    out = []
    for attrs, body in re.findall(r'<div class="product-item" ([^>]+)>(.*?)(?=<div class="product-item-frame"|\Z)', page, re.S):
        a = dict(re.findall(r'(data-tss-[\w-]+)="([^"]*)"', attrs))
        name = re.search(r'class="product-item__name" href="([^"]+)"[^>]*title="([^"]+)"', body)
        if not name:
            continue
        cash = _cents(a.get("data-tss-price"))
        if not cash:
            continue  # "monte seu PC" vem com preço 0
        inst = None
        ju = re.search(r'product-item__juros"><span>(\d+)x</span><small> de </small><span>(.*?)</span>', body)
        if ju:
            each = _cents(ju.group(2))
            inst = int(ju.group(1)) * each if each else None
        img = re.search(r'<img[^>]+src="([^"]+)"', body)
        title = html.unescape(name.group(2))
        out.append(Offer(
            store="terabyte", url="https://www.terabyteshop.com.br" + name.group(1), title=title,
            price_cash=cash, price_installment=inst, in_stock=a.get("data-tss-estoque") == "1",
            image_url=_https(img.group(1) if img else None), seller="Terabyte",
            condition=condition_from_title(title),
        ))
    return out


# --------------------------------------------------------------------------- Amazon

AMAZON_SELLER = "A1ZZFT5FULY4LN"  # "vendido pela Amazon" (Amazon.com.br)


def amazon_search_url(query: str) -> str:
    return f"https://www.amazon.com.br/s?k={quote_plus(query)}&rh=p_6%3A{AMAZON_SELLER}"


def parse_amazon(page: str) -> list[Offer]:
    if "/errors/validateCaptcha" in page or "Digite os caracteres que você vê" in page:
        raise StoreBlocked("Amazon pediu captcha")
    out = []
    blocks = re.split(r'(?=<div[^>]+data-asin="B0[A-Z0-9]{8}"[^>]*data-component-type="s-search-result")', page)[1:]
    for b in blocks:
        if "AdHolder" in b or "Anúncio patrocinado" in b or "Patrocinado" in b:
            continue
        asin = re.search(r'data-asin="(B0[A-Z0-9]{8})"', b).group(1)
        t = re.search(r'<h2[^>]*aria-label="([^"]+)"', b) or re.search(r'<h2[^>]*>.*?<span[^>]*>(.*?)</span>', b, re.S)
        p = re.search(r'<span class="a-price"[^>]*><span class="a-offscreen">(.*?)</span>', b)
        if not t or not p:
            continue  # sem preço = indisponível
        cash = _cents(p.group(1))
        if not cash:
            continue
        img = re.search(r'<img[^>]+class="s-image"[^>]+src="([^"]+)"', b)
        title = html.unescape(re.sub(r"<[^>]+>", "", t.group(1))).strip()
        out.append(Offer(
            store="amazon", url=f"https://www.amazon.com.br/dp/{asin}", title=title, price_cash=cash,
            in_stock=True, image_url=_https(img.group(1) if img else None), seller="Amazon",
            condition=condition_from_title(title),
        ))
    return out


STORES = {
    "kabum": (kabum_search_url, parse_kabum),
    "terabyte": (terabyte_search_url, parse_terabyte),
    "amazon": (amazon_search_url, parse_amazon),
}
