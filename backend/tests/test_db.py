from datetime import date, timedelta

import pytest
import sqlite3

from app.db import database as db


@pytest.fixture
def conn(tmp_path):
    c = db.init_db(tmp_path / "test.db")
    yield c
    c.close()


def add_part(conn, category="gpu", model="RTX 4060 8GB", brand="NVIDIA", specs="{}"):
    with conn:
        return conn.execute(
            "INSERT INTO parts (category, brand, model, specs) VALUES (?, ?, ?, ?)",
            (category, brand, model, specs),
        ).lastrowid


def add_listing(conn, part_id, store="kabum", url=None):
    store_id = conn.execute("SELECT id FROM stores WHERE slug = ?", (store,)).fetchone()[0]
    url = url or f"https://{store}.example/{part_id}"
    with conn:
        return conn.execute(
            "INSERT INTO listings (part_id, store_id, url) VALUES (?, ?, ?)",
            (part_id, store_id, url),
        ).lastrowid


def day(n_days_ago, today=date(2026, 10, 9)):
    return (today - timedelta(days=n_days_ago)).isoformat() + "T09:00:00"


# ------------------------------------------------------------------ estrutura e seed

def test_tabelas_e_view_existem(conn):
    nomes = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    for t in ("stores", "parts", "listings", "price_snapshots", "builds",
              "build_items", "settings", "v_latest_price"):
        assert t in nomes


def test_seed_nao_duplica(tmp_path):
    path = tmp_path / "x.db"
    db.init_db(path).close()
    c = db.init_db(path)  # segunda vez
    assert c.execute("SELECT COUNT(*) FROM stores").fetchone()[0] == 6
    assert c.execute("SELECT COUNT(*) FROM builds").fetchone()[0] == 2
    assert c.execute("SELECT COUNT(*) FROM build_items").fetchone()[0] == 8 + 7
    c.close()


def test_upgrade_nao_tem_placa_mae(conn):
    cats = {r[0] for r in conn.execute(
        "SELECT category FROM build_items bi JOIN builds b ON b.id = bi.build_id "
        "WHERE b.kind = 'upgrade'")}
    assert "motherboard" not in cats and "cpu" in cats


# ------------------------------------------------------------------ restrições

def test_recusa_categoria_invalida(conn):
    with pytest.raises(sqlite3.IntegrityError):
        add_part(conn, category="mouse")


def test_recusa_specs_json_invalido(conn):
    with pytest.raises(sqlite3.IntegrityError):
        add_part(conn, specs="{nao e json")


def test_recusa_preco_zero(conn):
    lid = add_listing(conn, add_part(conn))
    with pytest.raises(sqlite3.IntegrityError):
        db.record_snapshot(conn, lid, 0, True, day(0))


def test_recusa_link_de_peca_inexistente(conn):
    with pytest.raises(sqlite3.IntegrityError):
        add_listing(conn, part_id=999)


def test_recusa_data_mal_formatada(conn):
    lid = add_listing(conn, add_part(conn))
    with pytest.raises(ValueError):
        db.record_snapshot(conn, lid, 100000, True, "09/10/2026")


# ------------------------------------------------------------------ preços

def test_mesmo_dia_substitui_nao_duplica(conn):
    lid = add_listing(conn, add_part(conn))
    db.record_snapshot(conn, lid, 150000, True, "2026-10-09T09:00:00")
    db.record_snapshot(conn, lid, 140000, True, "2026-10-09T18:00:00")
    rows = conn.execute("SELECT price_cash FROM price_snapshots").fetchall()
    assert [r[0] for r in rows] == [140000]


def test_melhor_preco_ignora_esgotado(conn):
    pid = add_part(conn)
    k, p, t = (add_listing(conn, pid, s) for s in ("kabum", "pichau", "terabyte"))
    db.record_snapshot(conn, k, 100000, False, day(0))  # mais barato, mas esgotado
    db.record_snapshot(conn, p, 120000, True, day(0))
    db.record_snapshot(conn, t, 130000, True, day(0))
    best = db.best_price(conn, pid)
    assert best["store"] == "pichau" and best["price_cash"] == 120000


def test_melhor_preco_none_se_tudo_esgotado(conn):
    pid = add_part(conn)
    db.record_snapshot(conn, add_listing(conn, pid), 100000, False, day(0))
    assert db.best_price(conn, pid) is None


def test_historico_em_ordem(conn):
    pid = add_part(conn)
    lid = add_listing(conn, pid)
    for n, preco in ((2, 110000), (0, 100000), (1, 105000)):
        db.record_snapshot(conn, lid, preco, True, day(n))
    precos = [h["price_cash"] for h in db.price_history(conn, pid)]
    assert precos == [110000, 105000, 100000]


# ------------------------------------------------------------------ promoção

def _historico(conn, lid, precos_antigos, hoje):
    for i, preco in enumerate(precos_antigos, start=1):
        db.record_snapshot(conn, lid, preco, True, day(i))
    db.record_snapshot(conn, lid, hoje, True, day(0))


def test_promocao_quando_cai_10_por_cento_ou_mais(conn):
    lid = add_listing(conn, add_part(conn))
    _historico(conn, lid, [100000] * 10, hoje=85000)  # 15% abaixo
    d = db.deal_status(conn, lid)
    assert d["status"] == "deal" and d["drop_pct"] == 15.0 and d["median_cash"] == 100000


def test_nao_e_promocao_se_cai_pouco(conn):
    lid = add_listing(conn, add_part(conn))
    _historico(conn, lid, [100000] * 10, hoje=95000)  # 5% abaixo
    assert db.deal_status(conn, lid)["status"] == "normal"


def test_limite_exato_de_10_por_cento_conta(conn):
    lid = add_listing(conn, add_part(conn))
    _historico(conn, lid, [100000] * 10, hoje=90000)
    assert db.deal_status(conn, lid)["status"] == "deal"


def test_historico_curto_nao_vira_promocao(conn):
    lid = add_listing(conn, add_part(conn))
    _historico(conn, lid, [100000] * 3, hoje=50000)  # caiu 50%, mas só 3 dias
    d = db.deal_status(conn, lid)
    assert d["status"] == "short_history" and d["days_of_history"] == 3


def test_mediana_ignora_pico_isolado(conn):
    lid = add_listing(conn, add_part(conn))
    # um dia de "preço inflado" não pode fazer o preço normal parecer promoção
    _historico(conn, lid, [100000] * 9 + [300000], hoje=100000)
    assert db.deal_status(conn, lid)["status"] == "normal"


def test_preco_fora_da_janela_nao_conta(conn):
    lid = add_listing(conn, add_part(conn))
    for n in range(40, 31, -1):           # 9 dias, todos com mais de 30 dias
        db.record_snapshot(conn, lid, 200000, True, day(n))
    db.record_snapshot(conn, lid, 100000, True, day(0))
    assert db.deal_status(conn, lid)["status"] == "short_history"


def test_sem_dados(conn):
    lid = add_listing(conn, add_part(conn))
    assert db.deal_status(conn, lid) == {"status": "no_data"}


def test_lista_de_promocoes_ordena_e_ignora_esgotado(conn):
    a, b, c = (add_listing(conn, add_part(conn, model=m)) for m in ("A", "B", "C"))
    _historico(conn, a, [100000] * 10, hoje=88000)   # 12%
    _historico(conn, b, [100000] * 10, hoje=70000)   # 30%
    _historico(conn, c, [100000] * 10, hoje=50000)   # 50%, mas esgotado:
    db.record_snapshot(conn, c, 50000, False, day(0))
    deals = db.list_deals(conn)
    assert [d["model"] for d in deals] == ["B", "A"]


# ------------------------------------------------------------------ builds

def test_total_da_build(conn):
    build_id = conn.execute("SELECT id FROM builds WHERE kind = 'full'").fetchone()[0]
    gpu = add_part(conn, "gpu", "RTX 4060")
    ram = add_part(conn, "ram", "32GB DDR4", brand="Kingston")
    psu = add_part(conn, "psu", "650W", brand="XPG")
    db.record_snapshot(conn, add_listing(conn, gpu, "kabum"), 199990, True, day(0))
    db.record_snapshot(conn, add_listing(conn, gpu, "pichau"), 189990, True, day(0))
    db.record_snapshot(conn, add_listing(conn, ram), 49990, True, day(0))
    db.record_snapshot(conn, add_listing(conn, psu), 39990, False, day(0))  # esgotada
    with conn:
        for cat, pid in (("gpu", gpu), ("ram", ram), ("psu", psu)):
            conn.execute("UPDATE build_items SET part_id = ? WHERE build_id = ? AND category = ?",
                         (pid, build_id, cat))
    t = db.build_total(conn, build_id)
    assert t["total_cash"] == 189990 + 49990       # conta feita à mão
    assert t["unavailable"] == ["psu"]
    assert set(t["missing"]) == {"cpu", "motherboard", "storage", "case", "cooler"}
