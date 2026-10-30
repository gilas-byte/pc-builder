"""Lista de peças vigiadas e a regra que decide se um anúncio É aquela peça.

Título normalizado: minúsculo, sem acento, "16 GB" → "16gb". Cada palavra de `must` precisa aparecer
como palavra inteira (então "5600" não casa com "5600X" nem "5600GT"); nenhuma de `exclude` (da peça ou
global) pode aparecer. Preço abaixo do piso da categoria = acessório/anúncio isca, descartado.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

WATCHLIST = Path(__file__).resolve().parents[2] / "watchlist.json"

GLOBAL_EXCLUDE = ["pc gamer", "pc office", "computador", "notebook", "laptop", "kit", "combo", "monte seu",
                  "cpu gamer", "workstation", "mini pc", "all in one", "sodimm", "so dimm", "so-dimm"]

# piso de preço por categoria (reais): abaixo disso é cabo, suporte, adesivo, isca
FLOOR = {"cpu": 250, "motherboard": 350, "ram": 90, "gpu": 500, "storage": 120, "psu": 150, "case": 120,
         "cooler": 50}


def norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    t = re.sub(r"(\d+)\s*(gb|tb|w|mhz)\b", r"\1\2", t)
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return f" {t.strip()} "


def _has(title_n: str, phrase: str) -> bool:
    return f" {norm(phrase).strip()} " in title_n


@dataclass
class Watch:
    category: str
    brand: str
    model: str
    query: str
    must: list[str]
    exclude: list[str] = field(default_factory=list)
    specs: dict = field(default_factory=dict)
    alert_below: float | None = None     # reais; aviso no Telegram se o melhor preço ficar abaixo
    stores: list[str] | None = None      # None = todas as que funcionam

    @property
    def name(self) -> str:
        return f"{self.brand} {self.model}"

    def matches(self, title: str, price_cash: int) -> bool:
        t = norm(title)
        if price_cash < FLOOR.get(self.category, 0) * 100:
            return False
        if " + " in f" {title} " or t.startswith(" pc "):
            return False   # combo ("placa de vídeo + fonte") ou computador montado
        if any(_has(t, x) for x in GLOBAL_EXCLUDE + self.exclude):
            return False
        return all(_has(t, w) for w in self.must)


def load_watchlist(path: str | Path = WATCHLIST) -> list[Watch]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return [Watch(**w) for w in raw["parts"]]
