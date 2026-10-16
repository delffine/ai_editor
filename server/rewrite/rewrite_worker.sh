#!/bin/bash
# Запуск воркера рерайта из cron раз в минуту: если воркер уже работает
# (держит flock) — сразу выход. Лог: ~/ai-editor/logs/rewrite_ГГГГ-ММ.log
cd "$(dirname "$0")"
mkdir -p logs run
exec 9>run/.rewrite.lock
flock -n 9 || exit 0
set -a; . "$HOME/.config/ai-editor.env"; set +a
exec python3 rewrite_worker.py >>"logs/rewrite_$(date +%Y-%m).log" 2>&1
