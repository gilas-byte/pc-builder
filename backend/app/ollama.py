"""Conversa com o Ollama local (fase 4 da docs/07): presença, versão, modelos instalados, votação e download.

Tudo por httpx, no endereço das Configurações (`ollama.url`). Os testes passam um `httpx.MockTransport`; o
conftest proíbe `default_client()` (nunca rede de verdade nos testes).

Mensagem de erro nunca repete o que a biblioteca disse (pode ter o endereço interno): só o motivo em português.
O download é UM por vez, no máximo PULL_PER_HOUR por hora, e lê o progresso do stream NDJSON de /api/pull.
"""

from __future__ import annotations

import json
import math
import threading
import time
from typing import Callable, Iterator

import httpx

from . import settings as S
from .tg import vote as V

PROBE_TIMEOUT = 3.0          # teste de presença: curto (a rodada não pode travar esperando)
LIST_TIMEOUT = 10.0
CHAT_TIMEOUT = 120.0         # 1º pedido de cada modelo inclui carregar na placa
PULL_PER_HOUR = 5
HOUR = 3600


class OllamaError(RuntimeError):
    """Falha ao falar com o Ollama. A mensagem é segura para a tela (sem endereço nem detalhe interno)."""


class PullBusy(RuntimeError):
    pass


class PullLimited(RuntimeError):
    def __init__(self, wait: int):
        super().__init__(f"limite de {PULL_PER_HOUR} downloads por hora")
        self.wait = wait


def default_client() -> httpx.Client:
    return httpx.Client(timeout=CHAT_TIMEOUT, follow_redirects=False, trust_env=False)


def reason(e: BaseException) -> str:
    """Motivo em português, sem o texto da exceção (que traz o endereço)."""
    if isinstance(e, httpx.TimeoutException):
        return "o Ollama não respondeu a tempo"
    if isinstance(e, httpx.HTTPStatusError):
        return f"o Ollama respondeu com erro {e.response.status_code}"
    if isinstance(e, (ValueError, KeyError, TypeError)):
        return "o Ollama respondeu num formato inesperado"
    return "o Ollama não respondeu (está desligado ou o endereço está errado)"


class OllamaClient:
    def __init__(self, url: str, http: httpx.Client | None = None):
        self.url = url.rstrip("/")
        self.http = http if http is not None else default_client()

    def _get(self, path: str, timeout: float) -> dict:
        try:
            r = self.http.get(self.url + path, timeout=timeout)
            r.raise_for_status()
            data = r.json()
            if not isinstance(data, dict):
                raise ValueError("não é objeto")
            return data
        except (httpx.HTTPError, ValueError) as e:
            raise OllamaError(reason(e)) from None

    def version(self) -> str:
        v = self._get("/api/version", PROBE_TIMEOUT).get("version")
        if not isinstance(v, str):
            raise OllamaError(reason(ValueError()))
        return v[:40]

    def ping(self) -> bool:
        try:
            self.version()
            return True
        except OllamaError:
            return False

    def models(self) -> list[dict]:
        """Instalados: nome, tamanho (bytes), quantização, parâmetros e família."""
        out = []
        for m in self._get("/api/tags", LIST_TIMEOUT).get("models") or []:
            if not isinstance(m, dict) or not isinstance(m.get("name"), str):
                continue
            d = m.get("details") if isinstance(m.get("details"), dict) else {}
            out.append({"name": m["name"][:200], "size": m.get("size") if isinstance(m.get("size"), int) else None,
                        "quantization": str(d.get("quantization_level") or "")[:40] or None,
                        "parameters": str(d.get("parameter_size") or "")[:40] or None,
                        "family": str(d.get("family") or "")[:40] or None})
        return out

    def chat(self, model: str, system: str, user: str, schema: dict) -> str:
        """O `Chat` da votação (tg/vote.py). Queda vira V.OllamaDown (a rodada decide o que fazer)."""
        body = {"model": model, "stream": False, "format": schema, "keep_alive": "2m",
                "options": {"temperature": 0, "num_predict": 20, "num_thread": 4},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        try:
            r = self.http.post(self.url + "/api/chat", json=body, timeout=CHAT_TIMEOUT)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise V.OllamaDown(reason(e)) from None
        return r.json()["message"]["content"]     # formato ruim: ValueError/KeyError = voto perdido

    def unload(self, model: str) -> None:
        """Tira o modelo da placa (keep_alive 0): a placa fica livre para quem usa o PC (pode estar jogando)."""
        try:
            self.http.post(self.url + "/api/chat", json={"model": model, "keep_alive": 0, "messages": []},
                           timeout=30)
        except httpx.HTTPError:
            pass

    def pull(self, model: str) -> Iterator[dict]:
        """As linhas do stream NDJSON de /api/pull, uma por vez."""
        try:
            with self.http.stream("POST", self.url + "/api/pull", json={"model": model, "stream": True},
                                  timeout=httpx.Timeout(30, read=None)) as r:
                if r.status_code >= 400:
                    raise OllamaError(f"o Ollama recusou o download (erro {r.status_code})")
                for line in r.iter_lines():
                    if line.strip():
                        msg = json.loads(line)
                        if isinstance(msg, dict):
                            yield msg
        except (httpx.HTTPError, ValueError) as e:
            raise OllamaError(reason(e)) from None


def _pull_error(raw) -> str:
    """O erro que o Ollama manda no stream pode citar endereço/registro: só o motivo conhecido passa."""
    text = str(raw).lower()
    if "does not exist" in text or "not found" in text:
        return "esse modelo não existe na biblioteca do Ollama (confira o nome)"
    if "no space" in text or "disk" in text:
        return "falta espaço em disco para o modelo"
    return "o Ollama não conseguiu baixar o modelo (sem internet?)"


class PullManager:
    """Um download por vez, em segundo plano. `spawn` roda a tarefa (thread no app; os testes rodam na hora)."""

    def __init__(self, client_factory: Callable[[], OllamaClient], clock: Callable[[], float] = time.time,
                 spawn: Callable[[Callable[[], None]], None] | None = None, per_hour: int = PULL_PER_HOUR):
        self._factory = client_factory
        self._clock = clock
        self._spawn = spawn or (lambda fn: threading.Thread(target=fn, name="ollama-pull", daemon=True).start())
        self._per_hour = per_hour
        self._lock = threading.Lock()
        self._starts: list[float] = []
        self._cancel = threading.Event()
        self._state = self._blank(None, "idle")
        self.on_progress: Callable[[dict], None] | None = None

    @staticmethod
    def _blank(model, state) -> dict:
        return {"model": model, "state": state, "phase": None, "completed": 0, "total": 0, "percent": 0,
                "error": None}

    def status(self) -> dict:
        with self._lock:
            return dict(self._state)

    def start(self, model: str) -> dict:
        if not S.valid_model(model):
            raise ValueError("nome de modelo inválido (ex.: qwen2.5:3b)")
        with self._lock:
            if self._state["state"] == "running":
                raise PullBusy("já tem um download em andamento")
            now = self._clock()
            self._starts = [t for t in self._starts if now - t < HOUR]
            if len(self._starts) >= self._per_hour:
                raise PullLimited(max(1, math.ceil(self._starts[0] + HOUR - now)))
            self._starts.append(now)
            self._cancel = threading.Event()
            self._state = self._blank(model, "running")
            cancel = self._cancel
        self._spawn(lambda: self._run(model, cancel))
        return self.status()

    def cancel(self) -> bool:
        with self._lock:
            if self._state["state"] != "running":
                return False
            self._cancel.set()
            return True

    def _update(self, **kw) -> None:
        with self._lock:
            self._state.update(kw)
            snap = dict(self._state)
        if self.on_progress:
            self.on_progress(snap)

    def _run(self, model: str, cancel: threading.Event) -> None:
        layers: dict[str, tuple[int, int]] = {}
        stream = None
        try:
            stream = self._factory().pull(model)
            for msg in stream:
                if cancel.is_set():
                    break
                if "error" in msg:
                    self._update(state="error", error=_pull_error(msg["error"]))
                    return
                status = str(msg.get("status") or "")
                if msg.get("digest") and isinstance(msg.get("total"), int) and msg["total"] > 0:
                    done = msg.get("completed") if isinstance(msg.get("completed"), int) else 0
                    layers[str(msg["digest"])] = (min(done, msg["total"]), msg["total"])
                    got, total = sum(c for c, _ in layers.values()), sum(t for _, t in layers.values())
                    self._update(phase="baixando", completed=got, total=total, percent=100 * got // total)
                elif status == "success":
                    self._update(state="done", phase=None, percent=100)
                    return
                elif status.startswith("verifying"):
                    self._update(phase="conferindo")
                elif status.startswith("writing"):
                    self._update(phase="gravando")
            if cancel.is_set():
                self._update(state="canceled", phase=None)
            else:
                self._update(state="error", error="o download parou antes do fim")
        except OllamaError as e:
            self._update(state="error", error=str(e))
        except Exception:                                       # nunca derruba o servidor
            self._update(state="error", error="o download falhou")
        finally:
            if stream is not None:
                stream.close()
