"""Verificador de higiene pública (tools/check_public.py).

Os textos "proibidos" daqui são montados por concatenação, senão o próprio verificador acusaria este arquivo
quando roda no repositório.
"""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import check_public as CP  # noqa: E402

HOME = "/ho" + "me/"
USERS = "/Us" + "ers/"
AT = "@"


def regras(text, path="docs/x.md", deny=()):
    return {f.rule for f in CP.scan_text(path, text, list(deny))}


# --------------------------------------------------------------------------- conteúdo que PASSA

@pytest.mark.parametrize("text", [
    "texto normal sem nada",
    "pasta em ~/.config/pc-builder e $HOME/.pc-builder-pause",
    HOME + "<usuario>/pc-builder",                      # marcador de exemplo, não é ninguém
    "user" + AT + "example.com e dev" + AT + "test.example.org",
    "123+fulano" + AT + "users.noreply.github.com",
    "https://cdn1.telesco.pe" + AT + "evil.com/a",       # credencial em URL (teste de segurança), não e-mail
    "https://user" + AT + "cdn1.telesco.pe/file/a",
    '"vite' + AT + '5.4.1"', "@app.get('/api')",
    "127.0.0.1:8787, 0.0.0.0, 8.8.8.8, 203.0.113.7",
    "versão 1.10.0.12 do pacote",
    "100.63.0.1 e 172.32.0.1 e 192.169.0.1",             # vizinhos das faixas privadas
    "IP de exemplo 192.168." + "0.10  # public-ok",
    "now = 1791900000  # timestamp, sem contexto de chat",
    '<a href="//telegram.org/x" emoji-id="5424972470023104089">',
])
def test_texto_limpo_passa(text):
    assert regras(text) == set()


# --------------------------------------------------------------------------- conteúdo que FALHA

@pytest.mark.parametrize("text, regra", [
    ("cd " + HOME + "fulano/projeto", "home"),
    ("ExecStart=" + USERS + "fulana/bin/uv", "home"),
    ("TOKEN=123456789:" + "AAH" + "x" * 32, "token"),
    ("bot1234567890:" + "a-b_c" * 7 + " no texto", "token"),
    ("chat_id = " + "18" + "23456789", "chat_id"),
    ("TELEGRAM_CHAT_ID=-100" + "1234567890", "chat_id"),
    ("o chat " + "9876" + "54321 recebe", "chat_id"),
    ("fale com fulano" + AT + "gmail.com", "email"),
    ("Autor: Fulano <dev.fulano" + AT + "empresa.com.br>", "email"),
    ("rede " + "192.168." + "100.25", "ip"),
    ("host " + "10." + "1.2.3", "ip"),
    ("docker " + "172." + "20.0.5", "ip"),
    ("tailnet " + "100." + "107.221.96", "ip"),
    ("CGNAT no limite " + "100." + "127.255.1", "ip"),
])
def test_texto_sujo_falha(text, regra):
    assert regra in regras(text)


def test_achado_traz_arquivo_linha_e_trecho():
    [f] = CP.scan_text("a/b.py", "ok\nok\nx = '" + HOME + "fulano'\n", [])
    assert (f.path, f.line, f.rule) == ("a/b.py", 3, "home") and "fulano" in f.excerpt


def test_marcador_public_ok_nao_libera_caminho_nem_token():
    assert "home" in regras(HOME + "fulano  # public-ok")
    assert "token" in regras("123456789:" + "Z" * 35 + "  # public-ok")


# --------------------------------------------------------------------------- nomes de arquivo

@pytest.mark.parametrize("path", [
    "data/pcbuilder.db", "backend/x.sqlite", "y.sqlite3", ".env", "deploy/.env", "prod.env",
    "secrets.env", "config/secrets.json", "data/tg_img/gpcrpromo_1.jpg", "x/tg_img/a.webp", "tg_img/b.PNG",
    ".public-denylist",
])
def test_arquivo_proibido(path):
    assert [f.rule for f in CP.scan_names([path])] == ["arquivo"]


@pytest.mark.parametrize("path", [
    ".env.example", "SECURITY.md", "docs/05-canais-telegram.md", "backend/app/tg/images.py",
    "frontend/public/favicon.svg", "tests/fixtures/tg_gpcrpromo.html", "backend/app/db/database.py",
])
def test_arquivo_permitido(path):
    assert CP.scan_names([path]) == []


# --------------------------------------------------------------------------- lista extra (.public-denylist)

def test_denylist_le_termos_comentarios_e_regex(tmp_path):
    f = tmp_path / ".public-denylist"
    f.write_text("# comentário\n\nFulanoDeTal\nre:\\bcidadezinha\\b\n")
    deny = CP.load_denylist(f)
    assert len(deny) == 2
    assert "denylist" in regras("mora com fulanodetal", deny=deny)          # sem diferenciar maiúscula
    assert "denylist" in regras("Cidadezinha - SP", deny=deny)
    assert regras("cidadezinhas não é a palavra", deny=deny) == set()
    assert CP.load_denylist(tmp_path / "nao_existe") == []


# --------------------------------------------------------------------------- rodando numa pasta

def _arvore(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "ok.md").write_text("limpo\n")
    return tmp_path


def test_pasta_limpa_da_zero(tmp_path, capsys):
    assert CP.main([str(_arvore(tmp_path))]) == 0
    assert "0 achados" in capsys.readouterr().out


def test_pasta_suja_falha_e_lista(tmp_path, capsys):
    root = _arvore(tmp_path)
    (root / "docs" / "sujo.md").write_text("a\n" + HOME + "fulano/x\n")
    (root / "pcbuilder.db").write_bytes(b"SQLite format 3\x00")
    assert CP.main([str(root)]) == 1
    out = capsys.readouterr().out
    assert "docs/sujo.md:2" in out and "pcbuilder.db" in out


def test_sem_git_pula_pastas_de_dependencia_e_le_denylist(tmp_path, capsys):
    root = _arvore(tmp_path)
    for d in ("node_modules/pkg", ".venv/lib", ".git/x"):
        (root / d).mkdir(parents=True)
        (root / d / "f.txt").write_text(HOME + "fulano\n")
    assert CP.main([str(root)]) == 0
    (root / ".public-denylist").write_text("limpo\n")      # a própria lista não é varrida (fora do git)
    assert CP.main([str(root)]) == 1
    assert "docs/ok.md:1" in capsys.readouterr().out


def test_binario_nao_e_lido_mas_nome_vale(tmp_path):
    root = _arvore(tmp_path)
    (root / "logo.png").write_bytes(b"\x89PNG\x00\x00" + (HOME + "fulano").encode())
    assert CP.main([str(root)]) == 0


def test_com_git_respeita_gitignore(tmp_path):
    root = _arvore(tmp_path)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / ".gitignore").write_text("data/\n.public-denylist\n")
    (root / "data").mkdir()
    (root / "data" / "pcbuilder.db").write_bytes(b"x")       # ignorado pelo git: não entra
    (root / ".public-denylist").write_text("proibidao\n")
    assert CP.main([str(root)]) == 0
    (root / "novo.md").write_text("um termo proibidao aqui\n")  # não rastreado, mas não ignorado: entra
    assert CP.main([str(root)]) == 1


def test_repositorio_atual_esta_limpo():
    r = subprocess.run([sys.executable, "-B", str(ROOT / "tools" / "check_public.py")],
                       capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stdout + r.stderr
