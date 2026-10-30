# PC Builder: imagem única (frontend compilado + backend Python). Uso: `docker compose up -d --build`.
# Nada de banco, segredo ou data/ entra aqui (veja o .dockerignore): os dados moram no volume montado em /data.

# ---------------------------------------------------------------- 1) frontend: npm ci + build
FROM node:24-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------------------------------------------------------------- 2) uv (só o binário, versão fixa)
FROM ghcr.io/astral-sh/uv:0.12.5 AS uv

# ---------------------------------------------------------------- 3) imagem final
FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    PATH=/opt/venv/bin:$PATH \
    HOME=/var/lib/pcb \
    PCB_HOST=0.0.0.0 \
    PCB_IN_DOCKER=1 \
    PCB_DATA_DIR=/data

# usuário sem root: UID/GID fixos, HOME próprio, sem shell de login
RUN groupadd --system --gid 10001 pcb \
 && useradd --system --uid 10001 --gid 10001 --home-dir /var/lib/pcb --create-home --shell /usr/sbin/nologin pcb

# dependências EXATAMENTE como o uv.lock (sem as de desenvolvimento)
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev

# só o backend e o frontend compilado (onde FRONTEND_DIST espera: /app/frontend/dist)
COPY backend/ ./
COPY --from=frontend /build/dist /app/frontend/dist

# /data nasce do usuário pcb: um volume novo herda esse dono, então escreve do zero sem sudo nem chmod 777
RUN mkdir /data && chown 10001:10001 /data
VOLUME ["/data"]

USER 10001:10001
EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8787/api/health', timeout=4).status == 200 else 1)"]

CMD ["python", "-m", "app.serve"]
