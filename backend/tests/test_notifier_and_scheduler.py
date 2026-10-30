"""Token do bot write-only (secrets.env), notificador (Telegram, saída padrão,
nenhum), agendador interno com trava de arquivo e modo jogo, e as rotas novas.

Sem rede: o Telegram é um httpx.MockTransport (nada sai da máquina); o conftest proíbe criar cliente de verdade.
Sem espera real: relógio falso, `sleep` falso e o laço do agendador com `wait` injetado."""

import io
import json
import logging
import os
import stat
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app import notify as N
from app import runlock
from app import scheduler as SC
from app import secrets_store as SS
from app import settings as S
from app.collect import run as collect_run
from app.db import database as db
from app.main import create_app
from app.tg import run as R
from tests import test_store_parsers as T4
from tests.test_telegram_channels import CH, GPU, fake_chat, fake_fetch, precos

BASE = "http://127.0.0.1:8787"
# Montado em pedaços: o verificador público (tools/check_public.py) não pode ver um token literal no código.
TOKEN = "987654" + "321:" + "AAH" + "fakeTokenForTestsOnly_0123456789"
TOKEN2 = "1122334" + "4:" + "BBx" + "outroTokenFalsoParaTeste-9876543"
CHAT = "123456"


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


def tg_server(responses=None):
    """Telegram falso: grava cada pedido. responses[método] = lista de (status, corpo) usada em ordem (a última
    se repete). Corpo que é função recebe o pedido e pode levantar exceção (ex.: queda de conexão)."""
    calls = []

    def handler(request):
        method = request.url.path.rsplit("/", 1)[1]
        calls.append({"url": str(request.url), "method": method, "json": json.loads(request.content or b"{}")})
        queue = (responses or {}).get(method)
        status, body = (queue.pop(0) if len(queue) > 1 else queue[0]) if queue else (200, {"ok": True, "result": {}})
        if callable(body):
            body = body(request)
        return httpx.Response(status, json=body)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    client.calls = calls
    return client


def data_dir():
    return Path(os.environ["PCB_DATA_DIR"])


def secrets_file():
    return data_dir() / "secrets.env"


@pytest.fixture
def env(tmp_path):
    clock = Clock()
    client = tg_server()
    steps_called = []
    steps = {"coleta": lambda n: steps_called.append("coleta"), "canais": lambda n: steps_called.append("canais")}
    app = create_app(db_path=tmp_path / "t.db", frontend_dist=tmp_path / "x", channel_fetch=lambda u: "",
                     http_client=client, clock=clock, scheduler_steps=steps, spawn=lambda fn: fn(),
                     proc_root=tmp_path / "proc",       # Ollama falso, sempre com erro 503
                     ollama_http=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503))))
    (tmp_path / "proc").mkdir()
    return {"c": TestClient(app, base_url=BASE), "db_path": tmp_path / "t.db", "tmp": tmp_path, "clock": clock,
            "tg": client, "steps": steps_called, "app": app}


def put_secret(env, **body):
    return env["c"].put("/api/secrets/telegram", json=body)


# =========================================================================== 1. validação do token e do chat id

@pytest.mark.parametrize("bom", [TOKEN, TOKEN2, "123456:" + "a" * 30, "123456789012:" + "Z-_" * 16 + "ab"])
def test_token_valido(bom):
    assert SS.validate_token(bom) == bom
    assert SS.validate_token(f"  {bom}\n") == bom          # colado com espaço/quebra de linha nas pontas


@pytest.mark.parametrize("ruim", ["", "abc", "12345:" + "a" * 35, "1234567890123:" + "a" * 35, "123456:" + "a" * 29,
                                  "123456:" + "a" * 51, "123456:" + "a" * 20 + "!" + "a" * 14,
                                  "123456 :" + "a" * 35, TOKEN + "\nPCB_TELEGRAM_CHAT_ID=1", None, 123, ["x"]])
def test_token_invalido_sem_eco(ruim):
    with pytest.raises(SS.SecretsError) as e:
        SS.validate_token(ruim)
    if isinstance(ruim, str) and len(ruim) > 6:
        assert ruim.strip()[-12:] not in str(e.value)


@pytest.mark.parametrize("bom", ["123456", "-1001234567890", "@meu_canal", "1", "-" + "9" * 20])
def test_chat_id_valido(bom):
    assert SS.validate_chat_id(bom) == bom


@pytest.mark.parametrize("ruim", ["", "abc", "@abc", "@" + "a" * 33, "12 34", "-", "9" * 21, "1\n2", "@canal!",
                                  "@cañal", None, 12345])
def test_chat_id_invalido(ruim):
    with pytest.raises(SS.SecretsError):
        SS.validate_chat_id(ruim)


def test_mascara_so_os_4_ultimos():
    assert SS.hint(TOKEN) == "…" + TOKEN[-4:]
    assert SS.hint(None) is None


# =========================================================================== 2. arquivo secrets.env

def test_arquivo_criado_0600_no_diretorio_de_dados():
    store = SS.SecretStore()
    store.save(token=TOKEN, chat_id=CHAT)
    f = secrets_file()
    assert stat.S_IMODE(f.stat().st_mode) == 0o600 and f.stat().st_uid == os.getuid()
    assert f.read_text().splitlines() == [f"PCB_TELEGRAM_TOKEN={TOKEN}", f"PCB_TELEGRAM_CHAT_ID={CHAT}"]
    assert [p.name for p in data_dir().iterdir()] == ["secrets.env"]       # sem arquivo temporário sobrando


def test_0600_mesmo_com_umask_aberta():
    old = os.umask(0)
    try:
        SS.SecretStore().save(token=TOKEN)
    finally:
        os.umask(old)
    assert stat.S_IMODE(secrets_file().stat().st_mode) == 0o600


def test_escrita_atomica_troca_o_arquivo_inteiro():
    store = SS.SecretStore()
    store.save(token=TOKEN, chat_id=CHAT)
    ino = secrets_file().stat().st_ino
    store.save(token=TOKEN2)
    assert secrets_file().stat().st_ino != ino                             # os.replace: arquivo novo
    assert store.get("token") == (TOKEN2, "file") and store.get("chat_id") == (CHAT, "file")


def test_recusa_link_simbolico(tmp_path, caplog):
    alvo = tmp_path / "outro.txt"
    alvo.write_text("nao mexa\n")
    secrets_file().symlink_to(alvo)
    store = SS.SecretStore()
    with pytest.raises(SS.SecretsFileError):
        store.save(token=TOKEN)
    assert alvo.read_text() == "nao mexa\n" and secrets_file().is_symlink()
    assert store.get("token") == (None, None)                              # leitura também recusa
    assert store.status()["file_error"]


def test_permissao_aberta_e_corrigida_com_aviso(caplog):
    SS.SecretStore().save(token=TOKEN)
    secrets_file().chmod(0o644)
    caplog.set_level(logging.WARNING)
    assert SS.SecretStore().get("token") == (TOKEN, "file")
    assert stat.S_IMODE(secrets_file().stat().st_mode) == 0o600
    assert "0600" in caplog.text and TOKEN not in caplog.text


def test_variavel_de_ambiente_vence_o_arquivo(monkeypatch):
    store = SS.SecretStore()
    store.save(token=TOKEN, chat_id=CHAT)
    monkeypatch.setenv("PCB_TELEGRAM_TOKEN", TOKEN2)
    assert store.get("token") == (TOKEN2, "env")
    assert store.get("chat_id") == (CHAT, "file")
    with pytest.raises(SS.SecretsLocked):
        store.save(token=TOKEN)


def test_remover_apaga_o_arquivo():
    store = SS.SecretStore()
    store.save(token=TOKEN, chat_id=CHAT)
    store.clear()
    assert not secrets_file().exists() and store.get("token") == (None, None)


def test_arquivo_com_lixo_e_linha_invalida_e_ignorado():
    secrets_file().write_text(f"# comentário\nOUTRA=1\nPCB_TELEGRAM_TOKEN=nao-e-token\nPCB_TELEGRAM_CHAT_ID={CHAT}\n")
    secrets_file().chmod(0o600)
    assert SS.SecretStore().get("token") == (None, None)
    assert SS.SecretStore().get("chat_id") == (CHAT, "file")


# =========================================================================== 3. rotas /api/secrets/telegram

def test_estado_sem_nada(env):
    j = env["c"].get("/api/secrets/telegram").json()
    assert (j["configured"], j["source"], j["hint"]) == (False, None, None)
    assert j["chat_id"]["configured"] is False and j["ready"] is False


def test_put_salva_e_devolve_so_a_mascara(env):
    r = put_secret(env, token=TOKEN, chat_id=CHAT)
    assert r.status_code == 200
    j = r.json()
    assert (j["configured"], j["source"], j["hint"]) == (True, "file", "…" + TOKEN[-4:])
    assert j["ready"] is True and j["chat_id"]["configured"] is True
    assert TOKEN[-5:] not in r.text and TOKEN[:12] not in r.text           # nada além dos 4 últimos
    g = env["c"].get("/api/secrets/telegram")
    assert g.json() == j and TOKEN[-5:] not in g.text


def test_token_nunca_vai_para_o_banco(env):
    put_secret(env, token=TOKEN, chat_id=CHAT)
    env["c"].put("/api/settings", json={"notify_target": "telegram"})
    raw = env["db_path"].read_bytes()
    assert TOKEN.encode() not in raw and TOKEN[-10:].encode() not in raw
    assert TOKEN not in json.dumps(env["c"].get("/api/settings").json())


@pytest.mark.parametrize("body", [{"token": "123:abc"}, {"token": TOKEN[:-10]}, {"chat_id": "abc"},
                                  {"token": TOKEN + "!"}, {"token": TOKEN, "x": 1}, {}, [], "texto", None])
def test_put_invalido_da_422_sem_eco(env, body):
    r = env["c"].put("/api/secrets/telegram", content=json.dumps(body), headers={"Content-Type": "application/json"})
    assert r.status_code == 422
    assert TOKEN[:-10] not in r.text and "123:abc" not in r.text
    assert not secrets_file().exists()


def test_json_quebrado_com_o_token_da_422_sem_eco(env):
    r = env["c"].put("/api/secrets/telegram", content=b'{"token": "' + TOKEN.encode() + b'"',
                     headers={"Content-Type": "application/json"})
    assert r.status_code == 422 and TOKEN not in r.text and TOKEN[-10:] not in r.text


def test_origem_env_bloqueia_o_put(env, monkeypatch):
    monkeypatch.setenv("PCB_TELEGRAM_TOKEN", TOKEN2)
    j = env["c"].get("/api/secrets/telegram").json()
    assert (j["source"], j["configured"], j["hint"]) == ("env", True, "…" + TOKEN2[-4:])
    r = put_secret(env, token=TOKEN)
    assert r.status_code == 409 and "variável de ambiente" in r.json()["detail"]
    assert not secrets_file().exists()
    assert put_secret(env, chat_id=CHAT).status_code == 200                 # o chat id continua livre


def test_delete_remove(env):
    put_secret(env, token=TOKEN, chat_id=CHAT)
    r = env["c"].delete("/api/secrets/telegram")
    assert r.status_code == 200 and r.json()["configured"] is False and not secrets_file().exists()


@pytest.mark.parametrize("metodo,rota,corpo", [
    ("PUT", "/api/secrets/telegram", {"token": TOKEN}),
    ("DELETE", "/api/secrets/telegram", None),
    ("POST", "/api/secrets/telegram/detect-chat", None),
    ("POST", "/api/notify/test", None),
    ("POST", "/api/scheduler/run-now", None),
])
def test_rotas_novas_tem_a_trava_de_escrita(env, metodo, rota, corpo):
    kw = {"json": corpo} if corpo is not None else {}
    assert env["c"].request(metodo, rota, headers={"Origin": "http://evil.example"}, **kw).status_code == 403
    evil = TestClient(env["app"], base_url="http://evil.example:8787")
    assert evil.request(metodo, rota, **kw).status_code == 403
    assert not secrets_file().exists() and env["steps"] == [] and env["tg"].calls == []


# =========================================================================== 4. vazamento: respostas e logs

def _sample(path):
    subs = {"{part_id}": "1", "{build_id}": "1", "{category}": "gpu", "{name}": "x_1.jpg", "{slug}": CH,
            "{key}": "language"}
    for k, v in subs.items():
        path = path.replace(k, v)
    return path


@pytest.mark.parametrize("origem", ["file", "env"])
def test_token_nao_aparece_em_nenhuma_resposta_nem_log(env, monkeypatch, caplog, capsys, origem):
    caplog.set_level(logging.DEBUG)
    if origem == "env":
        monkeypatch.setenv("PCB_TELEGRAM_TOKEN", TOKEN)
        put_secret(env, chat_id=CHAT)
    else:
        put_secret(env, token=TOKEN, chat_id=CHAT)
    env["tg"].calls.clear()
    c = env["c"]
    responses = []
    paths = c.get("/api/openapi.json").json()["paths"]
    for p, methods in paths.items():
        if "get" in methods:
            responses.append(c.get(_sample(p)))
    c.put("/api/settings", json={"notify_target": "telegram"})
    responses += [
        put_secret(env, token="123:" + TOKEN[-20:]),                         # inválido, com pedaço do token
        c.post("/api/secrets/telegram/detect-chat"),
        c.post("/api/notify/test", json={"target": "telegram"}),
        c.post("/api/scheduler/run-now"),
        c.get("/api/secrets/telegram"),
        c.get("/api/scheduler"),
    ]
    out = capsys.readouterr()
    textos = [r.text for r in responses] + [str(dict(r.headers)) for r in responses] + [caplog.text, out.out, out.err]
    for t in textos:
        assert TOKEN not in t and TOKEN[-12:] not in t and TOKEN[:10] not in t
    assert env["tg"].calls                                                   # o token foi usado de verdade (no falso)
    assert all(TOKEN in call["url"] for call in env["tg"].calls)


# =========================================================================== 5. notificador

def u16(s):
    return len(s.encode("utf-16-le")) // 2


def test_divide_em_4096_pelas_linhas():
    linhas = [f"• linha {i} " + "x" * 90 for i in range(150)]
    texto = "\n".join(linhas)
    parts = N.split_message(texto)
    assert len(parts) >= 4 and all(u16(p) <= 4096 for p in parts)
    assert "\n".join(parts) == texto


def test_divide_linha_gigante_e_conta_emoji_como_2():
    texto = "🛰" * 3000                                                   # 6000 unidades UTF-16
    parts = N.split_message(texto)
    assert len(parts) == 2 and all(u16(p) <= 4096 for p in parts) and "".join(parts) == texto
    assert N.split_message("curta") == ["curta"]
    assert N.split_message("x" * 4096) == ["x" * 4096]


def test_telegram_manda_texto_simples_em_partes():
    client = tg_server()
    bot = N.TelegramBot(TOKEN, CHAT, client=client, sleep=lambda s: None)
    res = bot.send("a" * 5000)
    assert res.ok and res.parts == 2
    assert [c["url"] for c in client.calls] == [f"https://api.telegram.org/bot{TOKEN}/sendMessage"] * 2
    assert all(c["json"]["chat_id"] == CHAT and "parse_mode" not in c["json"] for c in client.calls)
    assert "".join(c["json"]["text"] for c in client.calls) == "a" * 5000


def test_429_espera_o_retry_after_e_tenta_1_vez():
    pausas = []
    client = tg_server({"sendMessage": [(429, {"ok": False, "parameters": {"retry_after": 3}}),
                                        (200, {"ok": True, "result": {}})]})
    res = N.TelegramBot(TOKEN, CHAT, client=client, sleep=pausas.append).send("oi")
    assert res.ok and pausas == [3] and len(client.calls) == 2


def test_429_de_novo_desiste_sem_loop():
    pausas = []
    client = tg_server({"sendMessage": [(429, {"ok": False, "parameters": {"retry_after": 2}})]})
    res = N.TelegramBot(TOKEN, CHAT, client=client, sleep=pausas.append).send("oi")
    assert not res.ok and pausas == [2] and len(client.calls) == 2


def test_429_com_espera_longa_nao_trava():
    pausas = []
    client = tg_server({"sendMessage": [(429, {"ok": False, "parameters": {"retry_after": 3600}})]})
    res = N.TelegramBot(TOKEN, CHAT, client=client, sleep=pausas.append).send("oi")
    assert not res.ok and pausas == [] and len(client.calls) == 1


def test_queda_de_conexao_mascara_o_token():
    def cai(request):
        raise httpx.ConnectError(f"falhou ao abrir {request.url}", request=request)
    client = tg_server({"sendMessage": [(200, cai)], "getMe": [(200, cai)]})
    bot = N.TelegramBot(TOKEN, CHAT, client=client, sleep=lambda s: None)
    res = bot.send("oi")
    assert not res.ok and "sem conexão" in res.error and TOKEN not in res.error and "bot***" in res.error
    with pytest.raises(N.NotifyError) as e:
        bot.get_me()
    tb = "".join(traceback.format_exception(e.value))
    assert TOKEN not in tb and TOKEN not in repr(bot) and TOKEN not in repr(e.value)


def test_erro_do_telegram_vira_mensagem_tratada():
    client = tg_server({"sendMessage": [(401, {"ok": False, "description": f"Unauthorized {TOKEN}"})]})
    res = N.TelegramBot(TOKEN, CHAT, client=client).send("oi")
    assert not res.ok and "token" in res.error and TOKEN not in res.error
    client = tg_server({"sendMessage": [(400, {"ok": False, "description": "Bad Request: chat not found"})]})
    assert "/start" in N.TelegramBot(TOKEN, CHAT, client=client).send("oi").error


def test_log_do_httpx_nao_mostra_a_url_com_token(caplog):
    caplog.set_level(logging.DEBUG)
    N.TelegramBot(TOKEN, CHAT, client=tg_server()).send("oi")
    assert "api.telegram.org" in caplog.text                       # o httpx logou o pedido...
    assert TOKEN not in caplog.text and TOKEN[-12:] not in caplog.text   # ...sem o token


def test_redact_pega_qualquer_token():
    assert N.redact(f"x https://api.telegram.org/bot{TOKEN}/getMe y") == "x https://api.telegram.org/bot***/getMe y"


def test_stdout_imprime_igual_ao_print(capsys):
    assert N.Stdout().send("🛰 linha\nlinha 2").ok
    assert capsys.readouterr().out == "🛰 linha\nlinha 2\n"


def test_make_notifier_escolhe_pelo_destino(caplog):
    store = SS.SecretStore()
    assert isinstance(N.make_notifier({"notify_target": "stdout"}, store), N.Stdout)
    assert isinstance(N.make_notifier({"notify_target": "none"}, store), N.NoneNotifier)
    caplog.set_level(logging.WARNING)
    n1 = N.make_notifier({"notify_target": "telegram"}, store)
    n2 = N.make_notifier({"notify_target": "telegram"}, store)
    assert isinstance(n1, N.Stdout) and isinstance(n2, N.Stdout)    # sem token: cai na saída padrão
    assert caplog.text.count("falta o token ou o chat") == 1        # e avisa uma vez só
    store.save(token=TOKEN, chat_id=CHAT)
    bot = N.make_notifier({"notify_target": "telegram"}, store, client=tg_server())
    assert isinstance(bot, N.TelegramBot)


def test_nenhum_nao_manda_nada(capsys):
    assert N.NoneNotifier().send("x").ok and capsys.readouterr().out == ""


def test_chats_do_getupdates():
    upd = [{"update_id": 1, "message": {"chat": {"id": 111, "type": "private", "first_name": "Ana", "last_name": "B"}}},
           {"update_id": 2, "message": {"chat": {"id": 111, "type": "private", "first_name": "Ana"}}},
           {"update_id": 3, "my_chat_member": {"chat": {"id": -100222, "type": "supergroup", "title": "Grupo"}}},
           {"update_id": 4, "channel_post": {"chat": {"id": -100333, "type": "channel", "title": "Canal",
                                                       "username": "meucanal"}}},
           {"update_id": 5, "edited_message": {"chat": {"id": 444, "type": "private", "username": "zé"}}},
           {"update_id": 6, "outra_coisa": {}}]
    assert N.chats_from_updates(upd) == [
        {"id": "111", "tipo": "privado", "nome": "Ana B"},
        {"id": "-100222", "tipo": "supergrupo", "nome": "Grupo"},
        {"id": "-100333", "tipo": "canal", "nome": "Canal"},
        {"id": "444", "tipo": "privado", "nome": "@zé"}]


def test_deliver_cai_na_saida_padrao_se_o_telegram_falhar(capsys):
    client = tg_server({"sendMessage": [(500, {"ok": False, "description": "x"})]})
    res = N.deliver(N.TelegramBot(TOKEN, CHAT, client=client), "aviso importante")
    out = capsys.readouterr()
    assert not res.ok and out.out == "aviso importante\n" and TOKEN not in out.err


# =========================================================================== 6. rotas de teste e detectar chat

def test_mensagem_de_teste_pelo_telegram(env):
    put_secret(env, token=TOKEN, chat_id=CHAT)
    r = env["c"].post("/api/notify/test", json={"target": "telegram"})
    assert r.status_code == 200 and r.json() == {"ok": True, "target": "telegram"}
    assert [c["json"] for c in env["tg"].calls] == [{"chat_id": CHAT, "text": "PC Builder: mensagem de teste"}]


def test_mensagem_de_teste_usa_o_destino_salvo(env, capsys):
    r = env["c"].post("/api/notify/test")                            # padrão: stdout
    assert r.status_code == 200 and r.json()["target"] == "stdout"
    assert capsys.readouterr().out == "PC Builder: mensagem de teste\n" and env["tg"].calls == []


@pytest.mark.parametrize("prep", ["nada", "so_token", "nenhum"])
def test_mensagem_de_teste_sem_configuracao_da_409(env, prep):
    if prep == "so_token":
        put_secret(env, token=TOKEN)
    body = {"target": "none"} if prep == "nenhum" else {"target": "telegram"}
    r = env["c"].post("/api/notify/test", json=body)
    assert r.status_code == 409 and env["tg"].calls == []


def test_mensagem_de_teste_destino_invalido_422(env):
    assert env["c"].post("/api/notify/test", json={"target": "email"}).status_code == 422


def test_limite_1_teste_a_cada_10s_e_20_por_hora(env):
    put_secret(env, token=TOKEN, chat_id=CHAT)
    send = lambda: env["c"].post("/api/notify/test", json={"target": "telegram"})
    assert send().status_code == 200
    r = send()
    assert r.status_code == 429 and int(r.headers["Retry-After"]) >= 1
    for _ in range(19):
        env["clock"].advance(10)
        assert send().status_code == 200
    env["clock"].advance(10)
    assert send().status_code == 429                                 # 21º na mesma hora
    env["clock"].advance(3600)
    assert send().status_code == 200
    assert len(env["tg"].calls) == 21


def test_erro_do_telegram_no_teste_vira_502_tratado(env):
    put_secret(env, token=TOKEN, chat_id=CHAT)
    env["tg"].calls.clear()

    def cai(request):
        raise httpx.ConnectError(f"sem rota para {request.url}", request=request)
    app = create_app(db_path=env["db_path"], frontend_dist=env["tmp"] / "x", http_client=tg_server(
        {"sendMessage": [(200, cai)]}), clock=Clock())
    r = TestClient(app, base_url=BASE).post("/api/notify/test", json={"target": "telegram"})
    assert r.status_code == 502 and "sem conexão" in r.json()["detail"] and TOKEN not in r.text


def test_detectar_chat(tmp_path):
    client = tg_server({"getMe": [(200, {"ok": True, "result": {"username": "meu_pc_bot"}})],
                        "getUpdates": [(200, {"ok": True, "result": [
                            {"update_id": 1, "message": {"chat": {"id": 555, "type": "private", "first_name": "Ana"}}}]})]})
    app = create_app(db_path=tmp_path / "t.db", frontend_dist=tmp_path / "x", http_client=client, clock=Clock())
    c = TestClient(app, base_url=BASE)
    assert c.post("/api/secrets/telegram/detect-chat").status_code == 409          # sem token
    c.put("/api/secrets/telegram", json={"token": TOKEN})
    r = c.post("/api/secrets/telegram/detect-chat")
    assert r.status_code == 200
    assert r.json() == {"bot": "meu_pc_bot", "chats": [{"id": "555", "tipo": "privado", "nome": "Ana"}]}
    assert TOKEN not in r.text and TOKEN[-5:] not in r.text
    assert {x["method"] for x in client.calls} == {"getMe", "getUpdates"}


def test_detectar_chat_vazio_explica_o_start(env):
    put_secret(env, token=TOKEN)
    r = env["c"].post("/api/secrets/telegram/detect-chat")
    assert r.status_code == 200 and r.json()["chats"] == [] and "/start" in r.json()["hint"]


def test_detectar_chat_token_recusado(tmp_path):
    client = tg_server({"getMe": [(401, {"ok": False, "description": "Unauthorized"})]})
    c = TestClient(create_app(db_path=tmp_path / "t.db", frontend_dist=tmp_path / "x", http_client=client,
                              clock=Clock()), base_url=BASE)
    c.put("/api/secrets/telegram", json={"token": TOKEN})
    r = c.post("/api/secrets/telegram/detect-chat")
    assert r.status_code == 502 and "token" in r.json()["detail"] and TOKEN not in r.text


def test_detectar_chat_tem_limite(env):
    put_secret(env, token=TOKEN)
    assert env["c"].post("/api/secrets/telegram/detect-chat").status_code == 200
    assert env["c"].post("/api/secrets/telegram/detect-chat").status_code == 429


# =========================================================================== 7. regressão do --notify (cron/Hermes)

# Saídas de antes do notificador (capturadas do código anterior com os mesmos dados falsos).
OUT_CANAIS = ("🛰 Promoção nos canais\n• Placa de Vídeo RTX 5060 8GB GDDR7 Palit\n  R$ 2.564,00 (?) — menor preço já "
              "visto; típico R$ 2.700,00, menor antes R$ 2.690,00 (3 preços)\n  https://t.me/gpcrpromo/4\n")
OUT_COLETA = ("🎯 Abaixo do alvo\n• AMD Ryzen 5 5600: R$ 858,80 na Amazon (alvo R$ 900,00)\n  "
              "https://www.amazon.com.br/dp/B09VCHR1VH\n🧯 Coleta com problema\n• kabum: ConnectionError: fora do ar\n"
              "Painel: http://127.0.0.1:8787\n")


def canais_main(tmp_path, **kw):
    path = tmp_path / "t.db"
    conn = db.init_db(path)
    precos(conn, ["2.700,00", "2.750,00", "2.690,00"], day=10)
    conn.close()
    fetch = fake_fetch({CH: [(4, "2026-10-11T10:00:00", GPU.format("2.564,00"))]})
    rc = R.main(["--notify", "--channels", CH], db_path=path, fetch=fetch, chat=fake_chat(default="peca:gpu"),
                pause=0, now=datetime(2026, 10, 11, 12), img_get=lambda u: None, img_dir=tmp_path / "img", **kw)
    return rc, fetch, path


def coleta_main(tmp_path, **kw):
    wl = tmp_path / "wl.json"
    wl.write_text(json.dumps({"parts": [w.__dict__ for w in T4.WL]}))
    fetch = T4.fake_fetch(broken=("kabum",))
    rc = collect_run.main(["--watchlist", str(wl), "--notify"], db_path=tmp_path / "c.db", fetch=fetch, pause=0,
                          now=datetime(2026, 10, 9, 9), **kw)
    return rc, fetch


def test_notify_dos_canais_imprime_igual_a_antes(tmp_path, capsys):
    rc, _, _ = canais_main(tmp_path)
    out = capsys.readouterr()
    assert rc == 0 and out.out == OUT_CANAIS


def test_notify_da_coleta_imprime_igual_a_antes(tmp_path, capsys):
    rc, _ = coleta_main(tmp_path)
    assert rc == 1 and capsys.readouterr().out == OUT_COLETA


def test_notify_com_telegram_manda_pelo_bot_e_nao_imprime(tmp_path, capsys):
    client = tg_server()
    rc, _, path = canais_main(tmp_path, notifier=N.TelegramBot(TOKEN, CHAT, client=client))
    assert rc == 0 and capsys.readouterr().out == ""
    assert [c["json"]["text"] + "\n" for c in client.calls] == [OUT_CANAIS]
    conn = db.connect(path)
    assert conn.execute("SELECT COUNT(*) FROM tg_alerts_sent").fetchone()[0] == 1


def test_notify_usa_o_destino_salvo_sem_notifier_injetado(tmp_path, capsys):
    path = tmp_path / "t.db"
    conn = db.init_db(path)
    S.save(conn, {"notify_target": "none"})
    conn.close()
    rc, _, _ = canais_main(tmp_path)
    assert rc == 0 and capsys.readouterr().out == ""


# =========================================================================== 8. trava de arquivo

def test_trava_nao_deixa_duas_rodadas():
    a, b = runlock.round_lock(), runlock.round_lock()
    assert a.acquire() and not b.acquire() and not a.acquire()
    a.release()
    assert b.acquire()
    b.release()
    assert (data_dir() / "rodada.lock").exists()


def test_trava_vale_entre_processos():
    lock = runlock.round_lock()
    code = ("import fcntl, os, sys; fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o600)\n"
            "try:\n fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB); print('livre')\n"
            "except BlockingIOError:\n print('ocupada')")
    other = lambda: subprocess.run([sys.executable, "-c", code, str(data_dir() / "rodada.lock")],
                                   capture_output=True, text=True, timeout=30).stdout.strip()
    assert lock.acquire()
    try:
        assert other() == "ocupada"
    finally:
        lock.release()
    assert other() == "livre"


def test_espera_pela_trava_com_relogio_falso():
    a, b = runlock.round_lock(), runlock.round_lock()
    a.acquire()
    clock, pausas = Clock(0), []

    def sleep(s):
        pausas.append(s)
        clock.advance(s)
    assert not b.acquire(wait=12, sleep=sleep, clock=clock)
    assert sum(pausas) >= 12 and len(pausas) >= 2
    a.release()


@pytest.mark.parametrize("qual", ["canais", "coleta"])
def test_cli_com_a_trava_ocupada_nao_roda(tmp_path, capsys, qual):
    lock = runlock.round_lock()
    assert lock.acquire()
    try:
        if qual == "canais":
            rc, fetch, _ = canais_main(tmp_path, lock_wait=0)
        else:
            rc, fetch = coleta_main(tmp_path, lock_wait=0)
    finally:
        lock.release()
    out = capsys.readouterr()
    assert rc == 0 and out.out == "" and fetch.calls == [] and "outra rodada" in out.err


# =========================================================================== 9. agendador

class Rec:
    """Notificador falso que guarda o que mandaria."""

    def __init__(self):
        self.sent = []

    def send(self, text):
        self.sent.append(text)
        return N.Result(True)


def make_sched(tmp_path, cfg=None, steps=None, game=False, clock=None, notifier=None, **kw):
    cfg = {"scheduler_enabled": True, "collect_every_minutes": 60, "game_mode": False, **(cfg or {})}
    calls = []
    steps = steps or {"coleta": lambda n: calls.append("coleta"), "canais": lambda n: calls.append("canais")}
    rec = notifier or Rec()
    kw.setdefault("game_available", True)
    sch = SC.Scheduler(settings=lambda: cfg, steps=steps, notifier=lambda: rec, lock=runlock.round_lock(),
                       clock=clock or Clock(), game_running=lambda: game, state_path=tmp_path / "agendador.json",
                       spawn=lambda fn: fn(), **kw)
    sch.calls, sch.rec, sch.cfg = calls, rec, cfg
    return sch


def test_desligado_nunca_roda(tmp_path):
    sch = make_sched(tmp_path, {"scheduler_enabled": False})
    for _ in range(50):
        assert sch.tick() == "desligado"
        sch.clock.advance(3600)
    assert sch.calls == [] and sch.status()["next_run_at"] is None


def test_roda_no_intervalo(tmp_path):
    sch = make_sched(tmp_path)
    assert sch.tick() == "esperando"                       # 1ª rodada: 1 min depois de ligar
    sch.clock.advance(SC.START_DELAY_S)
    assert sch.tick() == "rodou" and sch.calls == ["coleta", "canais"]
    sch.clock.advance(59 * 60)
    assert sch.tick() == "esperando"
    sch.clock.advance(60)
    assert sch.tick() == "rodou" and sch.calls == ["coleta", "canais"] * 2
    st = sch.status()
    assert st["last_ok"] is True and st["last_error"] is None and st["running"] is False


def test_mudar_o_intervalo_vale_na_hora(tmp_path):
    sch = make_sched(tmp_path, {"collect_every_minutes": 1440})
    sch.clock.advance(SC.START_DELAY_S)
    sch.tick()
    sch.cfg["collect_every_minutes"] = 30
    sch.clock.advance(30 * 60)
    assert sch.tick() == "rodou"


def test_lembra_a_ultima_rodada_depois_de_reiniciar(tmp_path):
    clock = Clock()
    sch = make_sched(tmp_path, clock=clock)
    clock.advance(SC.START_DELAY_S)
    sch.tick()
    novo = make_sched(tmp_path, clock=clock)                 # servidor reiniciou 10 min depois
    clock.advance(600)
    assert novo.tick() == "esperando"
    clock.advance(50 * 60)
    assert novo.tick() == "rodou"


def test_trava_ocupada_pula_e_tenta_depois(tmp_path):
    sch = make_sched(tmp_path)
    sch.clock.advance(SC.START_DELAY_S)
    cron = runlock.round_lock()
    cron.acquire()                                          # um cron externo está rodando
    try:
        assert sch.tick() == "ocupado" and sch.calls == []
    finally:
        cron.release()
    sch.clock.advance(SC.BUSY_RETRY_S)
    assert sch.tick() == "rodou"


def test_erro_numa_etapa_nao_para_a_outra_e_vira_aviso_1_por_hora(tmp_path):
    calls = []

    def quebra(n):
        calls.append("coleta")
        raise RuntimeError(f"loja caiu bot{TOKEN}")
    sch = make_sched(tmp_path, steps={"coleta": quebra, "canais": lambda n: calls.append("canais")})
    sch.clock.advance(SC.START_DELAY_S)
    assert sch.tick() == "falhou" and calls == ["coleta", "canais"]
    assert len(sch.rec.sent) == 1 and "coleta" in sch.rec.sent[0] and TOKEN not in sch.rec.sent[0]
    assert "coleta" in sch.status()["last_error"] and TOKEN not in sch.status()["last_error"]
    sch.clock.advance(15 * 60)                              # backoff: tenta de novo em 15 min, depois 30
    assert sch.tick() == "falhou"
    sch.clock.advance(30 * 60)
    assert sch.tick() == "falhou"
    assert len(sch.rec.sent) == 1                           # 3 erros em 45 min: 1 aviso só
    sch2 = make_sched(tmp_path, steps={"coleta": quebra, "canais": lambda n: None})
    sch2.run_now()
    sch2.clock.advance(1800)
    sch2.run_now()
    assert len(sch2.rec.sent) == 1                          # 2 erros em 30 min: 1 aviso
    sch2.clock.advance(1801)
    sch2.run_now()
    assert len(sch2.rec.sent) == 2                          # passou 1 h: avisa de novo


def test_backoff_depois_de_erro_e_volta_ao_normal(tmp_path):
    estado = {"quebra": True}

    def etapa(n):
        if estado["quebra"]:
            raise RuntimeError("x")
    sch = make_sched(tmp_path, {"collect_every_minutes": 1440}, steps={"coleta": etapa})
    sch.clock.advance(SC.START_DELAY_S)
    assert sch.tick() == "falhou"
    t0 = sch.clock()
    assert sch._next_run == t0 + SC.RETRY_BASE_S
    sch.clock.advance(SC.RETRY_BASE_S)
    assert sch.tick() == "falhou" and sch._next_run == sch.clock() + 2 * SC.RETRY_BASE_S
    estado["quebra"] = False
    sch.clock.advance(2 * SC.RETRY_BASE_S)
    assert sch.tick() == "rodou" and sch._next_run == sch.clock() + 1440 * 60


def test_excecao_nunca_derruba_o_laco(tmp_path):
    vezes = {"n": 0}

    def cfg_quebrado():
        vezes["n"] += 1
        raise RuntimeError("banco travado")
    sch = SC.Scheduler(settings=cfg_quebrado, steps={}, notifier=Rec, lock=runlock.round_lock(), clock=Clock(),
                       state_path=tmp_path / "a.json")
    esperas = []

    def wait(s):
        esperas.append(s)
        if len(esperas) >= 3:
            sch._stop.set()
        return sch._stop.is_set()
    sch._wait = wait
    sch._loop()                                             # volta sozinho (stop), sem exceção
    assert vezes["n"] == 3 and len(esperas) == 3


def test_modo_jogo_pula_sem_avisar(tmp_path):
    sch = make_sched(tmp_path, {"game_mode": True}, game=True)
    sch.clock.advance(SC.START_DELAY_S)
    assert sch.tick() == "jogo" and sch.calls == [] and sch.rec.sent == []
    sch.cfg["game_mode"] = False                            # modo jogo desligado: roda mesmo com jogo aberto
    sch.clock.advance(SC.GAME_RETRY_S)
    assert sch.tick() == "rodou"


def test_modo_jogo_indisponivel_no_docker_nao_pula(tmp_path):
    sch = make_sched(tmp_path, {"game_mode": True}, game=True, game_available=False)
    sch.clock.advance(SC.START_DELAY_S)
    assert sch.tick() == "rodou" and sch.status()["game_mode_available"] is False


def proc_with(tmp_path, *cmdlines):
    root = tmp_path / "proc"
    root.mkdir(exist_ok=True)
    (root / "self").mkdir(exist_ok=True)
    for i, cmd in enumerate(cmdlines, 100):
        (root / str(i)).mkdir()
        (root / str(i) / "cmdline").write_bytes(b"\0".join(c.encode() for c in cmd.split(" ")) + b"\0")
    (root / "999").mkdir()                                  # processo que sumiu no meio (sem cmdline)
    return root


def test_jogo_aberto_pelo_proc(tmp_path):
    root = proc_with(tmp_path, "/usr/bin/bash", "/steam/ubuntu12_32/reaper SteamLaunch AppId=123 -- jogo")
    assert SC.game_running(proc_root=root) is True
    assert SC.game_running("gamescope", proc_root=root) is False
    assert SC.game_running("bash$", proc_root=root) is True
    assert SC.game_running("[invalido", proc_root=root) is False            # regex ruim: literal, sem quebrar
    assert SC.game_running(proc_root=tmp_path / "nao_existe") is False


def test_padrao_do_jogo_vem_do_ambiente(tmp_path, monkeypatch):
    root = proc_with(tmp_path, "meujogo --fullscreen")
    assert SC.game_running(proc_root=root) is False
    monkeypatch.setenv("PCB_GAME_PATTERN", "meujogo")
    assert SC.game_running(proc_root=root) is True


def test_docker_detectado(tmp_path, monkeypatch):
    assert SC.in_docker(marker=tmp_path / "nada") is False
    (tmp_path / ".dockerenv").touch()
    assert SC.in_docker(marker=tmp_path / ".dockerenv") is True
    monkeypatch.setenv("PCB_IN_DOCKER", "1")
    assert SC.in_docker(marker=tmp_path / "nada") is True


def test_parada_limpa(tmp_path):
    sch = make_sched(tmp_path, {"scheduler_enabled": False})
    sch.start()
    assert sch._thread.is_alive()
    sch.stop()
    assert not sch._thread.is_alive()
    sch.stop()                                              # parar duas vezes não quebra


def test_rodar_agora_com_trava_ocupada(tmp_path):
    sch = make_sched(tmp_path, {"scheduler_enabled": False})
    cron = runlock.round_lock()
    cron.acquire()
    try:
        assert sch.run_now() is False and sch.calls == []
    finally:
        cron.release()
    assert sch.run_now() is True and sch.calls == ["coleta", "canais"]    # manual roda mesmo desligado


def test_rodada_libera_a_trava_mesmo_com_erro(tmp_path):
    def quebra(n):
        raise RuntimeError("x")
    sch = make_sched(tmp_path, steps={"coleta": quebra})
    sch.run_now()
    lock = runlock.round_lock()
    assert lock.acquire()
    lock.release()


# =========================================================================== 10. configuração e rotas do agendador

def test_scheduler_enabled_padrao_desligado_e_validado(tmp_path, monkeypatch):
    conn = db.init_db(tmp_path / "t.db")
    assert S.get(conn, "scheduler_enabled") is False
    with pytest.raises(S.SettingsError):
        S.save(conn, {"scheduler_enabled": "sim"})
    S.save(conn, {"scheduler_enabled": True})
    assert S.get(conn, "scheduler_enabled") is True
    monkeypatch.setenv("PCB_SCHEDULER", "0")
    eff = S.effective(conn)["scheduler_enabled"]
    assert eff["value"] is False and eff["locked"] and eff["env"] == ["PCB_SCHEDULER"]
    monkeypatch.setenv("PCB_SCHEDULER", "1")
    assert S.get(conn, "scheduler_enabled") is True


def test_rota_do_agendador(env):
    st = env["c"].get("/api/scheduler").json()
    assert st["enabled"] is False and st["running"] is False and st["next_run_at"] is None
    assert st["last_run_at"] is None and st["game_mode_available"] is True
    env["c"].put("/api/settings", json={"scheduler_enabled": True, "collect_every_minutes": 60})
    st = env["c"].get("/api/scheduler").json()
    assert st["enabled"] is True and st["interval_minutes"] == 60 and st["next_run_at"]


def test_rota_do_agendador_no_docker(env, monkeypatch):
    monkeypatch.setenv("PCB_IN_DOCKER", "1")
    assert env["c"].get("/api/scheduler").json()["game_mode_available"] is False


def test_rodar_agora_pela_rota(env):
    r = env["c"].post("/api/scheduler/run-now")
    assert r.status_code == 202 and env["steps"] == ["coleta", "canais"]
    st = env["c"].get("/api/scheduler").json()
    assert st["last_ok"] is True and st["last_run_at"]
    assert env["c"].post("/api/scheduler/run-now").status_code == 429       # limite de taxa
    env["clock"].advance(SC.RUN_NOW_GAP_S)
    lock = runlock.round_lock()
    lock.acquire()
    try:
        assert env["c"].post("/api/scheduler/run-now").status_code == 409   # outra rodada em andamento
    finally:
        lock.release()
