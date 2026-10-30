"""Dados de EXEMPLO pro frontend enquanto a coleta não existe.

Vai num banco separado (`data/demo.db`), recriado do zero a cada partida do serviço. Preços inventados,
mas plausíveis; links apontam pra BUSCA da loja (não pra produto inventado). Sem imagem: não invento foto.
A API marca tudo com `demo: true` e o frontend mostra a faixa EXEMPLO.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote_plus

from .db import database as db
from .ingest import ingest_batch
from .schemas import IngestBatch

DEMO_DB = db.DEFAULT_DB.with_name("demo.db")

# (categoria, marca, modelo, specs, preço base em reais)
PARTS = [
    ("cpu", "AMD", "Ryzen 5 5600", {"socket": "AM4"}, 699),
    ("cpu", "AMD", "Ryzen 7 5700X3D", {"socket": "AM4"}, 1399),
    ("cpu", "AMD", "Ryzen 5 7600", {"socket": "AM5"}, 1099),
    ("cpu", "Intel", "Core i5-12400F", {"socket": "LGA1700"}, 749),
    ("motherboard", "ASRock", "B550M-HDV", {"socket": "AM4", "memory_type": "DDR4", "form_factor": "mATX"}, 549),
    ("motherboard", "Gigabyte", "B650M Gaming X AX", {"socket": "AM5", "memory_type": "DDR5", "form_factor": "mATX"}, 1199),
    ("motherboard", "MSI", "PRO B760M-E DDR4", {"socket": "LGA1700", "memory_type": "DDR4", "form_factor": "mATX"}, 699),
    ("ram", "Kingston", "Fury Beast 16GB (2x8) DDR4 3200", {"memory_type": "DDR4"}, 279),
    ("ram", "XPG", "Lancer 32GB (2x16) DDR5 6000", {"memory_type": "DDR5"}, 749),
    ("gpu", "NVIDIA", "GeForce RTX 4060 8GB", {"recommended_psu_w": 550}, 1899),
    ("gpu", "AMD", "Radeon RX 7600 8GB", {"recommended_psu_w": 550}, 1699),
    ("gpu", "NVIDIA", "GeForce RTX 4070 Super 12GB", {"recommended_psu_w": 650}, 4299),
    ("storage", "Kingston", "NV3 1TB NVMe", {"type": "nvme"}, 379),
    ("storage", "WD", "Blue 2TB HD", {"type": "hdd"}, 389),
    ("psu", "MSI", "MAG A550BN 550W", {"wattage_w": 550}, 329),
    ("psu", "Corsair", "RM750e 750W", {"wattage_w": 750}, 649),
    ("case", "Montech", "AIR 100 ARGB", {"motherboard_support": ["mATX", "ITX"]}, 299),
    ("case", "Lian Li", "Lancool 216", {"motherboard_support": ["ATX", "mATX", "ITX"]}, 699),
    ("cooler", "DeepCool", "AK400", {"sockets": ["AM4", "AM5", "LGA1700"]}, 189),
    ("cooler", "Thermalright", "Peerless Assassin 120 SE", {"sockets": ["AM4", "AM5", "LGA1700"]}, 229),
]

SEARCH = {
    "kabum": "https://www.kabum.com.br/busca/{q}",
    "pichau": "https://www.pichau.com.br/search?q={q}",
    "terabyte": "https://www.terabyteshop.com.br/busca?str={q}",
}

# peças que ficam em promoção no último dia (índice em PARTS → loja)
DEALS = {1: "kabum", 9: "pichau", 15: "terabyte", 19: "kabum", 13: "kabum"}


def build_demo(path: str | Path = DEMO_DB, today: date | None = None, days: int = 30) -> Path:
    path = Path(path)
    for suffix in ("", "-wal", "-shm", "-journal"):
        Path(str(path) + suffix).unlink(missing_ok=True)
    today = today or date.today()
    rng = random.Random(42)
    conn = db.init_db(path)
    try:
        for d in range(days, -1, -1):
            day = today - timedelta(days=d)
            items = []
            for i, (cat, brand, model, specs, base) in enumerate(PARTS):
                for store, tpl in SEARCH.items():
                    if (i + len(store)) % 5 == 0:  # nem toda loja tem toda peça
                        continue
                    price = base * rng.uniform(0.97, 1.06) * (1 + 0.02 * (store == "pichau"))
                    if d == 0 and DEALS.get(i) == store:
                        price = base * 0.82
                    items.append({
                        "store": store, "url": tpl.format(q=quote_plus(f"{brand} {model}")),
                        "title": f"{brand} {model}", "category": cat, "brand": brand, "model": model,
                        "specs": specs, "price_cash": round(price * 100),
                        "price_installment": round(price * 118), "in_stock": (i + d) % 11 != 0 or d > 0,
                    })
            ingest_batch(conn, IngestBatch.model_validate(
                {"collected_at": f"{day.isoformat()}T09:00:00", "items": items}))
    finally:
        conn.close()
    return path
