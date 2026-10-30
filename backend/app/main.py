"""API do PC Builder (FastAPI).

Quem alcança o app: a própria máquina e, se você quiser, outros aparelhos por um proxy reverso local
(ex.: `tailscale serve`). A API LÊ, edita as builds, os favoritos, as configurações e os canais. Preço NÃO entra
pela rede: só pelo comando local `app.ingest`. (Atrás de um proxy local toda requisição chega de 127.0.0.1, então
checar IP não protege nada.)

Trava de escrita (POST/PUT/PATCH/DELETE em /api/*): Host na lista permitida (127.0.0.1:PORTA, localhost:PORTA e
PCB_ALLOWED_HOSTS), Origin (se vier) com host na mesma lista, e corpo só em application/json. Contra CSRF (outro
site mandando o navegador gravar) e DNS rebinding (um domínio do atacante apontando para 127.0.0.1).

Modo exemplo: se `demo_db_path` for passado e o banco real ainda não tiver peças, a API responde com o
banco de exemplo e marca `demo: true` no /api/health. Quando a coleta gravar a 1ª peça, o real assume.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from fastapi import Body, Depends, FastAPI, HTTPException, Path as PathParam, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import builder, compat
from . import notify as N
from . import ollama as O
from . import scheduler as SC
from . import secrets_store as SS
from . import settings as S
from .ratelimit import RateLimit
from .runlock import round_lock
from .search import matcher
from .db import database as db
from .schemas import BuildItemUpdate, Category, ChannelAdd, ChannelUpdate
from .tg import channels as tgch
from .tg import classifier as tgcls
from .tg import images as tgimg
from .tg import vote as tgvote
from .tg.rules import rules_kind

ROOT = Path(__file__).resolve().parents[2]          # pasta pc-builder/
FRONTEND_DIST = ROOT / "frontend" / "dist"
SPARK_DAYS = 30
PORT = 8787
WRITE_METHODS = ("POST", "PUT", "PATCH", "DELETE")
MAX_BODY = 64 * 1024
# rotas que fazem o servidor falar com o Ollama. Host/Origin conferidos em TODO método (até GET), senão
# um site de fora (DNS rebinding) usaria o app para sondar o endereço configurado.
AI_PATHS = ("/api/ollama", "/api/classifier")
TEST_TEXT_MAX = 2000
RULES_METRICS = Path(__file__).resolve().parent / "tg" / "rules_metrics.json"


def allowed_hosts(port: int = PORT, environ=None) -> set[str]:
    """Hosts (host:porta) que podem gravar. PCB_ALLOWED_HOSTS: extras separados por vírgula, ex.:
    `pc.minha-rede.example` (proxy em https na porta padrão) ou `pc.local:8443`. Comparação exata, sem curinga."""
    environ = os.environ if environ is None else environ
    extra = {h.strip().lower() for h in environ.get("PCB_ALLOWED_HOSTS", "").split(",") if h.strip()}
    return {f"127.0.0.1:{port}", f"localhost:{port}"} | extra


def _write_refusal(request: Request, hosts: set[str]) -> JSONResponse | None:
    h = request.headers
    if h.get("host", "").lower() not in hosts:
        return JSONResponse({"detail": "Host não permitido para gravar (veja PCB_ALLOWED_HOSTS)"}, status_code=403)
    origin = h.get("origin")
    if origin is not None:
        u = urlsplit(origin)
        if u.scheme not in ("http", "https") or u.netloc.lower() not in hosts:
            return JSONResponse({"detail": "Origin não permitido para gravar"}, status_code=403)
    try:
        length = int(h.get("content-length") or 0)
    except ValueError:
        return JSONResponse({"detail": "Content-Length inválido"}, status_code=400)
    if length > MAX_BODY:
        return JSONResponse({"detail": "corpo grande demais"}, status_code=413)
    ctype = h.get("content-type")
    has_body = length > 0 or "transfer-encoding" in h
    if (ctype is not None and ctype.split(";")[0].strip().lower() != "application/json") or (has_body and ctype is None):
        return JSONResponse({"detail": "mande o corpo como application/json"}, status_code=415)
    return None


def _in_range(cents: int, price_range: dict) -> bool:
    """Faixa de preço das Configurações (reais) contra um preço em centavos."""
    return price_range["min"] * 100 <= cents <= price_range["max"] * 100


def _sparkline(conn: sqlite3.Connection, part_id: int, days: int = SPARK_DAYS) -> list[int]:
    """Menor preço à vista por dia (todas as lojas), pro mini-gráfico do cartão."""
    by_day: dict[str, int] = {}
    for h in db.price_history(conn, part_id, days):
        d = h["collected_at"][:10]
        by_day[d] = min(by_day.get(d, h["price_cash"]), h["price_cash"])
    return [by_day[d] for d in sorted(by_day)]


def _is_fav(conn: sqlite3.Connection, part_id: int) -> bool:
    return conn.execute("SELECT 1 FROM favorites WHERE part_id = ?", (part_id,)).fetchone() is not None


def _photo(conn: sqlite3.Connection, part_id: int, image_url: str | None) -> str | None:
    """Foto da peça: a do site da loja quando existe; só quando falta, a foto mais recente de um post de canal
    (cópia local em data/tg_img, servida por /api/tg/img/). A coluna parts.image_url não é tocada."""
    if image_url:
        return image_url
    r = conn.execute(
        "SELECT o.image_path FROM listings l JOIN tg_offers o ON o.link = l.url "
        "WHERE l.part_id = ? AND o.image_path IS NOT NULL ORDER BY o.posted_at DESC LIMIT 1", (part_id,)).fetchone()
    return f"/api/tg/img/{r['image_path']}" if r else None


def _part_summary(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    part = dict(row)
    part["image_url"] = _photo(conn, part["id"], part["image_url"])
    part["specs"] = json.loads(part["specs"])
    best = db.best_price(conn, part["id"])
    part["best"] = best
    # sem estoque em lugar nenhum: mostra o último preço conhecido, apagado (decisão de 12/10/2026)
    part["out_of_stock"] = None if best else db.last_known_price(conn, part["id"])
    part["deal"] = db.deal_status(conn, best["listing_id"]) if best else {"status": "no_data"}
    part["spark"] = _sparkline(conn, part["id"])
    part["favorite"] = _is_fav(conn, part["id"])
    return part


def create_app(db_path: str | Path = db.DEFAULT_DB, frontend_dist: Path = FRONTEND_DIST,
               demo_db_path: str | Path | None = None, tg_img_dir: Path = tgimg.IMG_DIR,
               channel_fetch: Callable[[str], str] | None = None, port: int = PORT,
               data_dir: str | Path | None = None, http_client=None, clock: Callable[[], float] = time.time,
               run_scheduler: bool = False, scheduler_steps: dict | None = None,
               spawn: Callable | None = None, proc_root: str | Path = "/proc", ollama_http=None) -> FastAPI:
    """channel_fetch: quem abre a prévia t.me/s/<canal> ao adicionar um canal (os testes passam um falso).
    http_client: cliente httpx do Telegram (os testes passam um MockTransport; nunca rede nos testes).
    ollama_http: cliente httpx do Ollama (idem; padrão: app.ollama.default_client, criado no 1º uso).
    run_scheduler: liga a thread do agendador interno (o `app.serve` liga; ela só roda com scheduler_enabled).
    scheduler_steps / spawn / proc_root / clock: injetáveis nos testes."""
    db.init_db(db_path).close()
    hosts = allowed_hosts(port)
    fetch_preview = channel_fetch or tgch.preview_fetch
    ddir = Path(data_dir) if data_dir else SS.data_dir()
    store = SS.SecretStore(ddir / SS.FILE_NAME)
    test_limit = RateLimit(10, 20, clock)              # mensagem de teste: 1 a cada 10 s, 20 por hora
    detect_limit = RateLimit(3, 30, clock)             # achar o chat: 1 a cada 3 s, 30 por hora
    run_now_limit = RateLimit(SC.RUN_NOW_GAP_S, SC.RUN_NOW_PER_HOUR, clock)
    classify_limit = RateLimit(1, 300, clock)          # teste rápido: 1 por segundo, 300 por hora
    ollama_http_box: list = [ollama_http]

    def ollama_client(url: str | None = None) -> O.OllamaClient:
        if ollama_http_box[0] is None:
            ollama_http_box[0] = O.default_client()
        return O.OllamaClient(url or current_settings()["ollama"]["url"], ollama_http_box[0])

    pulls = O.PullManager(ollama_client, clock=clock, **({"spawn": spawn} if spawn else {}))

    def current_settings() -> dict:
        conn = db.connect(db_path)
        try:
            return S.values(conn)
        finally:
            conn.close()

    def notifier():
        return N.make_notifier(current_settings(), store, client=http_client)

    sched = SC.Scheduler(
        settings=current_settings, steps=scheduler_steps or SC.default_steps(db_path), notifier=notifier,
        lock=round_lock(ddir), clock=clock, game_running=lambda: SC.game_running(proc_root=proc_root),
        state_path=ddir / "agendador.json", **({"spawn": spawn} if spawn else {}))

    @asynccontextmanager
    async def lifespan(_app):
        if run_scheduler:
            sched.start()
        try:
            yield
        finally:
            sched.stop()

    app = FastAPI(title="PC Builder", version="0.5.0", docs_url="/api/docs", redoc_url=None,
                  openapi_url="/api/openapi.json", lifespan=lifespan)
    app.state.scheduler = sched

    @app.exception_handler(RequestValidationError)
    async def no_echo(request: Request, exc: RequestValidationError):
        """Nas rotas de segredo e aviso, o erro de validação não ecoa o corpo (pode ter o token)."""
        if request.url.path.startswith(("/api/secrets", "/api/notify", "/api/scheduler")):
            return JSONResponse({"detail": "corpo inválido: mande um objeto JSON"}, status_code=422)
        return await request_validation_exception_handler(request, exc)

    @app.middleware("http")
    async def write_guard(request: Request, call_next):
        path = request.url.path
        if (request.method in WRITE_METHODS and path.startswith("/api/")) or path.startswith(AI_PATHS):
            refusal = _write_refusal(request, hosts)
            if refusal is not None:
                return refusal
        return await call_next(request)

    def real_conn():
        """Configurações e canais moram sempre no banco real (nunca no de exemplo)."""
        conn = db.connect(db_path)
        try:
            yield conn
        finally:
            conn.close()

    def active_db() -> tuple[Path, bool]:
        if demo_db_path is None:
            return Path(db_path), False
        conn = db.connect(db_path)
        try:
            has_parts = conn.execute("SELECT 1 FROM parts LIMIT 1").fetchone() is not None
        finally:
            conn.close()
        return (Path(db_path), False) if has_parts else (Path(demo_db_path), True)

    def get_conn():
        path, _ = active_db()
        conn = db.connect(path)
        try:
            S.apply_stores(conn, current_settings()["stores"])   # loja desligada some de preço e promoção
            yield conn
        finally:
            conn.close()

    def _build_or_404(conn, build_id: int):
        build = conn.execute("SELECT * FROM builds WHERE id = ?", (build_id,)).fetchone()
        if build is None:
            raise HTTPException(404, "build não encontrada")
        return build

    def _build_payload(conn, build) -> dict:
        pc = current_settings()["current_pc"]
        total = db.build_total(conn, build["id"])
        chosen = builder.build_specs(conn, build["id"])
        for item in total["items"]:
            if item["part_id"] is None:
                continue
            row = conn.execute("SELECT specs, image_url FROM parts WHERE id = ?", (item["part_id"],)).fetchone()
            specs = json.loads(row["specs"])
            item["image_url"] = _photo(conn, item["part_id"], row["image_url"])
            if build["kind"] == "upgrade":
                item["compat"] = compat.check_upgrade(item["category"], specs, pc)
            else:
                item["compat"] = builder.check_in_build(item["category"], specs, chosen)
        return {**dict(build), **total}

    # ------------------------------------------------------------------ leitura

    @app.get("/api/health")
    def health():
        path, demo = active_db()
        conn = db.connect(path)
        try:
            last = conn.execute("SELECT MAX(collected_at) FROM price_snapshots").fetchone()[0]
            counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                      for t in ("parts", "listings", "price_snapshots")}
        finally:
            conn.close()
        return {"status": "ok", "demo": demo, "last_collection": last, **counts}

    @app.get("/api/stores")
    def stores(conn=Depends(get_conn)):
        return [dict(r) for r in conn.execute("SELECT id, slug, name, base_url, active, status_note FROM stores")]

    @app.get("/api/parts")
    def parts(category: Category | None = None, q: str | None = Query(default=None, max_length=100),
              upgrade: bool = False, favorites: bool = False, conn=Depends(get_conn)):
        cfg = current_settings()
        sql, args = "SELECT * FROM parts WHERE 1=1", []
        if category:
            sql += " AND category = ?"
            args.append(category)
        match = matcher(q)              # palavra por palavra, sem acento (app/search.py)
        if favorites:
            sql += " AND id IN (SELECT part_id FROM favorites)"
        out = []
        for row in conn.execute(sql + " ORDER BY category, brand, model", args).fetchall():
            if match and not match(f"{row['brand']} {row['model']}"):
                continue
            part = _part_summary(conn, row)
            shown = part["best"] or part["out_of_stock"]
            if shown and not _in_range(shown["price_cash"], cfg["price_range"]):
                continue                # fora da faixa de preço (peça sem preço nenhum fica: não dá pra julgar)
            if upgrade:
                part["compat"] = compat.check_upgrade(part["category"], part["specs"], cfg["current_pc"])
            out.append(part)
        # com estoque primeiro (mais barato antes), depois sem estoque, e sem preço nenhum no fim
        out.sort(key=lambda p: (0, p["best"]["price_cash"]) if p["best"] else
                 (1, p["out_of_stock"]["price_cash"]) if p["out_of_stock"] else (2, 0))
        return out

    @app.get("/api/parts/{part_id}")
    def part_detail(part_id: int, conn=Depends(get_conn)):
        row = conn.execute("SELECT * FROM parts WHERE id = ?", (part_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "peça não encontrada")
        part = _part_summary(conn, row)
        part["offers"] = [{**o, "deal": db.deal_status(conn, o["listing_id"])}
                          for o in db.latest_prices(conn, part_id)]
        part["compat"] = compat.check_upgrade(part["category"], part["specs"], current_settings()["current_pc"])
        return part

    @app.get("/api/parts/{part_id}/history")
    def part_history(part_id: int, days: int = Query(default=90, ge=1, le=3650), conn=Depends(get_conn)):
        if conn.execute("SELECT 1 FROM parts WHERE id = ?", (part_id,)).fetchone() is None:
            raise HTTPException(404, "peça não encontrada")
        return db.price_history(conn, part_id, days)

    @app.get("/api/deals")
    def deals(conn=Depends(get_conn)):
        price_range = current_settings()["price_range"]
        out = []
        for d in db.list_deals(conn):
            if not _in_range(d["price_cash"], price_range):
                continue
            row = conn.execute("SELECT image_url FROM parts WHERE id = ?", (d["part_id"],)).fetchone()
            out.append({**d, "image_url": _photo(conn, d["part_id"], row["image_url"]), "spark": _sparkline(conn, d["part_id"]),
                        "favorite": _is_fav(conn, d["part_id"])})
        return out

    @app.get("/api/builds")
    def builds(conn=Depends(get_conn)):
        return [_build_payload(conn, b) for b in conn.execute("SELECT * FROM builds ORDER BY id").fetchall()]

    # ------------------------------------------------------------------ canais do Telegram (só leitura)

    @app.get("/api/tg/offers")
    def tg_offers(kind: str | None = Query(default=None, max_length=40),
                  store: str | None = Query(default=None, max_length=40),
                  channel: str | None = Query(default=None, max_length=60),
                  q: str | None = Query(default=None, max_length=100),
                  days: int = Query(default=7, ge=1, le=3650),
                  only_deals: bool = False,
                  no_parts: bool = False,
                  limit: int = Query(default=200, ge=1, le=1000), conn=Depends(get_conn)):
        """Ofertas de tecnologia dos canais. Em cada uma, a comparação com o histórico do mesmo produto."""
        from .tg import run as tgrun
        sql = ("SELECT * FROM tg_offers WHERE posted_at >= datetime('now', 'localtime', ?) "
               "AND kind IS NOT NULL")
        args: list = [f"-{days} days"]
        if no_parts:                    # aba Canais: peça de PC fica na aba Peças
            sql += " AND kind NOT LIKE 'peca:%'"
        if not kind:                    # "não é peça" das regras pode ser comida, roupa... só se pedir
            sql += " AND kind != 'nao_peca'"
        for col, val in (("kind", kind), ("store", store), ("channel", channel)):
            if val:
                sql += f" AND {col} = ?"
                args.append(val)
        match = matcher(q)              # palavra por palavra, sem acento (app/search.py)
        out = []
        for r in conn.execute(sql + " ORDER BY posted_at DESC", args):
            if len(out) >= limit:
                break
            if match and not match(r["title"]):
                continue
            o = {k: r[k] for k in ("id", "channel", "msg_id", "posted_at", "title", "price_cash", "store", "link",
                                   "kind", "kind_agree", "product_key")}
            ref = tgrun.reference(conn, r["product_key"], r["posted_at"], r["id"]) if r["product_key"] else None
            o["image"] = f"/api/tg/img/{r['image_path']}" if r["image_path"] else None
            o["ref"] = ref
            o["deal"] = tgrun.judge(r["price_cash"], ref)
            o["pct"] = round(100 * (1 - r["price_cash"] / ref["median"])) if ref else None
            if only_deals and not o["deal"]:
                continue
            out.append(o)
        return out

    @app.get("/api/tg/img/{name}")
    def tg_img(name: str):
        """Foto de oferta de canal (cópia local). Só nome no formato canal_id.ext, só dentro de data/tg_img."""
        if not tgimg.NAME_RX.match(name):
            raise HTTPException(404, "foto não existe")
        path = (Path(tg_img_dir) / name).resolve()
        if Path(tg_img_dir).resolve() not in path.parents or not path.is_file():
            raise HTTPException(404, "foto não existe")
        media = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}[name.rsplit(".", 1)[1]]
        return FileResponse(path, media_type=media, headers={"Cache-Control": "public, max-age=2592000, immutable"})

    @app.get("/api/tg/meta")
    def tg_meta(conn=Depends(get_conn)):
        """Pros filtros da tela: tipos, lojas e canais com contagem, e o estado de cada canal."""
        def count(col):
            return [{"value": r[0], "n": r[1]} for r in conn.execute(
                f"SELECT {col}, COUNT(*) FROM tg_offers WHERE {col} IS NOT NULL GROUP BY 1 ORDER BY 2 DESC")]
        channels = [dict(r) for r in conn.execute(
            "SELECT slug, active, last_ok_at, fail_count, last_error FROM tg_channels WHERE removed_at IS NULL "
            "ORDER BY slug")]
        last = conn.execute("SELECT MAX(seen_at) FROM tg_offers").fetchone()[0]
        return {"kinds": count("kind"), "stores": count("store"), "channels": channels, "last_round": last,
                "total": conn.execute("SELECT COUNT(*) FROM tg_offers").fetchone()[0]}

    @app.get("/api/builds/{build_id}/options/{category}")
    def build_options(build_id: int, category: Category, conn=Depends(get_conn)):
        """Peças da categoria com preço, e se cada uma combina com o resto da build."""
        build = _build_or_404(conn, build_id)
        chosen = builder.build_specs(conn, build_id)
        pc = current_settings()["current_pc"]
        out = []
        for row in conn.execute("SELECT * FROM parts WHERE category = ?", (category,)).fetchall():
            part = _part_summary(conn, row)
            if part["best"] is None:
                continue
            part["compat"] = (compat.check_upgrade(category, part["specs"], pc) if build["kind"] == "upgrade"
                              else builder.check_in_build(category, part["specs"], chosen))
            out.append(part)
        out.sort(key=lambda p: (p["compat"]["compatible"] is False, p["best"]["price_cash"]))
        return out

    @app.get("/api/current-pc")
    def current_pc():
        return current_settings()["current_pc"]

    @app.get("/api/favorites")
    def favorites_list(conn=Depends(get_conn)):
        return [r["part_id"] for r in conn.execute("SELECT part_id FROM favorites ORDER BY created_at")]

    # ------------------------------------------------------------------ escrita (builds e favoritos)

    @app.put("/api/builds/{build_id}/items/{category}")
    def set_build_item(build_id: int, category: Category, body: BuildItemUpdate, conn=Depends(get_conn)):
        _build_or_404(conn, build_id)
        slot = conn.execute("SELECT 1 FROM build_items WHERE build_id = ? AND category = ?",
                            (build_id, category)).fetchone()
        if slot is None:
            raise HTTPException(422, f"a build não tem a categoria {category}")
        if body.part_id is not None:
            part = conn.execute("SELECT category FROM parts WHERE id = ?", (body.part_id,)).fetchone()
            if part is None:
                raise HTTPException(404, "peça não encontrada")
            if part["category"] != category:
                raise HTTPException(422, f"a peça é de {part['category']}, não de {category}")
        with conn:
            conn.execute("UPDATE build_items SET part_id = ? WHERE build_id = ? AND category = ?",
                         (body.part_id, build_id, category))
        return db.build_total(conn, build_id)

    @app.post("/api/builds/{build_id}/auto")
    def build_auto(build_id: int, conn=Depends(get_conn)):
        """Monta a build completa mais barata e compatível (substitui as escolhas atuais)."""
        build = _build_or_404(conn, build_id)
        if build["kind"] != "full":
            raise HTTPException(422, "montagem automática é só pra build completa")
        picks = builder.auto_pick(conn)
        with conn:
            for cat, pid in picks.items():
                conn.execute("UPDATE build_items SET part_id = ? WHERE build_id = ? AND category = ?",
                             (pid, build_id, cat))
        return _build_payload(conn, build)

    @app.put("/api/favorites/{part_id}", status_code=204)
    def favorite_add(part_id: int, conn=Depends(get_conn)):
        if conn.execute("SELECT 1 FROM parts WHERE id = ?", (part_id,)).fetchone() is None:
            raise HTTPException(404, "peça não encontrada")
        with conn:
            conn.execute("INSERT OR IGNORE INTO favorites (part_id) VALUES (?)", (part_id,))

    @app.delete("/api/favorites/{part_id}", status_code=204)
    def favorite_remove(part_id: int, conn=Depends(get_conn)):
        with conn:
            conn.execute("DELETE FROM favorites WHERE part_id = ?", (part_id,))

    # ------------------------------------------------------------------ configurações (sem segredo)

    def _settings_payload(conn) -> dict:
        eff = S.effective(conn)
        return {"values": {k: v["value"] for k, v in eff.items()},
                "meta": {k: {m: x for m, x in v.items() if m != "value"} for k, v in eff.items()},
                "options": S.options()}

    @app.get("/api/settings")
    def settings_get(conn=Depends(real_conn)):
        """Valores efetivos e a origem de cada um: default (padrão), banco (salvo na tela) ou env (PCB_*)."""
        return _settings_payload(conn)

    @app.put("/api/settings")
    def settings_put(payload: Any = Body(None), conn=Depends(real_conn)):
        """Atualização parcial. Tudo ou nada: 422 com a mensagem de cada campo ruim."""
        try:
            S.save(conn, payload)
        except S.SettingsError as e:
            raise HTTPException(422, {"message": "configuração recusada", "fields": e.fields}) from None
        return _settings_payload(conn)

    @app.post("/api/settings/reset/{key}")
    def settings_reset(key: str = PathParam(max_length=40), conn=Depends(real_conn)):
        try:
            S.reset(conn, key)
        except KeyError:
            raise HTTPException(404, "configuração não existe") from None
        return _settings_payload(conn)

    # ------------------------------------------------------------------ canais do Telegram

    @app.get("/api/channels")
    def channels_list(conn=Depends(real_conn)):
        return tgch.list_channels(conn)

    @app.post("/api/channels", status_code=201)
    def channels_add(body: ChannelAdd, conn=Depends(real_conn)):
        """Confere a prévia pública (t.me/s/<nome>) antes de gravar: 1 tentativa, timeout curto."""
        try:
            return tgch.add_channel(conn, body.handle, fetch_preview)
        except tgch.ChannelExists as e:
            raise HTTPException(409, str(e)) from None
        except tgch.ChannelUnreachable:
            raise HTTPException(503, "sem rede: não consegui abrir o t.me agora; nada foi gravado, tente de novo") from None
        except ValueError as e:             # nome inválido, limite de canais, sem prévia pública
            raise HTTPException(422, str(e)) from None

    @app.put("/api/channels/{slug}")
    def channels_set(body: ChannelUpdate, slug: str = PathParam(max_length=40), conn=Depends(real_conn)):
        ch = tgch.set_enabled(conn, slug, body.enabled)
        if ch is None:
            raise HTTPException(404, "canal não encontrado")
        return ch

    @app.delete("/api/channels/{slug}", status_code=204)
    def channels_remove(slug: str = PathParam(max_length=40), conn=Depends(real_conn)):
        """Desliga e esconde o canal. As ofertas antigas e o histórico de preço ficam."""
        if not tgch.remove_channel(conn, slug):
            raise HTTPException(404, "canal não encontrado")

    # ------------------------------------------------------------------ bot do Telegram (token write-only)

    def _limited(limit: RateLimit):
        wait = limit.check()
        if wait is not None:
            raise HTTPException(429, f"calma: tente de novo em {wait} s", headers={"Retry-After": str(wait)})

    @app.get("/api/secrets/telegram")
    def secrets_get():
        """Só o estado: configurado, origem (env | file | null) e os 4 últimos caracteres. Nunca o valor."""
        return store.status()

    @app.put("/api/secrets/telegram")
    def secrets_put(payload: Any = Body(None)):
        """{token?, chat_id?}. Recusa com 422 sem repetir o valor; 409 se o campo vem de variável de ambiente."""
        if not isinstance(payload, dict) or not payload or set(payload) - {"token", "chat_id"}:
            raise HTTPException(422, "mande {\"token\": ..., \"chat_id\": ...} (um dos dois ou os dois)")
        try:
            store.save(token=payload.get("token"), chat_id=payload.get("chat_id"))
        except SS.SecretsLocked as e:
            raise HTTPException(409, str(e)) from None
        except SS.SecretsFileError as e:
            raise HTTPException(409, str(e)) from None
        except SS.SecretsError as e:
            raise HTTPException(422, str(e)) from None
        return store.status()

    @app.delete("/api/secrets/telegram")
    def secrets_delete():
        """Apaga o token e o chat id do secrets.env. O que vem de variável de ambiente continua valendo."""
        try:
            store.clear()
        except SS.SecretsFileError as e:
            raise HTTPException(409, str(e)) from None
        return store.status()

    @app.post("/api/secrets/telegram/detect-chat")
    def secrets_detect_chat():
        """getUpdates com o token salvo: as conversas que falaram com o bot, para a pessoa escolher."""
        token, _ = store.get("token")
        if not token:
            raise HTTPException(409, "salve o token do bot primeiro")
        _limited(detect_limit)
        bot = N.TelegramBot(token, None, client=http_client)
        try:
            me = bot.get_me()
            chats = bot.get_chats()
        except N.NotifyError as e:
            raise HTTPException(502, str(e)) from None
        out = {"bot": me.get("username"), "chats": chats}
        if not chats:
            out["hint"] = "Nenhuma conversa ainda: abra o seu bot no Telegram, mande /start e tente de novo."
        return out

    @app.post("/api/notify/test")
    def notify_test(payload: Any = Body(None)):
        """Manda "PC Builder: mensagem de teste" pelo destino salvo (ou o do corpo: {"target": "telegram"})."""
        target = payload.get("target") if isinstance(payload, dict) else None
        if payload is not None and (not isinstance(payload, dict) or set(payload) - {"target"}
                                    or (target is not None and target not in S.NOTIFY_TARGETS)):
            raise HTTPException(422, f"target: escolha um de {', '.join(S.NOTIFY_TARGETS)}")
        target = target or current_settings()["notify_target"]
        if target == "none":
            raise HTTPException(409, "o destino do aviso está em \"nenhum\": escolha Telegram ou saída do script")
        if target == "telegram":
            token, _ = store.get("token")
            chat, _ = store.get("chat_id")
            if not (token and chat):
                raise HTTPException(409, "falta o token do bot ou o chat: siga os passos da tela")
            sender = N.TelegramBot(token, chat, client=http_client)
        else:
            sender = N.Stdout()
        _limited(test_limit)
        res = sender.send(N.TEST_TEXT)
        if not res.ok:
            raise HTTPException(502, res.error or "não consegui mandar")
        return {"ok": True, "target": target}

    # ------------------------------------------------------------------ agendador interno

    @app.get("/api/scheduler")
    def scheduler_status():
        return sched.status()

    @app.post("/api/scheduler/run-now", status_code=202)
    def scheduler_run_now():
        """Uma rodada agora (coleta + canais), em segundo plano, com a mesma trava do agendador e do cron."""
        _limited(run_now_limit)
        if not sched.run_now():
            raise HTTPException(409, "já tem uma rodada em andamento (agendador ou cron); espere ela terminar")
        return {"started": True}

    # ------------------------------------------------------------------ IA local (Ollama) e classificador

    def _tagged(name: str) -> str:
        """'llama3.2' e 'library/llama3.2' são o mesmo modelo que o Ollama lista como 'llama3.2:latest'."""
        name = name.removeprefix("registry.ollama.ai/").removeprefix("library/")
        return name if ":" in name.rsplit("/", 1)[-1] else f"{name}:latest"

    def _ollama_state(try_url: str | None = None) -> dict:
        """try_url: endereço ainda não salvo (botão "Testar"), validado como no salvar."""
        cfg = current_settings()
        url, selected, mode = cfg["ollama"]["url"], cfg["ollama"]["models"], cfg["classifier"]
        if try_url is not None:
            try:
                url = S.validate("ollama", {"url": try_url}, cfg["ollama"])["url"]
            except ValueError as e:
                raise HTTPException(422, str(e)) from None
        out = {"reachable": False, "url": url, "version": None, "error": None, "warning": S.ollama_warning(url),
               "classifier_mode": mode, "models_selected": selected, "models_missing": [], "installed": None}
        if mode != "rules" or try_url is not None:     # modo "só regras" só fala com o Ollama no "Testar"
            cli = ollama_client(url)
            try:
                out["version"] = cli.version()
                installed = cli.models()
                out.update(reachable=True, installed=installed)
                have = {_tagged(m["name"]) for m in installed}
                out["models_missing"] = [m for m in selected if _tagged(m) not in have]
            except O.OllamaError as e:
                out["error"] = str(e)
        else:
            out["error"] = "modo \"só regras\": o app não consulta o Ollama"
        if mode == "rules":
            eff = "rules"
        elif mode == "ollama":
            eff = "ollama"                             # fora do ar: guarda sem tipo, nunca usa regras
        else:
            eff = "ollama" if out["reachable"] and not out["models_missing"] else "rules"
        out["classifier_effective"] = eff
        return out

    @app.get("/api/ollama/status")
    def ollama_status(url: str | None = Query(default=None, max_length=200)):
        """Se o Ollama responde, a versão, e qual classificador vale agora. O erro é só o motivo, sem endereço.
        ?url=: testa um endereço antes de salvar (mesma validação do salvar; nada é gravado)."""
        st = _ollama_state(url)
        st.pop("installed")
        return st

    @app.get("/api/ollama/models")
    def ollama_models():
        """Modelos instalados no Ollama (GET {url}/api/tags): nome, tamanho em bytes, quantização."""
        try:
            return {"models": ollama_client().models()}
        except O.OllamaError as e:
            raise HTTPException(503, str(e)) from None

    @app.get("/api/ollama/pull")
    def ollama_pull_status():
        return pulls.status()

    @app.post("/api/ollama/pull", status_code=202)
    def ollama_pull(payload: Any = Body(None)):
        """Baixa um modelo em segundo plano. Um por vez (409), no máximo 5 por hora (429)."""
        if not isinstance(payload, dict) or set(payload) != {"model"} or not S.valid_model(payload["model"]):
            raise HTTPException(422, "mande {\"model\": \"nome:etiqueta\"} (ex.: qwen2.5:3b)")
        try:
            return pulls.start(payload["model"])
        except O.PullBusy:
            raise HTTPException(409, "já tem um download em andamento; espere ou cancele") from None
        except O.PullLimited as e:
            raise HTTPException(429, f"limite de {O.PULL_PER_HOUR} downloads por hora: tente em {e.wait} s",
                                headers={"Retry-After": str(e.wait)}) from None

    @app.delete("/api/ollama/pull")
    def ollama_pull_cancel():
        return {"canceled": pulls.cancel()}

    @app.post("/api/classifier/test")
    def classifier_test(payload: Any = Body(None)):
        """Classifica um título colado. Mostra o tipo, de onde veio e, sempre, o que as regras dizem e por quê."""
        text = payload.get("text") if isinstance(payload, dict) else None
        if not isinstance(payload, dict) or set(payload) != {"text"} or not isinstance(text, str) \
                or not text.strip() or len(text) > TEST_TEXT_MAX:
            raise HTTPException(422, f"mande {{\"text\": ...}} com 1 a {TEST_TEXT_MAX} caracteres")
        _limited(classify_limit)
        rk, rconf, rwhy = rules_kind(text)
        rules = {"kind": rk, "confidence": rconf, "why": rwhy}
        out = {"kind": rk, "source": "rules" if rk else None, "why": rwhy, "confidence": rconf, "agree": None,
               "votes": None, "rules": rules, "fallback": False, "error": None}
        cfg = current_settings()
        mode = cfg["classifier"]
        if mode == "rules":
            return out
        cli = ollama_client()
        try:
            if mode == "auto" and not cli.ping():
                raise tgvote.OllamaDown("o Ollama não respondeu")
            ollama = tgcls.Ollama(cli.chat, cfg["ollama"]["models"], cli.unload)
            v, = ollama.classify([text])
        except tgvote.OllamaDown as e:
            if mode == "auto":
                return {**out, "fallback": True, "error": str(e)}
            return {**out, "kind": None, "source": None, "why": None, "confidence": None, "error": str(e)}
        f = tgcls.fields(text, v, ollama.quorum)
        return {**out, "kind": f["kind"] if f else v.kind, "source": "ollama", "why": None, "confidence": None,
                "agree": v.agree, "votes": v.votes}

    @app.get("/api/classifier")
    def classifier_info(conn=Depends(real_conn)):
        """Modo escolhido, modo efetivo, a acurácia medida das regras (arquivo gerado) e ofertas por origem."""
        st = _ollama_state()
        try:
            m = json.loads(RULES_METRICS.read_text(encoding="utf-8"))
            metrics = {**m["all"], "sets": m["sets"]}
        except (OSError, ValueError, KeyError):
            metrics = None
        counts = {"ollama": 0, "rules": 0, "sem_tipo": 0}
        for r in conn.execute("SELECT CASE WHEN kind IS NULL THEN 'sem_tipo' ELSE kind_source END, COUNT(*) "
                              "FROM tg_offers GROUP BY 1"):
            if r[0] in counts:
                counts[r[0]] += r[1]
        return {"mode": st["classifier_mode"], "effective": st["classifier_effective"], "rules_metrics": metrics,
                "counts": counts}

    # ------------------------------------------------------------------ frontend

    @app.get("/api/{rest:path}", include_in_schema=False)
    def api_not_found(rest: str):
        raise HTTPException(404, "rota da API não existe")

    index = frontend_dist / "index.html"
    if (frontend_dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="assets")

    @app.get("/{rest:path}", include_in_schema=False)
    def spa(rest: str):
        static = (frontend_dist / rest).resolve()
        if rest and static.is_file() and frontend_dist.resolve() in static.parents:
            return FileResponse(static)   # favicon etc.
        if index.is_file():
            # o index.html aponta pros arquivos novos a cada build: o navegador tem que conferir sempre,
            # senão mostra a tela velha (aconteceu pelo proxy em 12/10/2026). assets/ têm hash no nome.
            return FileResponse(index, headers={"Cache-Control": "no-cache"})
        return {"app": "PC Builder", "status": "frontend ainda não foi gerado",
                "api_docs": "/api/docs"}

    return app
