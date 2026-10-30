"""Segredos do PC Builder: token do bot do Telegram e chat id. Write-only.

Moram no arquivo `secrets.env` (CHAVE=valor) no diretório de dados (`PCB_DATA_DIR`, padrão `data/` do projeto;
no Docker, o volume). Nunca no banco, nem em log, nem em mensagem de erro, nem em resposta da API: a tela só vê
`{configured, source, hint: "…1234"}`. Variável de ambiente (`PCB_TELEGRAM_TOKEN`, `PCB_TELEGRAM_CHAT_ID`) vale mais
que o arquivo, e aí o campo fica bloqueado na tela.

O arquivo: modo 0600, dono = quem roda o servidor, escrita atômica (temporário + fchmod 0600 + os.replace). Link
simbólico ou dono diferente: recusa (não lê, não grava). Permissão mais aberta que 0600: corrige e avisa no log.
"""

from __future__ import annotations

import logging
import os
import re
import stat
from pathlib import Path
from typing import Mapping

FILE_NAME = "secrets.env"
TOKEN_VAR, CHAT_VAR = "PCB_TELEGRAM_TOKEN", "PCB_TELEGRAM_CHAT_ID"
FIELDS = {"token": TOKEN_VAR, "chat_id": CHAT_VAR}
TOKEN_RX = re.compile(r"\d{6,12}:[A-Za-z0-9_-]{30,50}", re.ASCII)
CHAT_RX = re.compile(r"-?\d{1,20}|@[A-Za-z0-9_]{4,32}", re.ASCII)

log = logging.getLogger("pcbuilder.segredos")


def data_dir(environ: Mapping[str, str] | None = None) -> Path:
    """Onde ficam banco, fotos, segredos e a trava da rodada. PCB_DATA_DIR troca (Docker: o volume)."""
    environ = os.environ if environ is None else environ
    custom = environ.get("PCB_DATA_DIR", "").strip()
    return Path(custom) if custom else Path(__file__).resolve().parents[2] / "data"


class SecretsError(ValueError):
    """Mensagem para a tela. NUNCA contém o valor recusado."""


class SecretsLocked(SecretsError):
    """O campo vem de variável de ambiente: a tela não troca."""


class SecretsFileError(SecretsError):
    """O arquivo é link simbólico, de outro dono ou não é arquivo comum."""


def validate_token(value) -> str:
    v = value.strip() if isinstance(value, str) else None
    if not v or not TOKEN_RX.fullmatch(v):
        raise SecretsError("token em formato inválido: são números, dois-pontos e 30 a 50 letras/números "
                           "(copie de novo a linha que o @BotFather mandou)")
    return v


def validate_chat_id(value) -> str:
    v = value.strip() if isinstance(value, str) else None
    if not v or not CHAT_RX.fullmatch(v):
        raise SecretsError("chat id inválido: um número (pode começar com -) ou @canal")
    return v


VALIDATE = {"token": validate_token, "chat_id": validate_chat_id}


def hint(value: str | None) -> str | None:
    """Os 4 últimos caracteres, e só eles."""
    return f"…{value[-4:]}" if value else None


class SecretStore:
    def __init__(self, path: str | Path | None = None, environ: Mapping[str, str] | None = None):
        self.path = Path(path) if path else data_dir(environ) / FILE_NAME
        self._environ = environ

    @property
    def environ(self) -> Mapping[str, str]:
        return os.environ if self._environ is None else self._environ

    # ------------------------------------------------------------------ leitura

    def read_file(self) -> dict[str, str]:
        """CHAVE → valor (só as chaves conhecidas e com formato válido). SecretsFileError se o arquivo é suspeito."""
        try:
            fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            return {}
        except OSError:                          # ELOOP: é link simbólico
            if self.path.is_symlink():
                raise SecretsFileError(f"{FILE_NAME} é um link simbólico: apague e salve o token de novo") from None
            raise SecretsFileError(f"não consegui abrir o {FILE_NAME}") from None
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode):
                raise SecretsFileError(f"{FILE_NAME} não é um arquivo comum")
            if st.st_uid != os.getuid():
                raise SecretsFileError(f"{FILE_NAME} é de outro usuário: apague e salve o token de novo")
            if stat.S_IMODE(st.st_mode) & 0o077:
                os.fchmod(fd, 0o600)
                log.warning("%s estava com permissão %o; corrigi para 0600", FILE_NAME, stat.S_IMODE(st.st_mode))
            with os.fdopen(fd, "r", encoding="utf-8", closefd=False) as f:
                text = f.read(65536)
        finally:
            os.close(fd)
        out = {}
        for line in text.splitlines():
            key, sep, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if not sep or key not in (TOKEN_VAR, CHAT_VAR):
                continue
            field = "token" if key == TOKEN_VAR else "chat_id"
            try:
                out[key] = VALIDATE[field](value)
            except SecretsError:
                log.warning("%s: valor de %s com formato inválido; ignorado", FILE_NAME, key)
        return out

    def _file_or_empty(self) -> tuple[dict[str, str], str | None]:
        try:
            return self.read_file(), None
        except SecretsFileError as e:
            log.warning("%s recusado: %s", FILE_NAME, e)
            return {}, str(e)

    def get(self, field: str) -> tuple[str | None, str | None]:
        """(valor, origem "env" | "file" | None). Variável de ambiente vence o arquivo."""
        var = FIELDS[field]
        raw = self.environ.get(var, "").strip()
        if raw:
            try:
                return VALIDATE[field](raw), "env"
            except SecretsError:
                log.warning("%s com formato inválido; ignorada", var)
        value = self._file_or_empty()[0].get(var)
        return (value, "file") if value else (None, None)

    def status(self) -> dict:
        """O que a API pode mostrar: configurado, origem e os 4 últimos caracteres. Nunca o valor."""
        _, file_error = self._file_or_empty()
        token, tsrc = self.get("token")
        chat, csrc = self.get("chat_id")
        return {"configured": bool(token), "source": tsrc, "hint": hint(token),
                "chat_id": {"configured": bool(chat), "source": csrc, "hint": hint(chat)},
                "ready": bool(token and chat), "file_error": file_error}

    # ------------------------------------------------------------------ escrita

    def save(self, token: str | None = None, chat_id: str | None = None) -> None:
        """Grava os campos passados (os outros ficam). Valida tudo antes; nada é gravado se um falhar."""
        updates = {}
        for field, value in (("token", token), ("chat_id", chat_id)):
            if value is None:
                continue
            if self.environ.get(FIELDS[field], "").strip():
                raise SecretsLocked(f"{field}: definido por variável de ambiente ({FIELDS[field]}); mude lá")
            updates[FIELDS[field]] = VALIDATE[field](value)
        if not updates:
            raise SecretsError("mande o token e/ou o chat id")
        current = self.read_file()               # recusa link simbólico/outro dono antes de gravar
        self._write({**current, **updates})

    def clear(self) -> None:
        self.read_file()
        if self.path.exists():
            self.path.unlink()

    def _write(self, values: dict[str, str]) -> None:
        if self.path.is_symlink():
            raise SecretsFileError(f"{FILE_NAME} é um link simbólico: apague e salve o token de novo")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        text = "".join(f"{k}={values[k]}\n" for k in (TOKEN_VAR, CHAT_VAR) if values.get(k))
        if not text:
            self.path.unlink(missing_ok=True)
            return
        tmp = self.path.with_name(f".{FILE_NAME}.{os.getpid()}.tmp")
        tmp.unlink(missing_ok=True)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            os.fchmod(fd, 0o600)                 # vale mesmo com umask aberta
            os.write(fd, text.encode("utf-8"))
            os.fsync(fd)
        except BaseException:
            os.close(fd)
            tmp.unlink(missing_ok=True)
            raise
        os.close(fd)
        os.replace(tmp, self.path)
