"""Limite de taxa simples, em memória, para as rotas que falam com o Telegram ou disparam rodada."""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from typing import Callable


class RateLimit:
    """No máximo 1 a cada `gap_s` segundos e `per_hour` por hora."""

    def __init__(self, gap_s: float, per_hour: int, clock: Callable[[], float] = time.time):
        self.gap_s, self.per_hour, self.clock = gap_s, per_hour, clock
        self._hits: deque[float] = deque()
        self._mu = threading.Lock()

    def check(self) -> int | None:
        """None = pode (e conta). Senão, quantos segundos esperar (para o Retry-After)."""
        with self._mu:
            now = self.clock()
            while self._hits and now - self._hits[0] >= 3600:
                self._hits.popleft()
            waits = []
            if self._hits and now - self._hits[-1] < self.gap_s:
                waits.append(self.gap_s - (now - self._hits[-1]))
            if len(self._hits) >= self.per_hour:
                waits.append(3600 - (now - self._hits[0]))
            if waits:
                return max(1, math.ceil(max(waits)))
            self._hits.append(now)
            return None
