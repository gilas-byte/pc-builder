#!/usr/bin/env python3
"""Verificador de higiene pública: falha se algum arquivo que iria para o repositório tem dado pessoal ou segredo.

Uso: python3 tools/check_public.py [pasta]   (padrão: a raiz do repositório)

Quais arquivos: com git, os rastreados + os novos não ignorados (`git ls-files -co --exclude-standard`,
ou seja, o que um `git add -A` levaria). Sem git, a árvore inteira, menos .git, node_modules, .venv etc.

Regras: caminho de home (/home/<alguém>, /Users/<alguém>), token de bot do Telegram, chat id longo em contexto
de chat/telegram, e-mail pessoal (exemplos e noreply do GitHub passam), IP privado/CGNAT (passa na linha com
o marcador `public-ok`), arquivo .db/.sqlite/.env/secrets*, imagem em pasta tg_img, e os termos do arquivo
OPCIONAL `.public-denylist` (fora do git; uma linha por termo, sem diferenciar maiúscula; `re:` = regex;
`#` = comentário). O repositório não traz essa lista, para não carregar nomes.

Só biblioteca padrão. Saída 0 = limpo, 1 = achados (listados como arquivo:linha).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

DENYLIST_NAME = ".public-denylist"
MARKER = "public-ok"   # libera IP e e-mail de exemplo na mesma linha (nunca caminho de home nem token)
SKIP_DIRS = {".git", "node_modules", ".venv", "__pycache__", ".pytest_cache", "dist"}

HOME_RE = re.compile(r"/(?:home|Users)/[A-Za-z0-9._-]+")
TOKEN_RE = re.compile(r"(?<!\d)\d{8,10}:[A-Za-z0-9_-]{30,}")
CHAT_ID_RE = re.compile(r"(?i)(?:chat|telegram)[\w ]{0,12}?[\s:=\"']{1,4}-?\d{8,}")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})\b")
EMAIL_OK_DOMAINS = ("example.com", "example.org", "example.net", "noreply.github.com")   # e subdomínios
EMAIL_OK_TLDS = (".example", ".test", ".invalid", ".localhost")
IP_RE = re.compile(r"(?<![\d.])(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?!\d|\.\d)")

DB_EXT = (".db", ".sqlite", ".sqlite3", ".db-journal", ".db-wal", ".db-shm")
IMG_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif")
CODE_EXT = (".py", ".js", ".jsx", ".ts", ".tsx", ".md")


@dataclass(frozen=True)
class Finding:
    path: str
    line: int      # 0 = o arquivo inteiro (regra de nome)
    rule: str
    excerpt: str

    def __str__(self) -> str:
        where = f"{self.path}:{self.line}" if self.line else self.path
        return f"{where}: [{self.rule}] {self.excerpt}"


def _private_ip(a: int, b: int) -> bool:
    return a == 10 or (a == 172 and 16 <= b <= 31) or (a == 192 and b == 168) or (a == 100 and 64 <= b <= 127)


def _email_ok(line: str, m: re.Match) -> bool:
    domain = m.group(1).lower()
    if line[max(0, m.start() - 2):m.start()] == "//":
        return True    # credencial dentro de URL (https://x@host), não é e-mail
    return domain.endswith(EMAIL_OK_TLDS) or any(domain == d or domain.endswith("." + d) for d in EMAIL_OK_DOMAINS)


def load_denylist(path: Path) -> list[re.Pattern]:
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for raw in lines:
        term = raw.strip()
        if not term or term.startswith("#"):
            continue
        out.append(re.compile(term[3:], re.I) if term.startswith("re:") else re.compile(re.escape(term), re.I))
    return out


def scan_text(path: str, text: str, deny: list[re.Pattern]) -> list[Finding]:
    found = []
    for n, line in enumerate(text.splitlines(), 1):
        def hit(rule, m):
            found.append(Finding(path, n, rule, m.group(0)[:80]))

        marked = MARKER in line
        for m in HOME_RE.finditer(line):
            hit("home", m)
        for m in TOKEN_RE.finditer(line):
            hit("token", m)
        for m in CHAT_ID_RE.finditer(line):
            hit("chat_id", m)
        if not marked:
            for m in EMAIL_RE.finditer(line):
                if not _email_ok(line, m):
                    hit("email", m)
            for m in IP_RE.finditer(line):
                parts = [int(x) for x in m.groups()]
                if all(p <= 255 for p in parts) and _private_ip(parts[0], parts[1]):
                    hit("ip", m)
        for rx in deny:
            for m in rx.finditer(line):
                hit("denylist", m)
    return found


def _bad_name(path: str) -> str | None:
    p = Path(path)
    name = p.name.lower()
    if name == DENYLIST_NAME:
        return "a lista de termos proibidos não pode ir para o git"
    if name.endswith(DB_EXT):
        return "banco de dados"
    if name == ".env" or name.endswith(".env"):
        return "arquivo .env"
    if name.startswith("secrets") and not name.endswith(CODE_EXT):
        return "arquivo de segredos"
    if "tg_img" in p.parts[:-1] and name.endswith(IMG_EXT):
        return "imagem baixada de canal"
    return None


def scan_names(paths: list[str]) -> list[Finding]:
    return [Finding(p, 0, "arquivo", why) for p in paths if (why := _bad_name(p))]


def list_files(root: Path) -> list[str]:
    if (root / ".git").exists():
        try:
            r = subprocess.run(["git", "-C", str(root), "ls-files", "-co", "--exclude-standard", "-z"],
                               capture_output=True, check=True)
            return sorted(f for f in r.stdout.decode().split("\0") if f and (root / f).is_file())
        except (OSError, subprocess.CalledProcessError):
            pass
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for f in filenames:
            rel = os.path.relpath(os.path.join(dirpath, f), root).replace(os.sep, "/")
            if rel != DENYLIST_NAME:
                out.append(rel)
    return sorted(out)


def check(root: Path) -> tuple[list[str], list[Finding]]:
    files = list_files(root)
    deny = load_denylist(root / DENYLIST_NAME)
    found = scan_names(files)
    for rel in files:
        data = (root / rel).read_bytes()
        if b"\0" in data[:8192]:
            continue   # binário: só a regra de nome vale
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        found += scan_text(rel, text, deny)
    return files, found


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    root = Path(args[0]) if args else Path(__file__).resolve().parents[1]
    files, found = check(root.resolve())
    for f in found:
        print(f)
    print(f"{'FALHOU' if found else 'OK'}: {len(files)} arquivos, {len(found)} achados")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
