English: [docs/en/02-backend.md](en/02-backend.md)

# Backend (Python)

**Objetivo:** uma API que o frontend consome. Os preços coletados entram por um comando local (ver abaixo).

**Tecnologia:** FastAPI + Uvicorn, dependências pelo `uv`. Python 3.11.

## Endpoints

| método | rota | o que faz |
|---|---|---|
| GET | `/api/health` | status, data da última coleta e quantos preços existem |
| GET | `/api/stores` | as lojas |
| GET | `/api/parts?category=gpu` | peças, com melhor preço atual, loja e link |
| GET | `/api/parts/{id}` | uma peça, com o preço em cada loja |
| GET | `/api/parts/{id}/history` | histórico de preço, pro gráfico |
| GET | `/api/deals` | as promoções de hoje (regra descrita em `01-banco-de-dados.md`) |
| GET | `/api/builds` | as 2 builds com total |
| PUT | `/api/builds/{id}/items/{category}` | escolher qual peça entra numa categoria da build |
| GET | `/api/current-pc` | o PC atual efetivo (configuração `current_pc`; sem nada salvo, o de exemplo) |
| GET | `/api/settings` | configurações efetivas + origem de cada uma (`default`, `banco`, `env`) + listas da tela |
| PUT | `/api/settings` | atualização parcial; tudo ou nada; 422 `{"detail": {"message", "fields": {chave: msg}}}` |
| POST | `/api/settings/reset/{chave}` | volta a chave ao padrão (apaga do banco); chave desconhecida = 404 |
| GET | `/api/channels` | canais cadastrados: ligado, origem, ofertas vistas, última leitura, falhas |
| POST | `/api/channels` | `{"handle"}`: `@nome`, `nome`, `t.me/nome`, `t.me/s/nome`; confere a prévia (201/409/422/503) |
| PUT | `/api/channels/{slug}` | `{"enabled": true/false}` |
| DELETE | `/api/channels/{slug}` | desliga e esconde; as ofertas e o histórico ficam (204) |
| GET | `/api/secrets/telegram` | só o estado do token e do chat: `{configured, source: env\|file\|null, hint: "…1234", chat_id: {...}, ready}` |
| PUT | `/api/secrets/telegram` | `{token?, chat_id?}`; 422 sem repetir o valor; 409 se o campo vem de variável de ambiente |
| DELETE | `/api/secrets/telegram` | apaga token e chat do `secrets.env` (o que vem de variável continua) |
| POST | `/api/secrets/telegram/detect-chat` | `getUpdates` com o token salvo: `{bot, chats: [{id, tipo, nome}], hint?}`; 409 sem token |
| POST | `/api/notify/test` | manda "PC Builder: mensagem de teste" (`{"target"}` opcional); 409 sem configuração; 1 a cada 10 s, 20/h |
| GET | `/api/scheduler` | agendador: ligado, rodando, última/próxima rodada, último erro, modo jogo disponível |
| POST | `/api/scheduler/run-now` | 1 rodada agora em segundo plano (202); 409 se outra rodada tem a trava; 1/min, 10/h |
| GET | `/api/ollama/status` | `{reachable, url, version, error, warning, classifier_mode, classifier_effective, models_selected, models_missing}`; `?url=` testa um endereço sem salvar |
| GET | `/api/ollama/models` | modelos instalados (`{url}/api/tags`): nome, tamanho, quantização, parâmetros; 503 sem Ollama |
| GET | `/api/ollama/pull` | download: `{model, state (idle/running/done/error/canceled), phase, completed, total, percent, error}` |
| POST | `/api/ollama/pull` | `{"model"}`; baixa em segundo plano (202); um por vez (409); 5 por hora (429 + `Retry-After`) |
| DELETE | `/api/ollama/pull` | cancela o download em andamento: `{canceled}` |
| POST | `/api/classifier/test` | `{"text"}` (1 a 2000 caracteres): tipo, origem (`ollama`/`rules`), votos e o porquê das regras; 1/s, 300/h |
| GET | `/api/classifier` | modo escolhido, efetivo, métricas das regras (`app/tg/rules_metrics.json`) e ofertas por origem |

**Classificador e Ollama:** classificador por regras (`app/tg/rules.py`) como plano B do Ollama, escolhido pela
configuração `classifier` (`auto` | `rules` | `ollama`; `app/tg/classifier.py`). O cliente do Ollama
(`app/ollama.py`, httpx) usa o endereço salvo; erro nunca repete o endereço. As rotas `/api/ollama/*` e
`/api/classifier*` conferem Host e Origin **também no GET** (fazem o servidor falar com outro endereço).

**Aviso e agendador:** o token do bot é **write-only**. Mora em `secrets.env` (`app/secrets_store.py`) no
diretório de dados (`PCB_DATA_DIR`, padrão `data/`), modo 0600, escrita atômica; `PCB_TELEGRAM_TOKEN` /
`PCB_TELEGRAM_CHAT_ID` valem mais. Nunca no banco, em log, em erro ou em resposta. O aviso sai pelo notificador
(`app/notify.py`: `TelegramBot`, `Stdout`, `NoneNotifier`), escolhido por `notify_target`. O agendador interno
(`app/scheduler.py`) é uma thread do servidor que só roda com `scheduler_enabled`/`PCB_SCHEDULER=1`; a trava de
arquivo (`app/runlock.py`, `data/rodada.lock`) é a mesma do CLI, então nunca roda junto com um cron externo.

**Trava de escrita e configurações:** toda rota que grava passa pela trava de escrita (`write_guard`): `Host` em
`127.0.0.1:8787`, `localhost:8787` ou `PCB_ALLOWED_HOSTS` (senão 403); `Origin`, se vier, com host na mesma lista
(senão 403; sem Origin, como o `curl`, passa); corpo só `application/json` (415) e até 64 KB (413). GET não exige
nada disso. Configurações em `app/settings.py` (padrões, validação, `PCB_*`) e canais em `app/tg/channels.py`.

**Preço não entra pela rede.** A gravação é o comando local `python -m app.ingest lote.json`, que
escreve direto no banco. A API só lê e edita as builds. (Ver "Por que o preço não entra pela rede" abaixo.)

## Compatibilidade (lista de upgrades)

Regras simples, sem tentar ser perfeito:
- CPU: só o socket da placa do PC atual (no exemplo, **AM4**; não aceita AM5).
- RAM: só o tipo de memória da placa (no exemplo, **DDR4**).
- Placa-mãe: não entra nos upgrades (trocar placa é outra build).
- GPU, armazenamento, fonte, gabinete e cooler: sem filtro duro, só avisos (ex.: fonte com potência baixa).

Peça sem `specs` preenchido aparece com o aviso "compatibilidade não verificada", em vez de sumir.

## Servir o frontend

O backend serve os arquivos que o `vite build` gera (pasta `frontend/dist`). Um processo, uma porta.

## Rodar

- Local: escuta em `127.0.0.1:8787`.
- Sempre ligado: serviço systemd de usuário (modelo em `deploy/pc-builder.service`), com reinício automático.
  Com `loginctl enable-linger` ele sobe mesmo sem login gráfico.
- **Outro aparelho:** um proxy reverso local (ex.: `tailscale serve`) apontando pra `127.0.0.1:8787`. O app
  continua sem escutar na rede.

## Por que o preço não entra pela rede

Uma versão inicial gravava preço por `POST /api/snapshots`, protegido por **IP local + token**. Atrás do
`tailscale serve` isso não protege: o proxy roda no próprio PC, então **toda** requisição que ele repassa chega de
`127.0.0.1`, a trava de IP deixa de valer e sobra só o token, num arquivo na máquina.

Por isso a rota de gravação não existe. O preço entra só pelo comando local `app.ingest` (ou pela coleta), que
escreve direto no banco, sem rede. Qualquer POST/PUT/PATCH de preço dá 405, e o OpenAPI não lista nenhuma rota que
grave preço (há testes para isso, inclusive simulando o caminho do proxy local com cabeçalhos de identidade).

A edição das builds (`PUT /api/builds/...`) fica aberta a quem alcança o app, de propósito: é o próprio usuário
escolhendo peças, pelo PC ou por outro aparelho. Ela, como toda rota que grava, exige Host/Origin permitidos e JSON,
então outro site aberto no navegador não consegue gravar (CSRF) nem por um domínio que aponta para 127.0.0.1
(DNS rebinding).

## Testes

`cd backend && uv run python -B -m pytest`. Os testes usam o cliente de teste do FastAPI num banco temporário, sem
rede e sem Ollama de verdade.
