English: [docs/en/03-frontend.md](en/03-frontend.md)

# Frontend (React)

**Objetivo:** a tela onde o usuário vê preços, promoções e as builds.

**Tecnologia:** React + Vite, JavaScript puro (sem TypeScript, pra ficar simples de mexer). Gráficos
de histórico em SVG feito à mão (sem biblioteca de gráficos).

## Decisões de projeto

- **Navegação:** barra lateral fixa à esquerda (no celular vira barra embaixo).
- **Build completa:** o app monta sozinho a mais barata **compatível** e o usuário troca peça por peça.
  A lista de upgrades continua manual (a "mais barata" ali seria pior que a peça que a pessoa já tem).
- **Até a coleta existir:** dados de exemplo, com faixa **EXEMPLO** sempre visível. Os exemplos ficam num
  banco separado (`data/demo.db`), gerado a cada partida do serviço. Assim o código de verdade (promoção,
  montagem, compatibilidade) roda em cima deles. Quando o banco real tiver peças, o exemplo some sozinho.
- **Peças em cartões grandes com imagem e efeito de luz** em volta da imagem.
- **Extras:** funcionar bem no celular e **favoritar peça**.

### Suporte no backend

- `parts.image_url` (só `https://`) e campo `image_url` opcional no lote do `app.ingest`. A imagem vem da
  loja na coleta. Sem imagem (inclusive nos exemplos, pra não inventar foto), aparece um ícone da categoria.
- Tabela `favorites` e rotas `GET /api/favorites`, `PUT`/`DELETE /api/favorites/{id}`.
- Montagem automática (`POST /api/builds/{id}/auto`) e opções por categoria com compatibilidade
  (`GET /api/builds/{id}/options/{categoria}`).
- Regras de compatibilidade da build completa: socket CPU/placa, tipo de RAM/placa, formato placa/gabinete,
  socket do cooler, potência da fonte vs. a recomendada pela GPU.

## Visual

- **Fundo preto** (`#0a0a0a`), cartões em cinza muito escuro (`#141414`), bordas `#262626`.
- **Amarelo** só nos detalhes: `#ffea00`.
  Vai em preço em promoção, botão principal, item selecionado e links.
- Texto principal `#f5f5f5`, secundário `#a3a3a3`. Contraste conferido pra ser legível.
- Fonte Inter, com fallback pra fonte padrão.
- Sem modo claro.

## Telas

1. **Promoções** (tela inicial): peças com preço abaixo da mediana dos 30 dias, a maior queda primeiro.
   Cada cartão mostra o preço à vista, de quanto caiu, a loja e o botão "ver na loja" (link).
2. **Peças:** lista por categoria (abas: CPU, Placa-mãe, RAM, GPU...). Busca por nome.
   Cada linha: modelo, melhor preço, loja, estoque, link, e o mini-gráfico de 30 dias.
3. **Detalhe da peça:** preço em cada loja lado a lado, histórico completo e os links.
4. **Builds:** duas abas, "Build completa" e "Upgrades do PC atual". Em cada categoria, a peça escolhida
   e o preço. Total no topo. Na de upgrades, o aviso de compatibilidade.

5. **Configurações** (`#/config`, engrenagem na navegação; no celular o rótulo é "Ajustes"):
   Canais do Telegram (liga/desliga, remover com confirmação, adicionar com a checagem da prévia e o erro da API),
   Lojas, Coleta (frequência), Meu PC (selects de socket, memória, formato e RAM; texto curto pra CPU, placa e GPU),
   Faixa de preço, Modo jogo, Notificação, IA local (abaixo) e
   Idioma. Cada seção mostra a origem (padrão / salvo / variável de ambiente, que bloqueia o campo), tem
   "Salvar" e "Restaurar padrão" e mostra a mensagem de erro de cada campo vinda da API. Alvos de toque de 44 px.
   Promoções e Peças avisam a faixa de preço e as lojas desligadas, com link pra cá.

   **Aviso e agendador:**
   - **Notificação:** destino (Bot do Telegram / Saída do script (cron ou Hermes Agent) / Nenhum) e a caixa "Bot do
     Telegram": tutorial em 4 passos (@BotFather e `/newbot`; copiar o token; `/start` no seu bot; "Encontrar meu
     chat"), campo de token `type=password` **sem estado do React** (só o `ref`; limpo depois de salvar, inclusive
     em erro; nunca em atributo nem no console), estado "configurado (termina em …1234)" com "Trocar" e "Remover"
     (com confirmação), "Encontrar meu chat" (lista para escolher; vazio explica o `/start`), chat id à mão
     (opcional, dentro de um `<details>`), "Enviar mensagem de teste" com o retorno. Token de variável de ambiente:
     sem campo, com aviso.
   - **Coleta:** caixa "Agendador interno" com interruptor que salva na hora (`scheduler_enabled`), o aviso "deixe
     desligado se já usa cron externo (ou Hermes Agent), para não rodar em dobro", situação (ligado/desligado/rodando,
     última rodada e se deu certo, próxima, erro) e "Rodar agora". `PCB_SCHEDULER` bloqueia o interruptor.
   - **Modo jogo:** diz "Indisponível no Docker" quando `/api/scheduler` responde `game_mode_available: false`.

   **IA local** (`src/pages/OllamaSection.jsx`), seção "IA local (Ollama)":
   - Modo em 3 opções com uma linha de explicação (Automático / Só regras / Só Ollama), salvo na hora;
     `PCB_CLASSIFIER` bloqueia.
   - "Sem Ollama instalado? O app usa as regras, que acertam X% nos exemplos": X vem de `GET /api/classifier`
     (nunca do código); sem métrica, a frase sai sem número.
   - Estado: ponto verde/vermelho + "Ollama responde"/"não responde", o motivo, quem classifica agora, modelo
     escolhido que falta, aviso de "outra máquina" e a contagem de ofertas por origem.
   - Endereço com "Testar" (`?url=`, não grava) e "Salvar"; modelos instalados com tamanho/quantização, de 1 a 3
     (com 3 marcados os outros ficam desligados), aviso de memória de vídeo/RAM; estados vazios ("nenhum modelo
     instalado", "não deu para listar").
   - "Baixar outro modelo" (sugestões no `datalist`) com barra `role=progressbar` + `aria-valuenow` e "Cancelar";
     erro do download aparece com o motivo. Polling a cada 1 s **só** com download em andamento; para no fim e ao
     sair da página.
   - Teste rápido: cola um título (até 2000 caracteres), vê o tipo, de onde veio e o porquê das regras.

Rodapé fixo: "Última coleta: dd/mm às hh:mm", pra saber se os preços estão velhos.

## Links

Todo preço tem link pra página da loja, abrindo em nova aba (`target="_blank"` com `rel="noopener noreferrer"`).
O nome da loja aparece junto, pra saber onde vai cair.

## Como é hoje

- **Abrir:** `http://127.0.0.1:8787` no PC; de outro aparelho, pelo endereço do proxy local (ex.: `tailscale serve`).
- **Telas:** Promoções (início), Peças (abas por categoria + busca), Favoritos, detalhe da peça (preço por loja,
  histórico de 90 dias por loja em SVG), Builds (completa e upgrades). Roteamento por hash (`#/pecas/12`),
  então F5 e voltar funcionam sem biblioteca de rotas.
- **Cartões grandes** com imagem e halo de luz amarela que gira no hover (e sempre, em promoção). Sem foto,
  aparece o ícone da categoria com a mesma luz. `prefers-reduced-motion` desliga a animação.
- **Celular:** abaixo de 820 px a barra lateral vira barra de baixo; abas roláveis; cartões em 1 coluna.
- **Build completa:** nasce montada (a mais barata compatível, testando cada placa-mãe como plataforma).
  Botão "Montar a mais barata" refaz. "Trocar" abre a lista com o aviso de compatibilidade de cada opção;
  incompatível vai pro fim, mas dá pra escolher (o aviso fica vermelho no cartão).
- **Modo exemplo:** `data/demo.db` (20 peças, 30 dias, 4 promoções), recriado a cada partida do serviço.
  Links de exemplo apontam pra BUSCA da loja. Faixa amarela listrada "EXEMPLO" no topo.
- Gráficos em SVG na mão: JS final 245 kB (77 kB gzip).

## Testes e atualização

- Frontend: `cd frontend && npx vitest run`; build sem erro nem aviso: `npm run build`.
- Os testes cobrem a renderização das telas com dados falsos (inclusive lista vazia e erro de API), `noopener` em todo
  link externo e o servidor de estáticos contra path traversal.
- O visual precisa de olho humano: os testes não conferem aparência.
- Depois de mexer no frontend: `cd frontend && npm run build && systemctl --user restart pc-builder`.
