English: [docs/en/04-coleta-de-precos.md](en/04-coleta-de-precos.md)

# Coleta de preços (agendada)

**Objetivo:** todo dia a coleta pesquisa os preços nas lojas e grava no banco. 

## Como a coleta funciona

1. **Lista de vigiados:** o banco tem os links acompanhados (tabela `listings`). Começa vazio. A lista
   inicial (`backend/watchlist.json`, editável) é focada em custo-benefício pra AM4 e GPU.
2. **Coleta:** pra cada link, abro a página e leio o preço à vista, o parcelado e o estoque.
3. **Gravação:** comando local `uv run python -m app.ingest lote.json` (sem rede; a API não grava preço).
4. **Descoberta:** além dos vigiados, uma busca por categoria em cada loja pra achar promoção nova.
   O que for achado entra como sugestão, não direto na lista.

## Lojas testadas

Cada loja foi testada antes de entrar na coleta:

Teste com 1 busca por loja ("rtx 4060"), `httpx` com User-Agent de navegador, pausa de 3 s.

| loja | resultado | como | observação |
|---|---|---|---|
| KaBuM! | **funciona** | `__NEXT_DATA__` (JSON do Next.js) | `price`, `priceWithDiscount` (à vista), `image`, `sellerName`, `code`. Busca traz notebook junto: filtrar por `category` |
| Terabyte | **funciona** | HTML: `data-tss-price`, `data-tss-estoque`, `.product-item__new-price` ("à vista no Pix") | tem reCAPTCHA na página, mas só no checkout/form; a listagem veio inteira. Títulos com "Open Box" = usado/aberto |
| Amazon | **funciona** | HTML: `data-asin`, `a-offscreen`, `s-image` | 48 resultados. Tem patrocinado misturado e vendedor de terceiro; precisa filtrar |
| Pichau | **bloqueia** | HTTP 403 (proteção anti-bot) | sem navegador não dá |
| Mercado Livre | **bloqueia** | API pública de busca: 403 (o ML fechou a busca aberta). Site: redireciona pra `account-verification` | os serviços que "resolvem" isso contornam Cloudflare: fora da regra |
| Shopee | **bloqueia** | API: erro 90309999 (exige login). Site: página de verificação | idem |

Navegador de verdade (automação de navegador): não testado. Mesmo com navegador, página de verificação/captcha = loja fica de fora (regra do projeto).

Ordem de tentativa, do mais leve ao mais pesado:
1. Dados estruturados da página (JSON-LD com `offers.price`, que muita loja coloca pra SEO).
2. HTML com `httpx`.
3. Navegador de verdade (automação de navegador).

**Não contorna bloqueio.** Captcha, proteção anti-bot ou exigência de login: a loja fica de fora e a tela
avisa. Ritmo baixo: uma página por vez, com pausa, uma vez por dia.

## O agendamento

- Um agendador externo (cron, timer do systemd, agente) roda `deploy/coleta-diaria.sh`. Sem modelo de IA
  na rodada: o script faz tudo.
- Aviso: só quando aparecer promoção ou quando a coleta falhar. Dia normal, silêncio (saída vazia).

## O que o app não faz

Nada de comprar, carrinho ou login nas lojas. O app só lê preço.

## Lojas e anúncios aceitos

- **Lojas coletadas:** KaBuM!, Terabyte e Amazon. Pichau, Mercado Livre e Shopee bloqueiam robô: aparecem na tela como "fora (bloqueiam robô)" (`stores.status_note`).
- **Usado pode** (não precisa ser novo). A tela guarda e mostra a `condition` (novo/usado) por anúncio; a promoção é calculada separada por condição (usado não puxa a mediana do novo pra baixo).
- **Vendedor:** aceita **loja oficial OU vendedor com boa reputação**. O corte de reputação é definido por marketplace ao testar a fonte.
- Cada fonte é testada antes de entrar; não se contorna anti-bot, e fonte que bloquear fica de fora.

## Detalhes do coletor

- `backend/watchlist.json`: 24 peças vigiadas (proposta inicial, editável). `must`/`exclude` = palavras inteiras do título;
  piso de preço por categoria e regra anti-combo/PC montado descartam isca. `alert_below` define alvos de preço por peça
  (ex.: GPU até R$ 1.000, HD 2TB até R$ 350).
- `app/collect/stores.py`: parser por loja. KaBuM! = `__NEXT_DATA__` (só vendido pelo KaBuM! ou loja oficial do fabricante;
  oferta relâmpago só dentro da janela). Terabyte = atributos `data-tss-*` (preço com PONTO decimal!). Amazon = busca já
  filtrada "vendido pela Amazon" (`rh=p_6:A1ZZFT5FULY4LN`), pula patrocinado; captcha → `StoreBlocked`.
- Usado: título com Open Box/usado/recondicionado/seminovo/vitrine → `condition='used'`. Cada anúncio tem histórico
  próprio, então a promoção do usado é calculada só com ele.
- Até 3 anúncios por peça por loja, **com estoque primeiro** (senão indisponíveis baratos tomam as 3 vagas).
- `uv run python -m app.collect [--dry-run|--notify] [--only X] [--stores a,b]`. Uma busca por vez, 4 s de pausa
  (~6 min no total). Loja que bloqueia: 1 tentativa e sai; as outras seguem.
- Aviso: promoção (≥10% abaixo da mediana de 30 dias, ≥7 dias de histórico) ou preço abaixo do alvo, 1x por semana por
  anúncio (`alerts_sent`); falha de loja; crash. Dia normal = silêncio.
- `deploy/coleta-diaria.sh`: script pro agendador (a saída vira a mensagem). Crash (código 3) **nunca** fica mudo.
- Agendamento sugerido: **08:00 e 21:00** (`0 8,21 * * *`). A segunda coleta do dia substitui a primeira (1 registro por
  anúncio por dia, índice único listing+dia), então o histórico não duplica; o aviso de promoção continua 1x por semana
  por anúncio.

**Limites conhecidos**
- Peça sem estoque nas 3 lojas, ou vendida só por terceiros (que são filtrados), não aparece. Anúncio usado de
  marketplace que bloqueia robô (Mercado Livre, Shopee) a coleta não consegue.
- Preço da Amazon não tem parcelado na busca (`price_installment` vazio).

**Testes:** `cd backend && uv run python -B -m pytest`, com páginas reais salvas em `tests/fixtures/` (sem rede).
