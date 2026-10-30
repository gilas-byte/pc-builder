import json
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app import ingest as ingest_mod
from app.db import database as db
from app.main import create_app
from app.schemas import IngestBatch


@pytest.fixture
def env(tmp_path):
    db_path = tmp_path / "t.db"
    app = create_app(db_path=db_path, frontend_dist=tmp_path / "sem_frontend")
    # Atrás de um proxy reverso local (ex.: `tailscale serve`), TODA requisição chega de 127.0.0.1:
    # o aparelho remoto é igual ao local.
    local = TestClient(app, client=("127.0.0.1", 50000), base_url="http://127.0.0.1:8787")
    remote = TestClient(app, client=("203.0.113.7", 50000), base_url="http://127.0.0.1:8787")
    return {"local": local, "remote": remote, "db_path": db_path, "tmp": tmp_path}


def item(**over):
    base = {
        "store": "kabum",
        "url": "https://www.kabum.com.br/produto/1/rtx-4060",
        "title": "Placa de Vídeo RTX 4060 8GB",
        "category": "gpu",
        "brand": "NVIDIA",
        "model": "GeForce RTX 4060 8GB",
        "specs": {"recommended_psu_w": 550},
        "price_cash": 189990,
        "price_installment": 219990,
        "in_stock": True,
    }
    return {**base, **over}


def ingest(env, items, when=None):
    """Grava pelo caminho de verdade: o comando local `app.ingest` (não pela rede)."""
    body = {"items": items}
    if when:
        body["collected_at"] = when
    f = env["tmp"] / "lote.json"
    f.write_text(json.dumps(body))
    return ingest_mod.main([str(f)], db_path=env["db_path"])


def day(n, today=date(2026, 10, 9)):
    return (today - timedelta(days=n)).isoformat() + "T09:00:00"


# ------------------------------------------------------------------ segurança: a rede não grava preço

def test_nao_existe_rota_de_gravacao(env):
    body = {"items": [item()]}
    for metodo in ("post", "put", "patch"):
        r = getattr(env["local"], metodo)("/api/snapshots", json=body)
        assert r.status_code in (404, 405)
    assert env["local"].get("/api/health").json()["price_snapshots"] == 0


def test_caminho_do_proxy_local_nao_grava(env):
    # exatamente como um proxy local (ex.: tailscale serve) entrega: IP 127.0.0.1 + cabeçalhos de identidade
    headers = {"Tailscale-User-Login": "user@example.com", "X-Forwarded-For": "203.0.113.7"}
    r = env["local"].post("/api/snapshots", json={"items": [item()]}, headers=headers)
    assert r.status_code in (404, 405)
    assert env["local"].get("/api/health").json()["price_snapshots"] == 0


def test_openapi_so_tem_as_rotas_de_escrita_permitidas(env):
    # Escrita pela rede: build, favorito, configurações e canais. Preço/peça/loja NUNCA.
    # Rota nova de escrita quebra este teste.
    permitidas = {
        ("/api/builds/{build_id}/items/{category}", "put"),
        ("/api/builds/{build_id}/auto", "post"),
        ("/api/favorites/{part_id}", "put"),
        ("/api/favorites/{part_id}", "delete"),
        ("/api/settings", "put"),
        ("/api/settings/reset/{key}", "post"),
        ("/api/channels", "post"),
        ("/api/channels/{slug}", "put"),
        ("/api/channels/{slug}", "delete"),
        # token write-only, teste do aviso, achar o chat, rodar agora
        ("/api/secrets/telegram", "put"),
        ("/api/secrets/telegram", "delete"),
        ("/api/secrets/telegram/detect-chat", "post"),
        ("/api/notify/test", "post"),
        ("/api/scheduler/run-now", "post"),
        # baixar modelo do Ollama (um por vez, 5/hora), cancelar, e o teste rápido do classificador
        ("/api/ollama/pull", "post"),
        ("/api/ollama/pull", "delete"),
        ("/api/classifier/test", "post"),
    }
    paths = env["local"].get("/api/openapi.json").json()["paths"]
    gravam = {(p, m) for p, ms in paths.items() for m in ms if m in ("post", "put", "patch", "delete")}
    assert gravam == permitidas


def test_leitura_de_fora_funciona(env):
    assert env["remote"].get("/api/health").status_code == 200


# ------------------------------------------------------------------ gravação

def test_gravacao_cria_peca_link_e_preco(env, capsys):
    assert ingest(env, [item()]) == 0
    j = json.loads(capsys.readouterr().out)
    assert j["ok"] and (j["parts_created"], j["listings_created"], j["snapshots"]) == (1, 1, 1)
    h = env["local"].get("/api/health").json()
    assert (h["parts"], h["listings"], h["price_snapshots"]) == (1, 1, 1)


def test_mesma_peca_em_duas_lojas_vira_uma_peca(env, capsys):
    ingest(env, [item(), item(store="pichau", url="https://www.pichau.com.br/rtx-4060",
                              price_cash=179990)])
    j = json.loads(capsys.readouterr().out)
    assert j["parts_created"] == 1 and j["listings_created"] == 2
    parts = env["local"].get("/api/parts?category=gpu").json()
    assert len(parts) == 1
    assert parts[0]["best"]["store"] == "pichau" and parts[0]["best"]["price_cash"] == 179990


def test_regravar_no_mesmo_dia_nao_duplica(env):
    ingest(env, [item()], when=day(0))
    ingest(env, [item(price_cash=170000)], when=day(0))
    h = env["local"].get("/api/health").json()
    assert (h["parts"], h["listings"], h["price_snapshots"]) == (1, 1, 1)
    assert env["local"].get("/api/parts").json()[0]["best"]["price_cash"] == 170000


def test_loja_desconhecida_recusa_lote_inteiro(env):
    assert ingest(env, [item(), item(store="aliexpress", url="https://aliexpress.com/x")]) == 1
    assert env["local"].get("/api/health").json()["price_snapshots"] == 0


@pytest.mark.parametrize("campo,valor", [
    ("price_cash", 0), ("price_cash", -5), ("price_cash", 10**9),
    ("category", "mouse"), ("url", "nao-e-url"), ("brand", ""),
])
def test_recusa_dado_invalido(env, campo, valor):
    assert ingest(env, [item(**{campo: valor})]) == 1


def test_lote_vazio_recusado(env):
    f = env["tmp"] / "vazio.json"
    f.write_text('{"items": []}')
    assert ingest_mod.main([str(f)], db_path=env["db_path"]) == 1


def test_json_quebrado_recusado(env):
    f = env["tmp"] / "quebrado.json"
    f.write_text("{nao e json")
    assert ingest_mod.main([str(f)], db_path=env["db_path"]) == 1


def test_link_de_outra_peca_da_conflito_sem_gravar_nada(env):
    ingest(env, [item()])
    assert ingest(env, [item(model="GeForce RTX 4070 12GB")]) == 1  # mesma URL, outra peça
    h = env["local"].get("/api/health").json()
    assert (h["parts"], h["price_snapshots"]) == (1, 1)  # tudo ou nada


def test_specs_novos_completam_os_antigos(env):
    ingest(env, [item(specs={"recommended_psu_w": 550})], when=day(1))
    ingest(env, [item(specs={"vram_gb": 8})], when=day(0))
    specs = env["local"].get("/api/parts").json()[0]["specs"]
    assert specs == {"recommended_psu_w": 550, "vram_gb": 8}


# ------------------------------------------------------------------ leitura

def test_health_mostra_ultima_coleta(env):
    assert env["local"].get("/api/health").json()["last_collection"] is None
    ingest(env, [item()], when=day(0))
    assert env["local"].get("/api/health").json()["last_collection"] == day(0)


def test_lojas(env):
    slugs = [s["slug"] for s in env["local"].get("/api/stores").json()]
    assert slugs == ["kabum", "pichau", "terabyte", "amazon", "mercadolivre", "shopee"]


def test_filtro_categoria_e_busca(env):
    ingest(env, [item(), item(category="ram", brand="Kingston", model="Fury 16GB DDR4",
                              url="https://www.kabum.com.br/produto/2/ram", specs={"memory_type": "DDR4"})])
    assert [p["model"] for p in env["local"].get("/api/parts?category=ram").json()] == ["Fury 16GB DDR4"]
    assert [p["category"] for p in env["local"].get("/api/parts?q=kingston").json()] == ["ram"]
    assert env["local"].get("/api/parts?category=mouse").status_code == 422


def test_detalhe_com_ofertas_de_cada_loja(env):
    ingest(env, [item(), item(store="terabyte", url="https://www.terabyteshop.com.br/rtx-4060",
                              price_cash=185000, in_stock=False)])
    part = env["local"].get("/api/parts").json()[0]
    d = env["local"].get(f"/api/parts/{part['id']}").json()
    assert {o["store"] for o in d["offers"]} == {"kabum", "terabyte"}
    assert all(o["url"].startswith("https://") for o in d["offers"])
    assert d["best"]["store"] == "kabum"  # a da terabyte é mais barata mas está esgotada


def test_peca_inexistente_404(env):
    assert env["local"].get("/api/parts/999").status_code == 404
    assert env["local"].get("/api/parts/999/history").status_code == 404


def test_historico(env):
    for n, preco in ((2, 200000), (1, 195000), (0, 190000)):
        ingest(env, [item(price_cash=preco)], when=day(n))
    pid = env["local"].get("/api/parts").json()[0]["id"]
    hist = env["local"].get(f"/api/parts/{pid}/history?days=3650").json()
    assert [h["price_cash"] for h in hist] == [200000, 195000, 190000]


def test_promocao_aparece_em_deals(env):
    for n in range(10, 0, -1):
        ingest(env, [item(price_cash=200000)], when=day(n))
    ingest(env, [item(price_cash=160000)], when=day(0))  # 20% abaixo
    deals = env["local"].get("/api/deals").json()
    assert len(deals) == 1 and deals[0]["drop_pct"] == 20.0
    assert deals[0]["url"].startswith("https://www.kabum.com.br")


def test_sem_dados_deals_vazio(env):
    assert env["local"].get("/api/deals").json() == []


def test_rota_api_inexistente_404(env):
    assert env["local"].get("/api/nao-existe").status_code == 404


def test_sem_frontend_raiz_explica(env):
    r = env["local"].get("/")
    assert r.status_code == 200 and "frontend" in r.json()["status"]


# ------------------------------------------------------------------ builds e compatibilidade

def _ids(env):
    builds = env["local"].get("/api/builds").json()
    return {b["kind"]: b["id"] for b in builds}


def test_duas_builds_vazias(env):
    builds = env["local"].get("/api/builds").json()
    assert [(b["kind"], b["total_cash"], len(b["items"])) for b in builds] == [("full", 0, 8), ("upgrade", 0, 7)]


def test_escolher_peca_atualiza_total(env):
    ingest(env, [item()])
    pid = env["local"].get("/api/parts").json()[0]["id"]
    full = _ids(env)["full"]
    r = env["local"].put(f"/api/builds/{full}/items/gpu", json={"part_id": pid})
    assert r.status_code == 200 and r.json()["total_cash"] == 189990
    r = env["local"].put(f"/api/builds/{full}/items/gpu", json={"part_id": None})  # remover
    assert r.json()["total_cash"] == 0


def test_build_recusa_peca_da_categoria_errada(env):
    ingest(env, [item()])
    pid = env["local"].get("/api/parts").json()[0]["id"]
    r = env["local"].put(f"/api/builds/{_ids(env)['full']}/items/ram", json={"part_id": pid})
    assert r.status_code == 422


def test_upgrade_nao_aceita_placa_mae(env):
    r = env["local"].put(f"/api/builds/{_ids(env)['upgrade']}/items/motherboard", json={"part_id": None})
    assert r.status_code == 422


def test_build_ou_peca_inexistente(env):
    assert env["local"].put("/api/builds/99/items/gpu", json={"part_id": None}).status_code == 404
    assert env["local"].put(f"/api/builds/{_ids(env)['full']}/items/gpu",
                            json={"part_id": 999}).status_code == 404


def test_compatibilidade_na_lista_de_upgrades(env):
    ingest(env, [
        item(category="cpu", brand="AMD", model="Ryzen 7 5700X3D", url="https://www.kabum.com.br/a",
             specs={"socket": "AM4"}),
        item(category="cpu", brand="AMD", model="Ryzen 7 7800X3D", url="https://www.kabum.com.br/b",
             specs={"socket": "AM5"}),
        item(category="cpu", brand="AMD", model="Ryzen 5 sem specs", url="https://www.kabum.com.br/c",
             specs={}),
        item(category="ram", brand="Kingston", model="Fury DDR5", url="https://www.kabum.com.br/d",
             specs={"memory_type": "DDR5"}),
    ])
    parts = {p["model"]: p["compat"] for p in env["local"].get("/api/parts?upgrade=true").json()}
    assert parts["Ryzen 7 5700X3D"]["compatible"] is True
    assert parts["Ryzen 7 7800X3D"]["compatible"] is False
    assert parts["Ryzen 5 sem specs"]["compatible"] is None
    assert "não verificada" in parts["Ryzen 5 sem specs"]["warnings"][0]
    assert parts["Fury DDR5"]["compatible"] is False


def test_pc_atual(env):
    pc = env["local"].get("/api/current-pc").json()
    assert pc["socket"] == "AM4" and pc["memory_type"] == "DDR4"
