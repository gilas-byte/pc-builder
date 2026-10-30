"""Revota o tipo das ofertas já guardadas pelo Ollama (depois de mudar prompt/texto da votação, ou quando ele volta).

Uso: python -m app.tg.reclassify [--parts | --all] [--dry-run]
  padrão:  as de tipo dado pelas regras + as sem tipo (Ollama estava fora). A rodada já faz isso sozinha quando
           o Ollama volta; aqui é para rodar à mão.
  --parts: as sem tipo + as de peça (onde um erro de tipo muda a aba Peças), de qualquer origem.
  --all:   todas.
Usa o endereço e os modelos das Configurações, em qualquer modo. Com o Ollama fora, não mexe em nada.
"""

from __future__ import annotations

import argparse
import json

from .. import settings as S
from ..db import database as db
from . import classifier as C
from . import vote as V


def main(argv=None, db_path=db.DEFAULT_DB, chat: V.Chat | None = None, ollama_client=None) -> dict:
    ap = argparse.ArgumentParser(prog="python -m app.tg.reclassify")
    which = ap.add_mutually_exclusive_group()
    which.add_argument("--all", action="store_true")
    which.add_argument("--parts", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    conn = db.init_db(db_path)
    where = ("" if a.all else "WHERE kind IS NULL OR kind LIKE 'peca:%'" if a.parts
             else "WHERE kind_source = 'rules' OR kind IS NULL")
    rows = conn.execute(f"SELECT id, text, kind FROM tg_offers {where}").fetchall()
    ollama, _ = C.ollama_backend(S.values(conn), chat, ollama_client)
    try:
        verdicts = ollama.classify([r["text"] for r in rows])
    except V.OllamaDown as e:
        conn.close()
        out = {"revotadas": 0, "tipo_mudou": [], "descartadas": 0, "dry_run": a.dry_run,
               "erro": f"Ollama fora do ar ({e}); nada mudou"}
        print(json.dumps(out, ensure_ascii=False))
        return out
    changed, dropped = [], 0
    with conn:
        for r, v in zip(rows, verdicts):
            kind = C.update_offer(conn, r["id"], r["text"], v, ollama.quorum)
            if kind is None and v.kind in (V.NOT_TECH, V.COUPON):
                dropped += 1
            elif kind != r["kind"]:
                changed.append((r["id"], r["kind"], kind))
        if a.dry_run:
            conn.rollback()
    if not a.dry_run:
        from .sync import sync
        sync(conn)
    conn.close()
    out = {"revotadas": len(rows), "tipo_mudou": changed, "descartadas": dropped, "dry_run": a.dry_run}
    print(json.dumps(out, ensure_ascii=False))
    return out


if __name__ == "__main__":
    main()
