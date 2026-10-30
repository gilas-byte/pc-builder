"""Busca da tela: palavra por palavra, em qualquer ordem, sem ligar pra acento nem maiúscula.

"suporte monitor" acha "Suporte Articulado Para Monitor"; "placa video" acha "Placa de Vídeo";
"monitores" acha "Monitor" (plural simples cai pro singular). Cada palavra tem que ser começo de uma palavra
do título: "moni" acha Monitor enquanto digita, mas "ti" não acha "Articulado".
"""

from __future__ import annotations

from .collect.watchlist import norm


def _singular(tok: str) -> str | None:
    if len(tok) > 5 and tok.endswith("es"):
        return tok[:-2]
    if len(tok) > 4 and tok.endswith("s") and not tok[-2].isdigit():
        return tok[:-1]
    return None


def matcher(q: str | None):
    """Devolve uma função texto -> bool, ou None se a busca estiver vazia."""
    words = norm(q or "").split()
    if not words:
        return None

    def match(text: str) -> bool:
        t = norm(text)
        for w in words:                 # começo de palavra: "moni" acha monitor, "ti" não acha "articulado"
            if f" {w}" in t:
                continue
            s = _singular(w)
            if s and f" {s}" in t:
                continue
            return False
        return True
    return match
