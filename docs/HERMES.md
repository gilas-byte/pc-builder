English: [docs/en/HERMES.md](en/HERMES.md)

# Hermes Agent: agendar o PC Builder com cron (opcional)

O PC Builder **não precisa** do Hermes Agent. Sem ele, o agendador interno (ou o Docker) já roda tudo. Este guia é para quem **já usa** o
[Hermes Agent](https://hermes-agent.nousresearch.com/docs) e prefere que o cron dele dispare as rodadas.

## Antes de começar: escolha UM modo

| Modo | Quem dispara | Onde configurar |
|---|---|---|
| Agendador interno / Docker | o próprio servidor (`app.serve`) | Configurações > Coleta > "Agendador interno" |
| **Hermes Agent (este guia)** | cron do Hermes Agent chamando os scripts de `deploy/` | Configurações > Coleta: **desligado** |

Os dois juntos não quebram nada (a trava `data/rodada.lock` impede rodada dupla), mas uma das duas só vai esperar e pular. Deixe o interno
**desligado** (`scheduler_enabled` falso, e sem `PCB_SCHEDULER=1` no ambiente).

Este guia vale para a **instalação local** (`cd backend && uv sync`). Hermes chamando um PC Builder dentro do Docker **não está coberto
nem foi testado**; no Docker use o agendador interno.

## O que o cron faz (sem gastar modelo)

Cada rodada é um script que imprime o aviso no stdout e **sempre sai com código 0**:

- `deploy/coleta-diaria.sh`: coleta das lojas, 1 ou 2 vezes por dia.
- `deploy/canais-telegram.sh`: lê os canais públicos do Telegram, a cada ~45 min.

Saída vazia = nada a avisar (o Hermes Agent fica em silêncio). Texto = o aviso, e o Hermes Agent entrega no destino do job. Se o script quebrar sem
explicar, ele imprime "🧯 ... quebrou" com o fim do log: crash nunca vira silêncio. Por isso o job usa `--no-agent`: **nenhum modelo de IA
roda no cron**, então não gasta cota nem tem custo.

## Passo a passo

Troque `/caminho/do/pc-builder` pelo caminho real da sua cópia do repositório.

1. **Destino do aviso.** Em Configurações > Notificação, escolha **"Saída do script (cron ou Hermes Agent)"** (`notify_target = stdout`).
   O Hermes Agent entrega a mensagem no chat dele (Telegram, Discord...). Se preferir o seu próprio bot, escolha "Bot do Telegram": o app manda
   pelo bot e a saída fica vazia (o job só dispara a rodada e nunca entrega mensagem).
2. **Scripts-ponte.** O Hermes Agent só aceita scripts dentro de `~/.hermes/scripts/`. Crie dois arquivos que repassam para os do projeto:

   `~/.hermes/scripts/pc_builder_coleta.sh`
   ```bash
   #!/usr/bin/env bash
   exec "/caminho/do/pc-builder/deploy/coleta-diaria.sh" "$@"
   ```

   `~/.hermes/scripts/pc_builder_canais.sh`
   ```bash
   #!/usr/bin/env bash
   exec "/caminho/do/pc-builder/deploy/canais-telegram.sh" "$@"
   ```

   Depois: `chmod +x ~/.hermes/scripts/pc_builder_*.sh`.
3. **Teste as pontes no terminal, antes de agendar.** A saída deve ser vazia (nada a avisar) ou uma mensagem; nunca um erro de shell:
   ```bash
   ~/.hermes/scripts/pc_builder_coleta.sh --dry-run          # lojas: mostra o que seria salvo, sem gravar
   ~/.hermes/scripts/pc_builder_canais.sh --channels OPromoFacil   # canais: não tem --dry-run, esta grava de verdade (1 canal)
   ```
   Teste com o destino do aviso em "Saída do script" (passo 1); com "Bot do Telegram" o app pode mandar mensagem de verdade.
4. **Crie os dois jobs.** Para rodar a coleta às 8h e às 21h e os canais a cada 45 min:
   ```bash
   hermes cron create "0 8,21 * * *" --name pc-builder-coleta --no-agent \
     --script pc_builder_coleta.sh --deliver telegram
   hermes cron create "every 45m" --name pc-builder-canais --no-agent \
     --script pc_builder_canais.sh --deliver telegram
   ```
   Ajuste `--deliver` para o destino que você quer (`origin`, `telegram`, `discord`, `platform:chat_id`).
5. **Dispare um agora para provar.** Como o job é `--no-agent`, rodar na hora é seguro:
   ```bash
   hermes cron list                 # pegue o id
   hermes cron run <id>
   ```
   O resultado volta como mensagem (ou silêncio, se não havia nada). Para conferir que gravou, abra o PC Builder e veja a data da última coleta.

## Armadilhas conhecidas

- **Caminho do `--script` é relativo a `~/.hermes/scripts/`.** Passe `pc_builder_coleta.sh`, não `scripts/pc_builder_coleta.sh` (o job falha
  sem avisar).
- **"A cada 45 minutos" é `every 45m`.** `*/45 * * * *` dispara em :00 e :45 (intervalos de 45 e 15 min).
- **O script precisa do `uv` no PATH do cron.** Se o cron não achar, defina `PCB_UV=/caminho/do/uv` no topo do script-ponte
  (`export PCB_UV=...`).
- **Coleta de lojas à noite** pula a Terabyte (ela bloqueou a rodada da noite); isso já está dentro de `coleta-diaria.sh` (depois das 12h
  só `kabum,amazon`). Mude o script se a sua realidade for outra.
- **Pausa e jogo.** `touch ~/.pc-builder-pause` pausa os canais (apague o arquivo para voltar). Com o **Modo jogo** ligado (Configurações, ou
  `PCB_GAME_MODE=1`) as rodadas pulam enquanto um jogo estiver aberto.
- **Segredo.** O token do bot nunca passa pelo Hermes Agent: fica no `secrets.env` do PC Builder. Não cole token em prompt de cron.
- Depois de mudar o fuso do Hermes Agent (`hermes config set timezone ...`), atualize os jobs com `hermes cron edit` para os horários baterem
  com o relógio.

## Prompt pronto para o seu Hermes Agent

Se você quer que o próprio agente monte isso, cole o texto abaixo numa conversa com ele (troque o caminho). Ele só cria arquivos em
`~/.hermes/scripts/` e jobs de cron; peça para ele **confirmar com você antes** de criar os jobs.

```text
Quero agendar o PC Builder (instalação local em /caminho/do/pc-builder) pelo cron do Hermes Agent, sem gastar modelo.
Leia /caminho/do/pc-builder/docs/HERMES.md e siga o "Passo a passo". Regras:
1. Antes de tudo, confira em Configurações do PC Builder que o agendador interno está desligado e me diga o que achou.
2. Crie só os dois scripts-ponte em ~/.hermes/scripts/ (pc_builder_coleta.sh e pc_builder_canais.sh), com chmod +x.
3. Teste cada ponte no terminal (--dry-run na coleta, --channels OPromoFacil nos canais) e me mostre a saída real. Não invente saída.
4. Me pergunte o destino (--deliver) e os horários, e só crie os jobs depois do meu ok. Use sempre --no-agent.
5. Rode "hermes cron run" em um job e me conte o que voltou. Não mexa em nada fora de ~/.hermes/scripts/ e nos jobs de cron.
```

## O que não foi verificado

- Este guia foi escrito a partir de uma instalação real, que usa exatamente esse padrão (scripts-ponte + `--no-agent`). Não foi
  testado numa máquina limpa de outra pessoa nem em outras versões do Hermes Agent; se um comando de `hermes cron` mudar, vale mais a
  [documentação do Hermes Agent](https://hermes-agent.nousresearch.com/docs).
- Hermes Agent com o PC Builder no Docker: não coberto.
