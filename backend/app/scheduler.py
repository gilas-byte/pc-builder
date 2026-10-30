"""Agendador interno (fase 3 da docs/07): roda a coleta das lojas e a rodada dos canais sem cron externo.

Uma thread no processo do servidor. Fica parada (só olha a configuração a cada 30 s) até ligar: `scheduler_enabled`
na tela ou `PCB_SCHEDULER=1`. Quem já usa cron externo (ou o Hermes Agent) deixa desligado, senão roda em dobro.

- A cada `collect_every_minutes`: coleta das lojas, depois a rodada dos canais ativos. Os avisos saem pelo
  notificador escolhido (Telegram, saída padrão ou nenhum).
- Trava de arquivo (`runlock`): nunca duas rodadas juntas, nem com um cron externo. Ocupada: tenta em 5 min.
- Erro numa etapa não para a outra nem o servidor; vira aviso pelo notificador, no máximo 1 por hora. Depois de
  erro, tenta de novo em 15 min, 30, 60... (nunca mais que o intervalo normal).
- Modo jogo (`game_mode` / PCB_GAME_MODE): com jogo aberto (PCB_GAME_PATTERN, procurado em /proc/*/cmdline), pula
  sem avisar e olha de novo em 10 min. No Docker o /proc é o do contêiner: o modo jogo fica indisponível.
- Relógio, trava, etapas, notificador e detecção de jogo são injetáveis (os testes não esperam de verdade).
- A hora da última rodada fica em `agendador.json` no diretório de dados: reiniciar o servidor não repete a rodada.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from .notify import NoneNotifier, Notifier, Stdout, redact
from .runlock import RoundLock

START_DELAY_S = 60          # 1ª rodada 1 min depois de ligar (o servidor termina de subir antes)
BUSY_RETRY_S = 5 * 60
GAME_RETRY_S = 10 * 60
RETRY_BASE_S = 15 * 60
ERROR_NOTICE_GAP_S = 3600
POLL_S = 30.0
RUN_NOW_GAP_S = 60          # "Rodar agora": 1 por minuto, 10 por hora
RUN_NOW_PER_HOUR = 10
GAME_PATTERN = r"reaper SteamLaunch|gamescope"   # o mesmo padrão do deploy/canais-telegram.sh

Step = Callable[[Notifier], object]
log = logging.getLogger("pcbuilder.agendador")


def game_running(pattern: str | None = None, proc_root: str | Path = "/proc") -> bool:
    """Algum processo com a linha de comando batendo no padrão (como `pgrep -f`), lendo /proc sem subprocess."""
    pattern = pattern or os.environ.get("PCB_GAME_PATTERN", "").strip() or GAME_PATTERN
    try:
        rx = re.compile(pattern)
    except re.error:
        rx = re.compile(re.escape(pattern))
    try:
        entries = list(Path(proc_root).iterdir())
    except OSError:
        return False
    me = str(os.getpid())
    for d in entries:
        if not d.name.isdigit() or d.name == me:
            continue
        try:
            raw = (d / "cmdline").read_bytes()
        except OSError:                      # processo acabou no meio, ou sem permissão
            continue
        if raw and rx.search(raw.replace(b"\0", b" ").decode("utf-8", "replace").strip()):
            return True
    return False


def in_docker(environ=None, marker: str | Path = "/.dockerenv") -> bool:
    environ = os.environ if environ is None else environ
    return environ.get("PCB_IN_DOCKER", "").strip() in ("1", "true") or Path(marker).exists()


def _iso(t: float | None) -> str | None:
    return datetime.fromtimestamp(t).replace(microsecond=0).isoformat() if t else None


def _spawn_thread(fn: Callable[[], None]) -> None:
    threading.Thread(target=fn, name="pcb-rodada-agora", daemon=True).start()


class Scheduler:
    def __init__(self, *, settings: Callable[[], dict], steps: dict[str, Step], notifier: Callable[[], Notifier],
                 lock: RoundLock, clock: Callable[[], float] = time.time,
                 game_running: Callable[[], bool] = game_running,
                 game_available: bool | Callable[[], bool] = lambda: not in_docker(),
                 state_path: str | Path | None = None, spawn: Callable[[Callable[[], None]], None] = _spawn_thread,
                 poll: float = POLL_S):
        self._settings = settings
        self.steps = steps
        self._notifier = notifier
        self.lock = lock
        self.clock = clock
        self._game_running = game_running
        self._game_available = game_available if callable(game_available) else (lambda: game_available)
        self.state_path = Path(state_path) if state_path else None
        self._spawn = spawn
        self.poll = poll
        self._mu = threading.Lock()
        self._stop = threading.Event()
        self._wait = self._stop.wait
        self._thread: threading.Thread | None = None
        self._running = False
        self._next_run: float | None = None
        self._interval_used: int | None = None
        self._failures = 0
        self._last_error_notice: float | None = None
        self.skipped: str | None = None
        self.last_run: float | None = None
        self.last_ok: bool | None = None
        self.last_error: str | None = None
        self._anchor: float | None = clock()     # desde quando está ligado (subida do servidor ou o clique na tela)
        self._load()

    # ------------------------------------------------------------------ estado salvo

    def _load(self) -> None:
        if not self.state_path:
            return
        try:
            s = json.loads(self.state_path.read_text(encoding="utf-8"))
            self.last_run = float(s["last_run"]) if s.get("last_run") else None
            self.last_ok = s.get("last_ok")
            self.last_error = s.get("last_error")
        except (OSError, ValueError, TypeError, KeyError):
            pass

    def _save(self) -> None:
        if not self.state_path:
            return
        try:
            tmp = self.state_path.with_name(self.state_path.name + ".tmp")
            tmp.write_text(json.dumps({"last_run": self.last_run, "last_ok": self.last_ok,
                                       "last_error": self.last_error}), encoding="utf-8")
            os.replace(tmp, self.state_path)
        except OSError as e:
            log.warning("agendador: não consegui guardar o estado (%s)", type(e).__name__)

    # ------------------------------------------------------------------ decisão

    def _first_run(self, now: float, interval: float) -> float:
        due = self.last_run + interval if self.last_run else now
        return max(due, (self._anchor if self._anchor is not None else now) + START_DELAY_S)

    def tick(self) -> str:
        """Um passo do laço. Devolve o que aconteceu: desligado, esperando, jogo, ocupado, rodou ou falhou."""
        cfg = self._settings()
        now = self.clock()
        if not cfg.get("scheduler_enabled"):
            self._next_run, self.skipped, self._anchor = None, None, None
            return "desligado"
        if self._anchor is None:
            self._anchor = now
        interval = int(cfg["collect_every_minutes"]) * 60
        if self._next_run is None or interval != self._interval_used:
            self._next_run, self._interval_used = self._first_run(now, interval), interval
        if now < self._next_run:
            return "esperando"
        if cfg.get("game_mode") and self._game_available() and self._game_running():
            self._next_run, self.skipped = now + GAME_RETRY_S, "jogo"
            return "jogo"
        if not self._claim():
            self._next_run, self.skipped = now + BUSY_RETRY_S, "ocupado"
            return "ocupado"
        self.skipped = None
        ok = self._run_claimed()
        wait = interval if ok else min(interval, RETRY_BASE_S * 2 ** (self._failures - 1))
        self._next_run = self.clock() + wait
        return "rodou" if ok else "falhou"

    def _claim(self) -> bool:
        with self._mu:
            if self._running or not self.lock.acquire():
                return False
            self._running = True
            return True

    def _run_claimed(self) -> bool:
        """Roda as etapas com a trava já tomada. Nunca levanta exceção; sempre solta a trava."""
        started, errors = self.clock(), {}
        try:
            try:
                notifier = self._notifier()
            except Exception as e:
                errors["aviso"] = f"{type(e).__name__}: {redact(str(e))}"[:200]
                notifier = Stdout()
            for name, step in self.steps.items():
                try:
                    step(notifier)
                except Exception as e:           # uma etapa quebrada não impede a outra
                    errors[name] = f"{type(e).__name__}: {redact(str(e))}"[:200]
                    log.warning("agendador: etapa %s falhou: %s", name, errors[name])
            self.last_run, self.last_ok = started, not errors
            self.last_error = "; ".join(f"{k}: {v}" for k, v in errors.items()) or None
            self._failures = self._failures + 1 if errors else 0
            self._save()
            if errors:
                self._notify_error(notifier)
            return not errors
        finally:
            with self._mu:
                self._running = False
            self.lock.release()

    def _notify_error(self, notifier: Notifier) -> None:
        now = self.clock()
        if self._last_error_notice is not None and now - self._last_error_notice < ERROR_NOTICE_GAP_S:
            return
        self._last_error_notice = now
        if isinstance(notifier, NoneNotifier):
            return
        try:
            notifier.send(f"🧯 PC Builder (agendador): a rodada teve erro. {self.last_error}")
        except Exception as e:
            log.warning("agendador: o aviso de erro também falhou (%s)", type(e).__name__)

    def run_now(self) -> bool:
        """Uma rodada agora (mesmo com o agendador desligado), em segundo plano. False se outra está rodando."""
        if not self._claim():
            return False

        def go():
            self._run_claimed()
            self._next_run = None                # recalcula a próxima a partir desta
        self._spawn(go)
        return True

    # ------------------------------------------------------------------ laço

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as e:               # configuração ilegível etc.: tenta no próximo passo
                log.warning("agendador: passo falhou (%s: %s)", type(e).__name__, redact(str(e))[:160])
            self._wait(self.poll)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="pcb-agendador", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Parada limpa: acorda o laço e espera a thread. Uma rodada no meio termina sozinha (thread daemon)."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout)

    # ------------------------------------------------------------------ tela

    def status(self) -> dict:
        try:
            cfg = self._settings()
        except Exception:
            cfg = {}
        enabled = bool(cfg.get("scheduler_enabled"))
        interval = int(cfg.get("collect_every_minutes") or 0)
        nxt = None
        if enabled and interval:
            nxt = self._next_run if (self._next_run and self._interval_used == interval * 60) \
                else self._first_run(self.clock(), interval * 60)
        return {"enabled": enabled, "running": self._running, "interval_minutes": interval,
                "last_run_at": _iso(self.last_run), "last_ok": self.last_ok, "last_error": self.last_error,
                "next_run_at": _iso(nxt), "skipped": self.skipped if enabled else None,
                "game_mode": bool(cfg.get("game_mode")), "game_mode_available": self._game_available()}


def default_steps(db_path) -> dict[str, Step]:
    """As etapas de verdade: as mesmas do cron (`--notify`), com a trava já tomada pelo agendador."""
    from .collect import run as collect_run
    from .tg import run as tg_run
    return {"coleta": lambda n: collect_run.main(["--notify"], db_path=db_path, notifier=n, locked=True),
            "canais": lambda n: tg_run.main(["--notify"], db_path=db_path, notifier=n, locked=True)}
