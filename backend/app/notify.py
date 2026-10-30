"""Para onde vai o aviso: bot do Telegram do próprio usuário, saída padrão ou nenhum.

    Notifier.send(texto) -> Result

- `TelegramBot`: Bot API por HTTPS com httpx (só sendMessage, getUpdates e getMe). Texto simples (sem parse_mode,
  então `_`, `*` e `<` do título da oferta não quebram), dividido em partes de até 4096 (contadas em UTF-16, como o
  Telegram conta), timeout curto, 1 nova tentativa em 429 respeitando o `retry_after`. O token está na URL: nunca
  aparece em log (filtro nos loggers do httpx), em exceção (mascarado) nem no repr.
- `Stdout`: imprime. É o modo do agendador externo (cron, Hermes Agent): quem agenda entrega a saída.
- `NoneNotifier`: não manda nada.

`make_notifier(settings, secrets)` escolhe por `notify_target`; Telegram sem token ou chat id cai na saída padrão
e avisa uma vez.
"""

from __future__ import annotations

import logging
import re
import sys
import time
from dataclasses import dataclass
from typing import Callable, Protocol

API = "https://api.telegram.org"
MAX_LEN = 4096
TIMEOUT_S = 10.0
MAX_RETRY_AFTER_S = 30          # 429 pedindo mais que isso: desiste agora em vez de travar a rodada
TEST_TEXT = "PC Builder: mensagem de teste"
TOKEN_ANY = re.compile(r"\d{6,12}:[A-Za-z0-9_-]{30,50}", re.ASCII)
CHAT_TYPES = {"private": "privado", "group": "grupo", "supergroup": "supergrupo", "channel": "canal"}

log = logging.getLogger("pcbuilder.aviso")
_warned: set[str] = set()


def redact(text: str, *secrets: str | None) -> str:
    for s in secrets:
        if s:
            text = text.replace(s, "***")
    return TOKEN_ANY.sub("***", text)


class _Redact(logging.Filter):
    """O httpx loga a URL de cada pedido ("HTTP Request: POST https://api.telegram.org/bot<TOKEN>/..."): tira o token."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        clean = redact(msg)
        if clean != msg:
            record.msg, record.args = clean, None
        return True


for _name in ("httpx", "httpcore", "httpcore.connection", "httpcore.http11", "httpcore.http2"):
    logging.getLogger(_name).addFilter(_Redact())


def warn_once(key: str, msg: str) -> None:
    if key not in _warned:
        _warned.add(key)
        log.warning(msg)


def default_client():
    import httpx
    return httpx.Client(timeout=TIMEOUT_S, follow_redirects=False)


@dataclass
class Result:
    ok: bool
    error: str | None = None
    parts: int = 0


class Notifier(Protocol):
    name: str

    def send(self, text: str) -> Result: ...


class NotifyError(Exception):
    """Mensagem já tratada e sem token."""


# --------------------------------------------------------------------------- divisão em 4096

def _u16(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


def _hard_split(line: str, limit: int) -> list[str]:
    out, cur, n = [], [], 0
    for ch in line:
        w = _u16(ch)
        if n + w > limit:
            out.append("".join(cur))
            cur, n = [], 0
        cur.append(ch)
        n += w
    if cur:
        out.append("".join(cur))
    return out


def split_message(text: str, limit: int = MAX_LEN) -> list[str]:
    """Partes de até `limit` (UTF-16), cortando nas quebras de linha; linha gigante é cortada no meio."""
    if _u16(text) <= limit:
        return [text]
    parts, cur, n = [], [], 0
    for line in text.split("\n"):
        w = _u16(line)
        if w > limit:
            if cur:
                parts.append("\n".join(cur))
                cur, n = [], 0
            parts += _hard_split(line, limit)
            continue
        if cur and n + 1 + w > limit:
            parts.append("\n".join(cur))
            cur, n = [], 0
        n += w + (1 if cur else 0)
        cur.append(line)
    if cur:
        parts.append("\n".join(cur))
    return parts


# --------------------------------------------------------------------------- notificadores

class Stdout:
    name = "stdout"

    def send(self, text: str) -> Result:
        print(text)
        return Result(True, parts=1)


class NoneNotifier:
    name = "none"

    def send(self, text: str) -> Result:
        return Result(True)


def _describe(status: int, data: dict, token: str) -> str:
    desc = redact(str(data.get("description") or ""), token)[:120]
    low = desc.lower()
    if status == 401 or status == 404:
        return "o Telegram recusou o token: confira e salve o token de novo"
    if "chat not found" in low:
        return "chat não encontrado: mande /start para o bot e escolha o chat de novo"
    if status == 403:
        return "o bot não pode falar nesse chat (bloqueado ou fora do grupo): mande /start para o bot"
    if status == 409:
        return "o bot está com webhook ligado: desligue o webhook para achar o chat por aqui"
    if status == 429:
        return "o Telegram pediu para esperar (muitas mensagens): tente daqui a pouco"
    return f"o Telegram respondeu {status}" + (f": {desc}" if desc else "")


class TelegramBot:
    name = "telegram"

    def __init__(self, token: str, chat_id: str | None, client=None, sleep: Callable[[float], None] = time.sleep):
        self._token = token
        self.chat_id = chat_id
        self._client = client
        self._sleep = sleep

    def __repr__(self) -> str:
        return f"TelegramBot(token=…{self._token[-4:]})"

    def _http(self):
        if self._client is None:
            self._client = default_client()
        return self._client

    def _call(self, method: str, payload: dict) -> dict:
        url = f"{API}/bot{self._token}/{method}"
        for attempt in (0, 1):
            try:
                r = self._http().post(url, json=payload, timeout=TIMEOUT_S)
                data = r.json() if r.content else {}
            except Exception as e:      # queda, timeout, resposta que não é JSON: a mensagem pode ter a URL
                raise NotifyError(f"sem conexão com o Telegram ({type(e).__name__}: "
                                  f"{redact(str(e), self._token)[:160]})") from None
            if not isinstance(data, dict):
                data = {}
            if r.status_code == 200 and data.get("ok"):
                return data
            if r.status_code == 429 and attempt == 0:
                wait = (data.get("parameters") or {}).get("retry_after")
                if isinstance(wait, (int, float)) and 0 <= wait <= MAX_RETRY_AFTER_S:
                    self._sleep(wait)
                    continue
            raise NotifyError(_describe(r.status_code, data, self._token))
        raise NotifyError("o Telegram pediu para esperar (muitas mensagens): tente daqui a pouco")

    def send(self, text: str) -> Result:
        parts = split_message(text)
        for i, part in enumerate(parts):
            try:
                self._call("sendMessage", {"chat_id": self.chat_id, "text": part})
            except NotifyError as e:
                return Result(False, str(e), i)
        return Result(True, parts=len(parts))

    def get_me(self) -> dict:
        res = self._call("getMe", {}).get("result")
        return res if isinstance(res, dict) else {}

    def get_chats(self) -> list[dict]:
        res = self._call("getUpdates", {"limit": 100, "timeout": 0}).get("result")
        return chats_from_updates(res if isinstance(res, list) else [])


def chats_from_updates(updates: list) -> list[dict]:
    """Conversas que falaram com o bot, sem repetir: [{id, tipo, nome}] (id em texto)."""
    out, seen = [], set()
    for u in updates:
        if not isinstance(u, dict):
            continue
        for kind in ("message", "edited_message", "channel_post", "edited_channel_post", "my_chat_member"):
            chat = (u.get(kind) or {}).get("chat") if isinstance(u.get(kind), dict) else None
            if not isinstance(chat, dict) or not isinstance(chat.get("id"), int):
                continue
            cid = str(chat["id"])
            if cid in seen:
                continue
            seen.add(cid)
            name = (chat.get("title") or " ".join(x for x in (chat.get("first_name"), chat.get("last_name")) if x)
                    or (f"@{chat['username']}" if chat.get("username") else cid))
            out.append({"id": cid, "tipo": CHAT_TYPES.get(chat.get("type"), "outro"), "nome": str(name)[:80]})
    return out


# --------------------------------------------------------------------------- escolha e entrega

def make_notifier(settings: dict, secrets, client=None, sleep: Callable[[float], None] = time.sleep) -> Notifier:
    target = settings.get("notify_target", "stdout")
    if target == "none":
        return NoneNotifier()
    if target == "telegram":
        token, _ = secrets.get("token")
        chat, _ = secrets.get("chat_id")
        if token and chat:
            return TelegramBot(token, chat, client=client, sleep=sleep)
        warn_once("telegram-sem-config", "aviso pelo Telegram escolhido, mas falta o token ou o chat id: "
                                         "o aviso vai para a saída padrão")
    return Stdout()


def from_config(db_path, client=None) -> Notifier:
    """O notificador escolhido nas Configurações (banco + PCB_*) com os segredos do secrets.env."""
    from . import settings as S
    from .db import database as db
    from .secrets_store import SecretStore
    conn = db.init_db(db_path)
    try:
        cfg = S.values(conn)
    finally:
        conn.close()
    return make_notifier(cfg, SecretStore(), client=client)


def deliver(notifier: Notifier, text: str) -> Result:
    """Manda o aviso. Se o Telegram falhar, o texto sai na saída padrão (um cron, se houver, ainda entrega)."""
    if not text:
        return Result(True)
    res = notifier.send(text)
    if not res.ok and not isinstance(notifier, Stdout):
        print(text)
        print(f"aviso: não consegui mandar pelo {notifier.name}: {res.error}", file=sys.stderr)
    return res
