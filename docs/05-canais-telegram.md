English: [docs/en/05-canais-telegram.md](en/05-canais-telegram.md)

# Promoções dos canais do Telegram

Agendador a cada 45 min → `deploy/canais-telegram.sh` →
`python -m app.tg --notify`.
Tela: menu **Canais** (`#/canais`).
Ollama local (opcional; endereço nas Configurações, padrão 127.0.0.1:11434). Sem Ollama, classificador por regras
(seção "Classificador por regras e modos" abaixo).

## Por quê

As lojas que bloqueiam robô (Pichau, Mercado Livre, Shopee) aparecem o tempo todo nos canais públicos de promoção. Ler esses canais traz esses preços sem contornar bloqueio nenhum e enche o banco de referências.

## Decisões de projeto

1. **Canais:** os 9 públicos que têm prévia na web (lista abaixo). Os 2 do Canaltech ficam de fora: são
   públicos, mas a prévia web está desligada, então só dariam com login de uma conta (fora do escopo).
2. **Sem limpeza de histórico.** Nem canais nem lojas apagam nada. Conta feita: ~1.100 posts/dia nos 9 canais
   = ~400 mil/ano, ~240 MB/ano se guardar tudo; SQLite aguenta tranquilo.
3. **Escopo:** apanhador de promoções de **tecnologia** (peça de PC, monitor, periférico, notebook/MacBook,
   áudio, console...). Casa, moda, comida etc. não são guardados. MacBook entra.
4. **Leitura a cada 45 min**, sem modelo de IA remoto na rodada (o script faz tudo).
5. **Aviso no Telegram** quando a oferta for, para o **mesmo produto**:
   - **7% ou mais abaixo** da referência, **ou**
   - **o menor preço já visto** (mesmo com menos de 7%).
   Referência = menor preço anterior do mesmo produto, juntando canais e as lojas do PC Builder.
   Exige pelo menos 3 aparições anteriores (sem isso não há "menor já visto" confiável). 1 aviso por produto/dia.
6. **IA local** (Ollama na própria máquina, modelo pequeno tipo `qwen2.5:3b`) só para classificar o **tipo** do que o
   script não souber. A IA **nunca** decide preço nem "mesmo produto": isso é regra, testada.

## Canais

| Canal | Posts/dia (medido) | Observação |
|---|---|---|
| OPromoFacil | ~530 | de tudo; muita Shopee |
| descontoemgames | ~160 | quase só jogo/console |
| grupo_promocoes | ~115 | de tudo, preço "por R$ X no pix" |
| EconomizandocomJP | ~70 | bastante peça/notebook, "POR: 279" sem R$ |
| especialistaemti | ~60 | notebooks |
| ToptechPROMO | ~55 | "💸 R$ 229" |
| gpcrpromo | ~55 | hardware |
| escolhasegura | ~40 | de tudo |
| lipeofertas | ~12 | notebook/tech, "De/Por" |

Amostra real (1.077 posts, 1.011 com preço): Mercado Livre 383, Shopee 291, Amazon 267, Magalu 32.
Peças de PC/monitor ~180, tech não-peça ~300 (palavra-chave), resto ~530 (casa/moda + tech que o script não
pega → IA local).

## Como vai funcionar

- **Leitura:** página pública `t.me/s/<canal>`, de trás pra frente até a última mensagem já vista (máx. ~10
  páginas por canal por rodada, pausa entre páginas). Canal que falhar não para os outros; falha vira aviso.
- **Extração:** preço "por"/primeiro R$ que não é o "De:" nem cupom; loja pelo domínio do link; o "De:" do canal
  é ignorado (inflado).
- **Tipo:** script (peça de PC + palavras-chave de tech); dúvida → IA local; sem Ollama no ar, a dúvida fica
  "sem tipo" e não é perdida (reclassifica depois).
- **Mesmo produto:** chave por categoria (GPU = chip + VRAM; CPU = modelo; RAM = DDR + total + MHz; SSD = tipo +
  capacidade + marca/linha; fonte = marca + W + selo; placa-mãe = marca + chipset; cooler/gabinete = código;
  monitor = marca + tamanho + resolução + Hz; MacBook = chip + RAM + SSD). Sem chave = mostra na tela, sem aviso.
- **Banco:** tabelas novas `tg_channels`, `tg_offers` (canal + id da mensagem único), `tg_alerts_sent`.
  Não mexe nas tabelas das lojas.
- **Tela:** seção "Promoções" no PC Builder (filtro por tipo, loja, canal; selo do desconto). Build/upgrade igual.

## Classificador de tipo por modelos locais

Sem fine-tuning: o "treino" é prompt + exemplos, medido contra posts reais rotulados à mão (medição feita antes da
publicação; o banco de provas não faz parte deste repositório). O melhor prompt foi o de 2 passos ("é tecnologia?"
e depois "qual tipo?"), com eletrodoméstico, ar-condicionado e ferramenta = não, headset = áudio e jogo ≠ cupom.

Verificação cruzada com 3 modelos (`qwen2.5:3b`, `llama3.2:3b`, `gemma3:4b`) num conjunto guardado: **unânime em
84% dos posts, com 98,4% de acerto**; maioria 2/3 = 92,5%. Velocidade por post: GPU qwen 0,15 s, gemma 0,47 s,
llama 1,7 s; CPU (sem placa) qwen ~2 s, gemma ~7 s. Erros que sobram: carregador de bateria de carro, LEGO, pote
de cozinha, lava e seca "Inverter" (marca/palavra de eletrônico em produto que não é), e tablet/celular
confundido com notebook.

## Implementação

- Código: `backend/app/tg/` — `parse.py` (página, preço, loja), `classify.py` (título, peça de PC, chave do produto),
  `vote.py` (3 modelos), `run.py` (rodada, referência, aviso). API só leitura: `/api/tg/offers`, `/api/tg/meta`.
- **Votação:** um modelo por vez na placa (os 3 juntos não cabem nos 8 GB: o 3º caía pra CPU) e cada um é
  descarregado no fim (`keep_alive 0`). Placa livre entre rodadas. Custo medido: ~2 s pra carregar cada modelo +
  qwen 0,12 / llama 0,15 / gemma 0,39 s por post. Rodada típica (10–40 posts novos): 15–40 s.
- **Mesmo produto só com chave:** script e votação precisam concordar no tipo (anúncio de notebook com "RTX" nunca
  vira GPU). Variante de cooler/gabinete conta (AK400 ≠ AK400 Zero Dark ≠ AK400 WH ≠ AK400 RD: bug real achado na
  1ª rodada, a mediana misturava R$150 e R$237). Monitor usa o código do modelo quando existe (24GS60F).
- **Rede:** t.me derruba conexão às vezes → 2 novas tentativas com pausa (5 s, 10 s). Canal só vira aviso depois
  de 3 rodadas seguidas falhando. Ollama fora → guarda sem tipo e avisa.

## Peças dos canais = peças de verdade

Todas as peças, de qualquer fonte, aparecem juntas; só muda a cor do cartão (azul fraco = Telegram), e a build
puxa as peças dos canais.
- `app/tg/sync.py` (roda no fim de toda rodada e no `reclassify`): loja `canal` ("Canais do Telegram");
  cada post de peça = 1 anúncio (URL = link do post, vendedor = "Shopee via @canal", preço na data do post).
  Mesma chave de produto de uma peça das lojas → entra nela e concorre pelo menor preço; senão → peça nova
  `parts.source = 'canal'` agrupada por `tg_key`. Specs pra compatibilidade saem do texto (socket pelo chipset/
  geração do Ryzen/Core, DDR, mATX/ATX, watts, sockets do cooler); o que faltar = "não verificado" na build.
- Post com mais de 14 dias ganha preço "sem estoque" (some da build, fica riscado). Post que deixou de ser peça sai;
  peça de canal sem anúncio some.
- Referência de preço do aviso ignora a loja `canal` (os posts já entram por `tg_offers`, senão contaria 2x).
- Tela: cartão `.is-tg` (borda azul fraca) quando a peça é do canal OU o menor preço atual é do canal;
  promoção (amarelo) ganha do azul. Botão "Ver no canal". Mesmo esquema nas opções da build e no detalhe.
- Post de notebook "🔥 RYZEN 5 COM BOM PREÇO" virava processador, então o título pula a chamada e a votação lê
  título + 1ª linha da ficha (`vote_text`).

## Classificador por regras e modos

Quem instala sem Ollama também recebe o tipo das ofertas: `backend/app/tg/rules.py` (`rules_kind`) usa as mesmas
regras de `classify.py` e devolve peça/monitor, "não é peça" ou None (dúvida). Na dúvida nunca vira peça. Só
peça com ficha completa (com chave do produto) entra na comparação de preço e no aviso.

| Modo (`classifier`, `PCB_CLASSIFIER`) | O que faz |
|---|---|
| `auto` (padrão) | Testa o Ollama (`/api/version`, 3 s). Responde → votação. Não responde ou cai no meio → regras e **um** aviso por queda ("Ollama não respondeu; usando regras. Quando voltar, as ofertas serão reavaliadas"). Quando volta, revota as de origem `rules` e as sem tipo. |
| `rules` | Só regras. Nunca fala com o Ollama. |
| `ollama` | Só a votação. Fora do ar → guarda sem tipo (como antes) e o erro sai no aviso; nunca usa regras. |

A votação aceita de 1 a 3 modelos: 1 decide sozinho, 2 têm de concordar, 3 = maioria (os 3 padrão dão exatamente
o mesmo resultado de antes; teste de regressão). Cada oferta guarda a origem do tipo em `tg_offers.kind_source`
(`ollama` | `rules`). "Não é peça" das regras não aparece na aba Canais (pode ser comida, roupa: as regras não
separam tecnologia do resto).

Acurácia das regras em ofertas reais de canais públicos rotuladas à mão (medição feita antes da publicação; o
número mostrado na tela vem de `backend/app/tg/rules_metrics.json`):

| Banco | Acertos | Dúvida | Peça inventada |
|---|---|---|---|
| ajuste (148) | 148/148 = 100% | 0 | 0 |
| guardado (147) | 146/147 = 99,3% | 1 | 0 |
| **geral** | **294/295 = 99,7%** | 1 | 0 |

Por tipo (geral): placa de vídeo 2/2, SSD/HD 3/3, gabinete 3/3, cooler 4/4, monitor 26/26, não é peça 256/257
(o erro: "MEMÓRIA RAM DDR5 8GB 4800MHZ" sem sinal de desktop, que a regra deixa em dúvida). Leia com cuidado: os
bancos têm só 38 peças/monitores, nenhum processador, placa-mãe, RAM de desktop ou fonte, e as regras foram
ajustadas olhando os erros dos dois conjuntos (o guardado deixou de ser prova cega). Antes dos ajustes: 289/295 =
98,0% com 1 peça inventada (notebook "HP 200 G2i ... 256GB SSD" virava SSD).

## Testes

Parser com páginas reais salvas (`backend/tests/fixtures/`), preço nos formatos dos 9 canais, filtro com os enganos
reais (liquidificador, celular "com processador", suporte de monitor, PC montado), chave de produto, regra 7% /
menor já visto, mínimo de 3 aparições, releitura sem duplicar, aviso 1x por dia, canal fora do ar e Ollama fora do ar.
Rodar: `cd backend && uv run python -B -m pytest`.
