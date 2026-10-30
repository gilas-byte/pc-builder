"""O que é peça de PC, e qual é a "chave" da peça (pra comparar o mesmo produto entre canais e lojas).

Chave = só o que define o preço: GPU = chip + VRAM; CPU = modelo; RAM = DDR + capacidade total + frequência;
SSD = marca + linha + capacidade; fonte = marca + watts + selo; placa-mãe = marca + chipset (+wifi);
cooler/gabinete = código do modelo; monitor = marca + tamanho + resolução + Hz.
Sem os dados mínimos, a chave é None: a oferta é guardada, mas não entra em comparação nem gera aviso.
"""

from __future__ import annotations

import re

from ..collect.watchlist import norm

CATEGORIES = ("cpu", "motherboard", "ram", "gpu", "storage", "psu", "case", "cooler", "monitor")

# eletrodoméstico, som e hub de fans: citam "processador", "ventilador", "300W"... sem ser peça de PC. Vale também
# para o tipo votado pelo Ollama (adjust_kind), que só vê o título e já tomou "mini processador" por CPU.
HOME_AUDIO_RX = (
    r"mini processador|processador de alimentos|multiprocessador|turbo pratic|mondial|mallory|"
    r"ventilador de (?:mesa|parede|teto|coluna|torre|chao|piso)|circulador de ar|climatizador|"
    r"hub de (?:ventilador|ventiladores|fans?|ventoinhas?)|"
    r"amplificador|modulo amplificador|caixa de som|caixa acustica|caixa amplificada|bombox|subwoofer|subgrave|"
    r"soundbar|som automotivo|bluetooth speaker|home theater|taramps"
)
HARD_NOT_PART = re.compile(r" (?:" + HOME_AUDIO_RX + r") ")

# não é peça (mesmo que cite RTX/Ryzen/processador no texto)
NOT_PART = re.compile(
    r" (sodimm|so dimm|impact|notebook|laptop|ultrabook|chromebook|macbook|ideapad|vivobook|zenbook|expertbook|thinkpad|thinkbook|"
    r"aspire|nitro v\d*|nitro 5|predator|loq|legion|rog strix g\d*|rog zephyrus\w*|rog flow\w*|tuf gaming [af]\d\d|galaxy book|"
    r"inspiron|vostro|latitude|pavilion|victus|omen|hp \d{3} g|positivo|slim 3|slim 5|yoga|celular|smartphone|"
    r"iphone|galaxy [asz]\d|redmi|poco|moto g|"
    r"tablet|ipad|console|playstation|ps5|ps4|xbox|nintendo|switch 2|steam deck|pc gamer|pc office|pc home|"
    r"computador|mini pc|all in one|desktop completo|kit upgrade|combo|suporte|braco articulado|capa|capinha|"
    r"pelicula|cabo|adaptador|carregador|power bank|hub usb|dock|liquidificador|mixer|picador|moedor|cozinha|"
    r"alimentos|impressora|smart tv|televis|projetor|relogio|fone|headset|mouse|teclado|cadeira|mesa|"
    r"roteador|webcam|controle|joystick|placa de captura|pendrive|cartao de memoria|micro ?sd|"
    r"hd externo|ssd externo|ssd portatil|case para ssd|gaveta|dissipador para ssd|pasta termica|"
    + HOME_AUDIO_RX
    + r") "
)

# RAM de notebook (SO-DIMM) não encaixa na placa do PC e não entra na build. O prompt da votação diz de
# propósito "inclusive de notebook" (o tipo é só "é RAM"), então esta regra roda DEPOIS da votação.
# "Impact" = linha de notebook da HyperX/Kingston Fury (Impact DDR4/DDR5 é sempre SO-DIMM).
LAPTOP_RAM = re.compile(r" (so ?dimm|impact|(para|p|pra|de|do) (o |seu )?(note ?books?|laptops?)) ")
# Só vira peça com evidência de DESKTOP no texto. Muito post de RAM não diz o formato (a foto é a única pista,
# e o modelo de visão local não distinguiu: testado em 16/10/2026), então na dúvida NÃO é peça.
DESKTOP_RAM = re.compile(
    r" (desktop|udimm|dimm|pc gamer|gamer|rgb|dissipador|heatsink|fury beast|fury renegade|hyperx fury|vengeance|"
    r"lancer|trident|ripjaws|t ?force|dominator|spectrix|viper|ballistix|predator|kit (2|4)x|[24]x ?\d{1,2} ?gb) ")


def adjust_kind(kind: str | None, text: str) -> str | None:
    """Corrige o tipo votado: RAM que é de notebook, ou sem nenhum sinal de desktop, vira 'outro_tech'
    (continua como oferta, mas sem chave: fora da comparação, dos avisos e da build). Só mexe em 'peca:ram'."""
    n = norm(head_of(text))
    if kind and (kind.startswith("peca:") or kind == "monitor") and HARD_NOT_PART.search(n):
        return "outro_tech"
    if kind != "peca:ram":
        return kind
    n = norm(text)
    if LAPTOP_RAM.search(n) or not DESKTOP_RAM.search(n):
        return "outro_tech"
    return kind


CAT_RX = {
    "motherboard": r" (placa mae|motherboard|mobo) ",
    "gpu": r" (placa de video|geforce|radeon rx|rtx \d{4}|gtx \d{4}|rx \d{4}|arc [ab]\d{3}|gpu) ",
    "cpu": r" (processador|ryzen [3579] \d{4}|core i[3579]|core ultra [579]) ",
    "ram": r" (memoria ram|memoria ddr|memoria [a-z]+ (fury|vengeance|ripjaws|trident|t force)|ddr[45]) ",
    "storage": r" (ssd|nvme|hd interno|hdd|disco rigido) ",
    "psu": r" (fonte) ",
    "cooler": r" (air cooler|water ?cooler|watercooler|cooler) ",
    "case": r" (gabinete) ",
    "monitor": r" (monitor) ",
}

# piso em reais: abaixo disso é acessório/isca (copiado da coleta das lojas; monitor novo)
FLOOR = {"cpu": 250, "motherboard": 350, "ram": 90, "gpu": 500, "storage": 120, "psu": 150, "case": 120,
         "cooler": 50, "monitor": 300}


def head_of(text: str) -> str:
    """Parte de cima do post, antes da linha do preço/link: é onde fica o nome do produto."""
    lines = []
    for line in text.split("\n"):
        low = line.lower()
        if re.search(r"r\$|\bpor\s*:|http|\bcupom\b|\blink\b|\bcompre\b", low):
            break
        lines.append(line)
    return " ".join(lines) if lines else text.split("\n")[0]


def title_of(text: str) -> str:
    """Nome do produto: 1ª linha do cabeçalho que parece nome. Pula grito de chamada ("PS5 SLIM POR UM ÓTIMO
    PREÇO!", "PARCELADO 🔥", tudo em maiúscula com !) e linha de ficha ("- Ryzen 5", "825GB - Branco - ...")."""
    head = []
    for line in text.split("\n"):
        if re.search(r"r\$|\bpor\s*:|http|\bcupom\b|\blink\b|\bcompre\b", line.lower()):
            break
        if line.strip():
            head.append(re.sub(r"^[^\w]+", "", line).strip())
    def shout(l):
        letters = [c for c in l if c.isalpha()]
        caps = bool(letters) and sum(c.isupper() for c in letters) / len(letters) > 0.8
        hype = re.search(r"\b(pra|por|preço|preco|barato|barata|top|ótimo|otimo|oferta|mais|hj|hoje|voltou|"
                         r"caiu|aproveita|completo|bom|boa|melhor|absurdo|corre)\b", l.lower())
        if "!" in l and (caps or len(letters) < 40):
            return True
        if caps and len(letters) < 60 and (not re.search(r"\d", l) or bool(hype)):
            return True
        # todo em maiúscula, mas com cara de nome (marca/modelo): "ASUS TUF GAMING F16 com RTX 5060" passa
        return False
    def spec(l):
        return l.startswith("-") or l.count(" - ") >= 2 or re.match(r"^\d+\s*(gb|tb)\b", l.lower())
    def noise(l):
        return l.startswith("(") or bool(re.search(r"vendido e entregue|tela \d+\" ips \+|^parcelado", l.lower()))
    for l in head:
        if len(l) >= 6 and not shout(l) and not spec(l) and not noise(l):
            return l[:200]
    cand = head or [l for l in text.split("\n") if l.strip()][:1] or [text]
    return re.sub(r"^[^\w]+", "", max(cand, key=len)).strip()[:200]


def vote_text(text: str) -> str:
    """O que vai pros 3 modelos: o título + a linha seguinte do cabeçalho (ficha curta). Sem isso, um post
    "RYZEN 5 COM BOM PREÇO" de notebook Positivo virou "processador" por unanimidade (12/10/2026)."""
    t = title_of(text)
    head = [re.sub(r"^[^\w]+", "", l).strip() for l in head_of_lines(text)]
    try:
        nxt = next(l for l in head[head.index(t) + 1:] if l)
    except (ValueError, StopIteration):
        nxt = ""
    return f"{t} — {nxt[:120]}" if nxt else t


def head_of_lines(text: str) -> list[str]:
    out = []
    for line in text.split("\n"):
        if re.search(r"r\$|\bpor\s*:|http|\bcupom\b|\blink\b|\bcompre\b", line.lower()):
            break
        if line.strip():
            out.append(line)
    return out


def category_match(h: str) -> tuple[str, str] | None:
    """(categoria, palavra que decidiu) pela 1ª palavra de peça no texto JÁ normalizado; None se não há nenhuma.
    Não olha NOT_PART nem watts: quem chama decide (category() e rules.rules_kind())."""
    best = None
    for cat, rx in CAT_RX.items():
        m = re.search(rx, h)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), cat, m.group(1))
    return (best[1], best[2]) if best else None


PSU_WATTS = re.compile(r" \d{3,4}w ")


def category(text: str) -> str | None:
    h = norm(head_of(text))
    if NOT_PART.search(h):
        return None
    hit = category_match(h)
    if not hit:
        return None
    cat = hit[0]
    if cat == "psu" and not PSU_WATTS.search(h):
        return None                         # "fonte" sem watts: carregador, fonte de luz...
    return cat


# --------------------------------------------------------------------------- chave da peça

BRANDS = ["asus", "gigabyte", "msi", "asrock", "biostar", "evga", "zotac", "palit", "pny", "galax", "inno3d",
          "gainward", "sapphire", "powercolor", "xfx", "asl", "colorful", "afox", "pcyes", "mancer", "corsair",
          "kingston", "samsung", "western digital", "wd", "crucial", "adata", "xpg", "lexar", "sandisk", "seagate",
          "kingspec", "netac", "teamgroup", "team group", "hiksemi", "patriot", "solidigm", "hynix", "rise mode",
          "redragon", "cooler master", "thermaltake", "super flower", "superflower", "gamemax", "aerocool",
          "lian li", "seasonic", "deepcool", "montech", "tgt", "husky", "be quiet", "nzxt", "fractal", "pichau",
          "lg", "aoc", "philips", "dell", "acer", "benq", "lenovo", "tcl", "koorui", "arzopa", "haiz",
          "hp", "aigo", "darkflash", "pcfort", "duex", "bluecase", "c3tech", "k mex", "kmex", "jonsbo", "id cooling",
          "thermalright", "arctic", "noctua", "gamdias", "fortrek", "oex", "mymax", "sk hynix", "nvidia", "amd",
          "intel", "zalman", "1stplayer", "valianty", "gskill", "g skill", "netac", "geil", "ballistix", "fury",
          "vengeance"]
_BRAND_RX = re.compile(r" (" + "|".join(sorted({re.escape(b) for b in BRANDS}, key=len, reverse=True)) + r") ")
ALIASES = {"western digital": "wd", "team group": "teamgroup", "superflower": "super flower", "kmex": "k mex",
           "g skill": "gskill", "sk hynix": "hynix"}


def _brand(h: str, skip=("nvidia", "amd", "intel", "fury", "vengeance")) -> str | None:
    for m in _BRAND_RX.finditer(h):
        b = ALIASES.get(m.group(1), m.group(1))
        if b not in skip:
            return b
    return None


def _gpu(h):
    chip = (re.search(r" (rtx|gtx) (\d{4})((?: ti| super)*) ", h) or
            re.search(r" (rx) (\d{4})((?: xtx| xt| gre)?) ", h) or
            re.search(r" (arc) ([ab]\d{3})()", h))
    vram = re.search(r" (\d{1,2})gb ", h)
    if not (chip and vram):
        return None
    return f"gpu|{chip.group(1)} {chip.group(2)}{chip.group(3)}|{vram.group(1)}gb"


def _cpu(h):
    m = (re.search(r" ryzen ([3579]) (\d{4}[a-z0-9]*) ", h) or
         re.search(r" (?:core )?i([3579]) ?(\d{4,5}[a-z]*) ", h) or
         re.search(r" core ultra ([579]) (\d{3}[a-z]*) ", h))
    if not m:
        return None
    fam = "ryzen" if "ryzen" in m.group(0) else ("ultra" if "ultra" in m.group(0) else "i")
    return f"cpu|{fam} {m.group(1)} {m.group(2)}"


def _ram(h):
    ddr = re.search(r" ddr([45]) ", h)
    kit = re.search(r" (\d)x(\d{1,2})gb ", h) or re.search(r" (\d) ?x ?(\d{1,2})gb ", h)
    total = int(kit.group(1)) * int(kit.group(2)) if kit else None
    if total is None:
        cap = re.search(r" (\d{1,3})gb ", h)
        total = int(cap.group(1)) if cap else None
    freq = re.search(r" (\d{4})mhz ", h) or re.search(r" (2400|2666|3000|3200|3600|4000|4800|5200|5600|6000|"
                                                       r"6400|6800|7200|8000)(?:mt s)? ", h)
    if not (ddr and total and freq):
        return None
    return f"ram|ddr{ddr.group(1)}|{total}gb|{freq.group(1)}"


def _storage(h):
    cap = re.search(r" (\d{3,4})gb ", h) or re.search(r" (\d)tb ", h)
    if not cap:
        return None
    gb = int(cap.group(1)) * (1000 if cap.re.pattern.endswith("tb ") else 1)
    kind = "hdd" if re.search(r" (hd interno|hdd|disco rigido|7200rpm|5400rpm) ", h) else (
        "nvme" if re.search(r" (nvme|m 2|pcie|gen ?[345]) ", h) else "sata")
    brand = _brand(h)
    if not brand:
        return None
    line = re.search(r" " + re.escape(brand) + r" (?:[a-z]+ )?([a-z]*\d+[a-z0-9]*) ", h)
    model = line.group(1) if line and not re.fullmatch(r"\d+(gb|tb)", line.group(1)) else ""
    return f"storage|{kind}|{gb}gb|{brand} {model}".strip()


def _psu(h):
    w = re.search(r" (\d{3,4})w ", h)
    rating = re.search(r" (bronze|silver|gold|platinum|titanium|white|standard) ", h)
    brand = _brand(h)
    if not (w and brand):
        return None
    return f"psu|{brand}|{w.group(1)}w|{rating.group(1) if rating else '-'}"


CHIPSETS = r"(a320m?|a520m?|b450m?|b550m?|x570|b650m?|b650e|x670e?|a620m?|b840m?|b850m?|x870e?|h610m?|b660m?|" \
           r"b760m?|h770|z690|z790|b860m?|h810m?|z890)"


def _motherboard(h):
    chip = re.search(r" " + CHIPSETS + r" ", h)
    brand = _brand(h)
    if not (chip and brand):
        return None
    wifi = "|wifi" if re.search(r" (wifi|wi fi|ax) ", h) else ""
    return f"motherboard|{brand}|{chip.group(1)}{wifi}"


GENERIC = re.compile(r"\d+(mm|w|v|rpm|gb|tb|mhz|hz|cm|pol|x)|am[45]|lga\d+|1[57]\d{2}|115x|\d+|tdp\d*|ddr[45]|"
                     r"r?gb|argb|pwm|atx|matx|itx|usb\d*|[a-z]\d? ?")


VARIANT = {"zero": "zerodark", "digital": "digital", "wh": "white", "white": "white", "branco": "white",
           "branca": "white", "rd": "rd", "pro": "pro", "plus": "plus", "se": "se", "lite": "lite", "max": "max",
           "mesh": "mesh", "v2": "v2", "v3": "v3", "elite": "elite", "airflow": "airflow"}


def _model_code(h, cat):
    """1º token com letra e número que não é unidade/socket (ak400, cv700b, ds900, a275) + variante logo depois
    ("AK400 Zero Dark", "AK400 WH", "AK400 RD" são produtos diferentes do AK400 com preço diferente).
    Preto/black é a cor padrão e não entra."""
    after = h.split(f" {'gabinete' if cat == 'case' else 'cooler'} ", 1)[-1].split()
    for i, tok in enumerate(after):
        if re.search(r"[a-z]", tok) and re.search(r"\d", tok) and not GENERIC.fullmatch(tok):
            var = sorted({VARIANT[t] for t in after[i + 1:i + 4] if t in VARIANT})
            if re.search(r" (branco|branca|white) ", " " + " ".join(after) + " "):
                var = sorted(set(var) | {"white"})
            return f"{cat}|{tok}" + (f"|{'+'.join(var)}" if var else "")
    return None


MONITOR_NOISE = re.compile(r"\d+(hz|ms|mm|cm|pol|gb|w|r)|\d{3,4}x\d{3,4}|hdr\d*|usb\w*|gen\d|\d+|[a-z]+")


def _monitor(raw_head: str, h: str):
    """Com código do modelo (24gs60f, vg34wqml5a) a chave é o código: 2 monitores com a mesma ficha podem ter
    preço bem diferente. Sem código, cai pra ficha (marca + tamanho + resolução + Hz)."""
    brand = _brand(h)
    if not brand:
        return None
    for tok in h.split():
        if (len(tok) >= 5 and re.search(r"[a-z]", tok) and re.search(r"\d", tok)
                and not MONITOR_NOISE.fullmatch(tok)):
            return f"monitor|{brand}|{tok}"
    size = re.search(r"(\d{2}(?:[.,]\d)?)\s*(?:\"|”|″|''|pol|polegadas)", raw_head.lower())
    hz = re.search(r" (\d{2,3}) ?hz ", h)
    res = ("uhd" if re.search(r" (4k|uhd|2160p) ", h) else "qhd" if re.search(r" (qhd|2k|1440p|wqhd) ", h)
           else "fhd" if re.search(r" (fhd|full hd|1080p) ", h) else None)
    if not (size and hz and res):
        return None
    return f"monitor|{brand}|{size.group(1).replace(',', '.')}|{res}|{hz.group(1)}hz"


def product_key(text: str, cat: str) -> str | None:
    raw = head_of(text)
    h = norm(raw)
    if cat == "monitor":
        return _monitor(raw, h)
    if cat in ("case", "cooler"):
        return _model_code(h, cat)
    return {"gpu": _gpu, "cpu": _cpu, "ram": _ram, "storage": _storage, "psu": _psu,
            "motherboard": _motherboard}[cat](h)
