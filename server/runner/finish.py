# Шаг 3 прогона: применить run/changes.json к state/proposals.json, собрать
# страницу и опубликовать через publish.php. Порядок — по итоговому баллу:
#   итоговый = базовый / (1 + минуты в выдаче / DECAY_MIN)
# (запас не затухает — сортируется по базовому баллу).
import datetime as dt
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
RUN, STATE = BASE / "run", BASE / "state"
SAM = dt.timezone(dt.timedelta(hours=4))
DECAY_MIN = float(os.environ.get("AI_EDITOR_DECAY_MIN", "60"))
LOG_KEEP = 40
now = dt.datetime.now(SAM)


def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


props = load(STATE / "proposals.json", [])
log = load(STATE / "log.json", [])
taken = load(STATE / "taken.json", [])
def load_changes(path):
    """changes.json -> (dict | None, причина). Частый сбой Claude — неэкранированные
    кавычки внутри текста («"Т Плюс"…»): экранируем кавычку, на которой споткнулся
    разбор, и пробуем снова."""
    try:
        s = path.read_text(encoding="utf-8")
    except OSError:
        return None, None
    for _ in range(50):
        try:
            return json.loads(s), None
        except json.JSONDecodeError as e:
            q = s.rfind('"', 0, e.pos)
            if q <= 0 or s[q - 1] == "\\" or "delimiter" not in e.msg:
                return None, f"ответ Claude — битый JSON ({e.msg}, строка {e.lineno}), исправить не удалось"
            s = s[:q] + '\\"' + s[q + 1:]
    return None, "ответ Claude — битый JSON, слишком много ошибок"


ch, json_error = load_changes(RUN / "changes.json")
failed = ch is None
if failed:
    # Claude не отработал (лимит подписки, ошибка, таймаут) или ответ не читается:
    # страницу всё равно публикуем — с предупреждением и прошлыми предложениями;
    # last_run не сдвигаем, чтобы следующий прогон разобрал пропущенное.
    info = load(RUN / "claude.json", {})
    reason = json_error or " ".join(str(info.get("result") or "Claude не ответил (таймаут или сбой)").split())[:200]
    ch = {"latest": f"⚠ Прогон в {now:%H:%M} не выполнен: {html.escape(reason)}. Ниже — предложения прошлых "
                    f"прогонов (итоговые баллы пересчитаны); пропущенное разберёт следующий прогон.",
          "log": f"⚠ не выполнен: {html.escape(reason)}"}
    print("Прогон не выполнен:", reason)

by_id = {p["id"]: p for p in props}
for d in ch.get("drop", []):
    p = by_id.pop(d["id"], None)
    # одна новость сайта засчитывается один раз, даже если совпала с двумя предложениями
    if p and d.get("taken_as") and not any(t["site"] == d["taken_as"] for t in taken):
        taken.insert(0, {"at": now.isoformat(timespec="minutes"), "title": p["headlines"][0], "site": d["taken_as"]})
for u in ch.get("update", []):
    p = by_id.get(u["id"])
    if not p:
        continue
    refresh = u.pop("refresh", False)
    p.update({k: v for k, v in u.items() if k != "id"})
    if refresh:  # существенно новые факты — снова «свежая»
        p["detected_at"] = now.isoformat(timespec="seconds")
for a in ch.get("add", []):
    a.setdefault("detected_at", now.isoformat(timespec="seconds"))
    by_id[a["id"]] = a
# Теги — только из списка сайта (tags.md, build_tags.py), буква в букву, до 3; чего нет в списке — выбросить
try:
    TAGS = {re.sub(r" \(\d+\)$", "", t) for t in (BASE / "tags.md").read_text(encoding="utf-8").strip().splitlines()[-1].split("; ")}
except OSError:
    TAGS = set()
for p in by_id.values():
    if "tags" in p:
        ok = [t for t in dict.fromkeys(p["tags"] if isinstance(p["tags"], list) else []) if t in TAGS][:3]
        if ok != p["tags"]:
            print(p["id"], "теги:", p["tags"], "->", ok)
        p["tags"] = ok
# Превью — только имя из банка (fotos.md, build_fotos.py), иначе пусто
try:
    FOTOS = dict(re.match(r"(\S+) — (.*?)(?: \(\d+\))?$", l).groups()
                 for l in (BASE / "fotos.md").read_text(encoding="utf-8").splitlines() if re.match(r"\S+\.\w+ — ", l))
except OSError:
    FOTOS = {}
for p in by_id.values():
    if p.get("foto") and p["foto"] not in FOTOS:
        print(p["id"], "превью не из банка:", p["foto"])
        p["foto"] = ""
# Рубрика — номер рубрики сайта (cats.md), иначе 0 (без рубрики)
CATS = {1: "Общество", 2: "Культура", 3: "Спорт", 4: "Коммунальная сфера", 5: "Экономика и бизнес",
        6: "Правопорядок", 7: "Происшествия", 8: "Из жизни", 9: "Медицина", 10: "Образование",
        11: "Власть", 12: "Благоустройство", 13: "В регионе, в стране", 14: "Непознанное",
        15: "Оперативная информация", 16: "Туризм", 17: "Нацпроекты"}  # как в build_cats.py и форме add_news
for p in by_id.values():
    if "cat" in p:
        try:
            c = int(p["cat"] or 0)
        except (TypeError, ValueError):
            c = 0
        p["cat"] = c if c in CATS else 0
# просроченное (expires) — убрать
props = [p for p in by_id.values() if not p.get("expires") or dt.datetime.fromisoformat(p["expires"]) > now]
# КТВ-ЛУЧ — прямой конкурент (правило 5 README): если главный источник — он,
# базовый балл ×KTV_FACTOR (один раз на предложение) и не в «Срочно»
KTV_FACTOR = float(os.environ.get("AI_EDITOR_KTV_FACTOR", "0.4"))
for p in props:
    m = re.search(r'href="([^"]+)"', p.get("sources_html", ""))
    if m and re.search(r"ktv-ray\.ru|t\.me/(s/)?ktv_ray", m.group(1)) and not p.get("ktv_penalty"):
        p["ktv_penalty"] = True
        p["score"] = round(p["score"] * KTV_FACTOR, 2)
        p["score_why"] = (p.get("score_why", "") + f" · источник КТВ-ЛУЧ (конкурент) ×{KTV_FACTOR:g}").lstrip(" ·")
        if p["block"] == "urgent":
            p["block"] = "queue"


def age_min(p):
    return max(0.0, (now - dt.datetime.fromisoformat(p["detected_at"])).total_seconds() / 60)


def eff(p):
    return p["score"] if p["block"] == "reserve" else p["score"] / (1 + age_min(p) / DECAY_MIN)


def fmt_age(m):
    return f"{int(m)} мин" if m < 60 else f"{int(m // 60)} ч {int(m % 60)} мин"


# «Срочно» — не дольше URGENT_RUNS прогонов: не взяли сразу — значит не срочно,
# переводим в обычную очередь (там затухает и может быть вытеснено).
URGENT_RUNS = int(os.environ.get("AI_EDITOR_URGENT_RUNS", "2"))
URGENT_MAX_MIN = float(os.environ.get("AI_EDITOR_URGENT_MAX_MIN", "70"))  # и не дольше 70 мин (ночь прогонов нет)
QUEUE_MAX = int(os.environ.get("AI_EDITOR_QUEUE_MAX", "10"))
evicted = []
for p in props:
    if p["block"] != "urgent":
        continue
    if p.get("runs_urgent", 0) >= URGENT_RUNS or age_min(p) > URGENT_MAX_MIN:
        p["block"] = "queue"
        p["label"] = p["label"] + f" <em>(было в «Срочно» — редакция не взяла)</em>"
        evicted.append(f"<strong>ИИ-редактор перевёл из «Срочно» в очередь</strong> (не взято за {URGENT_RUNS} прогона или {URGENT_MAX_MIN:g} мин): {html.escape(p['headlines'][0])}")
    else:
        p["runs_urgent"] = p.get("runs_urgent", 0) + 1
# В очереди — не больше QUEUE_MAX: лишние по итоговому баллу вытесняются
queue = sorted([p for p in props if p["block"] == "queue"], key=eff, reverse=True)
for p in queue[QUEUE_MAX:]:
    props.remove(p)
    evicted.append(f"<strong>ИИ-редактор убрал из очереди</strong> (лимит {QUEUE_MAX}, итоговый балл {eff(p):.2f}): {html.escape(p['headlines'][0])}")
# В запасе — не больше RESERVE_MAX: вытесняются с меньшим баллом, при равенстве — более старые
RESERVE_MAX = int(os.environ.get("AI_EDITOR_RESERVE_MAX", "8"))
reserve = sorted([p for p in props if p["block"] == "reserve"], key=lambda p: (p["score"], p["detected_at"]), reverse=True)
for p in reserve[RESERVE_MAX:]:
    props.remove(p)
    evicted.append(f"<strong>ИИ-редактор убрал из запаса</strong> (лимит {RESERVE_MAX}, балл {p['score']:.1f}): {html.escape(p['headlines'][0])}")


def card(p):
    e = html.escape
    hl = "".join(f"<li>{e(h)}</li>" for h in p["headlines"])
    body = f"<p>{e(p['body'])}</p>" if p.get("body") else ""
    score = (f'<span class="score">{p["score"]:.1f}</span>' if p["block"] == "reserve" else
             f'<span class="score">{eff(p):.2f}</span> базовый {p["score"]:.1f}, в выдаче {fmt_age(age_min(p))}')
    note = f'<br><span class="note">{p["note"]}</span>' if p.get("note") else ""
    exp = f' · до {dt.datetime.fromisoformat(p["expires"]):%d.%m %H:%M}' if p.get("expires") else ""
    tags = f'<br><strong>Теги:</strong> {e(", ".join(p["tags"]))}' if p.get("tags") else ""
    if p.get("cat"):
        tags = f'<br><strong>Рубрика:</strong> {e(CATS[p["cat"]])}' + tags
    if p.get("foto"):
        u = "https://www.syzran-small.ru/images/news/" + urllib.parse.quote(p["foto"])
        tags += (f'<br><strong>Превью:</strong> <a href="{e(u)}"><img src="{e(u)}" width="120" loading="lazy" '
                 f'style="vertical-align:top"></a> {e(p["foto"])} — {e(FOTOS.get(p["foto"], ""))}')
    return (f'<article>\n<h3>{p["label"]}</h3>\n<ol>{hl}</ol>\n<p><strong>Лид:</strong> {e(p["lead"])}</p>\n{body}\n'
            f'<div class="meta">{score} · {e(p.get("score_why", ""))}{exp}\n<br><strong>Источник:</strong> {p["sources_html"]}{tags}{note}</div>\n</article>')


blocks = {b: sorted([p for p in props if p["block"] == b], key=eff, reverse=True) for b in ("urgent", "queue", "reserve")}
latest = ch.get("latest") or "Новых сызранских новостей нет."
warn_file = RUN / "warnings.txt"  # fetch.py: например, сборщик недоступен
if warn_file.exists():
    warn = html.escape(warn_file.read_text(encoding="utf-8").strip())
    latest = f"⚠ ИИ-редактор: {warn}. {latest}"
    ch["log"] = f"⚠ {warn}; {ch.get('log') or ''}".rstrip("; ")
log.insert(0, f"{now:%d.%m %H:%M}: {ch.get('log') or latest}")
log = log[:LOG_KEEP]
skipped = "".join(f"<li>{s}</li>" for s in evicted + ch.get("skipped", [])) or "<li>—</li>"
taken_html = "".join(f"<li>{t['at'][5:16].replace('T', ' ')}: {html.escape(t['title'])} → {t['site']}</li>" for t in taken[:15]) or "<li>—</li>"


def section(title, cls, items, empty):
    inner = "\n".join(card(p) for p in items) or f"<p><em>{empty}</em></p>"
    return f'<h2 class="block {cls}">{title}</h2>\n{inner}\n'


page = (BASE / "template.html").read_text(encoding="utf-8")
page = page.replace("{{LATEST}}", f"<strong>Обновлено в {now:%H:%M}.</strong> {latest}")
page = page.replace("{{BLOCKS}}",
                    section("Срочно — ставить вместо следующей", "urgent", blocks["urgent"], "Срочных новостей нет.") +
                    section("В очередь (по итоговому баллу — свежесть учитывается)", "queue", blocks["queue"], "Пусто.") +
                    section("Запас — закрыть дыры", "reserve", blocks["reserve"], "Пусто."))
page = page.replace("{{SKIPPED}}", skipped).replace("{{TAKEN}}", taken_html)
page = page.replace("{{LOG}}", "\n".join(f"<li>{x}</li>" for x in log)).replace("{{DECAY}}", f"{DECAY_MIN:g}")



# Лента для «Предложки (ИИ)» в админке сайта (news.php?in=ai_feed забирает её через
# feed.php). HTML отсюда в админку не идёт: метки и примечания — текстом,
# источники — списком ссылок; рисует админка сама. Точечный файл nginx наружу не отдаёт.
def text_of(s):
    s = re.sub(r"<[^>]+>", "", re.sub(r"<(br|/p|/li)\b[^>]*>", " ", s or "", flags=re.I))
    return " ".join(html.unescape(s).split())


def parts_of(s):
    """sources_html -> [{"t": текст}, {"t": имя, "url": ссылка}, …] в исходном порядке."""
    out, pos = [], 0
    s = s or ""
    for m in re.finditer(r'<a\s[^>]*?href="([^"]+)"[^>]*>(.*?)</a>', s, re.S | re.I):
        out.append({"t": text_of(s[pos:m.start()])})
        u = html.unescape(m.group(1))
        out.append({"t": text_of(m.group(2)), "url": u} if re.match(r"https?://", u) else {"t": text_of(m.group(2))})
        pos = m.end()
    out.append({"t": text_of(s[pos:])})
    return [p for p in out if p["t"]]


def next_update(t):
    """Когда лента обновится: следующий слот cron (5,35 7-21 * * 1-5) + NEXT_AFTER мин —
    прогон обычно идёт 2–3 мин, в 90% случаев до 5 мин."""
    t = t.replace(second=0, microsecond=0)
    for _ in range(4 * 24 * 60):
        t += dt.timedelta(minutes=1)
        if t.weekday() < 5 and 7 <= t.hour <= 21 and t.minute in (5, 35):
            return t + dt.timedelta(minutes=float(os.environ.get("AI_EDITOR_NEXT_AFTER", "6")))
    return None


nxt = next_update(now)
feed = {"updated": now.isoformat(timespec="seconds"), "next": nxt and nxt.isoformat(timespec="minutes"),
        "latest": text_of(latest),
        "items": [{"id": p["id"], "block": b, "label": text_of(p["label"]), "headlines": p["headlines"],
                   "lead": p["lead"], "body": p.get("body") or "", "score": round(eff(p), 2),
                   "base": p["score"], "age_min": round(age_min(p)), "score_why": p.get("score_why", ""),
                   "note": text_of(p.get("note")), "expires": p.get("expires"), "tags": p.get("tags") or [],
                   "foto": p.get("foto") or "", "foto_caption": FOTOS.get(p.get("foto") or "", ""),
                   "cat": p.get("cat") or 0, "cat_name": CATS.get(p.get("cat") or 0, ""),
                   "sources": parts_of(p.get("sources_html"))}
                  for b in ("urgent", "queue", "reserve") for p in blocks[b]]}
feed_path = Path(os.environ.get("AI_EDITOR_FEED_JSON", "/var/www/ai-editor/.feed.json"))
if os.environ.get("AI_EDITOR_DRY"):
    feed_path = RUN / "feed.json"
try:
    tmp = feed_path.with_name(feed_path.name + ".tmp")
    tmp.write_text(json.dumps(feed, ensure_ascii=False), encoding="utf-8")
    tmp.replace(feed_path)
except OSError as e:
    print("лента для админки не записана:", e)

if os.environ.get("AI_EDITOR_DRY"):  # песочница: страница — в файл, ничего не публикуем и state не трогаем
    (RUN / "page.html").write_text(page, encoding="utf-8")
    (RUN / "proposals.json").write_text(json.dumps(props, ensure_ascii=False, indent=1), encoding="utf-8")
    sys.exit(print("DRY: run/page.html, run/proposals.json"))
env = dict(l.strip().split("=", 1) for l in open(Path.home() / ".config" / "ai-editor-publish.env", encoding="utf-8")  # отдельно: Claude этот файл не видит
           if "=" in l and not l.startswith("#"))
data = urllib.parse.urlencode({"token": env["AI_EDITOR_PUBLISH_TOKEN"], "html": page}).encode()
for attempt in range(1, 5):
    try:
        r = urllib.request.urlopen(urllib.request.Request(env["AI_EDITOR_PUBLISH_URL"], data=data), timeout=40)
        print(r.status, r.read().decode(), "| предложений:", {b: len(v) for b, v in blocks.items()})
        break
    except OSError as e:
        print("попытка", attempt, e)
        time.sleep(6)
else:
    sys.exit("не опубликовано")

(STATE / "proposals.json").write_text(json.dumps(props, ensure_ascii=False, indent=1), encoding="utf-8")
(STATE / "log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
(STATE / "taken.json").write_text(json.dumps(taken[:50], ensure_ascii=False, indent=1), encoding="utf-8")
started = RUN / "started.txt"
if not failed:
    for f in ("site_max_id.txt", "feed_last.txt"):
        if (RUN / f).exists():
            (STATE / f).write_text((RUN / f).read_text())
    (STATE / "last_run.txt").write_text(started.read_text() if started.exists() else now.isoformat(timespec="seconds"))
