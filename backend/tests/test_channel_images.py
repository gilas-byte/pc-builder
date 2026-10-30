"""Fotos das ofertas dos canais. Fixtures reais em tests/fixtures/tg_*.html (12/10/2026)."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db import database as db
from app.main import create_app
from app.tg import images as IM
from app.tg import run as R
from app.tg import vote as V
from app.tg.parse import parse_page

F = Path(__file__).parent / "fixtures"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 200
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 200
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 200
OK_URL = "https://cdn1.telesco.pe/file/abc123"


# --------------------------------------------------------------------------- parser

def test_parser_pega_a_foto_das_paginas_reais():
    for name in ("tg_EconomizandocomJP", "tg_gpcrpromo", "tg_OPromoFacil"):
        posts = parse_page((F / f"{name}.html").read_text())
        com_foto = [p for p in posts if p.image]
        assert len(com_foto) == len(posts) > 0
        assert all(p.image.startswith("https://cdn") and "telesco.pe" in p.image for p in com_foto)


def _msg(extra: str) -> str:
    return ('<div class="tgme_widget_message_wrap"><div class="tgme_widget_message" data-post="c/7">'
            f'{extra}<div class="tgme_widget_message_text js-message_text" dir="auto">Fonte 650W<br/>Por: R$ 231</div>'
            '<time datetime="2026-10-13T10:00:00+00:00" class="time">x</time></div></div>')


def test_parser_sem_foto_nao_tem_imagem():
    assert parse_page(_msg(""))[0].image is None


def test_parser_ignora_foto_que_nao_e_https():
    foto = ('<a class="tgme_widget_message_photo_wrap" href="https://t.me/c/7" '
            'style="width:800px;background-image:url(\'http://cdn1.telesco.pe/file/x\')"></a>')
    assert parse_page(_msg(foto))[0].image is None


def test_parser_usa_a_primeira_de_varias_fotos():
    a = ('<a class="tgme_widget_message_photo_wrap" href="x" style="background-image:url(\'https://cdn1.telesco.pe/file/A\')"></a>')
    b = a.replace("/A", "/B")
    assert parse_page(_msg(a + b))[0].image == "https://cdn1.telesco.pe/file/A"


# --------------------------------------------------------------------------- baixar e validar

@pytest.fixture
def conn(tmp_path):
    c = db.init_db(tmp_path / "t.db")
    yield c
    c.close()


def oferta(conn, msg_id=1, src=OK_URL, channel="gpcrpromo", **kw):
    with conn:
        conn.execute("INSERT OR IGNORE INTO tg_channels (slug) VALUES (?)", (channel,))
        cur = conn.execute(
            "INSERT INTO tg_offers (channel, msg_id, posted_at, seen_at, title, text, price_cash, link, kind, image_src) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (channel, msg_id, "2026-10-13T10:00:00", "2026-10-13T10:05:00", "Fonte MSI 650W", "Fonte MSI 650W",
             23100, f"https://t.me/{channel}/{msg_id}", "peca:psu", src))
    return cur.lastrowid


def row(conn, oid):
    return conn.execute("SELECT image_src, image_path, image_tries FROM tg_offers WHERE id = ?", (oid,)).fetchone()


def dl(data=JPEG, calls=None):
    def get(url):
        if calls is not None:
            calls.append(url)
        if isinstance(data, Exception):
            raise data
        return data
    return get


def test_baixa_e_guarda_a_foto(conn, tmp_path):
    oid = oferta(conn)
    res = IM.fetch_pending(conn, dl(), tmp_path / "img")
    assert res == {"saved": 1, "failed": 0}
    r = row(conn, oid)
    assert r["image_path"] == "gpcrpromo_1.jpg"
    assert (tmp_path / "img" / "gpcrpromo_1.jpg").read_bytes() == JPEG


@pytest.mark.parametrize("data,ext", [(JPEG, "jpg"), (PNG, "png"), (WEBP, "webp")])
def test_extensao_vem_dos_bytes(conn, tmp_path, data, ext):
    oid = oferta(conn)
    IM.fetch_pending(conn, dl(data), tmp_path / "img")
    assert row(conn, oid)["image_path"] == f"gpcrpromo_1.{ext}"


@pytest.mark.parametrize("src", ["http://cdn1.telesco.pe/file/a", "https://evil.example.com/a.jpg",
                                 "https://127.0.0.1/a.jpg", "https://telesco.pe.evil.com/a.jpg",
                                 "https://cdn1.telesco.pe@evil.com/a", "file:///etc/passwd"])
def test_host_fora_da_lista_nem_e_pedido(conn, tmp_path, src):
    oid = oferta(conn, src=src)
    calls = []
    IM.fetch_pending(conn, dl(calls=calls), tmp_path / "img")
    assert calls == []
    assert row(conn, oid)["image_path"] is None


def test_arquivo_grande_demais_e_recusado(conn, tmp_path):
    oid = oferta(conn)
    IM.fetch_pending(conn, dl(JPEG + b"\x00" * IM.MAX_BYTES), tmp_path / "img")
    assert row(conn, oid)["image_path"] is None
    assert not list((tmp_path / "img").glob("*"))


def test_html_com_cara_de_jpeg_e_recusado(conn, tmp_path):
    oid = oferta(conn)
    IM.fetch_pending(conn, dl(b"<html>404 Not Found</html>" + b"x" * 200), tmp_path / "img")
    assert row(conn, oid)["image_path"] is None


def test_arquivo_minusculo_e_recusado(conn, tmp_path):
    oid = oferta(conn)
    IM.fetch_pending(conn, dl(b"\xff\xd8\xff"), tmp_path / "img")
    assert row(conn, oid)["image_path"] is None


def test_falha_conta_tentativa_e_desiste_na_terceira(conn, tmp_path):
    oid = oferta(conn)
    calls = []
    for _ in range(5):
        IM.fetch_pending(conn, dl(ConnectionError("fora"), calls), tmp_path / "img")
    assert len(calls) == IM.MAX_TRIES == 3
    assert row(conn, oid)["image_tries"] == 3


def test_erro_numa_foto_nao_derruba_as_outras(conn, tmp_path):
    a, b = oferta(conn, 1), oferta(conn, 2)

    def get(url):
        if url.endswith("/a"):
            raise TimeoutError("lento")
        return JPEG
    with conn:
        conn.execute("UPDATE tg_offers SET image_src = ? WHERE id = ?", ("https://cdn1.telesco.pe/file/a", a))
    res = IM.fetch_pending(conn, get, tmp_path / "img")
    assert res == {"saved": 1, "failed": 1}
    assert row(conn, a)["image_path"] is None and row(conn, b)["image_path"] == "gpcrpromo_2.jpg"


def test_nao_baixa_de_novo_o_que_ja_tem(conn, tmp_path):
    oferta(conn)
    calls = []
    IM.fetch_pending(conn, dl(calls=calls), tmp_path / "img")
    IM.fetch_pending(conn, dl(calls=calls), tmp_path / "img")
    assert len(calls) == 1


def test_limite_por_rodada(conn, tmp_path):
    for i in range(1, 6):
        oferta(conn, i)
    calls = []
    IM.fetch_pending(conn, dl(calls=calls), tmp_path / "img", limit=2)
    assert len(calls) == 2


def test_nome_do_arquivo_nao_vem_da_url_nem_de_canal_esquisito(conn, tmp_path):
    oid = oferta(conn, channel="../../etc", src="https://cdn1.telesco.pe/file/../../x")
    IM.fetch_pending(conn, dl(), tmp_path / "img")
    assert row(conn, oid)["image_path"] is None
    assert not (tmp_path / "etc").exists() and not list(tmp_path.glob("**/etc*"))


def test_rodada_com_foto_guarda_o_link_da_foto(conn):
    html = _msg('<a class="tgme_widget_message_photo_wrap" href="x" '
                'style="background-image:url(\'https://cdn1.telesco.pe/file/Z\')"></a>').replace("data-post=\"c/7\"", 'data-post="gpcrpromo/7"')
    html = html.replace("Fonte 650W", "Fonte MSI 650W")

    def fetch(url):
        return "<html>" + html + "</html>"
    chat = lambda model, system, user: "peca:psu"          # noqa: E731
    R.run_round(conn, fetch, lambda *a, **k: "peca:psu", datetime(2026, 10, 13, 12, 0), channels=["gpcrpromo"],
                pause=0, log=lambda *_: None)
    r = conn.execute("SELECT image_src FROM tg_offers WHERE msg_id = 7").fetchone()
    assert r is not None and r["image_src"] == "https://cdn1.telesco.pe/file/Z"


def test_backfill_preenche_o_link_de_oferta_antiga(conn):
    oid = oferta(conn, 7, src=None, channel="gpcrpromo")
    html = _msg('<a class="tgme_widget_message_photo_wrap" href="x" '
                'style="background-image:url(\'https://cdn1.telesco.pe/file/Z\')"></a>').replace('data-post="c/7"', 'data-post="gpcrpromo/7"')
    n = IM.backfill(conn, lambda url: "<html>" + html + "</html>", ["gpcrpromo"], pages=1, pause=0)
    assert n == 1 and row(conn, oid)["image_src"] == "https://cdn1.telesco.pe/file/Z"


def test_backfill_nao_troca_foto_que_ja_foi_baixada(conn, tmp_path):
    oid = oferta(conn, 7)
    IM.fetch_pending(conn, dl(), tmp_path / "img")
    html = _msg('<a class="tgme_widget_message_photo_wrap" href="x" '
                'style="background-image:url(\'https://cdn1.telesco.pe/file/OUTRA\')"></a>').replace('data-post="c/7"', 'data-post="gpcrpromo/7"')
    IM.backfill(conn, lambda url: "<html>" + html + "</html>", ["gpcrpromo"], pages=1, pause=0)
    assert row(conn, oid)["image_path"] == "gpcrpromo_7.jpg" and row(conn, oid)["image_src"] == OK_URL


# --------------------------------------------------------------------------- API

def _app(tmp_path):
    img = tmp_path / "tg_img"
    img.mkdir(exist_ok=True)
    app = create_app(tmp_path / "t.db", frontend_dist=tmp_path / "dist", tg_img_dir=img)
    return TestClient(app, base_url="http://127.0.0.1:8787"), img


def _peca_com_oferta(db_path, image_path, image_url=None, source="canal"):
    c = db.init_db(db_path)
    with c:
        c.execute("INSERT OR IGNORE INTO stores (slug, name, base_url) VALUES ('canal', 'Canais', 'https://t.me')")
        sid = c.execute("SELECT id FROM stores WHERE slug = 'canal'").fetchone()[0]
        c.execute("INSERT OR IGNORE INTO tg_channels (slug) VALUES ('gpcrpromo')")
        pid = c.execute("INSERT INTO parts (category, brand, model, specs, source, image_url) VALUES "
                        "('psu', 'MSI', 'MAG 650W', '{}', ?, ?)", (source, image_url)).lastrowid
        lid = c.execute("INSERT INTO listings (part_id, store_id, url, title, condition) VALUES (?, ?, ?, 'x', 'new')",
                        (pid, sid, "https://t.me/gpcrpromo/9")).lastrowid
        c.execute("INSERT INTO price_snapshots (listing_id, price_cash, in_stock, collected_at) VALUES (?, 23100, 1, '2026-10-13T10:00:00')", (lid,))
        # data relativa: a rota /api/tg/offers só traz os últimos 7 dias
        posted = datetime.now().replace(microsecond=0).isoformat()
        c.execute("INSERT INTO tg_offers (channel, msg_id, posted_at, seen_at, title, text, price_cash, link, kind, image_path) "
                  "VALUES ('gpcrpromo', 9, ?, ?, 'Fonte', 'Fonte', 23100, "
                  "'https://t.me/gpcrpromo/9', 'peca:psu', ?)", (posted, posted, image_path))
    c.close()
    return pid


def test_api_serve_a_foto(tmp_path):
    client, img = _app(tmp_path)
    (img / "gpcrpromo_9.jpg").write_bytes(JPEG)
    r = client.get("/api/tg/img/gpcrpromo_9.jpg")
    assert r.status_code == 200 and r.content == JPEG and r.headers["content-type"] == "image/jpeg"
    assert "max-age" in r.headers["cache-control"]


@pytest.mark.parametrize("name", ["../t.db", "..%2Ft.db", "a/b.jpg", "gpcrpromo_9.txt", ".hidden.jpg", "x" * 300 + ".jpg"])
def test_api_nao_serve_nome_esquisito(tmp_path, name):
    client, img = _app(tmp_path)
    (tmp_path / "secreto.jpg").write_bytes(JPEG)
    assert client.get(f"/api/tg/img/{name}").status_code in (404, 422)


def test_api_foto_que_nao_existe_e_404(tmp_path):
    client, _ = _app(tmp_path)
    assert client.get("/api/tg/img/nada_1.jpg").status_code == 404


def test_peca_de_canal_usa_a_foto_do_canal(tmp_path):
    client, img = _app(tmp_path)
    pid = _peca_com_oferta(tmp_path / "t.db", "gpcrpromo_9.jpg")
    assert client.get("/api/parts").json()[0]["image_url"] == "/api/tg/img/gpcrpromo_9.jpg"
    assert client.get(f"/api/parts/{pid}").json()["image_url"] == "/api/tg/img/gpcrpromo_9.jpg"


def test_foto_da_loja_tem_prioridade(tmp_path):
    client, _ = _app(tmp_path)
    _peca_com_oferta(tmp_path / "t.db", "gpcrpromo_9.jpg", image_url="https://img.kabum.com.br/x.jpg", source="loja")
    assert client.get("/api/parts").json()[0]["image_url"] == "https://img.kabum.com.br/x.jpg"


def test_peca_sem_foto_nenhuma_continua_sem(tmp_path):
    client, _ = _app(tmp_path)
    _peca_com_oferta(tmp_path / "t.db", None)
    assert client.get("/api/parts").json()[0]["image_url"] is None


def test_oferta_da_aba_canais_traz_a_foto(tmp_path):
    client, _ = _app(tmp_path)
    _peca_com_oferta(tmp_path / "t.db", "gpcrpromo_9.jpg")
    o = client.get("/api/tg/offers").json()[0]
    assert o["image"] == "/api/tg/img/gpcrpromo_9.jpg"


def test_sem_nenhuma_rota_nova_de_escrita(tmp_path):
    client, _ = _app(tmp_path)
    paths = client.get("/api/openapi.json").json()["paths"]
    assert "/api/tg/img/{name}" in paths and list(paths["/api/tg/img/{name}"]) == ["get"]


# --------------------------------------------------------------------------- travas isoladas (mutação achou fraqueza)

@pytest.mark.parametrize("url", ["https://cdn1.telesco.pe:8080/file/a", "https://user@cdn1.telesco.pe/file/a",
                                 "https://cdn1.telesco.pe/file/../x", "https://cdn1.telesco.pe:443/file/a"])
def test_allowed_recusa_porta_credencial_e_ponto_ponto(url):
    assert IM.allowed(url) is False


def test_allowed_aceita_o_link_normal():
    assert IM.allowed("https://cdn1.telesco.pe/file/AbC-123_x") is True


def test_canal_esquisito_nao_vira_caminho_mesmo_com_link_bom(conn, tmp_path):
    oid = oferta(conn, channel="gpcrpromo")
    with conn:
        conn.execute("INSERT INTO tg_channels (slug) VALUES ('../../fora')")
        conn.execute("UPDATE tg_offers SET channel = '../../fora' WHERE id = ?", (oid,))
    IM.fetch_pending(conn, dl(), tmp_path / "img")
    assert row(conn, oid)["image_path"] is None
    assert not list(tmp_path.rglob("*fora*"))


def test_backfill_repetido_nao_conta_de_novo(conn):
    oferta(conn, 7, src=None)
    html = _msg('<a class="tgme_widget_message_photo_wrap" href="x" '
                'style="background-image:url(\'https://cdn1.telesco.pe/file/Z\')"></a>').replace('data-post="c/7"', 'data-post="gpcrpromo/7"')
    get = lambda url: "<html>" + html + "</html>"      # noqa: E731
    assert IM.backfill(conn, get, ["gpcrpromo"], pages=1, pause=0) == 1
    assert IM.backfill(conn, get, ["gpcrpromo"], pages=1, pause=0) == 0


def test_com_duas_fotos_de_canal_vale_a_mais_nova(tmp_path):
    client, _ = _app(tmp_path)
    pid = _peca_com_oferta(tmp_path / "t.db", "gpcrpromo_9.jpg")
    c = db.init_db(tmp_path / "t.db")
    with c:
        sid = c.execute("SELECT id FROM stores WHERE slug = 'canal'").fetchone()[0]
        c.execute("INSERT INTO listings (part_id, store_id, url, title, condition) VALUES (?, ?, 'https://t.me/gpcrpromo/10', 'x', 'new')", (pid, sid))
        depois = (datetime.now() + timedelta(hours=8)).replace(microsecond=0).isoformat()   # mais nova que a 1ª
        c.execute("INSERT INTO tg_offers (channel, msg_id, posted_at, seen_at, title, text, price_cash, link, kind, image_path) "
                  "VALUES ('gpcrpromo', 10, ?, ?, 'Fonte', 'Fonte', 22000, "
                  "'https://t.me/gpcrpromo/10', 'peca:psu', 'gpcrpromo_10.jpg')", (depois, depois))
    c.close()
    assert client.get(f"/api/parts/{pid}").json()["image_url"] == "/api/tg/img/gpcrpromo_10.jpg"


def test_miniatura_de_link_preview_nao_e_foto_da_oferta():
    preview = ('<a class="tgme_widget_message_link_preview" href="https://loja.com/x"><i class="link_preview_image" '
               'style="background-image:url(\'https://cdn1.telesco.pe/file/PREVIEW\')"></i></a>')
    assert parse_page(_msg(preview))[0].image is None
