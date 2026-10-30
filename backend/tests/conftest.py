"""Valem para todos os testes: nenhum segredo da máquina, nenhum arquivo em data/ e nenhuma chamada ao Telegram."""

import pytest


@pytest.fixture(autouse=True)
def _isolado(tmp_path_factory, monkeypatch):
    for var in ("PCB_TELEGRAM_TOKEN", "PCB_TELEGRAM_CHAT_ID", "PCB_SCHEDULER", "PCB_NOTIFY_TARGET", "PCB_GAME_MODE",
                "PCB_GAME_PATTERN", "PCB_IN_DOCKER"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("PCB_DATA_DIR", str(tmp_path_factory.mktemp("dados")))

    from app import notify

    def sem_rede():
        raise RuntimeError("teste tentou criar um cliente HTTP de verdade (rede proibida nos testes)")
    monkeypatch.setattr(notify, "default_client", sem_rede)
    from app import ollama
    monkeypatch.setattr(ollama, "default_client", sem_rede)      # nunca o Ollama de verdade
    monkeypatch.delenv("PCB_CLASSIFIER", raising=False)
    monkeypatch.delenv("PCB_OLLAMA_URL", raising=False)
    monkeypatch.delenv("PCB_OLLAMA_MODELS", raising=False)
    notify._warned.clear()
