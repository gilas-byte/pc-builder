"""Canais do Telegram. Páginas reais salvas em tests/fixtures/tg_*.html (12/10/2026).
Rede e Ollama são falsos aqui: os testes não dependem de internet nem da placa."""

import json
from datetime import datetime
from pathlib import Path

import pytest

from app.db import database as db
from app.tg import run as R
from app.tg import vote as V
from app.tg.classify import adjust_kind, category, product_key, title_of
from app.tg.parse import Post, has_preview, parse_page, price_cents, store_of

F = Path(__file__).parent / "fixtures"


def page(name):
    return (F / f"tg_{name}.html").read_text(encoding="utf-8")


# --------------------------------------------------------------------------- leitura da página

def test_parse_pagina_real():
    posts = parse_page(page("OPromoFacil"))
    assert len(posts) == 8
    assert [p.msg_id for p in posts] == sorted(p.msg_id for p in posts)
    p = posts[0]
    assert p.channel == "OPromoFacil" and p.url == f"https://t.me/OPromoFacil/{p.msg_id}"
    assert p.posted_at.startswith("2026-10-12T")


def test_canal_sem_previa_web_e_detectado():
    assert not has_preview(page("sem_previa"))
    assert has_preview(page("gpcrpromo"))


# --------------------------------------------------------------------------- preço (formatos reais dos 9 canais)

@pytest.mark.parametrize("texto, centavos", [
    ("🚨 Air Cooler AK400\n\n💥 🔥 Por: R$148,00\n[em até 4x sem juros]", 14800),               # OPromoFacil
    ("Air Cooler AK400\n\nPOR: 148 REAIS E FRETE GRÁTIS PRIME", 14800),                         # EconomizandocomJP
    ("Notebook Positivo\n\nPOR: 2640 REAIS\n\nCUPOM: OFERTADEHOJE", 264000),
    ("Smart TV\n\npor: 928 (pix)\nou 1009 em 12x no cartão", 92800),
    ("🍅 Mixer 600W\n\n⚡ por R$ 237 no pix", 23700),                                            # grupo_promocoes
    ("PS5 Slim\n\nDe: R$ 4.299,00\nPor: R$ 3.741,10 (Pix)", 374110),                           # lipeofertas: ignora o De
    ("🔥 Monitor LG 24\"\n\n💲R$490\n\nAbra a LIVE, resgate o cupom de R$170", 49000),           # gpcrpromo
    ("Combo Galaxy A57 + Watch8\n\n- O Watch8 sozinho custa R$1000/R$1100\n\n💲R$2.206,16\n🛍Cupom R$100 OFF", 220616),
    ("Controle DualSense\n\n💸 R$ 359", 35900),                                                  # ToptechPROMO
    ("Console PS5 Slim (Shopee)\n\nResgate o cupom de R$100 OFF\n\nR$3.587,91 no PIX", 358791),  # descontoemgames
    ("Notebook IdeaPad\n🔗 https://x\nPor R$3257 no PIX", 325700),                              # especialistaemti
])
def test_preco(texto, centavos):
    assert price_cents(texto) == centavos


@pytest.mark.parametrize("texto", [
    "🔥 Resgate o cupom Mercado Livre\n\n20% OFF max R$ 50 Lojas Oficiais",
    "🔥 Ganhe 10% OFF nas compras a partir de R$ 30, limitado a R$ 15 de desconto",
    "Cupons liberados de hora em hora https://s.shopee.com.br/x",
])
def test_cupom_nao_tem_preco(texto):
    assert price_cents(texto) is None


def test_loja_pelo_link():
    mk = lambda links, text="x": Post("c", 1, "2026-10-12T10:00:00", text, links)
    assert store_of(mk(["https://meli.la/2uVzJi6"])) == "mercadolivre"
    assert store_of(mk(["https://s.shopee.com.br/20wAz0ukeY?lp=aff"])) == "shopee"
    assert store_of(mk(["https://cupom.cc/x", "https://www.amazon.com.br/dp/B0G5RDXV7N"])) == "amazon"
    assert store_of(mk(["https://tidd.ly/x"], "Loja: #Magalu")) == "magalu"


# --------------------------------------------------------------------------- título

@pytest.mark.parametrize("texto, titulo", [
    ("🤩PS5 SLIM DIGITAL POR UM ÓTIMO PREÇO!\n\nPlayStation 5 Slim Edição Digital\n\n825GB - Branco - 1 Controle\n\nPor: R$ 3.741,10",
     "PlayStation 5 Slim Edição Digital"),
    ("PARCELADO 🔥🔥🔥🔥\n\nAir Cooler GamerStorm X Redragon AK400 RD Preto\n\nPOR: 148 REAIS",
     "Air Cooler GamerStorm X Redragon AK400 RD Preto"),
    ("😍 BARATINHO E MUITO CONFORTÁVEL. COMPREI E AMEI!\n\n👟 Tênis Feminino Vili\n\n🔥 por R$ 76", "Tênis Feminino Vili"),
    ("⚡TELA 16\" IPS + RYZEN 7\n\nVAIO FE16\n\nRyzen 7 5825U - 16GB RAM - 256GB SSD\n\nPor: R$ 3.569,01", "VAIO FE16"),
    ("Notebook Positivo Vision R15M\n\n- Ryzen 5 5625U\n\nPOR: 2640 REAIS", "Notebook Positivo Vision R15M"),
])
def test_titulo(texto, titulo):
    assert title_of(texto) == titulo


# --------------------------------------------------------------------------- peça de PC (sem IA)

@pytest.mark.parametrize("titulo, cat", [
    ("Placa de Vídeo PELADN RTX 5060, 8GB, GDDR7, 128-bit", "gpu"),
    ("SSD Kingston NV3 1TB M.2 2280 PCIe 4.0 NVMe 6000 MB/s", "storage"),
    ("Air Cooler GamerStorm X Redragon AK400 RD Preto 4 Heatpipes", "cooler"),
    ("Placa-Mãe Amd Am4 Asus Tuf Gaming B550m-Plus", "motherboard"),
    ("Monitor LG UltraGear 24G411A-B 24\", FHD, 144Hz", "monitor"),
    ("Memória RAM Skhynix DDR5 8GB - 4800MHz - Seminova", "ram"),
    ("Fonte Atx MSI 650W Mag 2.4 Pcie 80 Plus Bronze", "psu"),
    # enganos reais do 1º teste (12/10/2026): não são peça
    ("3L Picador De Alimentos Moedor De Carne Mixer Elétrica Processador", None),
    ("Xiaomi 2026 Redmi Note 17 Amoled 120Hz Processador Snapdragon 6s Gen 2", None),
    ("Suporte Articulado de Parede Para Monitor Zinnia Fortress 200", None),
    ("Pc Home Essential S, Intel Core i3, 8Gb De Ram, Ssd 120Gb", None),
    ("Smart TV Hisense 50\" com Processador AI", None),
    ("ASUS ROG Strix G16 Intel Core i9 - RTX 5060 8GB", None),            # notebook
    ("Notebook Gamer Acer Nitro V15 i7-13620H - RTX 4050 6GB", None),    # notebook
    ("Lenovo Slim 3 i5 - 16 GB RAM DDR5 - 512 GB SSD", None),             # notebook
    ("Fonte de luz LED para estúdio", None),                               # "fonte" sem watts
])
def test_categoria(titulo, cat):
    assert category(titulo) == cat


@pytest.mark.parametrize("titulo, cat, chave", [
    ("GPU INNO3D GEFORCE RTX 5060 TWIN X2 8GB 128BITS GDDR7", "gpu", "gpu|rtx 5060|8gb"),
    ("Placa de Vídeo Palit GeForce Rtx 5060 Ti Infinity 16Gb Gddr7", "gpu", "gpu|rtx 5060 ti|16gb"),
    ("Processador Ryzen 7 5700X 3.4GHz (4.6GHz Max) - Novo S/Box", "cpu", "cpu|ryzen 7 5700x"),
    ("Memória RAM Skhynix DDR5 8GB - 4800MHz", "ram", "ram|ddr5|8gb|4800"),
    ("Monitor Gamer Curvo ASUS TUF VG34WQML5A 34\" WQHD 250Hz", "monitor", "monitor|asus|vg34wqml5a"),
    ("Monitor Asus TUF 34\" WQHD 3440X1440 Curvo 1500R Som Integrado VA 250Hz", "monitor", "monitor|asus|34|qhd|250hz"),
    ("Gabinete Gamer Mancer CV100 Purple Edition, Mid-Tower", "case", "case|cv100"),
])
def test_chave_do_produto(titulo, cat, chave):
    assert product_key(titulo, cat) == chave


def test_rtx_5060_e_5060_ti_nao_sao_o_mesmo_produto():
    a = product_key("Placa de Vídeo RTX 5060 8GB", "gpu")
    b = product_key("Placa de Vídeo RTX 5060 Ti 8GB", "gpu")
    assert a and b and a != b


def test_sem_vram_nao_tem_chave():
    assert product_key("Placa de Vídeo RTX 5060 Gamer", "gpu") is None


# --------------------------------------------------------------------------- votação (Ollama falso)

def fake_chat(answers: dict[str, dict[str, str]] | None = None, default="outro_tech", down=False):
    """answers[modelo][trecho do título] = tipo final. O portão responde de acordo."""
    calls = []

    def chat(model, system, user, schema):
        calls.append((model, user))
        if down:
            raise V.OllamaDown("connection refused")
        kind = default
        for frag, k in (answers or {}).get(model, {}).items():
            if frag in user:
                kind = k
        if "resposta" in schema["properties"]:
            return json.dumps({"resposta": {"nao_tech": "nao", "cupom": "cupom"}.get(kind, "sim")})
        return json.dumps({"tipo": kind})
    chat.calls = calls
    return chat


def test_votacao_unanime_maioria_e_duvidoso():
    q, l, g = V.MODELS
    chat = fake_chat({q: {"A": "peca:gpu", "B": "audio", "C": "monitor"},
                      l: {"A": "peca:gpu", "B": "audio", "C": "notebook"},
                      g: {"A": "peca:gpu", "B": "periferico", "C": "celular_tablet"}})
    (ka, na, _), (kb, nb, _), (kc, nc, _) = V.vote(["A", "B", "C"], chat)
    assert (ka, na) == ("peca:gpu", 3)
    assert (kb, nb) == ("audio", 2)
    assert kc == V.DOUBT


def test_votacao_carrega_cada_modelo_uma_vez_em_sequencia():
    chat = fake_chat()
    V.vote(["x", "y", "z"], chat)
    order = [m for m, _ in chat.calls]
    # todos os pedidos do 1º modelo antes do 2º (o modelo fica carregado na placa)
    assert order == sorted(order, key=V.MODELS.index)


# --------------------------------------------------------------------------- rodada completa

def post_html(channel, msg_id, when, text):
    body = text.replace("\n", "<br/>")
    return (f'<div class="tgme_widget_message_wrap"><div class="tgme_widget_message" data-post="{channel}/{msg_id}">'
            f'<div class="tgme_widget_message_text js-message_text" dir="auto">{body}</div>'
            f'<time datetime="{when}+00:00" class="time">x</time></div></div>')


def fake_fetch(pages: dict[str, list[tuple[int, str, str]]], broken=()):
    """pages[canal] = [(msg_id, quando_utc, texto)]. Responde t.me/s/<canal>[?before=N] com até 3 posts."""
    calls = []

    def fetch(url):
        calls.append(url)
        ch = url.split("/s/")[1].split("?")[0]
        if ch in broken:
            raise ConnectionError("fora do ar")
        before = int(url.split("before=")[1]) if "before=" in url else 10**9
        posts = [p for p in pages.get(ch, []) if p[0] < before][-3:]
        return "<html>" + "".join(post_html(ch, *p) for p in posts) + "</html>"
    fetch.calls = calls
    return fetch


GPU = "Placa de Vídeo RTX 5060 8GB GDDR7 Palit\n\nPor: R$ {}"
CH = "gpcrpromo"


@pytest.fixture
def conn(tmp_path):
    c = db.init_db(tmp_path / "t.db")
    yield c
    c.close()


def rodada(conn, pages, chat=None, now=datetime(2026, 10, 12, 12, 0), **kw):
    return R.run_round(conn, fake_fetch(pages, **kw), chat or fake_chat(default="peca:gpu"), now,
                       channels=[CH], pause=0, log=lambda *_: None)


def test_lixo_e_cupom_nao_sao_guardados(conn):
    chat = fake_chat({m: {"Fralda": "nao_tech", "Cupom": "cupom"} for m in V.MODELS}, default="peca:gpu")
    rodada(conn, {CH: [(1, "2026-10-12T10:00:00", "Fralda Pampers XG\n\nPor: R$ 80"),
                       (2, "2026-10-12T10:01:00", "Cupom Shopee\n\nR$ 20 OFF em R$ 89 - Cupom: X"),
                       (3, "2026-10-12T10:02:00", GPU.format("2.699,00"))]}, chat)
    rows = conn.execute("SELECT title, kind, product_key FROM tg_offers").fetchall()
    assert [(r["kind"], r["product_key"]) for r in rows] == [("peca:gpu", "gpu|rtx 5060|8gb")]


def test_rodar_de_novo_nao_duplica_e_le_so_o_novo(conn):
    pages = {CH: [(1, "2026-10-12T10:00:00", GPU.format("2.700,00"))]}
    rodada(conn, pages)
    pages[CH].append((2, "2026-10-12T11:00:00", GPU.format("2.650,00")))
    res = rodada(conn, pages)
    assert res["read"] == 1
    assert conn.execute("SELECT COUNT(*) FROM tg_offers").fetchone()[0] == 2
    assert conn.execute("SELECT last_msg_id FROM tg_channels WHERE slug = ?", (CH,)).fetchone()[0] == 2


def test_le_varias_paginas_ate_a_ultima_vista(conn):
    pages = {CH: [(1, "2026-10-12T09:00:00", GPU.format("2.700,00"))]}
    rodada(conn, pages)
    pages[CH] += [(i, f"2026-10-12T10:{i:02d}:00", GPU.format("2.700,00")) for i in range(2, 9)]
    f = fake_fetch(pages)
    R.run_round(conn, f, fake_chat(default="peca:gpu"), datetime(2026, 10, 12, 12), channels=[CH], pause=0,
                log=lambda *_: None)
    assert conn.execute("SELECT COUNT(*) FROM tg_offers").fetchone()[0] == 8
    assert len(f.calls) == 3            # 3 páginas de 3 posts cobrem os 7 novos e param no já visto


def precos(conn, valores, start=1, day=10):
    """Um post por rodada (canal novo só lê a 1ª página; assim nenhum preço se perde no teste)."""
    res = None
    for i, v in enumerate(valores):
        pages = {CH: [(start + i, f"2026-10-{day:02d}T1{i}:00:00", GPU.format(v))]}
        res = rodada(conn, pages, now=datetime(2026, 10, day, 23))
    return res


def test_sem_3_precos_anteriores_nao_avisa(conn):
    res = precos(conn, ["2.700,00", "2.000,00"])
    assert res["alerts"] == []


def test_menor_ja_visto_avisa_mesmo_com_menos_de_7(conn):
    precos(conn, ["2.700,00", "2.750,00", "2.690,00"], day=10)                # min 2.690, mediana 2.700
    res = precos(conn, ["2.650,00"], start=10, day=11)                         # -1,5% da mediana, mas é o menor
    assert [a["why"] for a in res["alerts"]] == ["menor_ja_visto"]


def test_7_abaixo_da_mediana_avisa_sem_ser_o_menor(conn):
    precos(conn, ["2.400,00", "2.800,00", "2.800,00", "2.800,00"], day=10)   # min 2.400, mediana 2.800
    res = precos(conn, ["2.600,00"], start=10, day=11)                         # -7,1%, mas acima do menor
    assert [a["why"] for a in res["alerts"]] == ["abaixo_7"]


def test_6_abaixo_e_acima_do_menor_nao_avisa(conn):
    precos(conn, ["2.400,00", "2.800,00", "2.800,00", "2.800,00"], day=10)
    res = precos(conn, ["2.640,00"], start=10, day=11)                         # -5,7%
    assert res["alerts"] == []


def test_aviso_uma_vez_por_produto_por_dia(conn, tmp_path):
    precos(conn, ["2.700,00", "2.750,00", "2.690,00"], day=10)
    a = precos(conn, ["2.600,00"], start=10, day=11)["alerts"]
    R.mark_sent(conn, R.pending(conn, a, "2026-10-11"), "2026-10-11")
    b = precos(conn, ["2.500,00"], start=20, day=11)["alerts"]
    assert b and R.pending(conn, b, "2026-10-11") == []


def test_tipo_do_script_e_da_ia_precisam_bater_pra_ter_chave(conn):
    """Script diz GPU, mas a IA diz notebook (ex.: anúncio de notebook com RTX): sem chave, sem comparação."""
    chat = fake_chat(default="notebook")
    rodada(conn, {CH: [(1, "2026-10-12T10:00:00", GPU.format("2.700,00"))]}, chat)
    assert conn.execute("SELECT kind, product_key FROM tg_offers").fetchone()[:] == ("notebook", None)


def test_ollama_fora_do_ar_guarda_sem_tipo_e_avisa(conn):
    """Modo "só Ollama" = o comportamento de antes. No modo automático as regras assumem (ver test_classifier_and_ollama.py)."""
    from app import settings as S
    S.save(conn, {"classifier": "ollama"})
    res = rodada(conn, {CH: [(1, "2026-10-12T10:00:00", GPU.format("2.700,00"))]}, fake_chat(down=True))
    assert "ollama" in res["errors"]
    row = conn.execute("SELECT kind, product_key FROM tg_offers").fetchone()
    assert row["kind"] is None and row["product_key"] is None
    assert "ollama" in R.format_message([], res["errors"], {})


def test_canal_fora_do_ar_so_avisa_depois_de_3_rodadas(conn):
    for n in range(1, 4):
        res = rodada(conn, {}, broken=(CH,))
        fails = {r["slug"]: r["fail_count"] for r in conn.execute("SELECT slug, fail_count FROM tg_channels")}
        msg = R.format_message([], res["errors"], fails)
        assert (CH in msg) == (n >= 3)


def test_canal_sem_previa_vira_erro_claro(conn):
    f = lambda url: page("sem_previa")
    res = R.run_round(conn, f, fake_chat(), datetime(2026, 10, 12), channels=["ctofertas"], pause=0,
                      log=lambda *_: None)
    assert "sem prévia" in res["errors"]["ctofertas"]


def test_referencia_inclui_preco_das_lojas(conn):
    """Preço da KaBuM/Terabyte/Amazon do mesmo modelo conta como referência."""
    with conn:
        conn.execute("INSERT INTO parts (category, brand, model, specs) VALUES ('gpu','NVIDIA','GeForce RTX 5060 8GB','{}')")
        pid = conn.execute("SELECT id FROM parts").fetchone()[0]
        for i, (slug, cents) in enumerate([("kabum", 279999), ("terabyte", 269999), ("amazon", 279998)]):
            sid = conn.execute("SELECT id FROM stores WHERE slug = ?", (slug,)).fetchone()[0]
            conn.execute("INSERT INTO listings (part_id, store_id, url, title) VALUES (?,?,?,?)",
                         (pid, sid, f"https://x/{i}", "Placa de Vídeo RTX 5060 8GB GDDR7"))
            conn.execute("INSERT INTO price_snapshots (listing_id, price_cash, in_stock, collected_at) "
                         "VALUES (?,?,1,'2026-10-11T08:00:00')", (conn.execute("SELECT last_insert_rowid()").fetchone()[0], cents))
    res = rodada(conn, {CH: [(1, "2026-10-12T10:00:00", GPU.format("2.564,00"))]})
    assert [a["why"] for a in res["alerts"]] == ["menor_ja_visto"]
    assert res["alerts"][0]["ref"]["n"] == 3


def test_mensagem_do_aviso(conn):
    precos(conn, ["2.700,00", "2.750,00", "2.690,00"], day=10)
    a = precos(conn, ["2.564,00"], start=10, day=11)["alerts"]
    msg = R.format_message(a, {}, {})
    assert "R$ 2.564,00" in msg and "menor preço já visto" in msg and f"https://t.me/{CH}/10" in msg


def test_main_notify_silencioso_sem_novidade(tmp_path, capsys):
    rc = R.main(["--notify", "--channels", CH], db_path=tmp_path / "t.db", fetch=fake_fetch({}),
                chat=fake_chat(), pause=0, now=datetime(2026, 10, 12, 12))
    assert rc == 0 and capsys.readouterr().out == ""


def test_preco_igual_ao_menor_nao_e_novo_menor(conn):
    """Empate com o menor já visto não é 'menor já visto' (senão todo repost do mesmo preço vira aviso)."""
    precos(conn, ["2.690,00", "2.700,00", "2.750,00"], day=10)       # min 2.690, mediana 2.700
    res = precos(conn, ["2.690,00"], start=10, day=11)               # igual ao menor, -0,4% da mediana
    assert res["alerts"] == []


def test_canal_com_1_ou_2_falhas_fica_quieto(conn):
    res = rodada(conn, {}, broken=(CH,))
    assert R.format_message([], res["errors"], {CH: 1}) == ""
    assert R.format_message([], res["errors"], {CH: 2}) == ""
    assert CH in R.format_message([], res["errors"], {CH: 3})


@pytest.mark.parametrize("titulo, chave", [
    ("Cooler Para Processador DeepCool High Performance AK400, 120mm, Intel-AMD", "cooler|ak400"),
    ("Cooler Para Processador DeepCool AK400 Zero Dark, 120mm, Intel-AMD", "cooler|ak400|zerodark"),
    ("Cooler Para Processador DeepCool High Performance AK400 WH, 120mm, White", "cooler|ak400|white"),
    ("Air Cooler GamerStorm X Redragon AK400 RD Preto 4 Heatpipes Fan 120 mm", "cooler|ak400|rd"),
    # marca com número ("Mach1") vira o "código": não é o ideal, mas é estável (os 2 posts reais batem)
    ("Air Cooler Mach1 Boreal, Digital, Amd e Intel, 120mm, Preto B40 Dig V2", "cooler|mach1|digital"),
])
def test_variante_de_cooler_e_outro_produto(titulo, chave):
    """Bug real (12/10/2026): AK400, AK400 Zero Dark e AK400 WH viravam o mesmo produto; mediana errada."""
    assert product_key(titulo, "cooler") == chave


# --------------------------------------------------------------------------- API

def test_api_ofertas_e_filtros(tmp_path):
    from fastapi.testclient import TestClient
    from app.main import create_app
    path = tmp_path / "t.db"
    conn = db.init_db(path)
    now = datetime.now().replace(microsecond=0)
    hoje = now.date().isoformat()
    chat = fake_chat({m: {"Fone": "audio"} for m in V.MODELS}, default="peca:gpu")
    pages = {CH: [(1, f"{hoje}T00:00:01", GPU.format("2.700,00")),
                  (2, f"{hoje}T00:00:02", "Fone JBL Tune 520\n\nPor: R$ 199")]}
    rodada(conn, pages, chat, now=now)
    conn.close()
    c = TestClient(create_app(db_path=path, frontend_dist=tmp_path / "x"), base_url="http://127.0.0.1:8787")
    todas = c.get("/api/tg/offers").json()
    assert {o["kind"] for o in todas} == {"peca:gpu", "audio"}
    assert [o["title"] for o in c.get("/api/tg/offers?kind=audio").json()] == ["Fone JBL Tune 520"]
    assert c.get("/api/tg/offers?only_deals=true").json() == []          # sem histórico, sem promoção
    meta = c.get("/api/tg/meta").json()
    assert meta["total"] == 2 and {k["value"] for k in meta["kinds"]} == {"peca:gpu", "audio"}
    assert any(ch["slug"] == CH for ch in meta["channels"])


def test_http_fetch_tenta_de_novo_quando_o_tme_derruba(monkeypatch):
    import httpx
    monkeypatch.setattr(R.time, "sleep", lambda s: None)
    n = {"c": 0}

    def handler(request):
        n["c"] += 1
        if n["c"] < 3:
            raise httpx.RemoteProtocolError("Server disconnected without sending a response.")
        return httpx.Response(200, text="<html>ok</html>")
    real = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    assert R.http_fetch()("https://t.me/s/x") == "<html>ok</html>" and n["c"] == 3


def test_http_fetch_nao_insiste_em_404(monkeypatch):
    import httpx
    monkeypatch.setattr(R.time, "sleep", lambda s: None)
    n = {"c": 0}

    def handler(request):
        n["c"] += 1
        return httpx.Response(404)
    real = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    with pytest.raises(httpx.HTTPStatusError):
        R.http_fetch()("https://t.me/s/x")
    assert n["c"] == 1


# --------------------------------------------------------------------------- busca e cache (12/10/2026)

@pytest.mark.parametrize("q, titulo, acha", [
    ("suporte monitor", "Suporte Articulado Para Monitor Zinnia Nimbo 110", True),   # caso real
    ("monitor suporte", "Suporte Articulado Para Monitor Zinnia Nimbo 110", True),   # qualquer ordem
    ("placa video", "Placa de Vídeo RTX 5060 8GB", True),                            # sem acento, pula "de"
    ("PLACA DE VÍDEO", "placa de video rtx 5060", True),
    ("monitores", "Monitor LG UltraGear 24GS60F", True),                             # plural simples
    ("rtx 5060", "Placa de Vídeo RTX 5060 8GB", True),
    ("16 gb", "Memória DDR5 16GB 5600MHz", True),
    ("suporte teclado", "Suporte Articulado Para Monitor", False),                    # toda palavra precisa existir
    ("5060 ti", "Placa de Vídeo RTX 5060 8GB", False),
    ("rtx 5060 ti", "Suporte Articulado RTX 5060", False),                           # "ti" não casa no meio
    ("moni", "Monitor LG UltraGear", True),                                          # enquanto digita
])
def test_busca_palavra_por_palavra(q, titulo, acha):
    from app.search import matcher
    assert matcher(q)(titulo) is acha


def test_busca_vazia_nao_filtra():
    from app.search import matcher
    assert matcher("") is None and matcher("  !! ") is None


def _app_com(tmp_path, ofertas):
    from fastapi.testclient import TestClient
    from app.main import create_app
    path = tmp_path / "t.db"
    conn = db.init_db(path)
    now = datetime.now().replace(microsecond=0)
    hoje = now.date().isoformat()
    pages = {CH: [(i + 1, f"{hoje}T00:00:0{i}", t) for i, t in enumerate(ofertas)]}
    rodada(conn, pages, fake_chat(default="outro_tech"), now=now)
    conn.close()
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>tela</html>")
    return TestClient(create_app(db_path=path, frontend_dist=dist), base_url="http://127.0.0.1:8787")


def test_api_busca_dos_canais_por_palavra(tmp_path):
    c = _app_com(tmp_path, ["Suporte Articulado Para Monitor Zinnia\n\nPor: R$ 199",
                            "Suporte de Celular Veicular\n\nPor: R$ 30"])
    assert [o["title"] for o in c.get("/api/tg/offers?q=suporte monitor").json()] == \
        ["Suporte Articulado Para Monitor Zinnia"]
    assert len(c.get("/api/tg/offers?q=suporte").json()) == 2


def test_busca_respeita_o_limite_depois_de_filtrar(tmp_path):
    """O filtro é no Python: o limite tem que valer sobre o que casou, não sobre o que veio do banco."""
    c = _app_com(tmp_path, [f"Cabo HDMI {i}\n\nPor: R$ 30" for i in range(5)] + ["Suporte Monitor\n\nPor: R$ 99"])
    assert [o["title"] for o in c.get("/api/tg/offers?q=suporte&limit=1").json()] == ["Suporte Monitor"]


def test_tela_nao_fica_presa_no_cache(tmp_path):
    c = _app_com(tmp_path, [])
    for rota in ("/", "/canais"):
        r = c.get(rota)
        assert r.text == "<html>tela</html>" and r.headers["cache-control"] == "no-cache"


# --------------------------------------------------------------------------- peças dos canais na aba Peças

@pytest.mark.parametrize("texto, titulo, pros_modelos", [
    # bug real: post de notebook com chamada "RYZEN 5 ..." virou processador por unanimidade
    ("🔥 RYZEN 5 COM BOM PREÇO\n\nPositivo Vision R15M\n\nRyzen 5 5625U - 8GB RAM\n\nPor: R$ 2.534,43",
     "Positivo Vision R15M", "Positivo Vision R15M — Ryzen 5 5625U - 8GB RAM"),
    ("⚡TUF 5060 COMPLETO COM 16GB E WINDOWS\n\nASUS TUF GAMING F16 com RTX 5060\n\ni5 14450HX - RTX 5060 8GB\n\nPor: R$ 7.869,34",
     "ASUS TUF GAMING F16 com RTX 5060", "ASUS TUF GAMING F16 com RTX 5060 — i5 14450HX - RTX 5060 8GB"),
    ("NOTEBOOK COM RTX 4050 MAIS BARATO HJ\n\nAcer Nitro V15\n\nPor: R$ 4.000", "Acer Nitro V15", "Acer Nitro V15"),
    ("Placa de Vídeo RTX 5060 8GB\n\nPor: R$ 2.000", "Placa de Vídeo RTX 5060 8GB", "Placa de Vídeo RTX 5060 8GB"),
])
def test_titulo_e_texto_da_votacao(texto, titulo, pros_modelos):
    from app.tg.classify import vote_text
    assert title_of(texto) == titulo and vote_text(texto) == pros_modelos


def _loja(conn, category, brand, model, title, cents, day="2026-10-11T08:00:00"):
    with conn:
        cur = conn.execute("INSERT INTO parts (category, brand, model, specs) VALUES (?,?,?,'{}')", (category, brand, model))
        sid = conn.execute("SELECT id FROM stores WHERE slug = 'kabum'").fetchone()[0]
        lid = conn.execute("INSERT INTO listings (part_id, store_id, url, title) VALUES (?,?,?,?)",
                           (cur.lastrowid, sid, f"https://k/{cur.lastrowid}", title)).lastrowid
        conn.execute("INSERT INTO price_snapshots (listing_id, price_cash, in_stock, collected_at) VALUES (?,?,1,?)",
                     (lid, cents, day))
    return cur.lastrowid


def _canais(tmp_path, posts, chat=None, loja=None):
    """Banco com (opcional) 1 peça de loja + uma rodada dos canais + sync. Devolve (cliente, id da peça da loja)."""
    from fastapi.testclient import TestClient
    from app.main import create_app
    from app.tg.sync import sync
    path = tmp_path / "t.db"
    conn = db.init_db(path)
    pid = _loja(conn, *loja) if loja else None
    now = datetime.now().replace(microsecond=0)
    hoje = now.date().isoformat()
    rodada(conn, {CH: [(i + 1, f"{hoje}T00:00:{i:02d}", t) for i, t in enumerate(posts)]},
           chat or fake_chat(default="peca:gpu"), now=now)
    sync(conn, now)
    conn.close()
    return TestClient(create_app(db_path=path, frontend_dist=tmp_path / "x"), base_url="http://127.0.0.1:8787"), pid, path


def test_peca_do_canal_e_peca_de_verdade_e_sai_de_canais(tmp_path):
    chat = fake_chat({m: {"Fone": "audio", "Gabinete": "peca:case"} for m in V.MODELS}, default="peca:gpu")
    c, pid, _ = _canais(tmp_path, [GPU.format("2.564,00"),                                # = peça da loja
                                   "Gabinete Gamer Aigo Apollo A275, Mid Tower\n\nPor: R$ 91",  # só no canal
                                   "Fone JBL Tune 520\n\nPor: R$ 199"], chat,
                        loja=("gpu", "NVIDIA", "GeForce RTX 5060 8GB", "Placa de Vídeo RTX 5060 8GB GDDR7", 279999))
    parts = {p["id"]: p for p in c.get("/api/parts").json()}
    gpu = parts[pid]
    assert gpu["source"] == "loja" and gpu["best"]["price_cash"] == 256400      # canal mais barato ganhou
    assert gpu["best"]["store"] == "canal" and gpu["best"]["url"] == f"https://t.me/{CH}/1"
    assert gpu["best"]["seller"] == f"? via @{CH}" or gpu["best"]["seller"].endswith(f"via @{CH}")
    case = next(p for p in parts.values() if p["category"] == "case")
    assert case["source"] == "canal" and case["best"]["price_cash"] == 9100
    assert case["specs"]["motherboard_support"] == ["ATX", "mATX", "ITX"]
    assert [p["category"] for p in parts.values()].count("gpu") == 1               # não duplicou a GPU
    assert [o["kind"] for o in c.get("/api/tg/offers?no_parts=true").json()] == ["audio"]


def test_peca_do_canal_entra_na_build(tmp_path):
    chat = fake_chat({m: {"Gabinete": "peca:case"} for m in V.MODELS}, default="peca:gpu")
    c, _, _ = _canais(tmp_path, ["Gabinete Gamer Aigo Apollo A275, Mid Tower\n\nPor: R$ 91"], chat)
    full = next(b for b in c.get("/api/builds").json() if b["kind"] == "full")
    opts = c.get(f"/api/builds/{full['id']}/options/case").json()
    assert [o["source"] for o in opts] == ["canal"]
    auto = c.post(f"/api/builds/{full['id']}/auto").json()
    case = next(i for i in auto["items"] if i["category"] == "case")
    assert case["part_id"] == opts[0]["id"]


def test_mesmo_produto_em_varios_posts_vira_uma_peca(tmp_path):
    txt = "Placa de Vídeo RX 9060 XT 16GB {}\n\nPor: R$ {}"
    c, _, _ = _canais(tmp_path, [txt.format("Gigabyte", "2.900,00"), txt.format("Sapphire", "2.750,00")])
    gpus = [p for p in c.get("/api/parts?category=gpu").json()]
    assert len(gpus) == 1 and gpus[0]["best"]["price_cash"] == 275000
    det = c.get(f"/api/parts/{gpus[0]['id']}").json()
    assert len(det["offers"]) == 2


def test_oferta_velha_do_canal_vira_sem_estoque(tmp_path):
    from app.tg.sync import sync, EXPIRE_DAYS
    from datetime import timedelta
    c, _, path = _canais(tmp_path, ["Placa de Vídeo RX 9060 XT 16GB\n\nPor: R$ 2.900"])
    conn = db.connect(path)
    sync(conn, datetime.now() + timedelta(days=EXPIRE_DAYS + 1))
    sync(conn, datetime.now() + timedelta(days=EXPIRE_DAYS + 1))                    # idempotente
    conn.close()
    g = c.get("/api/parts?category=gpu").json()[0]
    assert g["best"] is None and g["out_of_stock"]["price_cash"] == 290000


def test_sync_e_idempotente_e_post_que_virou_notebook_sai(tmp_path):
    from app.tg.sync import sync
    c, _, path = _canais(tmp_path, ["🔥 RYZEN 5 COM BOM PREÇO\n\nProcessador AMD Ryzen 5 5600\n\nPor: R$ 600"],
                         fake_chat(default="peca:cpu"))
    conn = db.connect(path)
    assert sync(conn)["created"] == 0
    with conn:
        conn.execute("UPDATE tg_offers SET kind = 'notebook'")
    r = sync(conn)
    conn.close()
    assert r["removed"] == 1 and r["parts_gone"] == 1
    assert c.get("/api/parts?category=cpu").json() == []


def test_referencia_nao_conta_o_canal_duas_vezes(tmp_path):
    """O post do canal vira anúncio da loja 'canal'; a referência não pode somar ele de novo."""
    c, _, path = _canais(tmp_path, [GPU.format("2.700,00"), GPU.format("2.650,00")])
    conn = db.connect(path)
    from app.tg.run import reference
    ref = reference(conn, "gpu|rtx 5060|8gb", "2099-01-01T00:00:00")
    conn.close()
    assert ref is None                                    # só 2 preços (não 4) → ainda sem referência


@pytest.mark.parametrize("cat, texto, specs", [
    ("cpu", "Processador AMD Ryzen 5 8500G Box - AM5", {"socket": "AM5"}),
    ("cpu", "Processador Ryzen 7 5700X 3.4GHz", {"socket": "AM4"}),
    ("cpu", "Processador Intel Core i5-12400F", {"socket": "LGA1700"}),
    ("motherboard", "Placa-mãe Msi A520m-a Pro Am4 Matx Ddr4", {"socket": "AM4", "memory_type": "DDR4", "form_factor": "mATX"}),
    ("motherboard", "Placa Mãe Gigabyte B650 Eagle AX ATX", {"socket": "AM5", "memory_type": "DDR5", "form_factor": "ATX"}),
    ("ram", "Memória Rise Mode 16GB DDR4 3200MHz", {"memory_type": "DDR4"}),
    ("psu", "Fonte Gamer Rise Mode Elektra, 650W, Bronze", {"wattage_w": 650}),
    ("case", "Gabinete Gamer TGT Jester V2, Mini-Tower, M-ATX", {"motherboard_support": ["mATX", "ITX"]}),
    ("cooler", "Water Cooler 360mm Gamdias Chione E4-360 Intel LGA1700 AMD AM5 AM4", {"sockets": ["AM4", "AM5", "LGA1700"]}),
    ("gpu", "Placa de Vídeo RTX 5060 8GB", {}),
])
def test_specs_do_texto_pra_compatibilidade(cat, texto, specs):
    from app.tg.sync import specs_from_text
    assert specs_from_text(cat, texto) == specs


def test_reclassify_corrige_tipo_antigo(tmp_path):
    from app.tg import reclassify
    path = tmp_path / "t.db"
    conn = db.init_db(path)
    rodada(conn, {CH: [(1, "2026-10-12T10:00:00", "🔥 RYZEN 5 COM BOM PREÇO\n\nPositivo Vision R15M\n\nPor: R$ 2.534")]},
           fake_chat(default="peca:cpu"))
    conn.close()
    # --parts: o padrão antigo (o padrão agora só revota as de origem "rules" e as sem tipo)
    out = reclassify.main(["--parts"], db_path=path, chat=fake_chat({m: {"Positivo": "notebook"} for m in V.MODELS}))
    assert out["tipo_mudou"][0][1:] == ("peca:cpu", "notebook") or list(out["tipo_mudou"][0][1:]) == ["peca:cpu", "notebook"]


def test_peca_sem_estoque_mostra_ultimo_preco_e_vai_pro_fim(tmp_path):
    from fastapi.testclient import TestClient
    from app.main import create_app
    path = tmp_path / "t.db"
    conn = db.init_db(path)
    com = _loja(conn, "storage", "Kingston", "NV3 1TB", "SSD Kingston NV3 1TB", 50000)
    sem = _loja(conn, "storage", "WD", "Blue 2TB HD", "HD WD Blue 2TB", 37690)
    nada = conn.execute("INSERT INTO parts (category, brand, model, specs) VALUES ('storage','X','Y','{}')").lastrowid
    with conn:
        conn.execute("UPDATE price_snapshots SET in_stock = 0 WHERE listing_id IN "
                     "(SELECT id FROM listings WHERE part_id = ?)", (sem,))
    conn.commit()
    conn.close()
    c = TestClient(create_app(db_path=path, frontend_dist=tmp_path / "x"), base_url="http://127.0.0.1:8787")
    ps = c.get("/api/parts?category=storage").json()
    assert [p["id"] for p in ps] == [com, sem, nada]          # mais barato (sem estoque) não passa na frente
    assert ps[0]["out_of_stock"] is None
    assert ps[1]["best"] is None and ps[1]["out_of_stock"]["price_cash"] == 37690
    assert ps[2]["best"] is None and ps[2]["out_of_stock"] is None


@pytest.mark.parametrize("titulo, marca, modelo", [
    ("Gabinete Gamer TGT Jester V2, Rainbow, Mini-Tower", "TGT", "Jester V2, Rainbow, Mini-Tower"),
    ("Processador AMD Ryzen 5 8500G Box - AM5 (Amazon)", "AMD", "Ryzen 5 8500G Box - AM5"),
    ("Placa-mãe Msi A520m-a Pro Am4 Matx Ddr4", "MSI", "A520m-a Pro Am4 Matx Ddr4"),
    ("Fonte Gamer Rise Mode Elektra, 650W, Bronze", "Rise Mode", "Elektra, 650W, Bronze"),
])
def test_nome_da_peca_do_canal(titulo, marca, modelo):
    from app.tg.sync import _brand_model
    assert _brand_model(titulo) == (marca, modelo)


# --------------------------------------------------------------------------- RAM de notebook não é peça de PC

SODIMM = [
    "— Impact Ddr4 preto 16Gb 1 HyperX 2666mhz\n\nPor: R$ 460,00\nShopee",
    "Memória Kingston Fury Impact 16GB DDR4 3200MHz\n\nPor: R$ 399",
    "Memória RAM SODIMM 8GB DDR4 2666MHz Crucial\n\nPor: R$ 189",
    "Memória RAM SO-DIMM 16GB DDR5 5600 Corsair Vengeance\n\nPor: R$ 499",
    "Memória RAM 8GB DDR4 2666MHz para Notebook Kingston\n\nPor: R$ 150",
    "Memória Ram P/ Notebook 16gb Ddr4 3200 Mhz\n\nPor: R$ 280",
    "Memória Ram De Notebook Ddr4 8gb Crucial\n\nPor: R$ 170",
]
DESKTOP = [
    "Memória RAM Kingston Fury Beast 16GB DDR4 3200MHz\n\nPor: R$ 279",
    "Memória RAM XPG Lancer 32GB (2x16) DDR5 6000MHz\n\nPor: R$ 749",
    "Memória RAM HyperX Fury 8GB DDR4 2666MHz\n\nPor: R$ 159",
    # posts reais dos canais (16/10/2026) com evidência de desktop no texto
    "🚨 Memória Corsair Vengeance RGB 32GB (2x16GB), DDR5, 5200Mhz, C40, Preto CMH32GX5M2B5200C40\n\n💥🔥 Por: R$1.896,00",
    "🚨 Kvr48u40bs8-16 Módulo de memória de 16Gb Dimm Ddr5 4800MHz Cl40 1,1V 1Rx8 288-pin para desktop\n\n💥🔥 Por: R$935,00",
    "Memória RAM Patriot Viper Steel 16GB DDR4 3600MHz\n\nPor: R$ 299",
]

# sem NENHUM sinal de formato no texto: pode ser SO-DIMM (a foto é a única pista). Na dúvida, não é peça.
AMBIGUA = [
    "⚡ MEMÓRIA RAM DDR5 8GB 4800MHZ!\n\nMemória RAM DDR5 8GB\n4800MHz\n\nPor: R$ 618,01 (Pix)\n\n🎟️RESGATE CUPOM 100 OFF",
    "Memória Skhynix DDR5 8GB - 4800MHz - Seminova\n\nPor: R$ 120",
    "Memória Kingston 8GB DDR4 3200MHz\n\nPor: R$ 159",
]


@pytest.mark.parametrize("texto", SODIMM)
def test_ram_de_notebook_nao_vira_peca(texto):
    assert adjust_kind("peca:ram", texto) == "outro_tech"
    assert category(texto) is None            # sem chave: nunca compara com RAM de desktop nem entra na build


@pytest.mark.parametrize("texto", DESKTOP)
def test_ram_de_desktop_continua_peca(texto):
    assert adjust_kind("peca:ram", texto) == "peca:ram"
    assert category(texto) == "ram"


def test_ajuste_so_mexe_em_peca():
    # um monitor ou fone com a palavra "impact" não é reclassificado; só peça que a IA chamou de peça
    assert adjust_kind("monitor", "Monitor Impact 24") == "monitor"
    assert adjust_kind("audio", "Headset Impact Gamer") == "audio"
    assert adjust_kind(None, "Impact Ddr4 16Gb") is None


def test_rodada_guarda_ram_de_notebook_como_outro_tech(tmp_path):
    conn = db.init_db(tmp_path / "t.db")
    rodada(conn, {CH: [(1, "2026-10-12T10:00:00", SODIMM[0])]}, fake_chat(default="peca:ram"))
    row = conn.execute("SELECT kind, product_key FROM tg_offers").fetchone()
    assert row["kind"] == "outro_tech" and row["product_key"] is None
    assert conn.execute("SELECT COUNT(*) FROM parts WHERE source = 'canal'").fetchone()[0] == 0


def test_reclassify_tira_ram_de_notebook_das_pecas(tmp_path):
    from app.tg import reclassify
    path = tmp_path / "t.db"
    conn = db.init_db(path)
    rodada(conn, {CH: [(1, "2026-10-12T10:00:00", SODIMM[0])]}, fake_chat(default="peca:ram"))
    with conn:   # dado antigo, de antes da regra: a RAM de notebook estava como peça
        conn.execute("UPDATE tg_offers SET kind = 'peca:ram', product_key = 'ram:ddr4:16:2666'")
    conn.close()
    out = reclassify.main(["--parts"], db_path=path, chat=fake_chat(default="peca:ram"))   # padrão antigo
    conn = db.init_db(path)
    row = conn.execute("SELECT kind, product_key FROM tg_offers").fetchone()
    assert row["kind"] == "outro_tech" and row["product_key"] is None
    assert out["tipo_mudou"]


@pytest.mark.parametrize("texto", AMBIGUA)
def test_ram_sem_sinal_de_formato_nao_vira_peca(texto):
    # caso real (16/10/2026): "DDR5 8GB 4800MHz" da lipeofertas era SO-DIMM e o texto não diz
    assert adjust_kind("peca:ram", texto) == "outro_tech"


@pytest.mark.parametrize("texto", [
    "Memória Corsair Vengeance 16GB DDR5 5200MHz\n\nPor: R$ 500",
    "Memória 16GB DDR4 3200MHz para desktop\n\nPor: R$ 300",
    "Memória 16GB DDR4 3200MHz UDIMM Kingston\n\nPor: R$ 300",
    "Memória Kingston Fury Beast 16GB DDR4 3200MHz\n\nPor: R$ 300",
    "Memória XPG Lancer 16GB DDR5 6000MHz\n\nPor: R$ 500",
    "Memória 16GB DDR4 3200MHz com dissipador\n\nPor: R$ 300",
    "Memória RAM 32GB (2x16GB) DDR4 3200MHz\n\nPor: R$ 500",
])
def test_ram_com_uma_unica_evidencia_de_desktop_continua_peca(texto):
    assert adjust_kind("peca:ram", texto) == "peca:ram"
