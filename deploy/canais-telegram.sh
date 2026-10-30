#!/usr/bin/env bash
# Rodada dos canais do Telegram. Feito para um agendador (cron, timer do systemd...) a cada ~45 min.
# Saída (stdout) vazia = nada a avisar. Qualquer texto é o aviso; quem agenda decide para onde ele vai.
# (Com o destino "Bot do Telegram" nas Configurações, o próprio app manda pelo bot e a saída fica vazia.)
# Crash nunca fica mudo: código != 0 vira aviso com o fim do log.
# Trava: o `python -m app.tg` toma a mesma trava do agendador interno (data/rodada.lock); se outra rodada estiver
# rodando, espera até 20 min e depois pula calado.
#
# Variáveis (todas opcionais):
#   PCB_UV            caminho do `uv` (padrão: `uv` do PATH)
#   PCB_PAUSE_FILE    se este arquivo existir, pula a rodada (padrão: $HOME/.pc-builder-pause)
#   PCB_GAME_MODE     1 = também pula se tiver jogo aberto; 0 = nunca. Vale mais que o "Modo jogo" da tela.
#                     Sem a variável, vale o que está salvo na tela (`python -m app.settings get game_mode`).
#   PCB_GAME_PATTERN  o que o `pgrep -f` procura no modo jogo (padrão: Steam/Proton e gamescope)
set -u

# Pausa: sai calado; as ofertas sem tipo ficam guardadas e o reclassify revota depois.
[ -e "${PCB_PAUSE_FILE:-$HOME/.pc-builder-pause}" ] && exit 0

cd "$(dirname "$0")/../backend" || { echo "🧯 PC Builder (canais): pasta do backend sumiu"; exit 0; }

UV="${PCB_UV:-uv}"
LOG="${TMPDIR:-/tmp}/pc-builder-canais.log"

game="${PCB_GAME_MODE:-}"
[ -z "$game" ] && game=$("$UV" run --frozen --no-dev python -m app.settings get game_mode 2>/dev/null)
case "$game" in
    1|true) pgrep -f "${PCB_GAME_PATTERN:-reaper SteamLaunch|gamescope}" >/dev/null && exit 0 ;;
esac

run=(nice -n 19)
command -v ionice >/dev/null && run+=(ionice -c3)
# se o Ollama estiver fora, a rodada guarda as ofertas sem tipo e avisa
msg=$("${run[@]}" "$UV" run --frozen --no-dev python -m app.tg --notify "$@" 2>"$LOG")
rc=$?
if [ $rc -ne 0 ]; then
    echo "🧯 PC Builder (canais): a rodada quebrou (código $rc)."
    tail -5 "$LOG"
    exit 0
fi
[ -n "$msg" ] && echo "$msg"
exit 0
