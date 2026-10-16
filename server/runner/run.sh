#!/bin/bash
# Прогон ИИ-редактора по cron: сбор -> Claude -> страница.
# Лог: ~/ai-editor/logs/run_ГГГГ-ММ-ДД.log
set -u
cd "$(dirname "$0")"
mkdir -p logs run state
LOG="logs/run_$(date +%F).log"
exec >>"$LOG" 2>&1
exec 9>run/.lock
flock -n 9 || { echo "$(date '+%F %T') прошлый прогон ещё идёт — пропуск"; exit 0; }
echo "===== $(date '+%F %T') старт"

set -a; . "$HOME/.config/ai-editor.env"; set +a
rm -f run/changes.json
python3 fetch.py; rc=$?
if [ $rc -eq 3 ]; then
  echo "нового нет — Claude не вызывается"
elif [ $rc -ne 0 ]; then
  echo "fetch упал"; exit 1
else

  # rules.md, tags.md (теги сайта) fotos.md (банк превью) и cats.md (рубрики) — в системном промпте (неизменный префикс кэшируется между прогонами);
  # --tools — только нужные инструменты (меньше базовый контекст на каждом шаге)
  timeout -s KILL 900 "$HOME/.local/bin/claude" -p "$(cat prompt.md)" \
  --append-system-prompt "$(cat rules.md tags.md fotos.md cats.md)" \
  --tools "Read,Edit,Write,Bash,WebFetch,WebSearch" \
  --permission-mode dontAsk \
  --allowedTools "Read(//home/deploy/ai-editor/**),Edit(//home/deploy/ai-editor/run/changes.json),Write(//home/deploy/ai-editor/run/changes.json),Bash(curl *),Bash(python3 *),Bash(grep *),Bash(head *),Bash(echo *),Bash(cd *),WebFetch,WebSearch" \
  --output-format json < /dev/null > run/claude.json
  echo "claude exit=$? $(python3 -c 'import json;d=json.load(open("run/claude.json"));print("is_error",d.get("is_error"),"turns",d.get("num_turns"),"ms",d.get("duration_ms"),"cost",round(d.get("total_cost_usd") or 0,3))' 2>/dev/null)"
fi

python3 finish.py
echo "===== $(date '+%F %T') конец"
