"""Parsers das lojas (páginas reais salvas em 09/10/2026), regra de casamento, coleta e avisos."""

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.collect import run
from app.collect.stores import (Offer, StoreBlocked, _cents, amazon_search_url, condition_from_title,
                                parse_amazon, parse_kabum, parse_terabyte)
from app.collect.watchlist import Watch, load_watchlist, norm
from app.db import database as db
from app.main import create_app

F = Path(__file__).parent / "fixtures"
OFFER_ATIVA = 1791900000  # dentro da janela da oferta relâmpago gravada na página da KaBuM!


# ------------------------------------------------------------------ parsers com páginas reais

def test_centavos():
    assert _cents("R$ 4.599,99") == 459999
    assert _cents("R$\xa02.645,10") == 264510
    assert _cents("4980.27") == 498027        # atributo da Terabyte (ponto decimal)
    assert _cents("1199") == 119900
    assert _cents(559) == 55900 and _cents(999.99) == 99999
    assert _cents("0") is None and _cents(None) is None and _cents("abc") is None


def test_kabum_so_kabum_ou_oficial_e_oferta_ativa():
    offs = parse_kabum((F / "kabum_busca.html").read_text(), now=OFFER_ATIVA)
    assert offs and all(o.seller == "KaBuM!" for o in offs)       # vendedores de marketplace ficam de fora
    o = next(o for o in offs if "7600X" in o.title)
    assert o.price_cash == 99999                                   # preço da oferta relâmpago, não o cheio
    assert o.url == "https://www.kabum.com.br/produto/378414/" + o.url.split("/")[-1]
    assert o.image_url.startswith("https://images.kabum.com.br/")


def test_kabum_oferta_vencida_usa_preco_normal():
    o = next(o for o in parse_kabum((F / "kabum_busca.html").read_text(), now=0) if "7600X" in o.title)
    assert o.price_cash == 218982
    depois = next(o for o in parse_kabum((F / "kabum_busca.html").read_text(), now=1893456000) if "7600X" in o.title)
    assert depois.price_cash == 218982     # oferta já acabou (2030)


def test_kabum_sem_next_data_da_erro_claro():
    with pytest.raises(ValueError, match="layout"):
        parse_kabum("<html>nada</html>")


def test_terabyte():
    offs = parse_terabyte((F / "terabyte_busca.html").read_text())
    r7 = next(o for o in offs if "Ryzen 7 5700X " in o.title)
    assert r7.price_cash == 119999 and r7.in_stock and r7.seller == "Terabyte"
    assert r7.price_installment == 12 * 11765
    assert r7.url.startswith("https://www.terabyteshop.com.br/produto/")
    assert all(o.price_cash < 10_000_000 for o in offs)           # nada de R$ 498 mil (bug do ponto decimal)


def test_amazon_pula_patrocinado():
    offs = parse_amazon((F / "amazon_busca.html").read_text())
    assert offs and not any("KIT UPGRADE" in o.title for o in offs)
    r5 = next(o for o in offs if o.url.endswith("B09VCHR1VH"))
    assert r5.price_cash == 85880 and r5.seller == "Amazon"
    assert "p_6%3AA1ZZFT5FULY4LN" in amazon_search_url("ryzen 5 5600")   # só vendido pela Amazon


def test_amazon_captcha_vira_bloqueio():
    with pytest.raises(StoreBlocked):
        parse_amazon('<form action="/errors/validateCaptcha">')


@pytest.mark.parametrize("titulo,esperado", [
    ("Placa de Vídeo RTX 4070 - Open Box", "used"), ("SSD 1TB Usado", "used"),
    ("Processador Recondicionado", "used"), ("Placa de vídeo RTX 4060", "new"),
])
def test_condicao_pelo_titulo(titulo, esperado):
    assert condition_from_title(titulo) == esperado


# ------------------------------------------------------------------ casamento anúncio → peça

R5 = Watch("cpu", "AMD", "Ryzen 5 5600", "ryzen 5 5600", ["ryzen 5 5600"],
           ["5600x", "5600g", "5600gt", "5600xt", "5600t"])


@pytest.mark.parametrize("titulo,bate", [
    ("PROCESSADOR AMD RYZEN 5 5600 3.5GHz (TURBO 4.4GHz) AM4", True),
    ("Processador AMD Ryzen 5 5600X, 3.7GHz", False),
    ("Processador AMD Ryzen 5 5600GT", False),
    ("PC Gamer AMD Ryzen 5 5600, 16GB", False),          # computador montado
    ("Kit Upgrade Ryzen 5 5600 + Placa Mãe", False),
    ("Processador Ryzen 5 56000", False),                # palavra inteira
])
def test_casamento(titulo, bate):
    assert R5.matches(titulo, 85000) is bate


def test_preco_isca_abaixo_do_piso_descartado():
    assert R5.matches("Ryzen 5 5600", 9900) is False


def test_norm_junta_unidade():
    assert " 32gb " in norm("Memória 32 GB DDR4") and " 2tb " in norm("HD 2 TB")


def test_watchlist_real_carrega_e_categorias_validas():
    w = load_watchlist()
    assert len(w) >= 20
    assert {x.category for x in w} == {"cpu", "motherboard", "ram", "gpu", "storage", "psu", "case", "cooler"}
    alvos = {x.model: x.alert_below for x in w if x.alert_below}
    assert alvos and all(v in (1000, 350) for v in alvos.values())   # alvos herdados do cron antigo


# ------------------------------------------------------------------ coleta de ponta a ponta (rede falsa)

PAGES = {
    "kabum": (F / "kabum_busca.html").read_text(),
    "terabyte": (F / "terabyte_busca.html").read_text(),
    "amazon": (F / "amazon_busca.html").read_text(),
}
WL = [Watch("cpu", "AMD", "Ryzen 7 5700X", "ryzen 7 5700x", ["ryzen 7 5700x"], ["5700x3d"], {"socket": "AM4"}),
      Watch("cpu", "AMD", "Ryzen 5 5600", "ryzen 5 5600", ["ryzen 5 5600"],
            ["5600x", "5600g", "5600gt", "5600xt", "5600t"], {"socket": "AM4"}, alert_below=900)]


def fake_fetch(blocked=(), broken=()):
    calls = []

    def fetch(url):
        calls.append(url)
        store = next(s for s in PAGES if s in url or (s == "terabyte" and "terabyteshop" in url))
        if store in blocked:
            raise StoreBlocked("HTTP 403")
        if store in broken:
            raise ConnectionError("fora do ar")
        return PAGES[store]
    fetch.calls = calls
    return fetch


@pytest.fixture
def wl_file(tmp_path):
    p = tmp_path / "wl.json"
    p.write_text(json.dumps({"parts": [w.__dict__ for w in WL]}))
    return str(p)


def test_coleta_grava_e_rodar_duas_vezes_nao_duplica(tmp_path, wl_file, capsys):
    path = tmp_path / "t.db"
    kw = dict(db_path=path, fetch=fake_fetch(), pause=0, now=datetime(2026, 10, 9, 9, 0))
    assert run.main(["--watchlist", wl_file], **kw) == 0
    conn = db.connect(path)
    n1 = conn.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()[0]
    assert n1 > 0
    assert run.main(["--watchlist", wl_file], **kw) == 0
    assert conn.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()[0] == n1
    lojas = {r[0] for r in conn.execute("SELECT DISTINCT st.slug FROM listings l JOIN stores st ON st.id=l.store_id")}
    assert lojas == {"terabyte", "amazon"}   # nesta página, a KaBuM! não tem os 2 modelos vendidos por ela
    r7 = conn.execute("SELECT p.image_url FROM parts p WHERE model='Ryzen 7 5700X'").fetchone()
    assert r7["image_url"].startswith("https://")


def test_loja_bloqueada_nao_para_as_outras_e_nao_insiste(tmp_path, wl_file, capsys):
    fetch = fake_fetch(blocked=("amazon",))
    rc = run.main(["--watchlist", wl_file], db_path=tmp_path / "t.db", fetch=fetch, pause=0,
                  now=datetime(2026, 10, 9, 9))
    assert rc == 1
    out = json.loads(capsys.readouterr().out)
    assert "amazon" in out["errors"] and "bloqueou" in out["errors"]["amazon"]
    assert out["ingest"]["snapshots"] > 0                         # Terabyte gravou mesmo assim
    assert sum("amazon" in u for u in fetch.calls) == 1           # 1 tentativa, sem insistir


def test_loja_fora_do_ar_entra_no_aviso(tmp_path, wl_file, capsys):
    rc = run.main(["--watchlist", wl_file, "--notify"], db_path=tmp_path / "t.db",
                  fetch=fake_fetch(broken=("kabum",)), pause=0, now=datetime(2026, 10, 9, 9))
    assert rc == 1
    msg = capsys.readouterr().out
    assert "Coleta com problema" in msg and "kabum" in msg and "fora do ar" in msg


def test_dry_run_nao_grava(tmp_path, wl_file, capsys):
    path = tmp_path / "t.db"
    assert run.main(["--watchlist", wl_file, "--dry-run"], db_path=path, fetch=fake_fetch(), pause=0) == 0
    assert json.loads(capsys.readouterr().out)["items"]
    assert not path.exists()


# ------------------------------------------------------------------ avisos (Telegram)

def test_alvo_avisa_uma_vez_por_semana(tmp_path, wl_file, capsys):
    path = tmp_path / "t.db"

    def go(d):
        run.main(["--watchlist", wl_file, "--notify"], db_path=path, fetch=fake_fetch(), pause=0,
                 now=datetime(2026, 10, d, 9))
        return capsys.readouterr().out

    m1 = go(9)
    assert "Abaixo do alvo" in m1 and "Ryzen 5 5600" in m1 and "R$ 858,80" in m1
    assert go(10) == ""                 # mesmo anúncio, mesma semana: silêncio
    assert "Abaixo do alvo" in go(17)   # passou a semana: avisa de novo


def test_link_do_painel_vem_do_ambiente(monkeypatch):
    # sem host fixo no código: padrão é a própria máquina; quem usa proxy (rede privada) põe o endereço no .env
    monkeypatch.delenv("PCB_PANEL_URL", raising=False)
    assert run.format_message([], {"kabum": "HTTP 500"}, None).endswith("Painel: http://127.0.0.1:8787")
    monkeypatch.setenv("PCB_PANEL_URL", "https://pc.exemplo.test")
    assert run.format_message([], {"kabum": "HTTP 500"}, None).endswith("Painel: https://pc.exemplo.test")
    assert run.format_message([], {}, None) == ""     # nada a avisar: nem o link


def test_dia_normal_e_silencio(tmp_path, capsys):
    wl = tmp_path / "wl.json"
    wl.write_text(json.dumps({"parts": [WL[0].__dict__]}))   # sem alvo, sem histórico pra promoção
    run.main(["--watchlist", str(wl), "--notify"], db_path=tmp_path / "t.db", fetch=fake_fetch(), pause=0,
             now=datetime(2026, 10, 9, 9))
    assert capsys.readouterr().out == ""


def test_promocao_avisa_com_link_e_usado_marcado(tmp_path):
    conn = db.init_db(tmp_path / "t.db")
    w = [Watch("gpu", "NVIDIA", "RTX 4070", "rtx 4070", ["rtx 4070"])]
    for d in range(20, 0, -1):
        batch = run.to_batch([(w[0], Offer("terabyte", "https://www.terabyteshop.com.br/produto/1/x", "RTX 4070 - Open Box",
                                           500000, True, condition="used"))],
                             (datetime(2026, 10, 9) - timedelta(days=d)).isoformat())
        from app.ingest import ingest_batch
        from app.schemas import IngestBatch
        ingest_batch(conn, IngestBatch.model_validate(batch))
    batch = run.to_batch([(w[0], Offer("terabyte", "https://www.terabyteshop.com.br/produto/1/x", "RTX 4070 - Open Box",
                                       400000, True, condition="used"))], "2026-10-09T09:00:00")
    ingest_batch(conn, IngestBatch.model_validate(batch))
    alerts = run.pending_alerts(conn, w, date(2026, 10, 9))
    msg = run.format_message(alerts, {}, None)
    assert "promoção" in msg and "(usado)" in msg and "-20.0%" in msg and "terabyteshop.com.br/produto/1/x" in msg
    run.mark_sent(conn, alerts, date(2026, 10, 9))
    assert run.pending_alerts(conn, w, date(2026, 10, 10)) == []     # mesma promoção: não repete na semana


def test_usado_e_novo_tem_historicos_separados(tmp_path):
    """Usado barato não pode virar 'promoção' do novo: cada anúncio tem a própria mediana."""
    conn = db.init_db(tmp_path / "t.db")
    from app.ingest import ingest_batch
    from app.schemas import IngestBatch
    w = Watch("gpu", "NVIDIA", "RTX 4070", "rtx 4070", ["rtx 4070"])
    novo = "https://www.kabum.com.br/produto/1/novo"
    for d in range(20, -1, -1):
        when = (datetime(2026, 10, 9) - timedelta(days=d)).isoformat()
        offers = [(w, Offer("kabum", novo, "RTX 4070", 500000, True))]
        if d == 0:   # hoje aparece um usado muito mais barato
            offers.append((w, Offer("terabyte", "https://www.terabyteshop.com.br/produto/2/u", "RTX 4070 Open Box",
                                    300000, True, condition="used")))
        ingest_batch(conn, IngestBatch.model_validate(run.to_batch(offers, when)))
    assert db.list_deals(conn) == []    # o novo não caiu; o usado não tem histórico
    lid = conn.execute("SELECT id FROM listings WHERE url=?", (novo,)).fetchone()[0]
    assert db.deal_status(conn, lid)["status"] == "normal"


def test_api_mostra_condicao_vendedor_e_lojas_bloqueadas(tmp_path, wl_file):
    path = tmp_path / "t.db"
    run.main(["--watchlist", wl_file], db_path=path, fetch=fake_fetch(), pause=0, now=datetime(2026, 10, 9, 9))
    c = TestClient(create_app(db_path=path, frontend_dist=tmp_path / "x"), base_url="http://127.0.0.1:8787")
    p = next(p for p in c.get("/api/parts").json() if p["model"] == "Ryzen 7 5700X")
    det = c.get(f"/api/parts/{p['id']}").json()
    assert {o["condition"] for o in det["offers"]} == {"new"} and all(o["seller"] for o in det["offers"])
    lojas = {s["slug"]: s["status_note"] for s in c.get("/api/stores").json()}
    assert lojas["kabum"] is None and lojas["amazon"] is None
    assert "bloqueia" in lojas["pichau"] and "bloqueia" in lojas["mercadolivre"] and "bloqueia" in lojas["shopee"]


@pytest.mark.parametrize("titulo", [
    "Placa de Vídeo RX 7600 Challenger ASRock + Fonte Gamer Rise Mode Elektra, 650W",
    "PC OFFICE PRO Intel Core i5 12400F / GeForce GT 610",
    "PC Intel Core i5 12400F 16GB",
])
def test_combo_e_pc_montado_nao_contam(titulo):
    for w in (Watch("gpu", "AMD", "RX 7600", "q", ["rx 7600"]), Watch("cpu", "Intel", "i5", "q", ["12400f"])):
        assert w.matches(titulo, 200000) is False


def test_kabum_busca_sem_resultado_e_lista_vazia():
    page = '<script id="__NEXT_DATA__">{"props":{"pageProps":{"data":{"params":{},"type":"search"}}}}</script>'
    assert parse_kabum(page) == []


def test_com_estoque_tem_prioridade_sobre_indisponivel_mais_barato():
    w = Watch("gpu", "NVIDIA", "RTX 3050", "q", ["rtx 3050"])
    offs = [Offer("terabyte", f"https://www.terabyteshop.com.br/produto/{i}/x", "RTX 3050 8GB", 99990 + i, False)
            for i in range(4)] + [Offer("terabyte", "https://www.terabyteshop.com.br/produto/9/x", "RTX 3050 8GB", 150000, True)]
    found, errors = run.collect([w], lambda url: "", pause=0, log=lambda *_: None,
                                registry={"terabyte": (lambda q: "u", lambda page: offs)})
    assert errors == {}
    assert len(found) == 3 and found[0][1].in_stock and found[0][1].price_cash == 150000
