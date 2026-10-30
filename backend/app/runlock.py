"""Trava da rodada: coleta das lojas e rodada dos canais nunca rodam duas ao mesmo tempo.

`flock` no arquivo `rodada.lock` do diretório de dados. Vale entre processos: o agendador interno do servidor e um
cron externo (deploy/*.sh chamam `python -m app.collect` / `python -m app.tg`, que tomam esta mesma trava). O sistema
solta a trava sozinho se o processo morrer.
"""

from __future__ import annotations

import fcntl
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator

from .secrets_store import data_dir

LOCK_NAME = "rodada.lock"
LOCK_WAIT_S = 20 * 60       # o CLI espera até 20 min (a coleta do dia não se perde por uma rodada dos canais)
POLL_S = 5.0


class RoundLock:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._fd: int | None = None
        self._mu = threading.Lock()

    def _try(self) -> bool:
        with self._mu:
            if self._fd is not None:
                return False                    # já está com esta instância
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                os.close(fd)
                return False
            self._fd = fd
            return True

    def acquire(self, wait: float = 0.0, sleep: Callable[[float], None] = time.sleep,
                clock: Callable[[], float] = time.monotonic) -> bool:
        """True se pegou. `wait` > 0: tenta de novo a cada POLL_S até o prazo."""
        deadline = clock() + wait
        while True:
            if self._try():
                return True
            left = deadline - clock()
            if left <= 0:
                return False
            sleep(min(POLL_S, left))

    def release(self) -> None:
        with self._mu:
            if self._fd is None:
                return
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            finally:
                os.close(self._fd)
                self._fd = None

    @contextmanager
    def hold(self, wait: float = 0.0) -> Iterator[bool]:
        got = self.acquire(wait)
        try:
            yield got
        finally:
            if got:
                self.release()


def round_lock(directory: str | Path | None = None) -> RoundLock:
    return RoundLock(Path(directory or data_dir()) / LOCK_NAME)
