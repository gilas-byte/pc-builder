Português: [../HERMES.md](../HERMES.md)

# Hermes Agent: scheduling PC Builder with cron (optional)

PC Builder does **not** need Hermes Agent. Without it, the internal scheduler (or Docker) already runs everything. This guide is for people who
**already use** [Hermes Agent](https://hermes-agent.nousresearch.com/docs) and prefer its cron to trigger the rounds.

## Before you start: pick ONE mode

| Mode | Who triggers it | Where to configure |
|---|---|---|
| Internal scheduler / Docker | the server itself (`app.serve`) | Settings > Coleta > "Agendador interno" |
| **Hermes Agent (this guide)** | Hermes cron calling the scripts in `deploy/` | Settings > Coleta: **off** |

Running both does not break anything (the `data/rodada.lock` lock prevents a double round), but one of them will just wait and skip. Keep the
internal one **off** (`scheduler_enabled` false, and no `PCB_SCHEDULER=1` in the environment).

This guide covers the **local install** (`cd backend && uv sync`). Hermes calling a PC Builder inside Docker is **not covered and was not
tested**; with Docker, use the internal scheduler.

## What the cron does (without spending a model)

Each round is a script that prints the alert to stdout and **always exits with code 0**:

- `deploy/coleta-diaria.sh`: store collection, once or twice a day.
- `deploy/canais-telegram.sh`: reads the public Telegram channels, every ~45 min.

Empty output = nothing to report (Hermes stays silent). Text = the alert, and Hermes delivers it to the job's target. If a script breaks without
explaining, it prints "🧯 ... quebrou" with the end of the log: a crash never turns into silence. That is why the job uses `--no-agent`: **no AI
model runs in the cron**, so it costs no quota and no money.

## Step by step

Replace `/path/to/pc-builder` with the real path of your copy of the repository.

1. **Alert target.** In Settings > Notificação, choose **"Saída do script (cron ou Hermes Agent)"** (`notify_target = stdout`). Hermes delivers
   the message to its chat (Telegram, Discord...). If you prefer your own bot, choose "Bot do Telegram": the app sends it through the bot and
   the output stays empty (the job only triggers the round and never delivers a message).
2. **Bridge scripts.** Hermes only accepts scripts inside `~/.hermes/scripts/`. Create two files that forward to the project's:

   `~/.hermes/scripts/pc_builder_coleta.sh`
   ```bash
   #!/usr/bin/env bash
   exec "/path/to/pc-builder/deploy/coleta-diaria.sh" "$@"
   ```

   `~/.hermes/scripts/pc_builder_canais.sh`
   ```bash
   #!/usr/bin/env bash
   exec "/path/to/pc-builder/deploy/canais-telegram.sh" "$@"
   ```

   Then: `chmod +x ~/.hermes/scripts/pc_builder_*.sh`.
3. **Test the bridges in the terminal, before scheduling.** The output must be empty (nothing to report) or a message; never a shell error:
   ```bash
   ~/.hermes/scripts/pc_builder_coleta.sh --dry-run          # stores: shows what would be saved, without writing
   ~/.hermes/scripts/pc_builder_canais.sh --channels OPromoFacil   # channels: has no --dry-run, this one really writes (1 channel)
   ```
   Test with the alert target on "Saída do script" (step 1); with "Bot do Telegram" the app may send a real message.
4. **Create the two jobs.** To run the collection at 8am and 9pm and the channels every 45 min:
   ```bash
   hermes cron create "0 8,21 * * *" --name pc-builder-coleta --no-agent \
     --script pc_builder_coleta.sh --deliver telegram
   hermes cron create "every 45m" --name pc-builder-canais --no-agent \
     --script pc_builder_canais.sh --deliver telegram
   ```
   Adjust `--deliver` to the target you want (`origin`, `telegram`, `discord`, `platform:chat_id`).
5. **Fire one now to prove it.** Since the job is `--no-agent`, running it right away is safe:
   ```bash
   hermes cron list                 # get the id
   hermes cron run <id>
   ```
   The result comes back as a message (or silence, if there was nothing). To check that it wrote, open PC Builder and look at the date of the last
   collection.

## Known pitfalls

- **The `--script` path is relative to `~/.hermes/scripts/`.** Pass `pc_builder_coleta.sh`, not `scripts/pc_builder_coleta.sh` (the job fails
  without warning).
- **"Every 45 minutes" is `every 45m`.** `*/45 * * * *` fires at :00 and :45 (gaps of 45 and 15 min).
- **The script needs `uv` in the cron's PATH.** If cron cannot find it, set `PCB_UV=/path/to/uv` at the top of the bridge script
  (`export PCB_UV=...`).
- **Evening store collection** skips Terabyte (it blocked the evening round); this is already inside `coleta-diaria.sh` (after 12h only
  `kabum,amazon`). Edit the script if your situation is different.
- **Pause and games.** `touch ~/.pc-builder-pause` pauses the channels (delete the file to resume). With **Modo jogo** on (Settings, or
  `PCB_GAME_MODE=1`) the rounds skip while a game is open.
- **Secrets.** The bot token never goes through Hermes: it stays in PC Builder's `secrets.env`. Do not paste a token into a cron prompt.
- After changing Hermes' timezone (`hermes config set timezone ...`), update the jobs with `hermes cron edit` so the times match your clock.

## Ready-made prompt for your Hermes Agent

If you want the agent itself to set this up, paste the text below into a conversation with it (change the path). It only creates files in
`~/.hermes/scripts/` and cron jobs; ask it to **confirm with you before** creating the jobs.

```text
I want to schedule PC Builder (local install at /path/to/pc-builder) through Hermes cron, without spending a model.
Read /path/to/pc-builder/docs/en/HERMES.md and follow "Step by step". Rules:
1. First, check in PC Builder's Settings that the internal scheduler is off and tell me what you found.
2. Create only the two bridge scripts in ~/.hermes/scripts/ (pc_builder_coleta.sh and pc_builder_canais.sh), with chmod +x.
3. Test each bridge in the terminal (--dry-run for the collection, --channels OPromoFacil for the channels) and show me the real output. Do not invent output.
4. Ask me for the target (--deliver) and the times, and only create the jobs after my OK. Always use --no-agent.
5. Run "hermes cron run" on one job and tell me what came back. Touch nothing outside ~/.hermes/scripts/ and the cron jobs.
```

## What was not verified

- This guide was written from a real install, which uses exactly this pattern (bridge scripts + `--no-agent`). It was not tested on
  another person's clean machine or on other Hermes Agent versions; if an `hermes cron` command changes, the
  [Hermes documentation](https://hermes-agent.nousresearch.com/docs) wins.
- Hermes Agent with PC Builder in Docker: not covered.
