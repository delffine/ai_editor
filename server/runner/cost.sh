#!/bin/bash
# Сумма оценок стоимости прогонов за день (оценка Claude Code, расход подписки):
#   ./cost.sh [ГГГГ-ММ-ДД]
d=${1:-$(date +%F)}
grep -o 'cost [0-9.]*' "$HOME/ai-editor/logs/run_$d.log" |
  awk -v d="$d" '{s += $2; n++} END {printf "%s: прогонов с оценкой %d, сумма $%.2f, в среднем $%.2f\n", d, n, s, (n ? s / n : 0)}'
