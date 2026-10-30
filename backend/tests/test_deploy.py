"""Scripts de deploy/: genéricos (uv do PATH ou PCB_UV, pasta descoberta pelo script), saída vazia = nada a avisar."""

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CANAIS = ROOT / "deploy" / "canais-telegram.sh"
COLETA = ROOT / "deploy" / "coleta-diaria.sh"


@pytest.fixture
def fake(tmp_path):
    """`uv` falso: grava a pasta e os argumentos, imprime $FAKE_OUT e sai com $FAKE_RC. Para
    `python -m app.settings get game_mode` responde $FAKE_GAME (o modo jogo salvo na tela; padrão 0)."""
    uv = tmp_path / "uv"
    uv.write_text('#!/bin/sh\ncase "$*" in *app.settings*) echo "$*" >> "$FAKE_LOG.settings"; '
                  'echo "${FAKE_GAME:-0}"; exit 0;; esac\n'
                  'pwd > "$FAKE_LOG"; echo "$@" >> "$FAKE_LOG"\n'
                  '[ -n "$FAKE_OUT" ] && echo "$FAKE_OUT"\necho "erro no log" >&2\nexit "${FAKE_RC:-0}"\n')
    uv.chmod(0o755)
    home = tmp_path / "home"
    home.mkdir()

    def run(script, out="", rc=0, **env):
        e = {"PATH": "/usr/bin:/bin", "HOME": str(home), "TMPDIR": str(tmp_path), "PCB_UV": str(uv),
             "FAKE_LOG": str(tmp_path / "chamada"), "FAKE_OUT": out, "FAKE_RC": str(rc), **env}
        (tmp_path / "chamada").unlink(missing_ok=True)
        r = subprocess.run(["bash", str(script)], capture_output=True, text=True, env=e, timeout=30)
        called = (tmp_path / "chamada").read_text() if (tmp_path / "chamada").exists() else None
        return r, called

    run.home = home
    run.tmp = tmp_path
    return run


@pytest.mark.parametrize("script, mod", [(CANAIS, "app.tg"), (COLETA, "app.collect")])
def test_roda_no_backend_do_clone_com_o_uv_escolhido(fake, script, mod):
    r, called = fake(script, out="🔥 promoção")
    assert r.returncode == 0 and r.stdout == "🔥 promoção\n"
    pasta, args = called.splitlines()
    assert Path(pasta) == ROOT / "backend"
    assert f"run --frozen --no-dev python -m {mod} --notify" in args


@pytest.mark.parametrize("script", [CANAIS, COLETA])
def test_saida_vazia_e_silencio(fake, script):
    r, called = fake(script)
    assert called and (r.returncode, r.stdout) == (0, "")


@pytest.mark.parametrize("script", [CANAIS, COLETA])
def test_quebra_nunca_fica_muda(fake, script):
    r, _ = fake(script, rc=3)
    assert r.returncode == 0 and "quebrou (código 3)" in r.stdout and "erro no log" in r.stdout


def test_uv_vem_do_path_sem_pcb_uv(fake):
    r, called = fake(CANAIS, out="ok", PCB_UV="", PATH=f"{fake.tmp}:/usr/bin:/bin")
    assert called and r.stdout == "ok\n"


def test_pausa_padrao_na_home_e_pausa_configuravel(fake):
    (fake.home / ".pc-builder-pause").touch()
    r, called = fake(CANAIS, out="não pode sair")
    assert (r.stdout, called) == ("", None)
    outra = fake.tmp / "pausa"
    r, called = fake(CANAIS, out="sai", PCB_PAUSE_FILE=str(outra))     # outro arquivo, que não existe
    assert r.stdout == "sai\n"
    outra.touch()
    assert fake(CANAIS, out="x", PCB_PAUSE_FILE=str(outra))[1] is None


def test_deteccao_de_jogo_so_com_pcb_game_mode(fake):
    jogo = subprocess.Popen(["sleep", "97531"])        # "jogo" aberto, achado pelo padrão
    try:
        r, called = fake(CANAIS, out="roda", PCB_GAME_PATTERN="sleep 97531")
        assert r.stdout == "roda\n"                     # desligado por padrão
        r, called = fake(CANAIS, out="roda", PCB_GAME_PATTERN="sleep 97531", PCB_GAME_MODE="1")
        assert (r.stdout, called) == ("", None)
        r, called = fake(CANAIS, out="roda", PCB_GAME_PATTERN="sleep 24680", PCB_GAME_MODE="1")
        assert r.stdout == "roda\n"                     # ligado, mas sem jogo aberto
    finally:
        jogo.kill()
        jogo.wait()


@pytest.mark.parametrize("script", [CANAIS, COLETA])
def test_modo_jogo_salvo_na_tela_vale_no_script(fake, script):
    jogo = subprocess.Popen(["sleep", "97532"])
    try:
        pat = {"PCB_GAME_PATTERN": "sleep 97532"}
        r, called = fake(script, out="roda", FAKE_GAME="1", **pat)          # ligado na tela, jogo aberto: pula
        assert (r.stdout, called) == ("", None)
        assert "get game_mode" in (fake.tmp / "chamada.settings").read_text()
        r, called = fake(script, out="roda", FAKE_GAME="0", **pat)          # desligado na tela: roda
        assert r.stdout == "roda\n"
        r, called = fake(script, out="roda", FAKE_GAME="1", PCB_GAME_MODE="0", **pat)   # a variável vale mais
        assert r.stdout == "roda\n"
        r, called = fake(script, out="roda", FAKE_GAME="1", PCB_GAME_PATTERN="sleep 13579")   # sem jogo: roda
        assert r.stdout == "roda\n"
    finally:
        jogo.kill()
        jogo.wait()


def test_coleta_tambem_respeita_pcb_game_mode(fake):
    jogo = subprocess.Popen(["sleep", "97533"])
    try:
        r, called = fake(COLETA, out="roda", PCB_GAME_MODE="1", PCB_GAME_PATTERN="sleep 97533")
        assert (r.stdout, called) == ("", None)
    finally:
        jogo.kill()
        jogo.wait()


@pytest.mark.parametrize("path", sorted((ROOT / "deploy").iterdir()))
def test_nada_fora_do_repositorio(path):
    s = path.read_text()
    for proibido in ("." + "hermes", "Documents/", "/" + "home/", "Gil" + "as"):
        assert proibido not in s, (path.name, proibido)
