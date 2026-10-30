"""Classificador por regras: o plano B quando não há Ollama.

Mesmas regras de `classify.py` (NOT_PART, CAT_RX, fonte com watts, RAM de desktop), sem duplicar nada; aqui só
entram os ajustes que o `category()` antigo não tinha e que a medição em ofertas reais mostrou (ver PECAS em
tests/test_classifier_and_ollama.py). Devolve o tipo no mesmo vocabulário da votação para peça e monitor (`peca:cpu` ...
`monitor`), `nao_peca` para o que claramente não é peça avulsa, ou None quando não dá para ter certeza.
Na dúvida, None: nunca vira peça por chute.

A acurácia mostrada na tela (`rules_metrics.json`) é a medida dessas regras contra ofertas reais de canais públicos
rotuladas à mão.
"""

from __future__ import annotations

import re

from ..collect.watchlist import norm
from .classify import DESKTOP_RAM, LAPTOP_RAM, NOT_PART, PSU_WATTS, category_match, head_of, product_key

NOT_A_PART = "nao_peca"
CAT2KIND = {"cpu": "peca:cpu", "gpu": "peca:gpu", "motherboard": "peca:motherboard", "ram": "peca:ram",
            "storage": "peca:storage", "psu": "peca:psu", "case": "peca:case", "cooler": "peca:cooler",
            "monitor": "monitor"}
KINDS = (*CAT2KIND.values(), NOT_A_PART)
# confiança: com chave de produto (ficha completa: chip + VRAM, DDR + GB + MHz...) a regra é forte; sem chave, a
# palavra bate mas falta ficha. Só com chave a oferta entra na comparação de preço e no aviso (como na votação).
HIGH, MEDIUM = 0.9, 0.7
LOW = 0.6

# "UPGRADE PRA NOTEBOOK, PC e PS5 Kingston NV3": o SSD é PARA o notebook, não é um notebook. Só vale para SSD
# (RAM de notebook não é peça: LAPTOP_RAM continua olhando o texto inteiro).
USE_FOR = re.compile(r" (?:para|pra|p) (?:o |seu |sua )?(?:(?:note ?books?|laptops?|pcs?|ps[45]|playstation \d|"
                     r"xbox|consoles?|e) )+")
# palavra de cooler que o category() não conhece (fan de gabinete; a votação já chamava de peca:cooler)
EXTRA_CAT = {"cooler": re.compile(r" (ventoinhas?|fans?|kit fan) ")}
# série de marca que também dá nome a monitor ("Acer Nitro 5", "HP Omen", "Lenovo Legion"): não derruba um
# título que COMEÇA por "monitor" (só monitor: "RTX 4060 ... Acer Nitro V15" é notebook)
SERIES = re.compile(r" (nitro v\d*|nitro 5|predator|loq|legion|omen|victus|rog strix g\d*|tuf gaming [af]\d\d) ")
# ficha de máquina inteira ("16GB RAM - 256GB SSD", "Core 5 120U ... SSD"): é notebook/PC, não peça avulsa
MACHINE_RAM = re.compile(r" \d{1,3}gb (?:de )?(?:ram|memoria) ")
MACHINE_OTHER = re.compile(r" (?:ssd|nvme|hd|emmc|ryzen [3579]|core (?:i[3579]|ultra [579]|[357])) ")


def _starts_with(h: str, word: str) -> bool:
    return h.startswith(f" {word} ")


def rules_kind(text: str) -> tuple[str | None, float, str]:
    """(tipo | None, confiança 0-1, porquê em português curto)."""
    h = norm(head_of(text))
    hit = category_match(h)
    if hit is None:
        for cat, rx in EXTRA_CAT.items():
            m = rx.search(h)
            if m:
                hit = (cat, m.group(1))
    if hit and hit[0] == "storage":
        h_check = USE_FOR.sub(" ", h)
    else:
        h_check = h
    bad = NOT_PART.search(h_check)
    if bad and hit and hit[0] == "monitor" and _starts_with(h, hit[1]) and SERIES.fullmatch(f" {bad.group(1)} "):
        bad = None                                          # "Monitor ... Acer Nitro 5": a série é do monitor
    if bad:
        return NOT_A_PART, HIGH, f"cita “{bad.group(1)}”: não é peça avulsa"
    if not hit:
        return NOT_A_PART, LOW, "nenhuma palavra de peça no título"
    cat, word = hit
    if MACHINE_RAM.search(h) and MACHINE_OTHER.search(h):
        return NOT_A_PART, MEDIUM, "ficha de máquina inteira (RAM + SSD/processador): notebook ou PC"
    if cat == "psu" and not PSU_WATTS.search(h):
        return None, 0.0, "“fonte” sem watts: pode ser carregador ou outra coisa"
    if cat == "ram":
        if LAPTOP_RAM.search(h):
            return NOT_A_PART, HIGH, "RAM de notebook (SO-DIMM): não encaixa no PC"
        if not DESKTOP_RAM.search(h):
            return None, 0.0, "RAM sem sinal de desktop: pode ser de notebook"
    if product_key(text, cat):
        return CAT2KIND[cat], HIGH, f"cita “{word}” e a ficha do produto"
    return CAT2KIND[cat], MEDIUM, f"cita “{word}”, mas falta ficha (modelo, capacidade...)"
