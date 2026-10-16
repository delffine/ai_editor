# Этапы 2–3 прогона: рерайт и фактчек каждой отобранной новости.
# run/selected.json (этап 1, отбор) + run/sources.json (полные тексты входа, fetch.py)
#   -> run/changes.json (формат finish.py) + run/stages.json (вердикты, время, стоимость).
# Рерайт и фактчек — отдельные `claude -p` без инструментов, со структурированным
# ответом: фактчекер видит только материал и готовый текст (чистый контекст).
# Правила: rewrite_rules.md + cats/tags/fotos.md, factcheck_rules.md, fix_rules.md
# (лежат рядом, в ~/ai-editor/). Схема с 16.10.2026.
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BASE = Path(__file__).resolve().parent
RUN, STATE = BASE / "run", BASE / "state"
SAM = dt.timezone(dt.timedelta(hours=4))
CLAUDE = os.path.expanduser("~/.local/bin/claude")
REWRITE_MODEL = os.environ.get("AI_EDITOR_REWRITE_MODEL", "")
FACTCHECK_MODEL = os.environ.get("AI_EDITOR_FACTCHECK_MODEL", "sonnet")
WORKERS = int(os.environ.get("AI_EDITOR_STAGE_WORKERS", "2"))  # 1 CPU / 1.9 ГБ — больше двух claude разом не стоит
TIMEOUT = int(os.environ.get("AI_EDITOR_STAGE_TIMEOUT", "240"))
ROUNDS = 3  # проверок фактчекера; между ними — точечная правка по замечаниям
SOURCE_MAX = 6000  # символов на один источник


def schema(props, required=None):
    return json.dumps({"type": "object", "properties": props, "required": required or list(props),
                       "additionalProperties": False})


STR = {"type": "string"}
REWRITE_SCHEMA = schema({"titles": {"type": "array", "items": STR, "minItems": 3, "maxItems": 3},
                         "lead": STR, "body": STR, "notes": STR, "cat": {"type": "integer"},
                         "tags": {"type": "array", "items": STR, "maxItems": 3}, "foto": STR})
EDIT_SCHEMA = schema({"edits": {"type": "array", "items": {
    "type": "object", "additionalProperties": False, "required": ["where", "old", "new"],
    "properties": {"where": {"type": "string", "enum": ["title1", "title2", "title3", "lead", "body"]},
                   "old": STR, "new": STR}}}})
FACTCHECK_SCHEMA = schema({
    "verdict": {"type": "string", "enum": ["ok", "fix", "stop"]},
    "issues": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                          "required": ["kind", "quote", "source", "fix"],
                                          "properties": {"kind": STR, "quote": STR, "source": STR, "fix": STR}}}})


def claude(prompt, system_file, json_schema, model):
    cmd = [CLAUDE, "-p", prompt, "--system-prompt-file", str(system_file), "--tools", "",
           "--output-format", "json", "--json-schema", json_schema]
    if model:
        cmd += ["--model", model]
    p = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=TIMEOUT, cwd=BASE)
    try:
        d = json.loads(p.stdout)
    except ValueError:
        raise RuntimeError(f"claude exit={p.returncode}: {p.stderr.strip()[:200]}")
    if d.get("is_error") or not isinstance(d.get("structured_output"), dict):
        raise RuntimeError(str(d.get("result") or "нет структурированного ответа")[:300])
    u = d.get("usage") or {}
    USAGE.append({"system": Path(system_file).name} | {k: u.get(k, 0) for k in (
        "input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")})
    return d["structured_output"], round(d.get("total_cost_usd") or 0, 4), d.get("duration_ms") or 0


USAGE = []  # токены по вызовам — видно, срабатывает ли кэш системного промпта


def norm_url(u):
    return re.sub(r"^https?://(www\.)?", "", (u or "").strip()).rstrip("/")


def material_of(item, sources):
    """Фактура для рерайта и фактчека: источники (текст из входа по url или выдержки
    этапа отбора) + контекст. Возвращает (текст, предупреждения)."""
    parts, warn = [], []
    for i, s in enumerate(item.get("sources") or [], 1):
        src = sources.get(norm_url(s.get("url")))
        text = (s.get("text") or "").strip() or (src or {}).get("text", "")
        if not text:
            warn.append(f"нет текста источника {s.get('url')}")
            continue
        head = f"Источник {i}{' (главный)' if i == 1 else ''}: {s.get('name') or (src or {}).get('name', '')}"
        if src and src.get("published"):
            head += f" | опубликовано {src['published']}"
        title = (src or {}).get("title", "")
        parts.append(f"{head} | {s.get('url')}\n{title + chr(10) if title else ''}{text[:SOURCE_MAX]}")
    if (item.get("context") or "").strip():
        parts.append(f"Контекст редактора: {item['context'].strip()}")
    return "\n\n".join(parts), warn


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


def clean(v):
    return fix_quotes(str(v or "").strip())


def as_text(r):
    return "\n".join(f"Заголовок {i}: {t}" for i, t in enumerate(r["titles"], 1)) + \
        f"\n\nЛид: {r['lead']}\n\nТекст: {r['body'] or '(нет)'}"


def issues_text(issues):
    return "\n".join(f"{n}. [{x['kind']}] «{x['quote']}» — в материале: {x['source']}; правка: {x['fix']}"
                     for n, x in enumerate(issues, 1))


def apply_edits(r, edits):
    """Точечные замены правщика; текст вне замен не меняется, так что правка не вносит
    новых ошибок в другие места (16.10.2026: при переписывании целиком появлялись новые
    выдумки). Пустой new для заголовка — вариант выбрасывается. Возвращает число применённых."""
    n = 0
    for e in edits:
        old, new, where = e["old"], clean(e["new"]), e["where"]
        if where.startswith("title"):
            i = int(where[-1]) - 1
            if i < len(r["titles"]) and old and old in r["titles"][i]:
                r["titles"][i] = r["titles"][i].replace(old, new, 1).strip() if new else ""
                n += 1
        elif old and old in r[where]:
            r[where] = re.sub(r"  +", " ", r[where].replace(old, new, 1)).strip()
            n += 1
    r["titles"] = [t for t in r["titles"] if t]
    return n


def drop_flagged_titles(r, issues):
    """Остались замечания только к вариантам заголовка — выбросить эти варианты (их три,
    хоть один должен остаться). Возвращает замечания, которые остались в силе."""
    bad = [t for t in r["titles"] if any(x["quote"] and x["quote"] in t for x in issues)]
    if bad and len(bad) < len(r["titles"]):
        r["titles"] = [t for t in r["titles"] if t not in bad]
        issues = [x for x in issues if not any(x["quote"] and x["quote"] in t for t in bad)]
    return issues


def process(item, sources, kind, prev=None):
    """Рерайт -> фактчек -> (правка -> фактчек). Возвращает поля для changes.json и статистику."""
    stat = {"id": item["id"], "kind": kind, "cost": 0.0, "ms": 0, "checks": []}
    material, warn = material_of(item, sources)
    if prev:  # update: прежняя версия нашего предложения — тоже материал (проверена раньше)
        material = (prev.get("material") or f"Прежняя версия новости (проверена ранее):\n{as_text({'titles': prev['headlines'], 'lead': prev['lead'], 'body': prev.get('body', '')})}") \
            + "\n\nНОВЫЕ МАТЕРИАЛЫ\n\n" + material
    stat["warn"] = warn
    if not material.strip():
        return None, stat | {"error": "пустая фактура"}
    task = (f"Обнови новость по новым материалам: собери одну новость по состоянию на сейчас.\n\n" if prev else "") + \
        f"Сейчас {dt.datetime.now(SAM):%d.%m.%Y %H:%M} (Самара).\nО чём новость: {item.get('topic', '')}\n\nМАТЕРИАЛ\n\n{material}"
    out, cost, ms = claude(task, RUN / "rewrite_system.md", REWRITE_SCHEMA, REWRITE_MODEL)
    stat["cost"] += cost
    stat["ms"] += ms
    r = {"titles": [clean(t) for t in out["titles"] if clean(t)][:3], "lead": clean(out["lead"]),
         "body": clean(out["body"]), "notes": clean(out["notes"]), "cat": out.get("cat") or 0,
         "tags": out.get("tags") or [], "foto": (out.get("foto") or "").strip()}
    for rnd in range(ROUNDS):
        fc, cost, ms = claude(f"МАТЕРИАЛ\n\n{material}\n\nНОВОСТЬ ДЛЯ ПРОВЕРКИ\n\n{as_text(r)}",
                              BASE / "factcheck_rules.md", FACTCHECK_SCHEMA, FACTCHECK_MODEL)
        stat["cost"] += cost
        stat["ms"] += ms
        stat["checks"].append({"verdict": fc["verdict"], "issues": fc["issues"]})
        if fc["verdict"] == "ok" or rnd == ROUNDS - 1:
            break
        # правка — точечными заменами (текст целиком не переписывается)
        ed, cost, ms = claude(f"МАТЕРИАЛ\n\n{material}\n\nНОВОСТЬ\n\n{as_text(r)}\n\nЗАМЕЧАНИЯ ФАКТЧЕКЕРА\n\n"
                              f"{issues_text(fc['issues'])}", BASE / "fix_rules.md", EDIT_SCHEMA, REWRITE_MODEL)
        stat["cost"] += cost
        stat["ms"] += ms
        stat["checks"][-1]["edits"] = f"{apply_edits(r, ed['edits'])}/{len(ed['edits'])}"
    if fc["verdict"] == "fix":
        fc["issues"] = drop_flagged_titles(r, fc["issues"])
        if not fc["issues"]:
            fc["verdict"] = "ok"
            stat["checks"][-1]["titles_dropped"] = True
    note = " ".join(x for x in [item.get("note", ""), r["notes"] and f"Рерайт: {r['notes']}"] if x)
    if fc["verdict"] != "ok":
        note = (note + " " if note else "") + f"⚠ Фактчек ({fc['verdict']}): " + \
            "; ".join(f"[{x['kind']}] «{x['quote']}» — {x['source']}" for x in fc["issues"])
    if warn:
        note = (note + " " if note else "") + "⚠ " + "; ".join(warn)
    res = {"headlines": r["titles"], "lead": r["lead"], "body": r["body"], "cat": r["cat"], "tags": r["tags"],
           "foto": r["foto"], "note": note, "material": material,
           "factcheck": {"verdict": fc["verdict"], "rounds": len(stat["checks"]), "issues": fc["issues"]}}
    return res, stat


def load_selected(path):
    """Частый сбой — неэкранированная кавычка внутри текста: экранируем ту, на которой
    споткнулся разбор, и пробуем снова (как load_changes в finish.py)."""
    s = path.read_text(encoding="utf-8")
    for _ in range(50):
        try:
            return json.loads(s)
        except json.JSONDecodeError as e:
            q = s.rfind('"', 0, e.pos)
            if q <= 0 or s[q - 1] == "\\" or "delimiter" not in e.msg:
                raise
            s = s[:q] + '\\"' + s[q + 1:]
    raise ValueError("selected.json: слишком много ошибок")


def main():
    sel = load_selected(RUN / "selected.json")
    sources = {norm_url(k): v for k, v in json.loads((RUN / "sources.json").read_text(encoding="utf-8")).items()} \
        if (RUN / "sources.json").exists() else {}
    props = {p["id"]: p for p in json.loads((STATE / "proposals.json").read_text(encoding="utf-8"))} \
        if (STATE / "proposals.json").exists() else {}
    (RUN / "rewrite_system.md").write_text("\n\n".join(
        (BASE / f).read_text(encoding="utf-8") for f in ("rewrite_rules.md", "cats.md", "tags.md", "fotos.md")), encoding="utf-8")

    jobs = [(a, "add", None) for a in sel.get("add", [])] + \
           [(u, "update", props[u["id"]]) for u in sel.get("update", []) if u["id"] in props]
    t0 = time.time()

    def run(job):
        item, kind, prev = job
        try:
            return job, *process(item, sources, kind, prev)
        except Exception as e:  # noqa: BLE001 — сбой одной новости не валит прогон
            return job, None, {"id": item["id"], "kind": kind, "error": f"{type(e).__name__}: {e}"[:300]}

    # первая новость — одна: её вызовы кладут системные промпты в кэш, остальные читают оттуда
    results = [run(j) for j in jobs[:1]]
    with ThreadPoolExecutor(WORKERS) as ex:
        results += list(ex.map(run, jobs[1:]))

    ch = {k: sel.get(k) for k in ("latest", "log", "drop", "skipped")}
    ch["add"], ch["update"] = [], []
    for (item, kind, prev), res, stat in results:
        if res is None:  # рерайт не удался — предложение всё равно показываем, с пометкой
            res = {"headlines": [item.get("topic") or item["id"]], "lead": item.get("topic", ""), "body": "",
                   "note": f"⚠ ИИ-редактор не смог написать текст ({stat.get('error')}). {item.get('note', '')}".strip()}
        if kind == "add":
            ch["add"].append({k: item.get(k) for k in ("id", "block", "label", "score", "score_why", "sources_html",
                                                         "expires")} | res)
        else:
            ch["update"].append({"id": item["id"], "refresh": bool(item.get("refresh"))} | res)
    (RUN / "changes.json").write_text(json.dumps(ch, ensure_ascii=False, indent=1), encoding="utf-8")
    stats = [s for _, _, s in results]
    total = round(sum(s.get("cost", 0) for s in stats), 3)
    (RUN / "stages.json").write_text(json.dumps({"sec": round(time.time() - t0), "cost": total, "items": stats,
                                                 "usage": USAGE},
                                                ensure_ascii=False, indent=1), encoding="utf-8")
    # «cost N» — суммирует cost.sh вместе с этапом отбора
    print(f"рерайт+фактчек: {len(jobs)} новостей за {time.time() - t0:.0f} с, cost {total};",
          ", ".join(f"{s['id']}: {'/'.join(c['verdict'] for c in s.get('checks', [])) or s.get('error')}" for s in stats))


if __name__ == "__main__":
    sys.exit(main())
