from app.compat import CURRENT_PC, check_upgrade


def test_pc_de_exemplo_e_neutro():
    # PC de EXEMPLO (AM4, DDR4, ATX); as regras abaixo dependem só de socket, memória e formato
    assert CURRENT_PC["cpu"] == "AMD Ryzen 5 5600" and CURRENT_PC["gpu"] == "NVIDIA GeForce RTX 3060"
    assert (CURRENT_PC["socket"], CURRENT_PC["memory_type"], CURRENT_PC["form_factor"]) == ("AM4", "DDR4", "ATX")
    assert CURRENT_PC["ram_gb"] == 16 and "B450" in CURRENT_PC["motherboard"]


def test_avisos_citam_a_placa_do_pc_atual():
    placa = CURRENT_PC["motherboard"]
    assert check_upgrade("cpu", {"socket": "AM5"})["warnings"] == [f"Socket AM5: a sua placa {placa} só aceita AM4."]
    assert check_upgrade("ram", {"memory_type": "DDR5"})["warnings"] == [f"DDR5: a sua placa {placa} só aceita DDR4."]
    assert check_upgrade("case", {"motherboard_support": ["ITX"]})["warnings"] == [
        f"Este gabinete não aceita placa ATX (a sua {placa} é ATX)."]


def test_cpu():
    assert check_upgrade("cpu", {"socket": "AM4"})["compatible"] is True
    assert check_upgrade("cpu", {"socket": "am4"})["compatible"] is True   # maiúscula/minúscula
    assert check_upgrade("cpu", {"socket": "AM5"})["compatible"] is False
    assert check_upgrade("cpu", {})["compatible"] is None
    assert check_upgrade("cpu", None)["compatible"] is None


def test_ram():
    assert check_upgrade("ram", {"memory_type": "DDR4"})["compatible"] is True
    assert check_upgrade("ram", {"memory_type": "DDR5"})["compatible"] is False


def test_placa_mae_nunca_e_upgrade():
    assert check_upgrade("motherboard", {"socket": "AM4"})["compatible"] is False


def test_cooler_e_gabinete():
    assert check_upgrade("cooler", {"sockets": ["AM4", "AM5"]})["compatible"] is True
    assert check_upgrade("cooler", {"sockets": ["LGA1700"]})["compatible"] is False
    assert check_upgrade("case", {"motherboard_support": ["ATX", "mATX"]})["compatible"] is True
    assert check_upgrade("case", {"motherboard_support": ["mATX", "ITX"]})["compatible"] is False


def test_gpu_avisa_fonte():
    r = check_upgrade("gpu", {"recommended_psu_w": 650})
    assert r["compatible"] is True and "650" in r["warnings"][0]
    assert check_upgrade("gpu", {}) == {"compatible": True, "warnings": []}
