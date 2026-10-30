"""Imagem, favoritos, compatibilidade da build completa, montagem automática e modo exemplo."""

import sqlite3
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import builder
from app.db import database as db
from app.demo import build_demo
from app.main import create_app
from tests.test_api import day, ingest, item


@pytest.fixture
def env(tmp_path):
    db_path = tmp_path / "t.db"
    app = create_app(db_path=db_path, frontend_dist=tmp_path / "sem_frontend")
    return {"local": TestClient(app, base_url="http://127.0.0.1:8787"), "db_path": db_path, "tmp": tmp_path}


def P(cat, model, specs, price, n):
    return item(category=cat, brand="X", model=model, specs=specs, price_cash=price,
                url=f"https://www.kabum.com.br/produto/{n}/x")


PLATAFORMA = [
    P("cpu", "CPU AM4", {"socket": "AM4"}, 70000, 1),
    P("cpu", "CPU AM5 barata", {"socket": "AM5"}, 50000, 2),
    P("motherboard", "Placa AM4", {"socket": "AM4", "memory_type": "DDR4", "form_factor": "ATX"}, 50000, 3),
    P("motherboard", "Placa AM5", {"socket": "AM5", "memory_type": "DDR5", "form_factor": "mATX"}, 90000, 4),
    P("ram", "DDR4", {"memory_type": "DDR4"}, 20000, 5),
    P("ram", "DDR5", {"memory_type": "DDR5"}, 40000, 6),
    P("gpu", "GPU 650", {"recommended_psu_w": 650}, 200000, 7),
    P("psu", "Fonte 550", {"wattage_w": 550}, 30000, 8),
    P("psu", "Fonte 750", {"wattage_w": 750}, 50000, 9),
    P("case", "Gabinete mATX", {"motherboard_support": ["mATX"]}, 20000, 10),
    P("case", "Gabinete ATX", {"motherboard_support": ["ATX", "mATX"]}, 40000, 11),
    P("cooler", "Cooler só AM5", {"sockets": ["AM5"]}, 10000, 12),
    P("cooler", "Cooler universal", {"sockets": ["AM4", "AM5"]}, 15000, 13),
    P("storage", "SSD", {}, 30000, 14),
]


# ------------------------------------------------------------------ imagem

def test_imagem_entra_pelo_ingest_e_sai_na_api(env):
    assert ingest(env, [item(image_url="https://img.kabum.com.br/x.jpg")]) == 0
    p = env["local"].get("/api/parts").json()[0]
    assert p["image_url"] == "https://img.kabum.com.br/x.jpg"
    # lote sem imagem não apaga a imagem que já existe
    assert ingest(env, [item()]) == 0
    assert env["local"].get("/api/parts").json()[0]["image_url"] == "https://img.kabum.com.br/x.jpg"


def test_imagem_http_e_recusada(env):
    assert ingest(env, [item(image_url="http://img.kabum.com.br/x.jpg")]) == 1
    assert ingest(env, [item(image_url="javascript:alert(1)")]) == 1
    conn = db.connect(env["db_path"])
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO parts (category, brand, model, image_url) VALUES ('gpu','a','b','http://x')")


def test_migracao_adiciona_image_url_em_banco_velho(tmp_path):
    path = tmp_path / "velho.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE parts (id INTEGER PRIMARY KEY, category TEXT NOT NULL, brand TEXT NOT NULL,"
                 " model TEXT NOT NULL, specs TEXT NOT NULL DEFAULT '{}', created_at TEXT,"
                 " UNIQUE (category, brand, model))")
    conn.close()
    conn = db.init_db(path)
    assert "image_url" in {r["name"] for r in conn.execute("PRAGMA table_info(parts)")}


# ------------------------------------------------------------------ favoritos

def test_favoritar_e_desfavoritar(env):
    ingest(env, [item()])
    pid = env["local"].get("/api/parts").json()[0]["id"]
    assert env["local"].put(f"/api/favorites/{pid}").status_code == 204
    assert env["local"].put(f"/api/favorites/{pid}").status_code == 204  # idempotente
    assert env["local"].get("/api/favorites").json() == [pid]
    assert env["local"].get("/api/parts?favorites=true").json()[0]["favorite"] is True
    assert env["local"].delete(f"/api/favorites/{pid}").status_code == 204
    assert env["local"].get("/api/favorites").json() == []
    assert env["local"].get("/api/parts?favorites=true").json() == []


def test_favoritar_peca_inexistente_da_404(env):
    assert env["local"].put("/api/favorites/999").status_code == 404


# ------------------------------------------------------------------ compatibilidade entre peças

@pytest.mark.parametrize("cat,specs,others,esperado", [
    ("cpu", {"socket": "AM5"}, {"motherboard": {"socket": "AM4"}}, False),
    ("cpu", {"socket": "am4"}, {"motherboard": {"socket": "AM4"}}, True),
    ("ram", {"memory_type": "DDR5"}, {"motherboard": {"memory_type": "DDR4"}}, False),
    ("case", {"motherboard_support": ["mATX"]}, {"motherboard": {"form_factor": "ATX"}}, False),
    ("cooler", {"sockets": ["AM5"]}, {"cpu": {"socket": "AM4"}}, False),
    ("psu", {"wattage_w": 550}, {"gpu": {"recommended_psu_w": 650}}, False),
    ("psu", {"wattage_w": 650}, {"gpu": {"recommended_psu_w": 650}}, True),
    ("cpu", {}, {"motherboard": {"socket": "AM4"}}, None),
    ("storage", {}, {"motherboard": {"socket": "AM4"}}, True),
])
def test_check_in_build(cat, specs, others, esperado):
    assert builder.check_in_build(cat, specs, others)["compatible"] is esperado


def test_montagem_automatica_escolhe_a_mais_barata_compativel(env):
    assert ingest(env, PLATAFORMA) == 0
    r = env["local"].post("/api/builds/1/auto")
    assert r.status_code == 200
    escolha = {i["category"]: i["model"] for i in r.json()["items"]}
    # AM4: 700+500+200+400(gab ATX)+150(cooler univ)+2000+500(fonte 750)+300 = 4750
    # AM5: 500+900+400+200+100+2000+500+300 = 4900  → AM4 vence, mesmo com a CPU AM5 mais barata
    assert escolha == {"cpu": "CPU AM4", "motherboard": "Placa AM4", "ram": "DDR4",
                       "case": "Gabinete ATX", "cooler": "Cooler universal", "gpu": "GPU 650",
                       "psu": "Fonte 750", "storage": "SSD"}
    assert r.json()["total_cash"] == 475000
    assert all(i["compat"]["compatible"] is True for i in r.json()["items"])


def test_montagem_pega_a_mais_barata_entre_varias_compativeis(env):
    extras = [
        P("storage", "SSD caro", {}, 90000, 20),
        P("cpu", "CPU AM4 cara", {"socket": "AM4"}, 150000, 21),
        P("case", "Gabinete ATX caro", {"motherboard_support": ["ATX"]}, 99000, 22),
    ]
    ingest(env, PLATAFORMA + extras)
    escolha = {i["category"]: i["model"] for i in env["local"].post("/api/builds/1/auto").json()["items"]}
    assert (escolha["storage"], escolha["cpu"], escolha["case"]) == ("SSD", "CPU AM4", "Gabinete ATX")


def test_montagem_prefere_verificada_a_nao_verificada(env):
    ingest(env, PLATAFORMA + [P("cooler", "Cooler sem specs", {}, 5000, 23)])
    escolha = {i["category"]: i["model"] for i in env["local"].post("/api/builds/1/auto").json()["items"]}
    assert escolha["cooler"] == "Cooler universal"


def test_montagem_prefere_build_completa_a_barata_incompleta(env):
    # placa AM5 baratíssima, mas não existe RAM DDR5: a build sairia sem memória
    ingest(env, [
        P("motherboard", "AM5 barata", {"socket": "AM5", "memory_type": "DDR5"}, 1000, 30),
        P("motherboard", "AM4 cara", {"socket": "AM4", "memory_type": "DDR4"}, 90000, 31),
        P("cpu", "CPU AM5", {"socket": "AM5"}, 50000, 32),
        P("cpu", "CPU AM4", {"socket": "AM4"}, 50000, 33),
        P("ram", "DDR4", {"memory_type": "DDR4"}, 20000, 34),
    ])
    r = env["local"].post("/api/builds/1/auto").json()
    escolha = {i["category"]: i["model"] for i in r["items"] if i["part_id"]}
    assert escolha["motherboard"] == "AM4 cara" and escolha["ram"] == "DDR4"


def test_montagem_automatica_so_na_build_completa(env):
    assert env["local"].post("/api/builds/2/auto").status_code == 422
    assert env["local"].post("/api/builds/99/auto").status_code == 404


def test_opcoes_marcam_incompativel_e_poem_no_fim(env):
    ingest(env, PLATAFORMA)
    env["local"].post("/api/builds/1/auto")
    ops = env["local"].get("/api/builds/1/options/cpu").json()
    assert [o["model"] for o in ops] == ["CPU AM4", "CPU AM5 barata"]
    assert ops[1]["compat"]["compatible"] is False
    assert "não encaixa" in ops[1]["compat"]["warnings"][0]


def test_cartao_tem_minigrafico(env):
    for n in (3, 2, 1):
        ingest(env, [item(price_cash=100000 + n)], when=day(n))
    assert env["local"].get("/api/parts").json()[0]["spark"] == [100003, 100002, 100001]


# ------------------------------------------------------------------ modo exemplo

def test_demo_aparece_so_com_banco_real_vazio(tmp_path):
    demo = build_demo(tmp_path / "demo.db", today=date(2026, 10, 9))
    real = tmp_path / "real.db"
    c = TestClient(create_app(db_path=real, frontend_dist=tmp_path / "x", demo_db_path=demo), base_url="http://127.0.0.1:8787")
    h = c.get("/api/health").json()
    assert h["demo"] is True and h["parts"] > 0
    assert len(c.get("/api/deals").json()) >= 3     # o exemplo tem promoções de verdade pela regra
    # 1ª peça real gravada → o exemplo some
    env = {"tmp": tmp_path, "db_path": real}
    assert ingest(env, [item()]) == 0
    h = c.get("/api/health").json()
    assert h["demo"] is False and h["parts"] == 1


def test_demo_links_sao_das_lojas_e_sem_imagem(tmp_path):
    conn = db.connect(build_demo(tmp_path / "demo.db"))
    urls = [r[0] for r in conn.execute("SELECT url FROM listings")]
    assert urls and all(u.startswith(("https://www.kabum.com.br/", "https://www.pichau.com.br/",
                                      "https://www.terabyteshop.com.br/")) for u in urls)
    assert conn.execute("SELECT COUNT(*) FROM parts WHERE image_url IS NOT NULL").fetchone()[0] == 0


def test_build_completa_do_demo_e_compativel(tmp_path):
    demo = build_demo(tmp_path / "demo.db")
    c = TestClient(create_app(db_path=tmp_path / "real.db", frontend_dist=tmp_path / "x", demo_db_path=demo), base_url="http://127.0.0.1:8787")
    r = c.post("/api/builds/1/auto").json()
    assert r["missing"] == [] and r["unavailable"] == []
    assert all(i["compat"]["compatible"] is True for i in r["items"])


# ------------------------------------------------------------------ frontend servido pelo backend

def test_frontend_servido_sem_vazar_arquivo_de_fora(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>INDEX</html>")
    (dist / "favicon.svg").write_text("<svg/>")
    (tmp_path / "segredo.txt").write_text("NAO PODE")
    c = TestClient(create_app(db_path=tmp_path / "t.db", frontend_dist=dist), base_url="http://127.0.0.1:8787")
    assert "INDEX" in c.get("/").text
    assert "INDEX" in c.get("/builds/completa").text       # rota do SPA
    assert c.get("/favicon.svg").text == "<svg/>"
    for path in ("/../segredo.txt", "/%2e%2e/segredo.txt", "/..%2fsegredo.txt"):
        assert "NAO PODE" not in c.get(path).text
