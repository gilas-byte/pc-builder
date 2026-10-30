"""Compatibilidade de peças com o PC atual (usada só na lista de upgrades).

Regras simples e honestas: o que dá pra verificar com os specs vira sim/não; o que falta vira
"não verificado" com aviso, em vez de esconder a peça.
"""

from __future__ import annotations

# PC de EXEMPLO e padrão da configuração `current_pc` (app/settings.py). O PC de verdade vem da tela de
# Configurações; quem chama passa o `pc` efetivo. Socket, memória e formato da placa são o que filtra os upgrades.
CURRENT_PC = {
    "cpu": "AMD Ryzen 5 5600",
    "motherboard": "MSI B450 TOMAHAWK MAX",
    "socket": "AM4",
    "memory_type": "DDR4",
    "form_factor": "ATX",
    "gpu": "NVIDIA GeForce RTX 3060",
    "ram_gb": 16,
    "storage": ["SSD NVMe 1 TB"],
    "psu": None,  # não dá pra ler pelo sistema
}


def _result(compatible: bool | None, *warnings: str) -> dict:
    return {"compatible": compatible, "warnings": list(warnings)}


def _norm(value) -> str:
    return str(value).strip().upper()


def check_upgrade(category: str, specs: dict | None, pc: dict | None = None) -> dict:
    """compatible: True (serve), False (não serve) ou None (faltam dados pra saber). pc: o PC atual salvo
    (sem ele, o de exemplo)."""
    specs = specs or {}
    pc = pc or CURRENT_PC
    board, socket_pc, mem_pc, ff = pc["motherboard"], _norm(pc["socket"]), _norm(pc["memory_type"]), pc["form_factor"]

    if category == "motherboard":
        return _result(False, "Trocar a placa-mãe é outra build, não upgrade.")

    if category == "cpu":
        socket = specs.get("socket")
        if not socket:
            return _result(None, "Compatibilidade não verificada: falta o socket.")
        if _norm(socket) != socket_pc:
            return _result(False, f"Socket {socket}: a sua placa {board} só aceita {pc['socket']}.")
        return _result(True)

    if category == "ram":
        mem = specs.get("memory_type")
        if not mem:
            return _result(None, "Compatibilidade não verificada: falta o tipo de memória.")
        if _norm(mem) != mem_pc:
            return _result(False, f"{mem}: a sua placa {board} só aceita {pc['memory_type']}.")
        return _result(True)

    if category == "cooler":
        sockets = specs.get("sockets")
        if not sockets:
            return _result(None, "Compatibilidade não verificada: faltam os sockets suportados.")
        if socket_pc not in {_norm(s) for s in sockets}:
            return _result(False, f"Este cooler não lista suporte a {pc['socket']}.")
        return _result(True)

    if category == "case":
        boards = specs.get("motherboard_support")
        if not boards:
            return _result(None, "Compatibilidade não verificada: faltam os formatos de placa suportados.")
        if _norm(ff) not in {_norm(b) for b in boards}:
            return _result(False, f"Este gabinete não aceita placa {ff} (a sua {board} é {ff}).")
        return _result(True)

    if category == "gpu":
        psu = specs.get("recommended_psu_w")
        if psu:
            return _result(True, f"Fonte recomendada: {psu} W. Confira a sua (não consigo ler pelo sistema).")
        return _result(True)

    # storage e psu: sem filtro duro.
    return _result(True)
