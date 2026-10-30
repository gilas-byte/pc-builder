"""Sobe o servidor. Uso: `python -m app.serve` (é o que o serviço systemd roda)."""

import ipaddress
import os
from typing import Mapping

import uvicorn

from .demo import build_demo
from .main import PORT as APP_PORT, create_app

HOST = "127.0.0.1"  # só a própria máquina; outro aparelho entra por um proxy local (ex.: `tailscale serve`)
PORT = APP_PORT     # 8787; a trava de escrita aceita Host 127.0.0.1:PORT e localhost:PORT (+ PCB_ALLOWED_HOSTS)


def listen_host(environ: Mapping[str, str] | None = None) -> str:
    """Endereço de escuta. Padrão 127.0.0.1. `PCB_HOST` só aceita IP válido (lixo cai no padrão, sem derrubar).
    A imagem Docker põe 0.0.0.0 (senão a porta publicada não alcança o servidor); quem publica a porta no host
    só em 127.0.0.1 é o docker-compose.yml."""
    environ = os.environ if environ is None else environ
    raw = environ.get("PCB_HOST", "").strip()
    try:
        return str(ipaddress.ip_address(raw)) if raw else HOST
    except ValueError:
        return HOST


def main() -> None:
    demo = build_demo()  # dados de EXEMPLO; só aparecem enquanto o banco real não tem peças
    uvicorn.run(
        # o agendador interno sobe junto, mas só roda com scheduler_enabled (tela) ou PCB_SCHEDULER=1
        create_app(demo_db_path=demo, port=PORT, run_scheduler=True),
        host=listen_host(),
        port=PORT,
        # Não confiar em X-Forwarded-For: o IP do cliente tem que ser o real da conexão,
        # senão a trava de "gravação só local" poderia ser enganada por um proxy.
        proxy_headers=False,
        server_header=False,
    )


if __name__ == "__main__":
    main()
