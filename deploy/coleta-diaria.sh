#!/usr/bin/env bash
# Coleta diária do PC Builder. Feito para um agendador (cron, timer do systemd...), 1 ou 2 vezes por dia.
# Saída (stdout) vazia = dia normal, nada a avisar. Qualquer texto é o aviso; quem agenda decide o destino.
# (Com o destino "Bot do Telegram" nas Configurações, o próprio app manda pelo bot e a saída fica vazia.)
#   código 0 = tudo certo · 1 = alguma loja falhou (a mensagem já explica) · outro = quebrou
# Trava: o `python -m app.collect` toma a mesma trava do agendador interno (data/rodada.lock); se outra rodada
# estiver rodando, espera até 20 min e depois pula calado.
# PCB_UV (opcional): caminho do `uv` (padrão: `uv` do PATH).
# Modo jogo: PCB_GAME_MODE (1/0) vale mais; sem ela, vale o salvo na tela. PCB_GAME_PATTERN muda o padrão.
set -uo pipefail
cd "$(dirname "$0")/../backend" || { echo "🧯 PC Builder: pasta do projeto sumiu"; exit 0; }
UV="${PCB_UV:-uv}"
LOG="${TMPDIR:-/tmp}/pc-builder-coleta.log"

game="${PCB_GAME_MODE:-}"
[ -z "$game" ] && game=$("$UV" run --frozen --no-dev python -m app.settings get game_mode 2>/dev/null)
case "$game" in
  1|true) pgrep -f "${PCB_GAME_PATTERN:-reaper SteamLaunch|gamescope}" >/dev/null && exit 0 ;;
esac

# Terabyte devolveu 403 na rodada da noite (10 e 11/10/2026); a da manhã passa. Preço não muda de manhã
# pra noite, então à noite ela fica de fora.
extra=()
if [ "$(date +%-H)" -ge 12 ]; then extra=(--stores kabum,amazon); fi
msg=$("$UV" run --frozen --no-dev python -m app.collect --notify "${extra[@]}" "$@" 2>"$LOG")
rc=$?
if [ "$rc" -ne 0 ] && [ -z "$msg" ]; then
  # falhou sem explicar: nunca ficar em silêncio
  echo "🧯 PC Builder: a coleta quebrou (código $rc). Últimas linhas do log ($LOG):"
  tail -4 "$LOG"
elif [ -n "$msg" ]; then
  echo "$msg"
fi
exit 0
