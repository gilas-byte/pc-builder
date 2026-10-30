"""Classificador por regras como plano B e a tela da IA local (Ollama).

Sem rede e sem Ollama de verdade: o Ollama é um httpx.MockTransport (`ollama_server`), a votação usa o cliente
falso dos testes dos canais e o conftest proíbe criar cliente HTTP de verdade (app.ollama.default_client)."""

import json
import random
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app import ollama as O
from app import settings as S
from app.db import database as db
from app.main import create_app
from app.tg import classifier as C
from app.tg import reclassify
from app.tg import run as R
from app.tg import vote as V
from app.tg.rules import HIGH, NOT_A_PART, rules_kind
from tests.test_telegram_channels import CH, GPU, SODIMM, fake_chat, fake_fetch, precos
from tests.test_notifier_and_scheduler import Clock

ROOT = Path(__file__).resolve().parents[2]
BASE = "http://127.0.0.1:8787"
F = Path(__file__).parent / "fixtures"


# =========================================================================== Ollama falso (httpx.MockTransport)

def ollama_server(models=("qwen2.5:3b", "llama3.2:3b", "gemma3:4b"), down=False, version="0.12.3",
                  pull_lines=None, pull_status=200, kind="peca:gpu"):
    """Responde /api/version, /api/tags, /api/chat (portão "sim" + tipo `kind`) e /api/pull (NDJSON `pull_lines`).
    down=True: toda conexão é recusada. Grava cada pedido em client.calls."""
    calls = []

    def handler(request):
        path = request.url.path
        body = json.loads(request.content) if request.content else {}
        calls.append({"path": path, "host": request.url.host, "port": request.url.port, "json": body})
        if down:
            raise httpx.ConnectError("[Errno 111] Connection refused to http://203.0.113.7:11434", request=request)
        if path == "/api/version":
            return httpx.Response(200, json={"version": version})
        if path == "/api/tags":
            return httpx.Response(200, json={"models": [
                {"name": m, "model": m, "size": 2_000_000_000 + i, "details": {
                    "quantization_level": "Q4_K_M", "parameter_size": "3.2B", "family": "llama"}}
                for i, m in enumerate(models)]})
        if path == "/api/chat":
            if not body.get("messages"):
                return httpx.Response(200, json={"done": True})        # unload (keep_alive 0)
            if body["model"] not in models:
                return httpx.Response(404, json={"error": f"model '{body['model']}' not found"})
            props = body["format"]["properties"]
            content = {"resposta": "sim"} if "resposta" in props else {"tipo": kind}
            return httpx.Response(200, json={"message": {"content": json.dumps(content)}})
        if path == "/api/pull":
            lines = pull_lines if pull_lines is not None else [{"status": "success"}]
            data = b"".join(json.dumps(x).encode() + b"\n" for x in lines)
            return httpx.Response(pull_status, content=data)
        return httpx.Response(404, json={"error": "rota"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    client.calls = calls
    return client


# =========================================================================== 1. regras

# títulos de exemplo, no estilo dos canais
PECAS = [
    ("Placa de Vídeo PELADN RTX 5060, 8GB, GDDR7", "peca:gpu"),
    ("🔥 Processador AMD Ryzen 5 5500 3.6GHz 4.2GHz Max Turbo Cache 16MB AM4 ", "peca:cpu"),
    ("🔥Placa Mae Gigabyte B550m Aorus Elite Am4 Ddr4 Hdmi M-atx Cor Preto ", "peca:motherboard"),
    ("🔥Kingston Fury Beast Ddr5 - Memória RAM de 8 GB e 5600 Mhz ", "peca:ram"),
    ("Fonte Husky Sledger 550W, 80 Plus White, PFC ativo, Bivolt ", "peca:psu"),
    ("🔥Gabinete Gamer Aquário Aigo Apollo A275, Mini-Tower, Lateral de Vidro, Preto, AC-A275-B-HQ1 ", "peca:case"),
    ("Water Cooler TGT Spartel V2, Rainbow, 240mm, Preto, TGT-SPLV240-BK01 ", "peca:cooler"),
    ("🔥 Monitor LG 24\" UltraGear 24GS60F 180Hz IPS", "monitor"),
    # erros das regras achados no banco de provas (corrigidos, com o teste escrito antes da correção):
    ("⭐UPGRADE PRA NOTEBOOK, PC e PS5  Kingston NV3 1TB  M.2 2280 - PCIe 4.0 NVMe - Leitura de até 6.000 MB/s - "
     "1TB de armazenamento ", "peca:storage"),                            # "pra notebook" não é notebook
    ("Kit Ventoinha Pichau Ventus NX, ARGB, 5x120mm, Branco, PCH-VTNX5-WH01 ", "peca:cooler"),   # ventoinha
    ("Monitor 24\" LED Full HD 100Hz Acer Nitro 5 - KG241Y - (Mercado Livre) ", "monitor"),     # série "Nitro 5"
]


@pytest.mark.parametrize("texto, tipo", PECAS)
def test_regras_por_tipo(texto, tipo):
    kind, conf, why = rules_kind(texto)
    assert kind == tipo and 0 < conf <= 1 and why


def test_regras_com_ficha_completa_tem_confianca_alta_e_sem_ficha_media():
    assert rules_kind("Placa de Vídeo RTX 5060 8GB GDDR7 Palit")[1] == HIGH
    assert rules_kind("Placa de Vídeo RTX 5060 Gamer")[1] < HIGH        # sem VRAM: sem chave do produto


DIFICEIS = [
    *SODIMM,                                                              # RAM de notebook
    "🔥 UPGRADE DE RAM PARA NOTEBOOK  Memória RAM Rise Mode Value 16GB  16GB - DDR4 - 3200MHz - CL22 - Para notebook ",
    "Notebook Gamer ASUS TUF A16 FA607NUQ-RL167 AMD Ryzen 7 170, 16GB, 512GB, RTX4050, 16″ 144Hz – Linux",
    "‼️BOA OPÇÃO COM JÁ COM 16GB  HP 200 G2i  Core 5 120U - 16GB RAM (Expansível) - 256GB SSD (Expansível) ",
    "⚫️ Celular Samsung Galaxy S25 Ultra 5G, 512GB, 12GB RAM, Câmera Quádrupla de 200+50+10+50",
    "🤩 PS5 SLIM DIGITAL POR UM ÓTIMO PREÇO!  PlayStation 5 Slim Edição Digital  825GB - Branco",
    "🔥 Mouse Pad Grande Speed Borda Costurada Gigante 70x30cm E Mousepad RGB 80x30cm ",
    "⚫️ Fone De Ouvido Mchose V9 Pro Headset Gamer Wireless Sem Fio Preto ",
    "🥝 Liquidificador Full Oster 1400W 110V ",
    "⚫️ Smart Tv 75 Polegadas 4K 75P6K Google TV HDR10 Processador Aipq TCL ",
    "🔥 Pasta Térmica SnowDog Husky 1g / 3g Com Adesivo Original - Processadores, Vga, XBOX, Playstation ",
    "Kit Upgrade Ryzen 5 5600 + Placa Mãe A520M",
    "🚨 Samsung Combo Smart TV 70\" + Soundbar",
    "Suporte Articulado Para Monitor Zinnia Nimbo 110",
    "Fonte Universal 12V 5A para fita de LED",                           # "fonte" sem watts de PC
    "⚡ MEMÓRIA RAM DDR5 8GB 4800MHZ!  Memória RAM Skhynix DDR5 8GB - 4800MHz - Seminova ",   # sem sinal de desktop
]


@pytest.mark.parametrize("texto", DIFICEIS)
def test_casos_dificeis_nunca_viram_peca(texto):
    kind, _conf, why = rules_kind(texto)
    assert kind in (NOT_A_PART, None) and why


@pytest.mark.parametrize("texto", [
    "Fonte Universal 12V 5A para fita de LED",
    "⚡ MEMÓRIA RAM DDR5 8GB 4800MHZ!  Memória RAM Skhynix DDR5 8GB - 4800MHz - Seminova ",
])
def test_na_duvida_e_none(texto):
    assert rules_kind(texto)[0] is None


# =========================================================================== 2. votação com 1, 2 e 3 modelos

def test_um_modelo_decide_sozinho():
    (k, n, v), = V.vote(["Placa"], fake_chat(default="peca:gpu"), models=["qwen2.5:3b"])
    assert (k, n) == ("peca:gpu", 1) and v == {"qwen2.5:3b": "peca:gpu"}


def test_um_modelo_com_resposta_ruim_e_duvidoso():
    def chat(model, system, user, schema):
        return "não é json"
    (k, n, _), = V.vote(["x"], chat, models=["m1"])
    assert (k, n) == (V.DOUBT, 0)


def test_dois_modelos_concordam_ou_e_duvidoso():
    chat = fake_chat({"a": {"A": "peca:gpu", "B": "audio"}, "b": {"A": "peca:gpu", "B": "monitor"}})
    (ka, na, _), (kb, nb, _) = V.vote(["A", "B"], chat, models=["a", "b"])
    assert (ka, na) == ("peca:gpu", 2)
    assert kb == V.DOUBT


def test_sem_modelo_nenhum_e_erro():
    with pytest.raises(ValueError):
        V.vote(["x"], fake_chat(), models=[])


def _vote_fase3(titles, chat, models=V.MODELS):
    """Cópia literal da votação original (antes de aceitar 1 ou 2 modelos), para a regressão."""
    votes = [{} for _ in titles]
    for m in models:
        for i, t in enumerate(titles):
            try:
                votes[i][m] = V.one_model(chat, m, t)
            except (ValueError, KeyError):
                votes[i][m] = "erro"
    out = []
    for v in votes:
        top, n = Counter(x for x in v.values() if x != "erro").most_common(1)[0] if any(
            x != "erro" for x in v.values()) else (V.DOUBT, 0)
        out.append((top if n >= 2 else V.DOUBT, n, v))
    return out


def test_regressao_3_modelos_padrao_mesmo_resultado_de_antes():
    """300 títulos com respostas sorteadas (inclusive JSON quebrado) nos 3 modelos padrão: igual à votação original."""
    rnd = random.Random(42)
    kinds = V.TECH_KINDS + [V.NOT_TECH, V.COUPON, "QUEBRADO"]
    answers = {m: {f"T{i:03d}#": rnd.choice(kinds) for i in range(300)} for m in V.MODELS}

    def chat(model, system, user, schema):
        kind = next(k for frag, k in answers[model].items() if frag in user)
        if kind == "QUEBRADO":
            return "{"
        if "resposta" in schema["properties"]:
            return json.dumps({"resposta": {"nao_tech": "nao", "cupom": "cupom"}.get(kind, "sim")})
        return json.dumps({"tipo": kind})
    titles = [f"T{i:03d}#" for i in range(300)]
    assert V.MODELS == ("qwen2.5:3b", "llama3.2:3b", "gemma3:4b")
    assert V.vote(titles, chat) == _vote_fase3(titles, chat)
    assert S.DEFAULTS["ollama"]["models"] == list(V.MODELS)


def test_um_modelo_por_vez_na_placa_e_descarrega_cada_um():
    events = []

    def chat(model, system, user, schema):
        events.append(("chat", model))
        return fake_chat(default="monitor")(model, system, user, schema)
    V.vote(["a", "b"], chat, models=["m1", "m2", "m3"], unload_fn=lambda m: events.append(("unload", m)))
    seq = [e for e in events if e[0] == "unload"]
    assert seq == [("unload", "m1"), ("unload", "m2"), ("unload", "m3")]
    # nenhum pedido ao m2 antes de descarregar o m1, etc.
    for i, m in enumerate(["m1", "m2", "m3"]):
        last_chat = max(j for j, e in enumerate(events) if e == ("chat", m))
        assert events.index(("unload", m)) > last_chat
        if i:
            assert events.index(("unload", ["m1", "m2", "m3"][i - 1])) < events.index(("chat", m))


# =========================================================================== 3. configuração e validação

def test_classifier_padrao_auto_e_env_sobrepoe(tmp_path):
    conn = db.init_db(tmp_path / "t.db")
    assert S.get(conn, "classifier") == "auto"
    S.save(conn, {"classifier": "rules"})
    assert S.get(conn, "classifier") == "rules"
    eff = S.effective(conn, {"PCB_CLASSIFIER": "ollama"})["classifier"]
    assert eff["value"] == "ollama" and eff["locked"]
    assert "env_error" in S.effective(conn, {"PCB_CLASSIFIER": "magia"})["classifier"]
    with pytest.raises(S.SettingsError):
        S.save(conn, {"classifier": "magia"})


@pytest.mark.parametrize("models", [["qwen2.5:3b"], ["qwen2.5:3b", "gemma3:4b"], list(V.MODELS),
                                    ["hf.co/bartowski/llama-3.2-1b-instruct-gguf:Q4_K_M"], ["library/llama3.2"],
                                    ["a" * 100]])
def test_modelos_validos_de_1_a_3(models):
    assert S.validate("ollama", {"url": "http://127.0.0.1:11434", "models": models})["models"] == models


@pytest.mark.parametrize("models", [[], ["a", "b", "c", "d"], ["qwen 2.5"], ["a//b"], ["../x"], ["/abs"], ["a" * 101],
                                    ["Qwen2.5:3b"], ["a:b:c"], [""], ["x:"], ["qwen;rm"], ["qwen2.5:3b\n"], [3]])
def test_modelos_invalidos(models):
    with pytest.raises(ValueError):
        S.validate("ollama", {"url": "http://127.0.0.1:11434", "models": models})


@pytest.mark.parametrize("url", [
    "http://169.254.169.254", "http://169.254.0.1:11434", "http://[fe80::1]:11434", "http://[::ffff:169.254.169.254]",
    "http://metadata.google.internal", "http://metadata", "http://user:x@127.0.0.1:11434", "ftp://127.0.0.1:11434",
    "file:///etc/passwd", "http://127.0.0.1:11434/api", "javascript:alert(1)",
])
def test_url_do_ollama_recusada(url):
    with pytest.raises(ValueError):
        S.validate("ollama", {"url": url, "models": ["qwen2.5:3b"]})


def test_aviso_quando_o_ollama_nao_e_local():
    assert S.ollama_warning("http://127.0.0.1:11434") is None
    assert S.ollama_warning("http://localhost:11434") is None
    assert S.ollama_warning("http://[::1]:11434") is None
    assert "outra máquina" in S.ollama_warning("http://ollama.example:11434")


def test_pcb_ollama_url_link_local_e_ignorada(tmp_path):
    conn = db.init_db(tmp_path / "t.db")
    eff = S.effective(conn, {"PCB_OLLAMA_URL": "http://169.254.169.254"})["ollama"]
    assert "env_error" in eff and eff["value"]["url"] == "http://127.0.0.1:11434"


# =========================================================================== 4. fluxo: auto, regras, só Ollama

PLACA = GPU.format("2.700,00")
CELULAR = "⚫️ Celular Samsung Galaxy S25 Ultra 5G, 512GB, 12GB RAM\n\nPor: R$ 5.999"
RAM_DUVIDA = "Memória RAM DDR5 8GB 4800MHz Seminova\n\nPor: R$ 199"


@pytest.fixture
def conn(tmp_path):
    c = db.init_db(tmp_path / "t.db")
    yield c
    c.close()


class Probe:
    def __init__(self, up):
        self.up, self.calls = up, 0

    def __call__(self):
        self.calls += 1
        return self.up


def rodada(conn, posts, chat=None, probe=None, state=None, now=datetime(2026, 10, 12, 12, 0)):
    pages = {CH: posts}
    return R.run_round(conn, fake_fetch(pages), chat or fake_chat(default="peca:gpu"), now, channels=[CH], pause=0,
                       log=lambda *_: None, probe=probe, state_path=state)


def offers(conn):
    return [dict(r) for r in conn.execute("SELECT msg_id, kind, kind_source, product_key FROM tg_offers ORDER BY msg_id")]


def test_auto_sem_ollama_usa_regras_e_marca_a_origem(conn, tmp_path):
    chat = fake_chat(default="audio")
    res = rodada(conn, [(1, "2026-10-12T10:00:00", PLACA), (2, "2026-10-12T10:01:00", CELULAR),
                        (3, "2026-10-12T10:02:00", RAM_DUVIDA)], chat, Probe(False), state=tmp_path / "st.json")
    assert chat.calls == []                                           # nem tentou votar
    assert offers(conn) == [
        {"msg_id": 1, "kind": "peca:gpu", "kind_source": "rules", "product_key": "gpu|rtx 5060|8gb"},
        {"msg_id": 2, "kind": NOT_A_PART, "kind_source": "rules", "product_key": None},
        {"msg_id": 3, "kind": None, "kind_source": None, "product_key": None},      # na dúvida: sem tipo
    ]
    assert res["notices"] == [C.FALLBACK_MSG] and "ollama" not in res["errors"]


def test_auto_avisa_uma_vez_por_queda(conn, tmp_path):
    st = tmp_path / "st.json"
    a = rodada(conn, [(1, "2026-10-12T10:00:00", PLACA)], probe=Probe(False), state=st)
    b = rodada(conn, [(1, "2026-10-12T10:00:00", PLACA), (2, "2026-10-12T11:00:00", PLACA)],
               probe=Probe(False), state=st)
    assert a["notices"] == [C.FALLBACK_MSG] and b["notices"] == []
    rodada(conn, [(3, "2026-10-12T12:00:00", PLACA)], probe=Probe(True), state=st)             # voltou
    d = rodada(conn, [(4, "2026-10-12T13:00:00", PLACA)], probe=Probe(False), state=st)        # caiu de novo
    assert d["notices"] == [C.FALLBACK_MSG]


def test_auto_cai_para_regras_se_o_ollama_morre_no_meio(conn, tmp_path):
    res = rodada(conn, [(1, "2026-10-12T10:00:00", PLACA)], fake_chat(down=True), Probe(True), tmp_path / "s.json")
    assert offers(conn)[0]["kind_source"] == "rules" and res["notices"] == [C.FALLBACK_MSG]


def test_quando_o_ollama_volta_reavalia_so_as_de_regras_e_sem_tipo(conn, tmp_path):
    st = tmp_path / "st.json"
    rodada(conn, [(1, "2026-10-12T10:00:00", PLACA), (3, "2026-10-12T10:02:00", RAM_DUVIDA)],
           probe=Probe(False), state=st)
    with conn:      # uma oferta que já veio do Ollama (não pode ser revotada)
        conn.execute("INSERT INTO tg_offers (channel, msg_id, posted_at, seen_at, title, text, price_cash, kind, "
                     "kind_agree, kind_source) VALUES (?, 9, '2026-10-12T09:00:00', '2026-10-12T09:00:00', 'Velha',"
                     " 'Velha do Ollama', 100, 'monitor', 3, 'ollama')", (CH,))
    chat = fake_chat({m: {"Memória RAM": "peca:ram"} for m in V.MODELS}, default="peca:gpu")
    res = rodada(conn, [(1, "2026-10-12T10:00:00", PLACA), (3, "2026-10-12T10:02:00", RAM_DUVIDA),
                        (4, "2026-10-12T11:00:00", PLACA)], chat, Probe(True), st)
    revotados = {u for _, u in chat.calls}
    assert not any("Velha" in u for u in revotados)
    assert res["reevaluated"] == 2
    got = {o["msg_id"]: (o["kind"], o["kind_source"]) for o in offers(conn)}
    assert got[1] == ("peca:gpu", "ollama") and got[4] == ("peca:gpu", "ollama")
    assert got[3] == ("outro_tech", "ollama")             # RAM sem sinal de desktop: adjust_kind de sempre
    assert got[9] == ("monitor", "ollama")


def test_modo_rules_nunca_chama_o_ollama(conn, tmp_path):
    S.save(conn, {"classifier": "rules"})
    chat, probe = fake_chat(), Probe(True)
    res = rodada(conn, [(1, "2026-10-12T10:00:00", PLACA)], chat, probe, tmp_path / "s.json")
    assert chat.calls == [] and probe.calls == 0
    assert offers(conn)[0]["kind_source"] == "rules" and res["notices"] == []


def test_modo_ollama_nunca_usa_regras(conn, tmp_path):
    S.save(conn, {"classifier": "ollama"})
    res = rodada(conn, [(1, "2026-10-12T10:00:00", PLACA)], fake_chat(down=True), Probe(False), tmp_path / "s.json")
    assert offers(conn) == [{"msg_id": 1, "kind": None, "kind_source": None, "product_key": None}]
    assert "ollama" in res["errors"] and res["notices"] == []


def test_modo_ollama_com_ollama_no_ar_marca_origem_ollama(conn, tmp_path):
    S.save(conn, {"classifier": "ollama", "ollama": {"url": "http://127.0.0.1:11434", "models": ["qwen2.5:3b"]}})
    chat = fake_chat(default="peca:gpu")
    rodada(conn, [(1, "2026-10-12T10:00:00", PLACA)], chat, Probe(True), tmp_path / "s.json")
    assert {m for m, _ in chat.calls} == {"qwen2.5:3b"}                 # usa só o modelo escolhido
    assert offers(conn)[0] == {"msg_id": 1, "kind": "peca:gpu", "kind_source": "ollama",
                               "product_key": "gpu|rtx 5060|8gb"}       # 1 modelo decide sozinho


def test_regras_tambem_avisam_promocao(conn, tmp_path):
    """Sem Ollama o app continua útil: peça com ficha completa pelas regras entra na comparação de preço."""
    S.save(conn, {"classifier": "rules"})
    precos(conn, ["2.700,00", "2.750,00", "2.690,00"], day=10)
    res = rodada(conn, [(9, "2026-10-12T10:00:00", GPU.format("2.400,00"))], state=tmp_path / "s.json")
    assert [a["why"] for a in res["alerts"]] == ["menor_ja_visto"]


def test_rodada_de_verdade_usa_o_endereco_salvo(conn, tmp_path, monkeypatch):
    """Sem chat injetado, a rodada fala com o Ollama do endereço salvo (aqui, um MockTransport)."""
    srv = ollama_server(models=("qwen2.5:3b",))
    monkeypatch.setattr(O, "default_client", lambda: srv)
    S.save(conn, {"ollama": {"url": "http://ollama.example:11500", "models": ["qwen2.5:3b"]}})
    R.run_round(conn, fake_fetch({CH: [(1, "2026-10-12T10:00:00", PLACA)]}), now=datetime(2026, 10, 12, 12),
                channels=[CH], pause=0, log=lambda *_: None, state_path=tmp_path / "s.json")
    assert {(c["host"], c["port"]) for c in srv.calls} == {("ollama.example", 11500)}
    assert [c["path"] for c in srv.calls][0] == "/api/version"            # teste de presença primeiro
    assert any(c["path"] == "/api/chat" and c["json"].get("keep_alive") == 0 for c in srv.calls)   # descarrega
    assert offers(conn)[0]["kind_source"] == "ollama"


def test_migracao_kind_source_em_banco_antigo(tmp_path):
    path = tmp_path / "velho.db"
    conn = db.init_db(path)
    with conn:
        conn.execute("INSERT INTO tg_channels (slug) VALUES ('canal_velho') ON CONFLICT DO NOTHING")
        for i, kind in ((1, "peca:gpu"), (2, None)):
            conn.execute("INSERT INTO tg_offers (channel, msg_id, posted_at, seen_at, title, text, price_cash, kind) "
                         "VALUES ('canal_velho', ?, 'x', 'x', 't', 't', 100, ?)", (i, kind))
        conn.execute("ALTER TABLE tg_offers DROP COLUMN kind_source")      # banco de antes da coluna kind_source
    conn.close()
    conn = db.init_db(path)
    assert [tuple(r) for r in conn.execute("SELECT msg_id, kind_source FROM tg_offers ORDER BY msg_id")] == \
        [(1, "ollama"), (2, None)]
    with conn:
        conn.execute("UPDATE tg_offers SET kind_source = 'rules' WHERE msg_id = 1")
    conn.close()
    conn = db.init_db(path)                                                # de novo: não mexe
    assert conn.execute("SELECT kind_source FROM tg_offers WHERE msg_id = 1").fetchone()[0] == "rules"
    with pytest.raises(Exception):
        with conn:
            conn.execute("UPDATE tg_offers SET kind_source = 'chute' WHERE msg_id = 1")
    conn.close()


# --------------------------------------------------------------------------- reclassify (CLI)

def _db_misto(tmp_path):
    path = tmp_path / "t.db"
    conn = db.init_db(path)
    S.save(conn, {"classifier": "rules"})
    R.run_round(conn, fake_fetch({CH: [(1, "2026-10-12T10:00:00", PLACA), (2, "2026-10-12T10:01:00", RAM_DUVIDA)]}),
                fake_chat(), datetime(2026, 10, 12, 12), channels=[CH], pause=0, log=lambda *_: None,
                state_path=tmp_path / "s.json")
    S.save(conn, {"classifier": "ollama"})
    with conn:
        conn.execute("INSERT INTO tg_offers (channel, msg_id, posted_at, seen_at, title, text, price_cash, kind, "
                     "kind_agree, kind_source, link) VALUES (?, 9, 'x', 'x', 'Velha', 'Placa Velha do Ollama', 100, "
                     "'peca:gpu', 3, 'ollama', 'https://loja.example/velha')", (CH,))
    conn.close()
    return path


def test_reclassify_padrao_so_reavalia_regras_e_sem_tipo(tmp_path, capsys):
    path = _db_misto(tmp_path)
    chat = fake_chat(default="monitor")
    out = reclassify.main([], db_path=path, chat=chat)
    assert out["revotadas"] == 2 and not any("Velha" in u for _, u in chat.calls)
    conn = db.connect(path)
    assert {r[0]: r[1] for r in conn.execute("SELECT msg_id, kind_source FROM tg_offers")} == \
        {1: "ollama", 2: "ollama", 9: "ollama"}


def test_reclassify_parts_mantem_o_comportamento_antigo(tmp_path, capsys):
    path = _db_misto(tmp_path)
    chat = fake_chat(default="monitor")
    out = reclassify.main(["--parts"], db_path=path, chat=chat)
    assert out["revotadas"] == 3 and any("Velha" in u for _, u in chat.calls)


def test_reclassify_com_ollama_fora_no_modo_ollama_nao_estraga_nada(tmp_path, capsys):
    path = _db_misto(tmp_path)
    out = reclassify.main([], db_path=path, chat=fake_chat(down=True))
    assert out["revotadas"] == 0 and "erro" in out
    conn = db.connect(path)
    assert conn.execute("SELECT kind_source FROM tg_offers WHERE msg_id = 1").fetchone()[0] == "rules"


# --------------------------------------------------------------------------- CLI --notify (cron / Hermes Agent)

def test_notify_com_queda_do_ollama_avisa_uma_vez(tmp_path, capsys):
    path = tmp_path / "t.db"
    db.init_db(path).close()
    srv = ollama_server(down=True)
    kw = dict(db_path=path, pause=0, img_get=lambda u: None, img_dir=tmp_path / "img")
    pages = {CH: [(1, "2026-10-11T10:00:00", CELULAR)]}
    R.main(["--notify", "--channels", CH], fetch=fake_fetch(pages), ollama_client=srv,
           now=datetime(2026, 10, 11, 12), **kw)
    assert capsys.readouterr().out == C.FALLBACK_MSG + "\n"
    pages[CH].append((2, "2026-10-11T11:00:00", CELULAR))
    R.main(["--notify", "--channels", CH], fetch=fake_fetch(pages), ollama_client=srv,
           now=datetime(2026, 10, 11, 13), **kw)
    assert capsys.readouterr().out == ""                              # cron quieto: já avisou
    assert all(c["path"] == "/api/version" for c in srv.calls)        # só o teste de presença
    msg = C.FALLBACK_MSG
    assert msg == "Ollama não respondeu; usando regras. Quando voltar, as ofertas serão reavaliadas"


# =========================================================================== 5. cliente do Ollama e download

def test_lista_de_modelos_instalados():
    cli = O.OllamaClient("http://127.0.0.1:11434", ollama_server(models=("qwen2.5:3b", "gemma3:4b")))
    ms = cli.models()
    assert [m["name"] for m in ms] == ["qwen2.5:3b", "gemma3:4b"]
    assert ms[0]["size"] == 2_000_000_000 and ms[0]["quantization"] == "Q4_K_M" and ms[0]["parameters"] == "3.2B"


def test_erro_do_ollama_nao_vaza_o_endereco():
    cli = O.OllamaClient("http://203.0.113.7:11434", ollama_server(down=True))       
    assert cli.ping() is False
    with pytest.raises(O.OllamaError) as e:
        cli.version()
    assert "203.0.113.7" not in str(e.value) and "11434" not in str(e.value) and "http" not in str(e.value)
    assert "não respondeu" in str(e.value)


PULL_OK = [{"status": "pulling manifest"},
           {"status": "pulling a1", "digest": "sha256:a1", "total": 1000, "completed": 0},
           {"status": "pulling a1", "digest": "sha256:a1", "total": 1000, "completed": 500},
           {"status": "pulling b2", "digest": "sha256:b2", "total": 3000, "completed": 3000},
           {"status": "pulling a1", "digest": "sha256:a1", "total": 1000, "completed": 1000},
           {"status": "verifying sha256 digest"}, {"status": "writing manifest"}, {"status": "success"}]


class Spawn:
    """Guarda a tarefa em vez de abrir thread; `run()` executa a última."""

    def __init__(self):
        self.fns = []

    def __call__(self, fn):
        self.fns.append(fn)

    def run(self):
        self.fns.pop()()


def puller(srv, clock=None, spawn=None):
    return O.PullManager(lambda: O.OllamaClient("http://127.0.0.1:11434", srv), clock=clock or Clock(),
                         spawn=spawn or (lambda fn: fn()))


def test_pull_le_o_progresso_do_stream_ndjson():
    seen = []
    pm = puller(ollama_server(pull_lines=PULL_OK))
    pm.on_progress = lambda st: seen.append((st["completed"], st["total"], st["percent"]))
    pm.start("qwen2.5:7b")
    st = pm.status()
    assert st["model"] == "qwen2.5:7b" and st["state"] == "done" and st["percent"] == 100 and st["error"] is None
    assert st["completed"] == st["total"] == 4000
    assert (500, 1000, 50) in seen and (3500, 4000, 87) in seen


def test_pull_com_erro_no_meio_guarda_o_que_fez_e_o_motivo_sem_endereco():
    lines = PULL_OK[:3] + [{"error": "pull model manifest: Get \"http://203.0.113.7:11434/v2/x\": dial tcp: refused"}]
    pm = puller(ollama_server(pull_lines=lines))
    pm.start("qwen2.5:7b")
    st = pm.status()
    assert st["state"] == "error" and st["percent"] == 50
    assert "203.0.113.7" not in st["error"] and "http" not in st["error"] and st["error"]


def test_pull_de_modelo_que_nao_existe():
    pm = puller(ollama_server(pull_lines=[{"error": "pull model manifest: file does not exist"}]))
    pm.start("nao-existe:1b")
    assert pm.status()["state"] == "error" and "não existe" in pm.status()["error"]


def test_pull_com_ollama_fora_do_ar():
    pm = puller(ollama_server(down=True))
    pm.start("qwen2.5:7b")
    st = pm.status()
    assert st["state"] == "error" and "não respondeu" in st["error"] and "203.0.113.7" not in st["error"]


def test_um_pull_por_vez():
    sp = Spawn()
    pm = puller(ollama_server(pull_lines=PULL_OK), spawn=sp)
    pm.start("a:1")
    with pytest.raises(O.PullBusy):
        pm.start("b:1")
    sp.run()
    assert pm.status()["state"] == "done"
    pm.start("b:1")                                       # terminou: pode de novo


def test_limite_de_5_pulls_por_hora():
    clock = Clock()
    pm = puller(ollama_server(pull_lines=PULL_OK), clock=clock)
    for i in range(5):
        pm.start(f"m{i}:1")
        clock.advance(1)
    with pytest.raises(O.PullLimited) as e:
        pm.start("m5:1")
    assert e.value.wait > 0
    clock.advance(3600)
    pm.start("m5:1")


def test_cancelar_pull():
    sp = Spawn()
    pm = puller(ollama_server(pull_lines=PULL_OK), spawn=sp)
    pm.start("qwen2.5:7b")
    assert pm.cancel() is True
    sp.run()
    assert pm.status()["state"] == "canceled"
    assert pm.cancel() is False                           # nada rodando


def test_pull_valida_o_nome():
    pm = puller(ollama_server())
    with pytest.raises(ValueError):
        pm.start("a b")
    assert pm.status()["state"] == "idle"


# =========================================================================== 6. rotas

@pytest.fixture
def env(tmp_path):
    srv = ollama_server()
    clock = Clock()
    sp = Spawn()
    app = create_app(db_path=tmp_path / "t.db", frontend_dist=tmp_path / "x", channel_fetch=lambda u: "",
                     clock=clock, ollama_http=srv, spawn=sp, proc_root=tmp_path)
    return {"c": TestClient(app, base_url=BASE), "srv": srv, "clock": clock, "spawn": sp, "path": tmp_path / "t.db"}


def test_status_com_ollama_respondendo(env):
    j = env["c"].get("/api/ollama/status").json()
    assert j["reachable"] is True and j["version"] == "0.12.3" and j["error"] is None
    assert j["url"] == "http://127.0.0.1:11434" and j["warning"] is None
    assert j["classifier_effective"] == "ollama" and j["classifier_mode"] == "auto"
    assert j["models_selected"] == list(V.MODELS) and j["models_missing"] == []


def test_status_com_ollama_fora_do_ar_e_sem_vazar_endereco(tmp_path):
    app = create_app(db_path=tmp_path / "t.db", frontend_dist=tmp_path / "x", ollama_http=ollama_server(down=True))
    j = TestClient(app, base_url=BASE).get("/api/ollama/status").json()
    assert j["reachable"] is False and j["classifier_effective"] == "rules"
    assert "não respondeu" in j["error"] and "203.0.113.7" not in j["error"]


def test_status_mostra_modelo_faltando_e_aviso_de_endereco(env):
    conn = db.connect(env["path"])
    S.save(conn, {"ollama": {"url": "http://ollama.example:11434", "models": ["qwen2.5:3b", "phi4:14b"]}})
    conn.close()
    j = env["c"].get("/api/ollama/status").json()
    assert j["models_missing"] == ["phi4:14b"] and j["classifier_effective"] == "rules"
    assert j["warning"] and "outra máquina" in j["warning"]


def test_status_no_modo_regras(env):
    env["c"].put("/api/settings", json={"classifier": "rules"})
    j = env["c"].get("/api/ollama/status").json()
    assert j["classifier_effective"] == "rules"


def test_rota_de_modelos(env):
    j = env["c"].get("/api/ollama/models").json()
    assert [m["name"] for m in j["models"]] == list(V.MODELS) and j["models"][0]["quantization"] == "Q4_K_M"


def test_rota_de_modelos_sem_ollama(tmp_path):
    app = create_app(db_path=tmp_path / "t.db", frontend_dist=tmp_path / "x", ollama_http=ollama_server(down=True))
    r = TestClient(app, base_url=BASE).get("/api/ollama/models")
    assert r.status_code == 503 and "não respondeu" in r.json()["detail"]


def test_rotas_do_pull(env):
    c = env["c"]
    env["srv"].calls.clear()
    assert c.post("/api/ollama/pull", json={"model": "a b"}).status_code == 422
    assert c.post("/api/ollama/pull", json={"model": "qwen2.5:7b", "x": 1}).status_code == 422
    r = c.post("/api/ollama/pull", json={"model": "qwen2.5:7b"})
    assert r.status_code == 202 and r.json()["model"] == "qwen2.5:7b"
    assert c.get("/api/ollama/pull").json()["state"] == "running"
    assert c.post("/api/ollama/pull", json={"model": "gemma3:4b"}).status_code == 409
    assert c.delete("/api/ollama/pull").json()["canceled"] is True
    env["spawn"].run()
    assert c.get("/api/ollama/pull").json()["state"] == "canceled"


def test_rota_do_pull_limite_por_hora(env):
    c = env["c"]
    for i in range(5):
        assert c.post("/api/ollama/pull", json={"model": f"m{i}:1"}).status_code == 202
        env["spawn"].run()
    r = c.post("/api/ollama/pull", json={"model": "m5:1"})
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0


def test_teste_rapido_pelas_regras(env):
    env["c"].put("/api/settings", json={"classifier": "rules"})
    j = env["c"].post("/api/classifier/test", json={"text": "Placa de Vídeo RTX 5060 8GB GDDR7 Palit"}).json()
    assert j["kind"] == "peca:gpu" and j["source"] == "rules" and j["why"] and j["confidence"] == HIGH
    assert [c for c in env["srv"].calls if c["path"] == "/api/chat"] == []


def test_teste_rapido_pelo_ollama(env):
    j = env["c"].post("/api/classifier/test", json={"text": "Placa de Vídeo RTX 5060 8GB GDDR7 Palit"}).json()
    assert j["kind"] == "peca:gpu" and j["source"] == "ollama" and j["agree"] == 3
    assert j["rules"]["kind"] == "peca:gpu" and j["rules"]["why"]                 # o porquê das regras sempre vem


def test_teste_rapido_limites(env):
    c = env["c"]
    env["c"].put("/api/settings", json={"classifier": "rules"})
    assert c.post("/api/classifier/test", json={"text": "x" * 2001}).status_code == 422
    assert c.post("/api/classifier/test", json={"text": ""}).status_code == 422
    assert c.post("/api/classifier/test", json={"texto": "x"}).status_code == 422
    assert c.post("/api/classifier/test", json={"text": "x" * 2000}).status_code == 200
    assert c.post("/api/classifier/test", json={"text": "y"}).status_code == 429         # 1 por segundo
    env["clock"].advance(2)
    assert c.post("/api/classifier/test", json={"text": "y"}).status_code == 200


def test_rota_do_classificador_mostra_metricas_reais_e_contagem(env):
    conn = db.connect(env["path"])
    with conn:
        conn.execute("INSERT INTO tg_channels (slug) VALUES ('c1') ON CONFLICT DO NOTHING")
        for i, src, kind in ((1, "rules", "peca:gpu"), (2, "rules", "nao_peca"), (3, "ollama", "audio"), (4, None, None)):
            conn.execute("INSERT INTO tg_offers (channel, msg_id, posted_at, seen_at, title, text, price_cash, kind, "
                         "kind_source) VALUES ('c1', ?, 'x', 'x', 't', 't', 100, ?, ?)", (i, kind, src))
    conn.close()
    j = env["c"].get("/api/classifier").json()
    gravado = json.loads((ROOT / "backend/app/tg/rules_metrics.json").read_text(encoding="utf-8"))
    assert j["mode"] == "auto" and j["effective"] == "ollama"
    assert j["rules_metrics"]["pct"] == gravado["all"]["pct"] and j["rules_metrics"]["n"] == gravado["all"]["n"]
    assert j["counts"] == {"ollama": 1, "rules": 2, "sem_tipo": 1}


@pytest.mark.parametrize("method, path", [("get", "/api/ollama/status"), ("get", "/api/ollama/models"),
                                          ("get", "/api/ollama/pull"), ("get", "/api/classifier"),
                                          ("post", "/api/classifier/test"), ("post", "/api/ollama/pull"),
                                          ("delete", "/api/ollama/pull")])
def test_rotas_da_ia_so_com_host_permitido(env, method, path):
    kw = {"json": {"text": "x", "model": "a:1"}} if method == "post" else {}
    r = getattr(env["c"], method)(path, headers={"Host": "evil.example"}, **kw)
    assert r.status_code == 403 and env["srv"].calls == []          # nem chegou a falar com o Ollama


def test_rotas_da_ia_recusam_origin_de_fora(env):
    r = env["c"].post("/api/classifier/test", json={"text": "x"}, headers={"Origin": "http://evil.example"})
    assert r.status_code == 403
    r = env["c"].get("/api/ollama/status", headers={"Origin": "http://evil.example"})
    assert r.status_code == 403


def test_nao_peca_das_regras_fica_fora_da_aba_canais(env):
    """As regras não sabem separar tecnologia de comida: "não é peça" só aparece se pedir pelo tipo."""
    conn = db.connect(env["path"])
    with conn:
        conn.execute("INSERT INTO tg_channels (slug) VALUES ('c1') ON CONFLICT DO NOTHING")
        for i, kind in ((1, "nao_peca"), (2, "monitor")):
            conn.execute("INSERT INTO tg_offers (channel, msg_id, posted_at, seen_at, title, text, price_cash, kind, "
                         "kind_source) VALUES ('c1', ?, datetime('now', 'localtime'), 'x', 't', 't', 100, ?, 'rules')",
                         (i, kind))
    conn.close()
    c = env["c"]
    assert [o["kind"] for o in c.get("/api/tg/offers", params={"no_parts": True}).json()] == ["monitor"]
    assert [o["kind"] for o in c.get("/api/tg/offers", params={"kind": "nao_peca"}).json()] == ["nao_peca"]


def test_status_testa_endereco_sem_salvar(env):
    c = env["c"]
    env["srv"].calls.clear()
    j = c.get("/api/ollama/status", params={"url": "http://ollama.example:11500"}).json()
    assert j["reachable"] is True and j["url"] == "http://ollama.example:11500" and "outra máquina" in j["warning"]
    assert {(x["host"], x["port"]) for x in env["srv"].calls} == {("ollama.example", 11500)}
    assert c.get("/api/settings").json()["values"]["ollama"]["url"] == "http://127.0.0.1:11434"     # nada gravado


@pytest.mark.parametrize("url", ["http://169.254.169.254", "http://[fe80::1]:11434", "http://u:p@127.0.0.1:11434",
                                 "file:///etc/passwd", "http://metadata.google.internal"])
def test_status_testar_endereco_recusado_nem_chama(env, url):
    env["srv"].calls.clear()
    r = env["c"].get("/api/ollama/status", params={"url": url})
    assert r.status_code == 422 and env["srv"].calls == []


def test_teste_rapido_no_automatico_sem_ollama_cai_nas_regras(tmp_path):
    app = create_app(db_path=tmp_path / "t.db", frontend_dist=tmp_path / "x", ollama_http=ollama_server(down=True))
    j = TestClient(app, base_url=BASE).post("/api/classifier/test", json={"text": "Monitor LG 24GS60F 180Hz"}).json()
    assert j["kind"] == "monitor" and j["source"] == "rules" and j["fallback"] is True
    assert "não respondeu" in j["error"] and "203.0.113.7" not in j["error"]


# eletrodoméstico, som e acessório que o classificador antigo tomava por peça (achados na tela Peças, 27/10/2026)
NAO_PECA_ELETRO = [
    "🔥 Mini Processador Mondial MP-16 300W 110V ",
    "MONDIAL Mini Processador Turbo Pratic, Preto, 300W, 110V - MP-16-B 220V",
    "Mini Processador Kian 500ml 120W ",
    "Ventilador de Mesa Mallory Turbo Compact 30cm ",
    "Hub de Ventilador de PC 10 Portas 4 Pinos 5V Thermalright ",
    "Modulo Amplificador Taramps Ts400x4 400w Rms 2 Ohms 4 Canais ",
    "Zealot ZE21 250w a Bombox poder de Subgrave! ",
    "Nexmidio 300w Famosa Imenso X41A caixa de som com pequenas melhorias ",
    "Caixa de Som Bluetooth JBL 300W Subwoofer ",
]


@pytest.mark.parametrize("texto", NAO_PECA_ELETRO)
def test_eletrodomestico_e_som_nao_viram_peca_pelas_regras(texto):
    kind, _conf, why = rules_kind(texto)
    assert kind in (NOT_A_PART, None) and why


@pytest.mark.parametrize("texto", NAO_PECA_ELETRO)
@pytest.mark.parametrize("votado", ["peca:cpu", "peca:cooler", "peca:psu", "monitor"])
def test_eletrodomestico_e_som_derrubam_o_tipo_votado_pelo_ollama(texto, votado):
    from app.tg.classify import adjust_kind
    assert adjust_kind(votado, texto) == "outro_tech"


def test_peca_de_verdade_com_palavra_parecida_continua_peca():
    from app.tg.classify import adjust_kind
    assert adjust_kind("peca:cpu", "Processador AMD Ryzen 5 5500 3.6GHz AM4 ") == "peca:cpu"
    assert adjust_kind("peca:cooler", "Ventoinha Pichau Ventus 120mm ARGB ") == "peca:cooler"
    assert adjust_kind("peca:psu", "Fonte Husky Sledger 550W 80 Plus White ") == "peca:psu"
