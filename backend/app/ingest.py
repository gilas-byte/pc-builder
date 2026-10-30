"""Gravação de preços no banco, SEM passar pela rede.

O app web (inclusive atrás de um proxy local) só lê e edita builds. Preço só entra por aqui,
rodando na própria máquina:

    uv run python -m app.ingest lote.json        # ou: ... -m app.ingest - < lote.json

Formato do JSON: o mesmo de `schemas.IngestBatch` ({"collected_at": ..., "items": [...]}).
Saída: JSON com o resumo. Código de saída 0 = gravou, 1 = recusado (nada gravado).
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from .db import database as db
from .schemas import IngestBatch


class IngestError(ValueError):
    """Lote recusado. Nada foi gravado."""


def ingest_batch(conn: sqlite3.Connection, batch: IngestBatch) -> dict:
    collected = (batch.collected_at or datetime.now()).replace(microsecond=0, tzinfo=None)
    collected_at = collected.isoformat()
    store_ids = {r["slug"]: r["id"] for r in conn.execute("SELECT id, slug FROM stores WHERE active = 1")}
    unknown = sorted({i.store for i in batch.items} - store_ids.keys())
    if unknown:
        raise IngestError(f"loja desconhecida ou inativa: {', '.join(unknown)}")

    stats = {"parts_created": 0, "listings_created": 0, "snapshots": 0}
    try:
        with conn:  # tudo ou nada
            for it in batch.items:
                part_id, new_part = db.upsert_part(conn, it.category, it.brand, it.model, it.specs,
                                                   str(it.image_url) if it.image_url else None)
                listing_id, new_listing = db.upsert_listing(
                    conn, part_id, store_ids[it.store], str(it.url), it.title, it.condition, it.seller)
                db.insert_snapshot(conn, listing_id, it.price_cash, it.in_stock,
                                   collected_at, it.price_installment)
                stats["parts_created"] += new_part
                stats["listings_created"] += new_listing
                stats["snapshots"] += 1
    except db.ListingConflict as e:
        raise IngestError(str(e)) from e
    return {"collected_at": collected_at, **stats}


def main(argv: list[str] | None = None, db_path: str | Path = db.DEFAULT_DB) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("uso: python -m app.ingest <arquivo.json | ->", file=sys.stderr)
        return 2
    raw = sys.stdin.read() if argv[0] == "-" else Path(argv[0]).read_text(encoding="utf-8")
    try:
        batch = IngestBatch.model_validate(json.loads(raw))
        conn = db.init_db(db_path)
        try:
            result = ingest_batch(conn, batch)
        finally:
            conn.close()
    except (json.JSONDecodeError, ValidationError, IngestError) as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, **result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
