"""Configurações do PC Builder. Os padrões vivem AQUI e só aqui.

Três camadas, a de baixo perde: padrão (este arquivo) < banco (tabela `settings`, valor em JSON) < variável de
ambiente `PCB_*`. Campo definido por variável fica bloqueado na tela. Nada aqui é segredo: o token do bot mora no
`secrets.env` (app/secrets_store.py) e nunca passa por esta tabela.

Tudo que vem da tela passa por `validate` no servidor. Valor ruim no banco (editado à mão, versão velha) cai no
padrão em vez de derrubar o app; variável de ambiente inválida é ignorada e aparece como `env_error`.

    uv run python -m app.settings get game_mode     # valor efetivo (bool sai 1/0; o resto, JSON)
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from .collect.stores import STORES as COLLECTORS
from .compat import CURRENT_PC
from .tg.vote import MODELS as OLLAMA_MODELS, OLLAMA as OLLAMA_URL

# Os 9 canais públicos que vêm prontos (entram uma vez, no 1º init do banco; ver db/seed.py).
DEFAULT_CHANNELS = ("OPromoFacil", "grupo_promocoes", "EconomizandocomJP", "descontoemgames", "escolhasegura",
                    "especialistaemti", "ToptechPROMO", "lipeofertas", "gpcrpromo")
MAX_CHANNELS = 50

KNOWN_STORES = tuple(COLLECTORS)                  # as lojas que a coleta sabe ler (collect/stores.py)
LANGUAGES = ("pt-BR", "en")
NOTIFY_TARGETS = ("none", "telegram", "stdout")
SOCKETS = ("AM4", "AM5", "LGA1151", "LGA1200", "LGA1700", "LGA1851")
MEMORY_TYPES = ("DDR3", "DDR4", "DDR5")
FORM_FACTORS = ("E-ATX", "ATX", "mATX", "ITX")
PC_FIELDS = ("socket", "memory_type", "motherboard", "cpu", "gpu", "ram_gb", "form_factor")
PC_TEXT = ("motherboard", "cpu", "gpu")
COLLECT_MIN, COLLECT_MAX = 15, 1440
PRICE_MAX = 1_000_000                             # reais
RAM_MAX = 1024
TEXT_MAX = 80
MIN_MODELS, MAX_MODELS = 1, 3
MODEL_MAX = 100
CLASSIFIERS = ("auto", "rules", "ollama")         # auto = Ollama se responder, senão regras

TEXT_RX = re.compile(r"[\w .,+()#/®™-]{1,80}")    # nome de peça: letras, números e pontuação de modelo
# nome de modelo do Ollama: "qwen2.5:3b", "library/llama3.2", "hf.co/dono/repo:Q4_K_M". Cada parte do caminho
# começa por letra/número (sem "..", sem "//", sem "/" no começo); a etiqueta depois do ":" é opcional.
MODEL_RX = re.compile(r"[a-z0-9][a-z0-9._-]*(?:/[a-z0-9][a-z0-9._-]*)*(?::[A-Za-z0-9._-]+)?", re.ASCII)
# endereço de metadados de nuvem: nunca (o Ollama recebe os títulos e devolve o que quiser)
METADATA_HOSTS = ("metadata", "metadata.google.internal", "metadata.goog", "instance-data")

DEFAULTS: dict[str, Any] = {
    "language": "pt-BR",
    "stores": {s: True for s in KNOWN_STORES},
    "collect_every_minutes": 1440,                # 1 vez por dia, como o agendador externo de hoje
    "price_range": {"min": 0, "max": PRICE_MAX},  # sem filtro
    "game_mode": False,
    "current_pc": {k: CURRENT_PC[k] for k in PC_FIELDS},
    "notify_target": "stdout",                    # hoje: a saída do script vira o aviso
    "ollama": {"url": OLLAMA_URL, "models": list(OLLAMA_MODELS)},
    "classifier": "auto",                         # auto | rules | ollama
    "scheduler_enabled": False,                   # agendador interno; desligado = quem agenda é o cron
}
KEYS = tuple(DEFAULTS)

# chave → variáveis que a sobrepõem
ENV_VARS = {
    "language": ("PCB_LANGUAGE",),
    "stores": ("PCB_STORES",),                    # lista das LIGADAS: "kabum,amazon"
    "collect_every_minutes": ("PCB_COLLECT_EVERY_MINUTES",),
    "price_range": ("PCB_PRICE_MIN", "PCB_PRICE_MAX"),
    "game_mode": ("PCB_GAME_MODE",),              # 1/0 (o mesmo nome que deploy/canais-telegram.sh já lia)
    "current_pc": ("PCB_CURRENT_PC",),            # JSON: '{"socket": "AM5", "memory_type": "DDR5"}'
    "notify_target": ("PCB_NOTIFY_TARGET",),
    "ollama": ("PCB_OLLAMA_URL", "PCB_OLLAMA_MODELS"),   # modelos separados por vírgula
    "classifier": ("PCB_CLASSIFIER",),
    "scheduler_enabled": ("PCB_SCHEDULER",),      # 1/0
}
BOOL_KEYS = {"game_mode": "modo jogo", "scheduler_enabled": "agendador interno"}


class SettingsError(ValueError):
    """fields: chave → mensagem para a tela."""

    def __init__(self, fields: dict[str, str]):
        super().__init__("; ".join(f"{k}: {v}" for k, v in fields.items()))
        self.fields = fields


# --------------------------------------------------------------------------- validação

def _int(v, lo: int, hi: int, what: str) -> int:
    if isinstance(v, bool) or not isinstance(v, int):
        raise ValueError(f"{what} tem que ser um número inteiro")
    if not lo <= v <= hi:
        raise ValueError(f"{what} tem que ficar entre {lo} e {hi}")
    return v


def _choice(v, options: tuple, what: str) -> str:
    if not isinstance(v, str) or v not in options:
        raise ValueError(f"{what}: escolha um de {', '.join(options)}")
    return v


def _obj(v, what: str) -> dict:
    if not isinstance(v, dict):
        raise ValueError(f"{what} tem que ser um objeto")
    return v


def _stores(v, current: dict) -> dict:
    v = _obj(v, "lojas")
    unknown = set(v) - set(KNOWN_STORES)
    if unknown:
        raise ValueError(f"loja desconhecida: {', '.join(sorted(map(str, unknown)))}")
    if any(not isinstance(x, bool) for x in v.values()):
        raise ValueError("cada loja é ligada (true) ou desligada (false)")
    out = {s: v.get(s, current.get(s, True)) for s in KNOWN_STORES}
    if not any(out.values()):
        raise ValueError("deixe pelo menos uma loja ligada")
    return out


def _price_range(v, current: dict) -> dict:
    v = _obj(v, "faixa de preço")
    if set(v) != {"min", "max"}:
        raise ValueError("faixa de preço precisa de min e max (e só deles)")
    lo = _int(v["min"], 0, PRICE_MAX, "o mínimo")
    hi = _int(v["max"], 0, PRICE_MAX, "o máximo")
    if lo > hi:
        raise ValueError("o mínimo não pode ser maior que o máximo")
    return {"min": lo, "max": hi}


def _url(v) -> str:
    if not isinstance(v, str) or len(v) > 200:
        raise ValueError("endereço do Ollama: texto de até 200 caracteres")
    try:
        u = urlsplit(v)
        u.port                                    # porta não numérica / fora de 0-65535 → ValueError
    except ValueError:
        raise ValueError("endereço do Ollama inválido") from None
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ValueError("endereço do Ollama tem que começar com http:// ou https:// e ter um host")
    if u.username is not None or u.password is not None or "@" in u.netloc:
        raise ValueError("endereço do Ollama não pode ter usuário/senha")
    if u.query or u.fragment or u.path not in ("", "/"):
        raise ValueError("endereço do Ollama: só esquema, host e porta (ex.: http://127.0.0.1:11434)")
    if not re.fullmatch(r"[A-Za-z0-9.\-\[\]:]+", u.netloc):
        raise ValueError("endereço do Ollama com caractere estranho")
    host = u.hostname.lower().rstrip(".")
    ip = _ip(host)
    if host in METADATA_HOSTS or (ip is not None and ip.is_link_local):
        raise ValueError("endereço do Ollama não pode ser link-local nem de metadados (169.254.x.x, fe80::)")
    return f"{u.scheme}://{u.netloc}"


def _ip(host: str):
    """IP do host (IPv4 dentro de IPv6, ::ffff:a.b.c.d, vira o IPv4), ou None se é nome."""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return None
    return (ip.ipv4_mapped or ip) if ip.version == 6 else ip


def ollama_warning(url: str) -> str | None:
    """Aviso para a tela quando o Ollama não está nesta máquina (os títulos das ofertas vão pela rede)."""
    host = (urlsplit(url).hostname or "").lower()
    ip = _ip(host)
    if host == "localhost" or (ip is not None and ip.is_loopback):
        return None
    return "o Ollama está em outra máquina: os títulos das ofertas vão pela rede até ela (use só na sua rede)"


def _ollama(v, current: dict) -> dict:
    v = _obj(v, "IA local")
    unknown = set(v) - {"url", "models"}
    if unknown:
        raise ValueError(f"campo desconhecido: {', '.join(sorted(map(str, unknown)))}")
    url = _url(v.get("url", current.get("url")))
    models = v.get("models", current.get("models"))
    if not isinstance(models, list) or not MIN_MODELS <= len(models) <= MAX_MODELS:
        raise ValueError(f"modelos: escolha de {MIN_MODELS} a {MAX_MODELS}")
    for m in models:
        if not valid_model(m):
            raise ValueError("nome de modelo inválido (ex.: qwen2.5:3b; minúsculas, números, . _ - / e :etiqueta)")
    if len(set(models)) != len(models):
        raise ValueError("modelo repetido")
    return {"url": url, "models": list(models)}


def valid_model(m) -> bool:
    return isinstance(m, str) and len(m) <= MODEL_MAX and ".." not in m and MODEL_RX.fullmatch(m) is not None


def _current_pc(v, current: dict) -> dict:
    v = _obj(v, "PC atual")
    unknown = set(v) - set(PC_FIELDS)
    if unknown:
        raise ValueError(f"campo desconhecido no PC: {', '.join(sorted(map(str, unknown)))}")
    out = {**current, **v}
    _choice(out["socket"], SOCKETS, "socket")
    _choice(out["memory_type"], MEMORY_TYPES, "tipo de memória")
    _choice(out["form_factor"], FORM_FACTORS, "formato da placa")
    _int(out["ram_gb"], 1, RAM_MAX, "a RAM (GB)")
    for k in PC_TEXT:
        t = out[k]
        if not isinstance(t, str) or not TEXT_RX.fullmatch(t) or not t.strip():
            raise ValueError(f"{k}: texto de 1 a {TEXT_MAX} caracteres (letras, números e . , + - ( ) # /)")
        out[k] = t.strip()
    return {k: out[k] for k in PC_FIELDS}


def validate(key: str, value, current=None):
    """Valor limpo, ou ValueError com a mensagem do campo. `current` = valor atual (para atualização parcial)."""
    current = DEFAULTS[key] if current is None else current
    if key == "language":
        return _choice(value, LANGUAGES, "idioma")
    if key == "stores":
        return _stores(value, current)
    if key == "collect_every_minutes":
        return _int(value, COLLECT_MIN, COLLECT_MAX, "a frequência (minutos)")
    if key == "price_range":
        return _price_range(value, current)
    if key in BOOL_KEYS:
        if not isinstance(value, bool):
            raise ValueError(f"{BOOL_KEYS[key]} é ligado (true) ou desligado (false)")
        return value
    if key == "current_pc":
        return _current_pc(value, current)
    if key == "notify_target":
        return _choice(value, NOTIFY_TARGETS, "destino do aviso")
    if key == "ollama":
        return _ollama(value, current)
    if key == "classifier":
        return _choice(value, CLASSIFIERS, "classificador")
    raise ValueError("configuração desconhecida")


# --------------------------------------------------------------------------- leitura (padrão < banco < env)

def _from_env(key: str, base, environ: Mapping[str, str]):
    """Valor da variável (já validado) ou None se nenhuma está definida. ValueError se a variável é inválida."""
    got = {v: environ[v].strip() for v in ENV_VARS[key] if environ.get(v, "").strip()}
    if not got:
        return None, []
    names = list(got)
    if key == "stores":
        on = {s.strip() for s in got["PCB_STORES"].split(",") if s.strip()}
        if on - set(KNOWN_STORES):
            raise ValueError(f"PCB_STORES: loja desconhecida ({', '.join(sorted(on - set(KNOWN_STORES)))})")
        return validate(key, {s: s in on for s in KNOWN_STORES}), names
    if key == "collect_every_minutes":
        raw = got["PCB_COLLECT_EVERY_MINUTES"]
        if not raw.isdigit():
            raise ValueError("PCB_COLLECT_EVERY_MINUTES: número inteiro")
        return validate(key, int(raw)), names
    if key == "price_range":
        out = dict(base)
        for var, field in (("PCB_PRICE_MIN", "min"), ("PCB_PRICE_MAX", "max")):
            if var in got:
                if not got[var].isdigit():
                    raise ValueError(f"{var}: número inteiro (reais)")
                out[field] = int(got[var])
        return validate(key, out), names
    if key in BOOL_KEYS:
        var = ENV_VARS[key][0]
        raw = got[var].lower()
        if raw not in ("1", "0", "true", "false"):
            raise ValueError(f"{var}: 1 ou 0")
        return raw in ("1", "true"), names
    if key == "current_pc":
        try:
            raw = json.loads(got["PCB_CURRENT_PC"])
        except json.JSONDecodeError:
            raise ValueError("PCB_CURRENT_PC: JSON inválido") from None
        return validate(key, raw, base), names
    if key == "ollama":
        patch = {}
        if "PCB_OLLAMA_URL" in got:
            patch["url"] = got["PCB_OLLAMA_URL"]
        if "PCB_OLLAMA_MODELS" in got:
            patch["models"] = [m.strip() for m in got["PCB_OLLAMA_MODELS"].split(",") if m.strip()]
        return validate(key, patch, base), names
    return validate(key, got[ENV_VARS[key][0]]), names


def _db_values(conn: sqlite3.Connection) -> dict:
    marks = ",".join("?" * len(KEYS))
    return {r["key"]: r["value"] for r in conn.execute(f"SELECT key, value FROM settings WHERE key IN ({marks})", KEYS)}


def effective(conn: sqlite3.Connection | None, environ: Mapping[str, str] | None = None) -> dict[str, dict]:
    """chave → {"value", "source" (default|banco|env), "env" (variáveis aplicadas), "locked", ["env_error"]}.
    conn None = ainda não há banco (só padrão e env)."""
    environ = os.environ if environ is None else environ
    saved = _db_values(conn) if conn is not None else {}
    out = {}
    for key in KEYS:
        value, source = DEFAULTS[key], "default"
        if key in saved:
            try:
                value, source = validate(key, json.loads(saved[key])), "banco"
            except (ValueError, TypeError):      # valor velho/corrompido no banco: vale o padrão
                pass
        item = {"value": value, "source": source, "env": [], "locked": False}
        try:
            env_value, names = _from_env(key, value, environ)
        except ValueError as e:
            msg = str(e)
            names = [v for v in ENV_VARS[key] if environ.get(v, "").strip()]
            item["env_error"] = msg if msg.startswith("PCB_") else f"{', '.join(names)}: {msg}"
        else:
            if names:
                item.update(value=env_value, source="env", env=names, locked=True)
        out[key] = item
    return out


def values(conn: sqlite3.Connection | None, environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    return {k: v["value"] for k, v in effective(conn, environ).items()}


def get(conn: sqlite3.Connection, key: str, environ: Mapping[str, str] | None = None):
    return effective(conn, environ)[key]["value"]


# --------------------------------------------------------------------------- escrita

def save(conn: sqlite3.Connection, patch, environ: Mapping[str, str] | None = None) -> dict[str, dict]:
    """Grava uma atualização parcial. Tudo ou nada: um campo ruim e nenhum é gravado (SettingsError)."""
    if not isinstance(patch, dict) or not patch:
        raise SettingsError({"_": "mande um objeto JSON com pelo menos uma configuração"})
    eff = effective(conn, environ)
    errors, clean = {}, {}
    for key, value in patch.items():
        if key not in DEFAULTS:
            errors[str(key)[:60]] = "configuração desconhecida"
            continue
        if eff[key]["locked"]:
            errors[key] = f"definido por variável de ambiente ({', '.join(eff[key]['env'])}); mude lá"
            continue
        current = eff[key]["value"] if eff[key]["source"] != "env" else DEFAULTS[key]
        try:
            clean[key] = validate(key, value, current)
        except ValueError as e:
            errors[key] = str(e)
    if errors:
        raise SettingsError(errors)
    now = datetime.now().replace(microsecond=0).isoformat()
    with conn:
        for key, value in clean.items():
            conn.execute("INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?) "
                         "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                         (key, json.dumps(value, ensure_ascii=False), now))
    return effective(conn, environ)


def reset(conn: sqlite3.Connection, key: str) -> None:
    """Volta ao padrão (apaga do banco). Se houver variável de ambiente, ela continua valendo."""
    if key not in DEFAULTS:
        raise KeyError(key)
    with conn:
        conn.execute("DELETE FROM settings WHERE key = ?", (key,))


def apply_stores(conn: sqlite3.Connection, enabled: dict[str, bool]) -> None:
    """Espelha a configuração `stores` em `stores.active`, que é o que as consultas de preço/promoção já usam.
    Só escreve se estiver diferente (leitura comum não abre transação de escrita)."""
    rows = conn.execute(f"SELECT slug, active FROM stores WHERE slug IN ({','.join('?' * len(KNOWN_STORES))})",
                        KNOWN_STORES).fetchall()
    wrong = [(int(enabled.get(r["slug"], True)), r["slug"]) for r in rows
             if bool(r["active"]) != bool(enabled.get(r["slug"], True))]
    if wrong:
        with conn:
            conn.executemany("UPDATE stores SET active = ? WHERE slug = ?", wrong)


def options() -> dict:
    """Listas controladas e limites, para a tela montar os campos."""
    return {"languages": list(LANGUAGES), "stores": list(KNOWN_STORES), "notify_targets": list(NOTIFY_TARGETS),
            "sockets": list(SOCKETS), "memory_types": list(MEMORY_TYPES), "form_factors": list(FORM_FACTORS),
            "collect_every_minutes": {"min": COLLECT_MIN, "max": COLLECT_MAX}, "price_max": PRICE_MAX,
            "ram_max": RAM_MAX, "text_max": TEXT_MAX, "min_models": MIN_MODELS, "max_models": MAX_MODELS,
            "model_max": MODEL_MAX, "classifiers": list(CLASSIFIERS), "max_channels": MAX_CHANNELS}


# --------------------------------------------------------------------------- CLI (para os scripts de deploy)

def main(argv: list[str] | None = None, db_path: str | Path | None = None) -> int:
    from .db import database as db
    ap = argparse.ArgumentParser(prog="python -m app.settings")
    ap.add_argument("cmd", choices=["get"])
    ap.add_argument("key")
    args = ap.parse_args(argv)
    if args.key not in DEFAULTS:
        print(f"configuração desconhecida: {args.key}", file=sys.stderr)
        return 2
    conn = db.init_db(db_path or db.DEFAULT_DB)
    try:
        v = get(conn, args.key)
    finally:
        conn.close()
    print(int(v) if isinstance(v, bool) else json.dumps(v, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
