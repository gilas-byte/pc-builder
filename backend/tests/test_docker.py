"""Docker compose. PCB_HOST, PCB_DATA_DIR para banco/fotos e testes ESTÁTICOS do Dockerfile, do compose
e do .dockerignore (lidos como texto; só o `docker compose config` precisa do Docker e pula sem ele)."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from app import serve
from app.scheduler import in_docker

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
DOCKERFILE = REPO / "Dockerfile"
COMPOSE = REPO / "docker-compose.yml"
DOCKERIGNORE = REPO / ".dockerignore"


def _text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _code(p: Path) -> str:
    """O arquivo sem os comentários (linhas e fim de linha), para as regras não casarem com texto explicativo."""
    return "\n".join(re.sub(r"\s+#.*$", "", ln) for ln in _text(p).splitlines() if not ln.lstrip().startswith("#"))


# ------------------------------------------------------------------------------------------------ PCB_HOST

def test_host_padrao_e_loopback():
    assert serve.HOST == "127.0.0.1"
    assert serve.listen_host({}) == "127.0.0.1"


@pytest.mark.parametrize("valor", ["0.0.0.0", "127.0.0.1", "::1", "203.0.113.5", " 0.0.0.0 "])
def test_host_valido_vale(valor):
    assert serve.listen_host({"PCB_HOST": valor}) == valor.strip()


@pytest.mark.parametrize("valor", ["", "   ", "lixo", "999.1.1.1", "localhost", "0.0.0.0; rm -rf /", "1.2.3", "http://x", "-1", "::g"])
def test_host_invalido_cai_no_padrao(valor):
    assert serve.listen_host({"PCB_HOST": valor}) == "127.0.0.1"


def test_main_sobe_no_host_da_variavel(monkeypatch, tmp_path):
    visto = {}
    monkeypatch.setattr(serve.uvicorn, "run", lambda app, **kw: visto.update(kw))
    monkeypatch.setattr(serve, "build_demo", lambda: tmp_path / "demo.db")
    monkeypatch.setattr(serve, "create_app", lambda **kw: object())
    monkeypatch.setenv("PCB_HOST", "0.0.0.0")
    serve.main()
    assert visto["host"] == "0.0.0.0" and visto["port"] == 8787 and visto["proxy_headers"] is False
    monkeypatch.setenv("PCB_HOST", "lixo")
    serve.main()                                  # lixo não derruba: volta para o loopback
    assert visto["host"] == "127.0.0.1"
    monkeypatch.delenv("PCB_HOST")
    serve.main()
    assert visto["host"] == "127.0.0.1"


# ------------------------------------------------------------------------------------------------ PCB_DATA_DIR

def _py(code: str, **env) -> str:
    e = {k: v for k, v in os.environ.items() if not k.startswith("PCB_")}
    e.update(env)
    out = subprocess.run([sys.executable, "-B", "-I", "-c", "import sys; sys.path.insert(0, '.'); " + code],
                         cwd=BACKEND, env=e, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def test_banco_fotos_e_demo_seguem_o_pcb_data_dir(tmp_path):
    d = str(tmp_path / "volume")
    got = _py("from app.db import database as d; from app.tg import images as i; from app import demo; "
              "print(d.DEFAULT_DB); print(i.IMG_DIR); print(demo.DEMO_DB)", PCB_DATA_DIR=d).splitlines()
    assert got == [f"{d}/pcbuilder.db", f"{d}/tg_img", f"{d}/demo.db"]


def test_sem_pcb_data_dir_o_banco_continua_em_data_do_projeto():
    got = _py("from app.db import database as d; from app.tg import images as i; print(d.DEFAULT_DB); print(i.IMG_DIR)").splitlines()
    assert got == [str(REPO / "data" / "pcbuilder.db"), str(REPO / "data" / "tg_img")]


# ------------------------------------------------------------------------------------------------ modo jogo

def test_no_docker_o_modo_jogo_fica_indisponivel(tmp_path):
    assert in_docker({"PCB_IN_DOCKER": "1"}, marker=tmp_path / "nao-existe") is True
    assert in_docker({}, marker=tmp_path / "nao-existe") is False


def test_imagem_define_pcb_in_docker_e_host():
    d = _code(DOCKERFILE)
    assert re.search(r"PCB_IN_DOCKER=1\b", d) and re.search(r"PCB_HOST=0\.0\.0\.0\b", d)


# ------------------------------------------------------------------------------------------------ Dockerfile

def _from_lines() -> list[str]:
    return re.findall(r"(?im)^\s*FROM\s+(\S+)", _code(DOCKERFILE))


def test_dockerfile_existe_e_e_multi_stage():
    assert len(_from_lines()) >= 2
    assert re.search(r"npm ci", _code(DOCKERFILE)) and re.search(r"npm run build", _code(DOCKERFILE))


def test_imagens_base_com_tag_de_versao():
    imagens = _from_lines()
    assert len(imagens) == 3, imagens                      # node, uv, python
    for i in imagens:
        assert re.search(r":\d[\w.-]*$", i), f"{i}: sem tag de versão"
    assert "latest" not in _code(DOCKERFILE).lower()


def test_dockerfile_roda_sem_root():
    d = _code(DOCKERFILE)
    users = re.findall(r"(?im)^\s*USER\s+(\S+)", d)
    assert users, "sem USER"
    ultimo = users[-1]
    assert ultimo not in ("root", "0", "0:0") and not ultimo.startswith("root:")
    assert re.search(r"10001", d), "UID fixo esperado"
    assert "nologin" in d or "/bin/false" in d, "sem shell de login"


def test_dockerfile_variaveis_porta_healthcheck_e_comando():
    d = _code(DOCKERFILE)
    for need in ("PYTHONUNBUFFERED=1", "PYTHONDONTWRITEBYTECODE=1", "PCB_DATA_DIR=/data"):
        assert need in d, need
    assert re.search(r"(?m)^EXPOSE 8787\b", d)
    hc = re.search(r"(?ms)^HEALTHCHECK.*?(?=^\S*[A-Z]+ |\Z)", d)
    assert hc and "/api/health" in hc.group(0) and "urllib" in hc.group(0) and "curl" not in d.lower()
    assert re.search(r'(?m)^CMD \[.*"-m",\s*"app\.serve".*\]', d)
    assert "--frozen" in d and "--no-dev" in d


def test_dockerfile_nao_copia_dado_nem_segredo():
    d = _code(DOCKERFILE)
    copias = [ln.strip() for ln in d.splitlines() if re.match(r"\s*(COPY|ADD)\b", ln)]
    assert copias and not any(c.startswith("ADD") for c in copias)
    for c in copias:
        for proibido in ("secrets", ".env", ".db", "tg_img", ".git", "data/", "COPY . ", "COPY ./ "):
            assert proibido not in c, c
    assert any(re.match(r"COPY backend/ ", c) for c in copias) and "/app/frontend/dist" in d
    assert not re.search(r"(?i)(TELEGRAM_TOKEN|BOT_TOKEN|\d{8,10}:[A-Za-z0-9_-]{30,})", _text(DOCKERFILE))


# ------------------------------------------------------------------------------------------------ .dockerignore

def test_dockerignore_cobre_dados_segredos_e_git():
    linhas = {ln.strip() for ln in _text(DOCKERIGNORE).splitlines() if ln.strip() and not ln.startswith("#")}
    for item in ("data/", "*.env", ".env", "secrets.env", ".git", "*.db", "tg_img/", "**/node_modules/", "**/.venv/",
                 "docs/", "tools/"):
        assert item in linhas, item


# ------------------------------------------------------------------------------------------------ docker-compose.yml

def _servico(nome: str) -> str:
    """Bloco do serviço (2 espaços de recuo) como texto, sem comentários."""
    m = re.search(rf"(?ms)^  {re.escape(nome)}:\n(.*?)(?=^  \S|^\S|\Z)", _code(COMPOSE))
    assert m, f"serviço {nome} não achado"
    return m.group(1)


def test_app_publica_so_em_loopback():
    app = _servico("pc-builder")
    portas = re.findall(r'(?m)^\s+-\s*["\']?([^"\'\s]*8787[^"\'\s]*)["\']?\s*$', app)
    assert portas, "sem ports"
    for p in portas:
        assert p.startswith("127.0.0.1:"), p
    assert "0.0.0.0:" not in app


def test_perfil_ollama_nao_publica_porta():
    ol = _servico("ollama")
    assert not re.search(r"(?m)^\s+ports:", ol)
    assert "expose" not in ol or "11434" in ol
    assert re.search(r'profiles:\s*\["?ollama"?\]', ol)
    assert re.search(r"image:\s*ollama/ollama:\d", ol) and "latest" not in ol


def test_app_endurecido():
    app = _servico("pc-builder")
    assert re.search(r"cap_drop:\s*\n\s*-\s*ALL", app) or "cap_drop: [ALL]" in app
    assert "no-new-privileges:true" in app
    assert "restart: unless-stopped" in app
    assert re.search(r"(?m)^\s+max-size:", app) and re.search(r"(?m)^\s+max-file:", app)
    assert "privileged" not in app and "network_mode" not in app and "docker.sock" not in app
    assert "PCB_DATA_DIR=/data" in app or "PCB_DATA_DIR: /data" in app or "PCB_DATA_DIR: \"/data\"" in app
    assert "PCB_SCHEDULER" in app and ":-1}" in app
    assert re.search(r"required:\s*false", _code(COMPOSE))


def test_compose_sem_latest_sem_segredo():
    t = _text(COMPOSE)
    assert "latest" not in _code(COMPOSE).lower()
    assert "secrets.env" not in _code(COMPOSE)
    assert not re.search(r"\d{8,10}:[A-Za-z0-9_-]{30,}", t)
    assert "PCB_TELEGRAM_TOKEN=" not in _code(COMPOSE)


def test_gpu_so_comentada():
    t = _text(COMPOSE)
    assert re.search(r"(?m)^\s*#.*nvidia", t, re.I)
    assert not re.search(r"(?m)^\s+(?!#)\s*devices:", t)


# ------------------------------------------------------------------------------------------------ docker compose config

def _docker_ok() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=20).returncode == 0
    except Exception:
        return False


@pytest.mark.skipif(not _docker_ok(), reason="Docker indisponível")
@pytest.mark.parametrize("perfil", [False, True])
def test_docker_compose_config(perfil, tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith("PCB_")}
    cmd = ["docker", "compose", "-p", "pcbtestecfg"] + (["--profile", "ollama"] if perfil else []) + ["config", "--format", "json"]
    out = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    cfg = json.loads(out.stdout)
    app = cfg["services"]["pc-builder"]
    assert all(p["host_ip"] == "127.0.0.1" and int(p["target"]) == 8787 for p in app["ports"])
    assert app["read_only"] is True and app["cap_drop"] == ["ALL"] and "no-new-privileges:true" in app["security_opt"]
    assert app["environment"]["PCB_DATA_DIR"] == "/data"
    assert ("ollama" in cfg["services"]) is perfil
    assert not app["environment"].get("PCB_OLLAMA_URL")           # sem a variável, vazio (o app ignora)
    if perfil:
        assert "ports" not in cfg["services"]["ollama"]
        # a variável do .env/ambiente chega ao app
        env["PCB_OLLAMA_URL"] = "http://ollama:11434"
        out = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True, text=True, timeout=60)
        assert json.loads(out.stdout)["services"]["pc-builder"]["environment"]["PCB_OLLAMA_URL"] == "http://ollama:11434"
