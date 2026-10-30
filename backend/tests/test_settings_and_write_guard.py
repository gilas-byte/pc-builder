"""Trava de escrita Host/Origin/Content-Type, configurações (settings),
canais do Telegram cadastrados pela tela, e o resto do app respeitando as configurações.

Sem rede: a prévia do canal usa um fetcher falso injetado no create_app."""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import compat
from app import settings as S
from app.collect import run as collect_run
from app.db import database as db
from app.main import create_app
from app.tg import channels as CH
from app.tg import run as R
from tests.test_api import day, ingest, item

F = Path(__file__).parent / "fixtures"
BASE = "http://127.0.0.1:8787"
PREVIA = (F / "tg_gpcrpromo.html").read_text(encoding="utf-8")
SEM_PREVIA = (F / "tg_sem_previa.html").read_text(encoding="utf-8")
PCB_VARS = [k for k in __import__("os").environ if k.startswith("PCB_")]


@pytest.fixture(autouse=True)
def _sem_env(monkeypatch):
    """Nenhuma PCB_* da máquina de quem roda o teste vaza pra cá."""
    for k in PCB_VARS:
        monkeypatch.delenv(k, raising=False)


def fake_preview(page=PREVIA, down=False):
    calls = []

    def fetch(url):
        calls.append(url)
        if down:
            raise CH.ChannelUnreachable("sem rede")
        return page
    fetch.calls = calls
    return fetch


@pytest.fixture
def env(tmp_path):
    db_path = tmp_path / "t.db"
    fetch = fake_preview()
    app = create_app(db_path=db_path, frontend_dist=tmp_path / "x", channel_fetch=fetch)
    return {"c": TestClient(app, base_url=BASE), "db_path": db_path, "tmp": tmp_path, "fetch": fetch, "app": app}


def conn_of(env):
    return db.connect(env["db_path"])


# =========================================================================== 1. trava de escrita

def test_escrita_com_host_e_origin_certos_passa(env):
    r = env["c"].put("/api/settings", json={"language": "en"}, headers={"Origin": BASE})
    assert r.status_code == 200


def test_sem_origin_como_o_curl_passa(env):
    assert env["c"].put("/api/settings", json={"language": "en"}).status_code == 200
    assert env["c"].post("/api/builds/1/auto").status_code == 200


def test_localhost_tambem_e_permitido(tmp_path):
    c = TestClient(create_app(db_path=tmp_path / "t.db", frontend_dist=tmp_path / "x"), base_url="http://localhost:8787")
    assert c.put("/api/settings", json={"language": "en"}, headers={"Origin": "http://localhost:8787"}).status_code == 200


@pytest.mark.parametrize("metodo,rota,corpo", [
    ("put", "/api/settings", {"language": "en"}),
    ("post", "/api/settings/reset/language", None),
    ("post", "/api/channels", {"handle": "gpcrpromo"}),
    ("put", "/api/channels/gpcrpromo", {"enabled": False}),
    ("delete", "/api/channels/gpcrpromo", None),
    ("put", "/api/builds/1/items/gpu", {"part_id": None}),
    ("post", "/api/builds/1/auto", None),
    ("put", "/api/favorites/1", None),
    ("delete", "/api/favorites/1", None),
])
def test_host_errado_da_403_em_toda_rota_que_grava(tmp_path, metodo, rota, corpo):
    app = create_app(db_path=tmp_path / "t.db", frontend_dist=tmp_path / "x", channel_fetch=fake_preview())
    c = TestClient(app, base_url="http://evil.example:8787")      # DNS rebinding: o Host é o do atacante
    kw = {"json": corpo} if corpo is not None else {}
    r = c.request(metodo.upper(), rota, **kw)
    assert r.status_code == 403
    conn = db.connect(tmp_path / "t.db")
    assert conn.execute("SELECT COUNT(*) FROM settings WHERE key = 'language'").fetchone()[0] == 0
    assert conn.execute("SELECT active FROM tg_channels WHERE slug = 'gpcrpromo'").fetchone()[0] == 1


@pytest.mark.parametrize("origin", ["http://evil.example", "http://evil.example:8787", "null",
                                    "http://127.0.0.1:9999", "https://127.0.0.1.evil.example:8787", "file://"])
def test_origin_de_outro_site_da_403(env, origin):
    r = env["c"].put("/api/settings", json={"language": "en"}, headers={"Origin": origin})
    assert r.status_code == 403
    assert env["c"].get("/api/settings").json()["values"]["language"] == "pt-BR"


@pytest.mark.parametrize("ctype", ["text/plain", "application/x-www-form-urlencoded", "multipart/form-data; boundary=x",
                                   None])
def test_content_type_errado_da_415(env, ctype):
    headers = {"Content-Type": ctype} if ctype else {}
    r = env["c"].put("/api/settings", content=b'{"language": "en"}', headers=headers)
    assert r.status_code == 415
    assert env["c"].get("/api/settings").json()["values"]["language"] == "pt-BR"


def test_json_com_charset_passa(env):
    r = env["c"].put("/api/settings", content=b'{"language": "en"}',
                     headers={"Content-Type": "application/json; charset=utf-8"})
    assert r.status_code == 200


def test_formulario_sem_corpo_mas_com_content_type_errado_da_415(env):
    # <form method=post> de outro site manda x-www-form-urlencoded mesmo vazio
    r = env["c"].post("/api/builds/1/auto", headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert r.status_code == 415


def test_corpo_grande_demais_da_413(env):
    r = env["c"].put("/api/settings", content=b'{"language": "' + b"x" * 70_000 + b'"}',
                     headers={"Content-Type": "application/json"})
    assert r.status_code == 413


def test_leitura_nao_exige_origin_nem_host(tmp_path):
    c = TestClient(create_app(db_path=tmp_path / "t.db", frontend_dist=tmp_path / "x"), base_url="http://evil.example")
    assert c.get("/api/settings", headers={"Origin": "http://evil.example"}).status_code == 200
    assert c.get("/api/health").status_code == 200


def test_pcb_allowed_hosts_libera_o_proxy(tmp_path, monkeypatch):
    monkeypatch.setenv("PCB_ALLOWED_HOSTS", " pc.tailnet.example , outro.example:8443 ")
    app = create_app(db_path=tmp_path / "t.db", frontend_dist=tmp_path / "x")
    c = TestClient(app, base_url="https://pc.tailnet.example")
    assert c.put("/api/settings", json={"language": "en"}, headers={"Origin": "https://pc.tailnet.example"}).status_code == 200
    c2 = TestClient(app, base_url="https://outro.example:8443")
    assert c2.put("/api/settings", json={"language": "en"}).status_code == 200
    # sem estar na lista, continua barrado
    c3 = TestClient(app, base_url="https://pc.tailnet.example.evil.example")
    assert c3.put("/api/settings", json={"language": "en"}).status_code == 403


def test_porta_errada_no_host_da_403(tmp_path):
    c = TestClient(create_app(db_path=tmp_path / "t.db", frontend_dist=tmp_path / "x"), base_url="http://127.0.0.1:9999")
    assert c.put("/api/settings", json={"language": "en"}).status_code == 403


# =========================================================================== 2. banco: migração e seed

def _banco_antigo(path: Path):
    """Banco do jeito antigo: settings (key, value) sem updated_at, tg_channels sem added_at/source/removed_at,
    com dados (canal, oferta e configuração antiga)."""
    c = sqlite3.connect(path)
    c.executescript("""
        CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO settings VALUES ('promo_threshold', '0.15');
        CREATE TABLE tg_channels (slug TEXT PRIMARY KEY, title TEXT, active INTEGER NOT NULL DEFAULT 1
            CHECK (active IN (0, 1)), last_msg_id INTEGER NOT NULL DEFAULT 0, last_ok_at TEXT,
            fail_count INTEGER NOT NULL DEFAULT 0, last_error TEXT);
        INSERT INTO tg_channels (slug, active, last_msg_id, last_ok_at) VALUES ('gpcrpromo', 1, 777, '2026-10-12T10:00:00');
        INSERT INTO tg_channels (slug, active, last_msg_id) VALUES ('canalmeu', 0, 55);
    """)
    c.commit()
    c.close()


def test_migracao_de_banco_antigo_nao_perde_dados(tmp_path):
    path = tmp_path / "old.db"
    _banco_antigo(path)
    conn = db.init_db(path)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(tg_channels)")}
    assert {"added_at", "source", "removed_at", "active"} <= cols
    assert "updated_at" in {r["name"] for r in conn.execute("PRAGMA table_info(settings)")}
    g = conn.execute("SELECT * FROM tg_channels WHERE slug = 'gpcrpromo'").fetchone()
    assert (g["last_msg_id"], g["last_ok_at"], g["active"], g["source"]) == (777, "2026-10-12T10:00:00", 1, "padrao")
    m = conn.execute("SELECT * FROM tg_channels WHERE slug = 'canalmeu'").fetchone()
    assert (m["last_msg_id"], m["active"], m["source"], m["removed_at"]) == (55, 0, "usuario", None)
    assert m["added_at"]
    assert conn.execute("SELECT value FROM settings WHERE key = 'promo_threshold'").fetchone()[0] == "0.15"
    conn.close()
    db.init_db(path).close()                       # de novo: idempotente
    conn = db.connect(path)
    assert conn.execute("SELECT last_msg_id FROM tg_channels WHERE slug = 'gpcrpromo'").fetchone()[0] == 777


def test_seed_dos_9_canais_e_idempotente(tmp_path):
    path = tmp_path / "t.db"
    for _ in range(3):
        db.init_db(path).close()
    conn = db.connect(path)
    rows = conn.execute("SELECT slug, source, active FROM tg_channels ORDER BY slug").fetchall()
    assert sorted(r["slug"] for r in rows) == sorted(S.DEFAULT_CHANNELS)
    assert len(S.DEFAULT_CHANNELS) == 9
    assert all(r["source"] == "padrao" and r["active"] == 1 for r in rows)


def test_seed_nao_ressuscita_canal_removido(env):
    assert env["c"].delete("/api/channels/gpcrpromo").status_code == 204
    db.init_db(env["db_path"]).close()
    slugs = [c["slug"] for c in env["c"].get("/api/channels").json()]
    assert "gpcrpromo" not in slugs


def test_sem_nenhuma_configuracao_salva_vale_o_de_hoje(env):
    j = env["c"].get("/api/settings").json()
    v = j["values"]
    assert v["language"] == "pt-BR" and v["notify_target"] == "stdout" and v["game_mode"] is False
    assert v["stores"] == {"kabum": True, "terabyte": True, "amazon": True}
    assert v["collect_every_minutes"] == 1440
    assert v["price_range"] == {"min": 0, "max": 1_000_000}
    assert v["current_pc"]["socket"] == compat.CURRENT_PC["socket"] == "AM4"
    assert {k: v["current_pc"][k] for k in S.PC_FIELDS} == {k: compat.CURRENT_PC[k] for k in S.PC_FIELDS}
    assert v["ollama"]["url"] == "http://127.0.0.1:11434" and len(v["ollama"]["models"]) == 3
    assert all(m["source"] == "default" and not m["locked"] for m in j["meta"].values())
    assert set(j["values"]) == set(S.DEFAULTS)


# =========================================================================== 3. settings: validação

OK = [
    ("language", "en"), ("stores", {"kabum": False, "terabyte": True, "amazon": True}),
    ("collect_every_minutes", 15), ("collect_every_minutes", 1440), ("price_range", {"min": 0, "max": 0}),
    ("price_range", {"min": 100, "max": 1_000_000}), ("game_mode", True), ("notify_target", "none"),
    ("notify_target", "telegram"), ("ollama", {"url": "https://ollama.example:11434", "models": ["qwen2.5:3b"]}),
    ("current_pc", {"socket": "AM5", "memory_type": "DDR5", "motherboard": "ASUS TUF B650M-PLUS", "cpu": "Ryzen 7 7700",
                    "gpu": "RX 7800 XT", "ram_gb": 32, "form_factor": "mATX"}),
]


@pytest.mark.parametrize("chave,valor", OK)
def test_valores_validos_sao_salvos(env, chave, valor):
    r = env["c"].put("/api/settings", json={chave: valor})
    assert r.status_code == 200, r.text
    j = r.json()
    for k, v in (valor.items() if isinstance(valor, dict) and chave != "stores" else [(None, valor)]):
        assert (j["values"][chave][k] if k else j["values"][chave]) == v
    assert j["meta"][chave]["source"] == "banco"
    row = conn_of(env).execute("SELECT value, updated_at FROM settings WHERE key = ?", (chave,)).fetchone()
    assert json.loads(row["value"]) == j["values"][chave] and row["updated_at"]


RUIM = [
    ("language", "fr"), ("language", 1), ("language", "pt-BR<script>"),
    ("stores", {"kabum": False, "terabyte": False, "amazon": False}),         # nenhuma ligada
    ("stores", {"pichau": True}), ("stores", {"kabum": "sim"}), ("stores", ["kabum"]),
    ("collect_every_minutes", 14), ("collect_every_minutes", 1441), ("collect_every_minutes", "60"),
    ("collect_every_minutes", 60.5), ("collect_every_minutes", True),
    ("price_range", {"min": 500, "max": 100}),                                 # min > max
    ("price_range", {"min": -1, "max": 100}), ("price_range", {"min": 0, "max": 1_000_001}),
    ("price_range", {"min": "0", "max": 100}), ("price_range", {"min": 0}), ("price_range", {"min": 0, "max": 5, "x": 1}),
    ("price_range", {"min": True, "max": 5}), ("price_range", 100),
    ("game_mode", "true"), ("game_mode", 1),
    ("notify_target", "email"), ("notify_target", None),
    ("ollama", {"url": "ftp://127.0.0.1", "models": []}), ("ollama", {"url": "javascript:alert(1)", "models": []}),
    ("ollama", {"url": "http://user:senha@127.0.0.1:11434", "models": []}),       # public-ok (exemplo de userinfo)
    ("ollama", {"url": "http://", "models": []}), ("ollama", {"url": "http://127.0.0.1:11434/?x=1", "models": []}),
    ("ollama", {"url": "http://127.0.0.1:11434", "models": ["a", "b", "c", "d"]}),
    ("ollama", {"url": "http://127.0.0.1:11434", "models": ["qwen; rm -rf /"]}),
    ("ollama", {"url": "http://127.0.0.1:11434", "models": ["../../etc/passwd"]}),
    ("ollama", {"url": "http://127.0.0.1:11434", "models": ["x" * 101]}),
    ("ollama", {"url": "http://127.0.0.1:11434", "models": []}),                    # de 1 a 3 modelos
    ("ollama", {"url": "http://127.0.0.1:11434", "models": ["qwen2.5:3b", "qwen2.5:3b"]}),
    ("ollama", {"url": "http://127.0.0.1:11434", "models": "qwen2.5:3b"}),
    ("current_pc", {"socket": "AM9"}), ("current_pc", {"memory_type": "DDR7"}), ("current_pc", {"form_factor": "XL"}),
    ("current_pc", {"ram_gb": 0}), ("current_pc", {"ram_gb": 4096}), ("current_pc", {"ram_gb": "16"}),
    ("current_pc", {"cpu": ""}), ("current_pc", {"cpu": "x" * 81}), ("current_pc", {"cpu": "<img src=x onerror=alert(1)>"}),
    ("current_pc", {"gpu": "RTX\n3060"}), ("current_pc", {"motherboard": "B450'; DROP TABLE parts;--"}),
    ("current_pc", {"cor": "azul"}), ("current_pc", "AM4"),
]


@pytest.mark.parametrize("chave,valor", RUIM)
def test_valores_invalidos_dao_422_com_mensagem_do_campo(env, chave, valor):
    r = env["c"].put("/api/settings", json={chave: valor})
    assert r.status_code == 422, (chave, valor, r.text)
    fields = r.json()["detail"]["fields"]
    assert chave in fields and isinstance(fields[chave], str) and fields[chave]
    assert env["c"].get("/api/settings").json()["meta"][chave]["source"] == "default"
    assert conn_of(env).execute("SELECT COUNT(*) FROM settings WHERE key = ?", (chave,)).fetchone()[0] == 0


def test_chave_desconhecida_da_422(env):
    r = env["c"].put("/api/settings", json={"telegram_token": "x"})
    assert r.status_code == 422 and "telegram_token" in r.json()["detail"]["fields"]


def test_put_e_atomico_um_campo_ruim_nao_salva_nenhum(env):
    r = env["c"].put("/api/settings", json={"language": "en", "collect_every_minutes": 5})
    assert r.status_code == 422
    assert set(r.json()["detail"]["fields"]) == {"collect_every_minutes"}
    assert env["c"].get("/api/settings").json()["values"]["language"] == "pt-BR"


def test_corpo_que_nao_e_objeto_da_422(env):
    for corpo in ([], "x", 3, None):
        assert env["c"].put("/api/settings", json=corpo).status_code == 422


def test_put_parcial_do_pc_completa_com_o_resto(env):
    env["c"].put("/api/settings", json={"current_pc": {"socket": "AM5", "memory_type": "DDR5"}})
    pc = env["c"].get("/api/settings").json()["values"]["current_pc"]
    assert (pc["socket"], pc["memory_type"], pc["cpu"]) == ("AM5", "DDR5", compat.CURRENT_PC["cpu"])


def test_lojas_parcial_completa_com_o_resto_e_exige_uma_ligada(env):
    assert env["c"].put("/api/settings", json={"stores": {"kabum": False, "terabyte": False}}).status_code == 200
    assert env["c"].get("/api/settings").json()["values"]["stores"] == {"kabum": False, "terabyte": False, "amazon": True}
    assert env["c"].put("/api/settings", json={"stores": {"amazon": False}}).status_code == 422


def test_restaurar_padrao_restaura(env):
    env["c"].put("/api/settings", json={"language": "en", "collect_every_minutes": 30})
    r = env["c"].post("/api/settings/reset/language")
    assert r.status_code == 200
    j = r.json()
    assert j["values"]["language"] == "pt-BR" and j["meta"]["language"]["source"] == "default"
    assert j["values"]["collect_every_minutes"] == 30                        # só a chave pedida
    assert conn_of(env).execute("SELECT COUNT(*) FROM settings WHERE key = 'language'").fetchone()[0] == 0


def test_restaurar_chave_desconhecida_da_404(env):
    assert env["c"].post("/api/settings/reset/promo_threshold").status_code == 404
    assert env["c"].post("/api/settings/reset/nada").status_code == 404


def test_valor_corrompido_no_banco_cai_no_padrao(env):
    c = conn_of(env)
    with c:
        c.execute("INSERT INTO settings (key, value) VALUES ('collect_every_minutes', '\"muito\"')")
        c.execute("INSERT INTO settings (key, value) VALUES ('language', '{nao json')")
    j = env["c"].get("/api/settings").json()
    assert j["values"]["collect_every_minutes"] == 1440 and j["values"]["language"] == "pt-BR"
    assert j["meta"]["language"]["source"] == "default"


# --------------------------------------------------------------------------- precedência default < banco < env

def test_precedencia_default_banco_env(env, monkeypatch):
    c = env["c"]
    assert c.get("/api/settings").json()["values"]["collect_every_minutes"] == 1440
    c.put("/api/settings", json={"collect_every_minutes": 60})
    assert c.get("/api/settings").json()["values"]["collect_every_minutes"] == 60
    monkeypatch.setenv("PCB_COLLECT_EVERY_MINUTES", "30")
    j = c.get("/api/settings").json()
    assert j["values"]["collect_every_minutes"] == 30
    assert j["meta"]["collect_every_minutes"] == {"source": "env", "env": ["PCB_COLLECT_EVERY_MINUTES"], "locked": True}


@pytest.mark.parametrize("var,valor,chave,esperado", [
    ("PCB_LANGUAGE", "en", "language", "en"),
    ("PCB_STORES", "kabum,amazon", "stores", {"kabum": True, "terabyte": False, "amazon": True}),
    ("PCB_PRICE_MIN", "100", "price_range", {"min": 100, "max": 1_000_000}),
    ("PCB_PRICE_MAX", "2000", "price_range", {"min": 0, "max": 2000}),
    ("PCB_GAME_MODE", "1", "game_mode", True),
    ("PCB_GAME_MODE", "0", "game_mode", False),
    ("PCB_NOTIFY_TARGET", "none", "notify_target", "none"),
    ("PCB_OLLAMA_URL", "http://10.0.0.5:11434", "ollama", None),      # public-ok (exemplo)
    ("PCB_OLLAMA_MODELS", "gemma3:4b", "ollama", None),
    ("PCB_CURRENT_PC", '{"socket": "AM5", "memory_type": "DDR5"}', "current_pc", None),
])
def test_cada_variavel_sobrepoe_o_banco(env, monkeypatch, var, valor, chave, esperado):
    monkeypatch.setenv(var, valor)
    j = env["c"].get("/api/settings").json()
    assert j["meta"][chave]["source"] == "env" and var in j["meta"][chave]["env"] and j["meta"][chave]["locked"]
    if esperado is not None:
        assert j["values"][chave] == esperado
    if var == "PCB_OLLAMA_URL":
        assert j["values"]["ollama"]["url"] == valor and len(j["values"]["ollama"]["models"]) == 3
    if var == "PCB_OLLAMA_MODELS":
        assert j["values"]["ollama"]["models"] == ["gemma3:4b"]
    if var == "PCB_CURRENT_PC":
        assert j["values"]["current_pc"]["socket"] == "AM5"


def test_campo_definido_por_env_nao_aceita_put_nem_e_trocado(env, monkeypatch):
    monkeypatch.setenv("PCB_LANGUAGE", "en")
    r = env["c"].put("/api/settings", json={"language": "pt-BR"})
    assert r.status_code == 422 and "variável de ambiente" in r.json()["detail"]["fields"]["language"]
    assert env["c"].get("/api/settings").json()["values"]["language"] == "en"


def test_env_invalida_e_ignorada_e_avisada(env, monkeypatch):
    monkeypatch.setenv("PCB_COLLECT_EVERY_MINUTES", "2")
    j = env["c"].get("/api/settings").json()
    assert j["values"]["collect_every_minutes"] == 1440
    assert j["meta"]["collect_every_minutes"]["source"] == "default"
    assert "PCB_COLLECT_EVERY_MINUTES" in j["meta"]["collect_every_minutes"]["env_error"]


def test_env_vazia_nao_conta(env, monkeypatch):
    monkeypatch.setenv("PCB_LANGUAGE", "")
    assert env["c"].get("/api/settings").json()["meta"]["language"]["source"] == "default"


def test_get_settings_nao_tem_segredo(env, monkeypatch):
    monkeypatch.setenv("PCB_TELEGRAM_TOKEN", "123456789:" + "A" * 35)
    txt = env["c"].get("/api/settings").text
    assert "AAAAAAAAAA" not in txt and "token" not in txt.lower()


def test_cli_le_o_valor_efetivo(tmp_path, capsys, monkeypatch):
    path = tmp_path / "t.db"
    assert S.main(["get", "game_mode"], db_path=path) == 0
    assert capsys.readouterr().out.strip() == "0"
    monkeypatch.setenv("PCB_GAME_MODE", "1")
    S.main(["get", "game_mode"], db_path=path)
    assert capsys.readouterr().out.strip() == "1"
    S.main(["get", "price_range"], db_path=path)
    assert json.loads(capsys.readouterr().out) == {"min": 0, "max": 1_000_000}
    assert S.main(["get", "nada"], db_path=path) == 2


# =========================================================================== 4. canais

@pytest.mark.parametrize("entrada,slug", [
    ("gpcrpromo", "gpcrpromo"), ("@gpcrpromo", "gpcrpromo"), ("  @gpcrpromo  ", "gpcrpromo"),
    ("https://t.me/gpcrpromo", "gpcrpromo"), ("http://t.me/gpcrpromo", "gpcrpromo"), ("t.me/gpcrpromo", "gpcrpromo"),
    ("t.me/s/gpcrpromo", "gpcrpromo"), ("https://t.me/s/gpcrpromo/", "gpcrpromo"), ("https://telegram.me/Canal_1", "Canal_1"),
    ("abcd", "abcd"), ("a" * 32, "a" * 32),
])
def test_handle_normalizado(entrada, slug):
    assert CH.normalize_handle(entrada) == slug


@pytest.mark.parametrize("entrada", [
    "a/b", "@@x", "@@gpcrpromo", "abc", "a" * 33, "canal-promo", "canal promo", "cañal_promo", "канал_promo",
    "gpcr\npromo", "gpcrpromo\n", "", "@", "https://evil.example/gpcrpromo", "https://t.me.evil.example/gpcrpromo",
    "https://user@t.me/gpcrpromo",                                              # public-ok (userinfo)
    "https://t.me:8080/gpcrpromo", "https://t.me/gpcrpromo/123", "https://t.me/gpcrpromo?x=1", "https://t.me/s/",
    "javascript:alert(1)", "t.me/joinchat/AAAAA", "https://t.me/+AbCdEf123", "../gpcrpromo", "gpcrpromo#x",
    "ｇｐｃｒｐｒｏｍｏ", None, 123, "x" * 300,
])
def test_handle_estranho_e_recusado(entrada):
    with pytest.raises(ValueError):
        CH.normalize_handle(entrada)


def test_lista_de_canais_com_estado(env):
    c = conn_of(env)
    with c:
        c.execute("UPDATE tg_channels SET last_ok_at = '2026-10-12T10:00:00' WHERE slug = 'gpcrpromo'")
        c.execute("INSERT INTO tg_offers (channel, msg_id, posted_at, seen_at, title, text, price_cash) "
                  "VALUES ('gpcrpromo', 1, '2026-10-12T09:00:00', '2026-10-12T10:00:00', 't', 't', 100)")
    lst = env["c"].get("/api/channels").json()
    assert len(lst) == 9
    g = next(x for x in lst if x["slug"] == "gpcrpromo")
    assert g["enabled"] is True and g["posts"] == 1 and g["last_ok_at"] == "2026-10-12T10:00:00"
    assert g["source"] == "padrao" and g["last_post_at"] == "2026-10-12T09:00:00"


def test_adicionar_canal_valida_a_previa_e_grava(env):
    r = env["c"].post("/api/channels", json={"handle": "https://t.me/s/NovoCanal_1"})
    assert r.status_code == 201, r.text
    assert r.json()["slug"] == "NovoCanal_1" and r.json()["enabled"] is True and r.json()["source"] == "usuario"
    assert env["fetch"].calls == ["https://t.me/s/NovoCanal_1"]
    assert "NovoCanal_1" in [x["slug"] for x in env["c"].get("/api/channels").json()]


def test_canal_sem_previa_da_422_e_nao_grava(tmp_path):
    fetch = fake_preview(SEM_PREVIA)
    c = TestClient(create_app(db_path=tmp_path / "t.db", frontend_dist=tmp_path / "x", channel_fetch=fetch), base_url=BASE)
    r = c.post("/api/channels", json={"handle": "@canalfechado"})
    assert r.status_code == 422 and "prévia pública" in r.json()["detail"]
    assert "canalfechado" not in [x["slug"] for x in c.get("/api/channels").json()]


def test_sem_rede_da_503_e_nao_grava(tmp_path):
    fetch = fake_preview(down=True)
    c = TestClient(create_app(db_path=tmp_path / "t.db", frontend_dist=tmp_path / "x", channel_fetch=fetch), base_url=BASE)
    r = c.post("/api/channels", json={"handle": "@canalnovo"})
    assert r.status_code == 503 and "rede" in r.json()["detail"].lower()
    assert len(fetch.calls) == 1                                  # 1 tentativa só
    assert "canalnovo" not in [x["slug"] for x in c.get("/api/channels").json()]


def test_handle_invalido_nem_chama_a_rede(env):
    for h in ("a/b", "@@x", "https://user@t.me/abcd", "cañal_x"):              # public-ok (userinfo)
        r = env["c"].post("/api/channels", json={"handle": h})
        assert r.status_code == 422, h
    assert env["fetch"].calls == []


def test_corpo_do_post_de_canal_validado(env):
    for corpo in ({}, {"handle": 3}, {"handle": "x" * 300}, {"handle": "abcd", "extra": 1}):
        assert env["c"].post("/api/channels", json=corpo).status_code == 422


def test_canal_duplicado_da_409(env):
    assert env["c"].post("/api/channels", json={"handle": "gpcrpromo"}).status_code == 409
    assert env["c"].post("/api/channels", json={"handle": "GPCRPROMO"}).status_code == 409      # maiúscula não engana
    assert env["fetch"].calls == []
    assert conn_of(env).execute("SELECT COUNT(*) FROM tg_channels WHERE lower(slug) = 'gpcrpromo'").fetchone()[0] == 1


def test_maximo_de_50_canais(env):
    c = conn_of(env)
    with c:
        c.executemany("INSERT INTO tg_channels (slug, source) VALUES (?, 'usuario')", [(f"canal_{i:02d}",) for i in range(41)])
    assert len(env["c"].get("/api/channels").json()) == 50
    r = env["c"].post("/api/channels", json={"handle": "canal_51"})
    assert r.status_code == 422 and "50" in r.json()["detail"]
    assert env["fetch"].calls == []
    # removido não conta no limite
    assert env["c"].delete("/api/channels/canal_00").status_code == 204
    assert env["c"].post("/api/channels", json={"handle": "canal_51"}).status_code == 201


def test_ligar_e_desligar_canal(env):
    r = env["c"].put("/api/channels/gpcrpromo", json={"enabled": False})
    assert r.status_code == 200 and r.json()["enabled"] is False
    assert conn_of(env).execute("SELECT active FROM tg_channels WHERE slug = 'gpcrpromo'").fetchone()[0] == 0
    assert env["c"].put("/api/channels/gpcrpromo", json={"enabled": True}).json()["enabled"] is True
    assert env["c"].put("/api/channels/gpcrpromo", json={"enabled": "nao"}).status_code == 422
    assert env["c"].put("/api/channels/naoexiste", json={"enabled": True}).status_code == 404
    assert env["c"].put("/api/channels/a%2Fb", json={"enabled": True}).status_code in (404, 405, 422)
    assert env["c"].put("/api/channels/x" * 1, json={"enabled": True}).status_code in (404, 422)


def test_delete_desativa_esconde_e_guarda_o_historico(env):
    c = conn_of(env)
    with c:
        c.execute("INSERT INTO tg_offers (channel, msg_id, posted_at, seen_at, title, text, price_cash) "
                  "VALUES ('gpcrpromo', 1, '2026-10-12T09:00:00', '2026-10-12T10:00:00', 't', 't', 100)")
    assert env["c"].delete("/api/channels/gpcrpromo").status_code == 204
    row = conn_of(env).execute("SELECT active, removed_at FROM tg_channels WHERE slug = 'gpcrpromo'").fetchone()
    assert row["active"] == 0 and row["removed_at"]
    assert conn_of(env).execute("SELECT COUNT(*) FROM tg_offers WHERE channel = 'gpcrpromo'").fetchone()[0] == 1
    assert "gpcrpromo" not in [x["slug"] for x in env["c"].get("/api/channels").json()]
    assert "gpcrpromo" not in [x["slug"] for x in env["c"].get("/api/tg/meta").json()["channels"]]
    assert env["c"].delete("/api/channels/gpcrpromo").status_code == 404           # já removido
    assert env["c"].put("/api/channels/gpcrpromo", json={"enabled": True}).status_code == 404


def test_readicionar_canal_removido_volta_com_o_historico(env):
    env["c"].delete("/api/channels/gpcrpromo")
    r = env["c"].post("/api/channels", json={"handle": "@gpcrpromo"})
    assert r.status_code == 201 and r.json()["enabled"] is True
    assert env["fetch"].calls == ["https://t.me/s/gpcrpromo"]       # revalida a prévia


def test_rodada_le_so_os_canais_ativos_do_banco(env):
    env["c"].put("/api/channels/gpcrpromo", json={"enabled": False})
    env["c"].delete("/api/channels/OPromoFacil")
    env["c"].post("/api/channels", json={"handle": "@NovoCanal_1"})
    lidos = []

    def fetch(url):
        lidos.append(url.split("/s/")[1].split("?")[0])
        return "<html></html>"
    conn = conn_of(env)
    R.run_round(conn, fetch, lambda *a: "{}", datetime(2026, 10, 12), pause=0, log=lambda *_: None)
    assert "gpcrpromo" not in lidos and "OPromoFacil" not in lidos
    assert "NovoCanal_1" in lidos and len(lidos) == 8
    # a rodada não recoloca canal padrão desligado/removido
    row = conn.execute("SELECT active, removed_at FROM tg_channels WHERE slug = 'OPromoFacil'").fetchone()
    assert row["active"] == 0 and row["removed_at"]


def test_meta_da_tela_de_canais_vem_dos_cadastrados(env):
    env["c"].post("/api/channels", json={"handle": "@NovoCanal_1"})
    slugs = [x["slug"] for x in env["c"].get("/api/tg/meta").json()["channels"]]
    assert "NovoCanal_1" in slugs and len(slugs) == 10


def test_preview_fetch_real_usa_timeout_curto_e_uma_tentativa(monkeypatch):
    """O fetcher de verdade (sem rede: o httpx é trocado por um falso)."""
    import httpx
    seen = {}

    class Falso:
        def __init__(self, **kw):
            seen.update(kw)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url):
            seen.setdefault("urls", []).append(url)
            raise httpx.ConnectError("sem rede")
    monkeypatch.setattr(httpx, "Client", Falso)
    with pytest.raises(CH.ChannelUnreachable):
        CH.preview_fetch("https://t.me/s/abcd")
    assert seen["urls"] == ["https://t.me/s/abcd"] and seen["timeout"] <= 10


# =========================================================================== 5. o app respeita as configurações

def _ids(env):
    c = conn_of(env)
    return {r["kind"]: r["id"] for r in c.execute("SELECT id, kind FROM builds")}


def test_faixa_de_preco_filtra_pecas(env):
    ingest(env, [item(), item(url="https://www.kabum.com.br/produto/2/x", model="RTX 4090", price_cash=1_200_000)])
    assert len(env["c"].get("/api/parts").json()) == 2
    env["c"].put("/api/settings", json={"price_range": {"min": 1000, "max": 5000}})       # reais
    modelos = [p["model"] for p in env["c"].get("/api/parts").json()]
    assert modelos == ["GeForce RTX 4060 8GB"]                    # R$ 1.899,90 entra; R$ 12.000 sai
    env["c"].put("/api/settings", json={"price_range": {"min": 1900, "max": 5000}})
    assert env["c"].get("/api/parts").json() == []                # 1.899,90 < 1.900


def _promo(env):
    for n in range(10, 0, -1):
        ingest(env, [item(price_cash=200000)], when=day(n))
    ingest(env, [item(price_cash=150000)], when=day(0))


def test_faixa_de_preco_filtra_promocoes(env):
    _promo(env)
    assert len(env["c"].get("/api/deals").json()) == 1
    env["c"].put("/api/settings", json={"price_range": {"min": 0, "max": 1000}})
    assert env["c"].get("/api/deals").json() == []
    env["c"].put("/api/settings", json={"price_range": {"min": 1500, "max": 1500}})
    assert len(env["c"].get("/api/deals").json()) == 1           # R$ 1.500,00 exato entra


def test_loja_desligada_some_de_pecas_e_promocoes(env):
    _promo(env)
    ingest(env, [item(store="amazon", url="https://www.amazon.com.br/dp/B0TESTE0001", price_cash=210000)], when=day(0))
    assert env["c"].get("/api/parts").json()[0]["best"]["store"] == "kabum"
    env["c"].put("/api/settings", json={"stores": {"kabum": False}})
    assert env["c"].get("/api/deals").json() == []
    assert env["c"].get("/api/parts").json()[0]["best"]["store"] == "amazon"
    lojas = {s["slug"]: s["active"] for s in env["c"].get("/api/stores").json()}
    assert lojas["kabum"] == 0 and lojas["amazon"] == 1 and lojas["pichau"] == 1
    env["c"].post("/api/settings/reset/stores")
    assert len(env["c"].get("/api/deals").json()) == 1


def test_loja_desligada_por_env_tambem_some(env, monkeypatch):
    _promo(env)
    monkeypatch.setenv("PCB_STORES", "amazon,terabyte")
    assert env["c"].get("/api/deals").json() == []


def test_coleta_nao_busca_loja_desligada(tmp_path, monkeypatch):
    path = tmp_path / "t.db"
    conn = db.init_db(path)
    S.save(conn, {"stores": {"terabyte": False}})
    conn.close()
    pedidas = []

    def fetch(url):
        pedidas.append(url)
        return "<html></html>"
    wl = tmp_path / "wl.json"
    wl.write_text(json.dumps({"parts": [{"category": "gpu", "brand": "NVIDIA", "model": "RTX 4060",
                                         "query": "rtx 4060", "must": ["4060"]}]}))
    collect_run.main(["--watchlist", str(wl)], db_path=path, fetch=fetch, pause=0)
    assert pedidas and not any("terabyte" in u for u in pedidas)
    assert any("kabum" in u for u in pedidas) and any("amazon" in u for u in pedidas)


def test_compat_usa_o_pc_salvo(env):
    ingest(env, [item(category="cpu", brand="AMD", model="Ryzen 7 7700", specs={"socket": "AM5"},
                      url="https://www.kabum.com.br/produto/3/x", price_cash=150000)])
    pid = env["c"].get("/api/parts").json()[0]["id"]
    assert env["c"].get(f"/api/parts/{pid}").json()["compat"]["compatible"] is False        # exemplo é AM4
    assert env["c"].get("/api/parts?upgrade=true").json()[0]["compat"]["compatible"] is False
    env["c"].put("/api/settings", json={"current_pc": {"socket": "AM5", "memory_type": "DDR5",
                                                       "motherboard": "Placa AM5 qualquer"}})
    assert env["c"].get(f"/api/parts/{pid}").json()["compat"]["compatible"] is True
    assert env["c"].get("/api/parts?upgrade=true").json()[0]["compat"]["compatible"] is True
    up = _ids(env)["upgrade"]
    assert all(o["compat"]["compatible"] is True for o in env["c"].get(f"/api/builds/{up}/options/cpu").json())
    pc = env["c"].get("/api/current-pc").json()
    assert pc["socket"] == "AM5" and pc["motherboard"] == "Placa AM5 qualquer"


def test_aviso_de_compat_cita_a_placa_salva(env):
    env["c"].put("/api/settings", json={"current_pc": {"motherboard": "Minha Placa X", "form_factor": "mATX"}})
    ingest(env, [item(category="case", brand="X", model="Gabinete ITX", specs={"motherboard_support": ["ITX"]},
                      url="https://www.kabum.com.br/produto/4/x", price_cash=30000),
                 item(category="case", brand="X", model="Gabinete mATX", specs={"motherboard_support": ["mATX", "ITX"]},
                      url="https://www.kabum.com.br/produto/5/x", price_cash=31000)])
    by = {p["model"]: p["compat"] for p in env["c"].get("/api/parts?upgrade=true&category=case").json()}
    assert by["Gabinete ITX"]["compatible"] is False and "Minha Placa X" in by["Gabinete ITX"]["warnings"][0]
    assert by["Gabinete mATX"]["compatible"] is True                # mATX x MATX: mesma coisa


def test_check_upgrade_sem_pc_usa_o_exemplo():
    assert compat.check_upgrade("cpu", {"socket": "AM4"})["compatible"] is True
    assert compat.check_upgrade("cpu", {"socket": "AM4"}, {**compat.CURRENT_PC, "socket": "AM5"})["compatible"] is False


def test_openapi_lista_as_rotas_novas(env):
    paths = env["c"].get("/api/openapi.json").json()["paths"]
    assert {"get", "put"} <= set(paths["/api/settings"])
    assert "post" in paths["/api/settings/reset/{key}"]
    assert {"get", "post"} <= set(paths["/api/channels"])
    assert {"put", "delete"} <= set(paths["/api/channels/{slug}"])
