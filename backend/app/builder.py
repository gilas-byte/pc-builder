"""Build completa: compatibilidade ENTRE as peças e montagem automática da mais barata.

Specs usados (todos opcionais; o que faltar vira "não verificado", nunca some da lista):
  cpu:         socket
  motherboard: socket, memory_type, form_factor
  ram:         memory_type
  cooler:      sockets (lista)
  case:        motherboard_support (lista de formatos)
  gpu:         recommended_psu_w
  psu:         wattage_w
"""

from __future__ import annotations

import json
import sqlite3

from .db import database as db

CATEGORIES = ("cpu", "motherboard", "ram", "gpu", "storage", "psu", "case", "cooler")


def _n(v) -> str:
    return str(v).strip().upper()


def _pair(a_cat: str, a: dict, b_cat: str, b: dict) -> tuple[bool | None, str | None]:
    """Compatibilidade entre duas peças. (True/False/None, aviso)."""
    pair = {a_cat: a, b_cat: b}
    keys = set(pair)

    if keys == {"cpu", "motherboard"}:
        s1, s2 = pair["cpu"].get("socket"), pair["motherboard"].get("socket")
        if not s1 or not s2:
            return None, "CPU × placa-mãe não verificado: falta o socket."
        if _n(s1) != _n(s2):
            return False, f"CPU {s1} não encaixa na placa {s2}."
        return True, None

    if keys == {"ram", "motherboard"}:
        m1, m2 = pair["ram"].get("memory_type"), pair["motherboard"].get("memory_type")
        if not m1 or not m2:
            return None, "RAM × placa-mãe não verificado: falta o tipo de memória."
        if _n(m1) != _n(m2):
            return False, f"Memória {m1} numa placa {m2}."
        return True, None

    if keys == {"case", "motherboard"}:
        ff, sup = pair["motherboard"].get("form_factor"), pair["case"].get("motherboard_support")
        if not ff or not sup:
            return None, "Gabinete × placa-mãe não verificado: falta o formato."
        if _n(ff) not in {_n(s) for s in sup}:
            return False, f"O gabinete não aceita placa {ff}."
        return True, None

    if keys == {"cooler", "cpu"}:
        s, sup = pair["cpu"].get("socket"), pair["cooler"].get("sockets")
        if not s or not sup:
            return None, "Cooler × CPU não verificado: falta o socket."
        if _n(s) not in {_n(x) for x in sup}:
            return False, f"O cooler não lista suporte a {s}."
        return True, None

    if keys == {"psu", "gpu"}:
        w, rec = pair["psu"].get("wattage_w"), pair["gpu"].get("recommended_psu_w")
        if not w or not rec:
            return None, "Fonte × GPU não verificado: falta a potência."
        if int(w) < int(rec):
            return False, f"Fonte de {w} W, a GPU pede {rec} W."
        return True, None

    return True, None  # par sem regra


def check_in_build(category: str, specs: dict, others: dict[str, dict]) -> dict:
    """Compara a peça com as outras já escolhidas na build. others = {categoria: specs}."""
    compatible: bool | None = True
    warnings: list[str] = []
    for cat, sp in others.items():
        if cat == category or sp is None:
            continue
        ok, warn = _pair(category, specs or {}, cat, sp or {})
        if warn:
            warnings.append(warn)
        if ok is False:
            compatible = False
        elif ok is None and compatible is True:
            compatible = None
    return {"compatible": compatible, "warnings": warnings}


# --------------------------------------------------------------------------- dados

def _priced_parts(conn: sqlite3.Connection) -> dict[str, list[dict]]:
    """Peças com preço em estoque, por categoria, da mais barata pra mais cara."""
    out: dict[str, list[dict]] = {c: [] for c in CATEGORIES}
    for row in conn.execute("SELECT id, category, specs FROM parts").fetchall():
        best = db.best_price(conn, row["id"])
        if best is None:
            continue
        out[row["category"]].append(
            {"id": row["id"], "specs": json.loads(row["specs"]), "price": best["price_cash"]})
    for lst in out.values():
        lst.sort(key=lambda p: p["price"])
    return out


def _cheapest(cands: list[dict], category: str, chosen: dict[str, dict]) -> dict | None:
    """Mais barata compatível; prefere verificada (True) a não verificada (None)."""
    best = None
    for p in cands:
        res = check_in_build(category, p["specs"], {c: x["specs"] for c, x in chosen.items()})
        if res["compatible"] is False:
            continue
        key = (res["compatible"] is None, p["price"])
        if best is None or key < best[0]:
            best = (key, p)
    return best[1] if best else None


def auto_pick(conn: sqlite3.Connection) -> dict[str, int | None]:
    """A combinação compatível mais barata. Testa cada placa-mãe como plataforma."""
    parts = _priced_parts(conn)

    def fill(start: dict[str, dict]) -> dict[str, dict]:
        chosen = dict(start)
        # ordem importa: CPU antes do cooler, GPU antes da fonte
        for cat in ("cpu", "ram", "case", "cooler", "gpu", "psu", "storage"):
            if cat in chosen:
                continue
            p = _cheapest(parts[cat], cat, chosen)
            if p:
                chosen[cat] = p
        return chosen

    candidates = [fill({"motherboard": mb}) for mb in parts["motherboard"]] or [fill({})]

    def score(ch: dict[str, dict]):
        # 1º: quantas categorias ficaram preenchidas; 2º: total
        return (-len(ch), sum(p["price"] for p in ch.values()))

    best = min(candidates, key=score)
    return {c: (best[c]["id"] if c in best else None) for c in CATEGORIES}


def build_specs(conn: sqlite3.Connection, build_id: int) -> dict[str, dict]:
    rows = conn.execute(
        """SELECT bi.category, p.specs FROM build_items bi JOIN parts p ON p.id = bi.part_id
           WHERE bi.build_id = ?""", (build_id,)).fetchall()
    return {r["category"]: json.loads(r["specs"]) for r in rows}
