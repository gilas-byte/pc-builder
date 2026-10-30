"""Quem diz o TIPO das ofertas dos canais: a votação do Ollama ou as regras.

Modo (configuração `classifier`, PCB_CLASSIFIER sobrepõe):
- auto (padrão): teste de presença curto no Ollama; respondeu → votação; não respondeu (ou caiu no meio) →
  regras, e avisa UMA vez por queda pelo notificador. Quando ele volta, as ofertas de origem `rules` e as sem
  tipo são reavaliadas pela votação.
- rules: só regras; nunca fala com o Ollama.
- ollama: só Ollama; se cair, guarda a oferta sem tipo (o comportamento original) e nunca usa regras.

Cada oferta grava a origem do tipo em `tg_offers.kind_source` (ollama | rules). A IA e as regras só dizem o
TIPO: preço e "mesmo produto" (chave) continuam no script (classify.py).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import vote as V
from .classify import adjust_kind, category, product_key, vote_text
from .rules import CAT2KIND, rules_kind

FALLBACK_MSG = "Ollama não respondeu; usando regras. Quando voltar, as ofertas serão reavaliadas"
STATE_FILE = "classificador.json"
REEVAL_MAX = 300            # por rodada (as mais novas primeiro); o resto fica para a próxima
KIND2CAT = {v: k for k, v in CAT2KIND.items()}


@dataclass
class Verdict:
    kind: str | None
    agree: int | None = None
    votes: dict | None = None
    source: str | None = None          # ollama | rules | None (sem tipo)
    why: str | None = None
    confidence: float | None = None


class Ollama:
    """A votação com os modelos escolhidos. `unload_fn` tira cada modelo da placa (só com o Ollama de verdade)."""

    source = "ollama"

    def __init__(self, chat: V.Chat, models, unload_fn: Callable[[str], None] | None = None):
        self.chat, self.models, self.unload_fn = chat, list(models), unload_fn

    @property
    def quorum(self) -> int:
        return V.quorum(len(self.models))

    def classify(self, texts: list[str]) -> list[Verdict]:
        if not texts:
            return []
        return [Verdict(k, a, v, "ollama")
                for k, a, v in V.vote([vote_text(t) for t in texts], self.chat, self.models, self.unload_fn)]


def rules_verdict(text: str) -> Verdict:
    kind, conf, why = rules_kind(text)
    return Verdict(kind, None, None, "rules" if kind else None, why, conf)


def ollama_backend(cfg: dict, chat: V.Chat | None = None, http=None,
                   probe: Callable[[], bool] | None = None) -> tuple[Ollama, Callable[[], bool]]:
    """A votação no endereço e com os modelos das Configurações. `chat` injetado (testes) = sem HTTP."""
    models = cfg["ollama"]["models"]
    if chat is not None:
        return Ollama(chat, models), probe or (lambda: True)
    from .. import ollama as O
    client = O.OllamaClient(cfg["ollama"]["url"], http if http is not None else O.default_client())
    return Ollama(client.chat, models, client.unload), probe or client.ping


class FallbackState:
    """Lembra se o Ollama já estava fora (para avisar só uma vez por queda). Arquivo pequeno no diretório de dados."""

    def __init__(self, path: str | Path | None = None):
        if path is None:
            from ..secrets_store import data_dir
            path = data_dir() / STATE_FILE
        self.path = Path(path)

    def _read(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write(self, data: dict) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            pass                        # sem onde gravar: no pior caso avisa de novo

    def went_down(self) -> bool:
        """Marca a queda. True se é uma queda NOVA (avisar)."""
        if self._read().get("ollama_down"):
            return False
        self._write({"ollama_down": True})
        return True

    def came_up(self) -> None:
        if self._read().get("ollama_down"):
            self._write({"ollama_down": False})

    def is_down(self) -> bool:
        return bool(self._read().get("ollama_down"))


@dataclass
class Outcome:
    fresh: list[Verdict]
    extra: list[Verdict]                # reavaliações (só quando o Ollama respondeu)
    effective: str | None               # quem classificou: ollama | rules | None (modo ollama, fora do ar)
    notices: list[str]
    error: str | None = None


def classify_round(mode: str, texts: list[str], extra: Callable[[], list[str]], ollama: Ollama,
                   probe: Callable[[], bool], state: FallbackState) -> Outcome:
    """Classifica os posts novos (`texts`) e, se o Ollama for usado, também os de `extra()` (reavaliação)."""
    def by_rules() -> list[Verdict]:
        return [rules_verdict(t) for t in texts]

    if mode == "rules":
        return Outcome(by_rules(), [], "rules", [])
    if mode == "auto" and not probe():
        return Outcome(by_rules(), [], "rules", [FALLBACK_MSG] if state.went_down() else [])
    again = extra()
    try:
        got = ollama.classify(texts + again)
    except V.OllamaDown as e:
        if mode == "auto":
            return Outcome(by_rules(), [], "rules", [FALLBACK_MSG] if state.went_down() else [])
        return Outcome([Verdict(None) for _ in texts], [], None, [], f"fora do ar ({e})"[:160])
    state.came_up()
    return Outcome(got[:len(texts)], got[len(texts):], "ollama", [])


def fields(text: str, v: Verdict, quorum: int) -> dict | None:
    """Colunas da oferta para o veredito. None = descartar (a votação disse não-tecnologia ou cupom)."""
    if v.kind in (V.NOT_TECH, V.COUPON):
        return None
    if v.source == "rules":
        cat = KIND2CAT.get(v.kind)
        return {"kind": v.kind, "kind_votes": None, "kind_agree": None, "kind_source": "rules",
                "product_key": product_key(text, cat) if cat else None}
    if v.source != "ollama":
        return {"kind": None, "kind_votes": None, "kind_agree": None, "kind_source": None, "product_key": None}
    kind = adjust_kind(v.kind, text)
    cat = category(text)
    key = product_key(text, cat) if cat and kind == CAT2KIND.get(cat) and v.agree >= quorum else None
    return {"kind": kind, "kind_votes": json.dumps(v.votes) if v.votes else None,
            "kind_agree": v.agree if kind else None, "kind_source": "ollama", "product_key": key}


def update_offer(conn, offer_id: int, text: str, v: Verdict, quorum: int) -> str | None:
    """Regrava o tipo de uma oferta já guardada. Devolve o tipo novo, ou None se ela foi descartada."""
    f = fields(text, v, quorum)
    if f is None:
        conn.execute("DELETE FROM tg_alerts_sent WHERE offer_id = ?", (offer_id,))
        conn.execute("DELETE FROM tg_offers WHERE id = ?", (offer_id,))
        return None
    conn.execute("UPDATE tg_offers SET kind = ?, kind_votes = ?, kind_agree = ?, kind_source = ?, product_key = ? "
                 "WHERE id = ?", (f["kind"], f["kind_votes"], f["kind_agree"], f["kind_source"], f["product_key"],
                                  offer_id))
    return f["kind"]


def reeval_rows(conn, limit: int = REEVAL_MAX) -> list:
    """O que o Ollama reavalia quando volta: tipo dado pelas regras, ou sem tipo."""
    return conn.execute("SELECT id, text, kind FROM tg_offers WHERE kind_source = 'rules' OR kind IS NULL "
                        "ORDER BY posted_at DESC, id DESC LIMIT ?", (limit,)).fetchall()
