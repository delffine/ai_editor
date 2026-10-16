#!/usr/bin/env python3
"""Воркер рерайта для диалога в админке syzran-small.ru.

Берёт задания из очереди /var/www/ai-editor/.rewrite/in/ (их кладёт rewrite.php
под www-data), прогоняет текст через `claude -p` без инструментов с правилами
режима (rewrite_rules.md — рерайт, proof_rules.md — проверка правописания) и пишет результат в .rewrite/out/<id>.json. Работает постоянно;
запускает его rewrite_worker.sh из cron раз в минуту под flock (второй экземпляр
сразу выходит). Сам выходит раз в сутки или при обновлении своего файла — cron
перезапустит в течение минуты.

Тексты новостей в лог не пишутся — только id, размер, время, стоимость.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
QUEUE = Path(os.environ.get("AI_EDITOR_REWRITE_QUEUE", "/var/www/ai-editor/.rewrite"))
IN, OUT = QUEUE / "in", QUEUE / "out"
ALIVE = QUEUE / "worker.alive"
CLAUDE = os.path.expanduser("~/.local/bin/claude")
MODEL = os.environ.get("AI_EDITOR_REWRITE_MODEL", "")
TIMEOUT = int(os.environ.get("AI_EDITOR_REWRITE_TIMEOUT", "240"))
OUT_TTL = 2 * 3600        # готовые результаты храним 2 ч
STALE_IN = 15 * 60        # задание, пролежавшее 15 мин, — уже никому не нужно
MAX_LIFE = 24 * 3600


def schema(props):
    """Структурированный вывод: claude сам проверяет ответ по схеме — без битого
    JSON из-за неэкранированных кавычек в тексте (13.10.2026)."""
    return json.dumps({"type": "object", "properties": props,
                       "required": list(props), "additionalProperties": False})


STR = {"type": "string"}
# Режимы: rewrite — 3 заголовка + лид + текст в стиле редакции; proof — только
# исправление ошибок и опечаток (13.10.2026)
MODES = {
    "rewrite": {
        "rules": HERE / "rewrite_rules.md",
        "prompt": "Текст новости:\n\n",
        "schema": schema({"titles": {"type": "array", "items": STR, "minItems": 3, "maxItems": 3},
                          "lead": STR, "body": STR, "notes": STR}),
    },
    "proof": {
        "rules": HERE / "proof_rules.md",
        "prompt": "Текст для проверки:\n\n",
        "schema": schema({"text": STR, "notes": STR}),
    },
}

QUOTES = "\"'`\u2018\u2019\u201a\u201b\u201c\u201d\u201e\u201f\u2039\u203a"
OPEN_AFTER = " \t\r\n([{«-\u2013\u2014/"


def fix_quotes(s):
    """Все кавычки — «ёлочки» (правило редакции). Открывающая — в начале строки
    или после пробела/скобки/тире, иначе закрывающая; апостроф между буквами
    (О'Нил) не трогаем."""
    out = []
    for i, ch in enumerate(s):
        if ch not in QUOTES:
            out.append(ch)
            continue
        prev = s[i - 1] if i else ""
        nxt = s[i + 1] if i + 1 < len(s) else ""
        if ch in "'\u2019`" and prev.isalpha() and nxt.isalpha():
            out.append(ch)
        elif not prev or prev in OPEN_AFTER or ch == "\u201e":
            out.append("«")
        else:
            out.append("»")
    return "".join(out)


def log(msg):
    print(time.strftime("%F %T"), msg, flush=True)


def write_out(job_id, data):
    tmp = OUT / f".{job_id}.tmp"
    tmp.write_text(json.dumps(data, ensure_ascii=True), encoding="utf-8")
    os.chmod(tmp, 0o640)
    tmp.rename(OUT / f"{job_id}.json")


def clean(v):
    return fix_quotes(str(v or "").strip())


def parse_result(d, mode):
    if not isinstance(d, dict):
        text = str(d or "")
        a, b = text.find("{"), text.rfind("}")
        if a < 0 or b <= a:
            raise ValueError("в ответе нет JSON")
        d = json.loads(text[a:b + 1])
    if mode == "proof":
        if not clean(d.get("text")):
            raise ValueError("в ответе нет текста")
        # notes — список «было → стало»: кавычки не трогаем, иначе «было» исказится
        return {"text": clean(d.get("text")), "notes": str(d.get("notes") or "").strip()}
    titles = [clean(t) for t in d.get("titles") or [] if clean(t)]
    if not titles or not clean(d.get("lead")):
        raise ValueError("в ответе нет заголовков или лида")
    return {"titles": titles[:3], "lead": clean(d.get("lead")),
            "body": clean(d.get("body")), "notes": clean(d.get("notes"))}


def rewrite(text, mode):
    m = MODES[mode]
    cmd = [CLAUDE, "-p", m["prompt"] + text,
           "--system-prompt-file", str(m["rules"]),
           "--tools", "", "--output-format", "json", "--json-schema", m["schema"]]
    if MODEL:
        cmd += ["--model", MODEL]
    p = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True,
                       text=True, timeout=TIMEOUT, cwd=HERE)
    try:
        d = json.loads(p.stdout)
    except ValueError:
        raise RuntimeError(f"claude exit={p.returncode}: {p.stderr.strip()[:200]}")
    if d.get("is_error"):
        raise RuntimeError(str(d.get("result") or "ошибка claude")[:300])
    res = parse_result(d.get("structured_output") or d.get("result") or "", mode)
    res["mode"] = mode
    res["ms"] = d.get("duration_ms")
    res["cost"] = round(d.get("total_cost_usd") or 0, 4)
    return res


def process(path):
    job_id = path.stem
    try:
        job = json.loads(path.read_text(encoding="utf-8"))
        text = str(job.get("text") or "").strip()
        mode = job.get("mode") if job.get("mode") in MODES else "rewrite"
    except (OSError, ValueError):
        text, mode = "", "rewrite"
    t0 = time.time()
    try:
        if not text:
            raise RuntimeError("пустое или повреждённое задание")
        if time.time() - path.stat().st_mtime > STALE_IN:
            raise RuntimeError("задание устарело")
        res = rewrite(text, mode)
        res["status"] = "ok"
        log(f"{job_id} ok {mode} len={len(text)} ms={res['ms']} cost={res['cost']}")
    except subprocess.TimeoutExpired:
        res = {"status": "error", "error": f"модель не ответила за {TIMEOUT} с"}
        log(f"{job_id} timeout len={len(text)}")
    except Exception as e:  # noqa: BLE001 — любую ошибку отдаём редактору
        res = {"status": "error", "error": str(e)}
        log(f"{job_id} error {e!r} {time.time() - t0:.1f}s")
    write_out(job_id, res)
    path.unlink(missing_ok=True)


def cleanup():
    now = time.time()
    for f in OUT.glob("*.json"):
        if now - f.stat().st_mtime > OUT_TTL:
            f.unlink(missing_ok=True)


def main():
    for d in (IN, OUT):
        d.mkdir(parents=True, exist_ok=True)
        os.chmod(d, 0o2770)
    started, me = time.time(), Path(__file__).stat().st_mtime
    log("воркер запущен")
    last_clean = 0
    while True:
        ALIVE.touch()
        jobs = sorted(IN.glob("*.json"), key=lambda f: f.stat().st_mtime)
        if jobs:
            process(jobs[0])
            continue
        if time.time() - last_clean > 600:
            cleanup()
            last_clean = time.time()
        if time.time() - started > MAX_LIFE or Path(__file__).stat().st_mtime != me:
            log("плановый перезапуск")
            return
        time.sleep(1.5)


if __name__ == "__main__":
    sys.exit(main())
