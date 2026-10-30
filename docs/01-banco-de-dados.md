English: [docs/en/01-banco-de-dados.md](en/01-banco-de-dados.md)

# Banco de dados

**Objetivo:** guardar peças, lojas, ofertas e o histórico de preço, de um jeito que o backend consiga
responder rápido "qual o menor preço de hoje" e "esse preço é promoção mesmo?".

**Tecnologia:** SQLite, arquivo `data/pcbuilder.db`. Acesso pelo módulo `sqlite3` do próprio Python,
sem ORM, pra ficar simples de ler.

## Tabelas

### `stores` — lojas
| coluna | tipo | exemplo |
|---|---|---|
| id | INTEGER PK | 1 |
| slug | TEXT UNIQUE | `kabum` |
| name | TEXT | `KaBuM!` |
| base_url | TEXT | `https://www.kabum.com.br` |
| active | INTEGER (0/1) | 1 |

Começa com 3 linhas: Kabum, Pichau e Terabyte.

### `parts` — a peça em si (independente de loja)
| coluna | tipo | exemplo |
|---|---|---|
| id | INTEGER PK | 7 |
| category | TEXT | `gpu` |
| brand | TEXT | `NVIDIA` |
| model | TEXT | `GeForce RTX 4060 8GB` |
| specs | TEXT (JSON) | `{"socket": "AM4", "memory_type": "DDR4"}` |
| created_at | TEXT (ISO) | `2026-10-09T09:00:00` |

Categorias fixas: `cpu`, `motherboard`, `ram`, `gpu`, `storage`, `psu`, `case`, `cooler`.
O `specs` guarda o que serve pra checar compatibilidade (socket, tipo de memória, potência, formato).

### `listings` — a peça numa loja específica (o link)
| coluna | tipo | exemplo |
|---|---|---|
| id | INTEGER PK | 12 |
| part_id | FK → parts | 7 |
| store_id | FK → stores | 1 |
| url | TEXT UNIQUE | link do produto |
| title | TEXT | título como a loja escreve |
| active | INTEGER | 1 |

Uma peça pode ter um link em cada loja. É aqui que mora o link que o usuário clica.

### `price_snapshots` — histórico (uma linha por coleta)
| coluna | tipo | observação |
|---|---|---|
| id | INTEGER PK | |
| listing_id | FK → listings | |
| price_cash | INTEGER | **à vista/PIX, em centavos** |
| price_installment | INTEGER | parcelado total, em centavos, pode ser nulo |
| in_stock | INTEGER | 1 em estoque, 0 esgotado |
| collected_at | TEXT (ISO) | quando coletei |

Preço em **centavos inteiros** pra não ter erro de arredondamento (R$ 1.299,90 vira `129990`).

### `builds` e `build_items` — a build completa e a lista de upgrades
| tabela | colunas |
|---|---|
| `builds` | id, name, kind (`full` ou `upgrade`), created_at |
| `build_items` | build_id, category, part_id (pode ser nulo enquanto não escolheu) |

Começa com 2 builds: "Build completa" (`full`) e "Upgrades do PC atual" (`upgrade`).

## Consultas que o backend vai precisar (viram views ou funções)

1. **Preço atual por link:** o snapshot mais recente de cada `listing`.
2. **Melhor preço por peça:** o menor `price_cash` atual entre as lojas, só com `in_stock = 1`.
3. **Histórico:** todos os snapshots de uma peça, por loja, pra desenhar o gráfico.
4. **Detector de promoção:** o preço de hoje comparado com a **mediana dos últimos 30 dias**.
   Promoção = hoje pelo menos 10% abaixo da mediana. O 10% fica numa configuração, fácil de mudar.
   Com menos de 7 dias de histórico, o app diz "histórico curto" em vez de chamar de promoção.
5. **Total da build:** soma do melhor preço de cada item escolhido.

## Arquivos

- `backend/app/db/schema.sql` — criação das tabelas, índices e as views.
- `backend/app/db/database.py` — abrir conexão, criar o banco se não existir, rodar o schema.
- `backend/app/db/seed.py` — inserir as 3 lojas e as 2 builds vazias.
- `backend/tests/test_db.py` — testes.

## Regras de projeto

- Coletar duas vezes no mesmo dia **substitui** o preço do dia em vez de duplicar (índice único por link e dia). Rodar a coleta de novo não bagunça o histórico.
- A mediana usa só os dias **anteriores** ao de hoje. Se o preço de hoje entrasse na conta, uma queda grande diminuiria a própria mediana.
- A configuração de promoção (10%, 30 dias, mínimo de 7 dias) fica na tabela `settings`, não no código.
- `data/` fica fora do git.
- Testes: `cd backend && uv run python -B -m pytest` (os do banco estão em `backend/tests/test_db.py`).
