# Шаг 1 прогона: собрать вход для Claude -> run/input.md.
# Лента RU-сборщика + лента сайта (с очередью) + VK/Telegram (social.py).
import datetime as dt
import json
import os
import time
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path

import social

BASE = Path(__file__).resolve().parent
RUN = BASE / "run"
STATE = BASE / "state"
RUN.mkdir(exist_ok=True)
STATE.mkdir(exist_ok=True)
SAM = dt.timezone(dt.timedelta(hours=4))
SITE_URL = "https://www.syzran-small.ru/rss-claude.php?limit=80"
TEXT_MAX = 1800
FIRST_RUN_HOURS = 6

now = dt.datetime.now(SAM)
last_file = STATE / "last_run.txt"
last = dt.datetime.fromisoformat(last_file.read_text().strip()) if last_file.exists() else now - dt.timedelta(hours=FIRST_RUN_HOURS)


# Верхняя граница окна — только для песочницы (повтор прошлого окна); в бою — сейчас
UNTIL = dt.datetime.fromisoformat(os.environ["AI_EDITOR_UNTIL"]) if os.environ.get("AI_EDITOR_UNTIL") else now


def get(url, tries=4):
    for attempt in range(1, tries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            return urllib.request.urlopen(req, timeout=60).read()
        except OSError as e:
            if attempt == tries:
                raise
            if url.startswith("https://") and attempt >= 2:
                url = "http://" + url[len("https://"):]  # syzran-small.ru режет HTTPS с KZ IP
            time.sleep(6)


def sam(s):
    return dt.datetime.fromisoformat(s).astimezone(SAM) if s else None


n_new = 0  # всего нового (сборщик + VK/TG)
sources = {}  # url -> полный текст материала (run/sources.json): по нему пишут рерайт и фактчек
out = [f"# Вход прогона {now:%d.%m.%Y %H:%M} (Самара). Прошлый прогон: {last:%d.%m %H:%M}\n"]

# --- лента сборщика; недоступна — прогон идёт без неё (сайт + VK/TG), на странице предупреждение.
# Своя отметка feed_last: сдвигается только после успешного чтения, чтобы засечённое
# за время сбоя разобрал следующий прогон (окно ленты — 48 ч)
for f in ("feed_last.txt", "warnings.txt", "social_seen.json"):
    (RUN / f).unlink(missing_ok=True)
feed_last_file = STATE / "feed_last.txt"
feed_last = dt.datetime.fromisoformat(feed_last_file.read_text().strip()) if feed_last_file.exists() else last
try:
    feed = json.loads(get(os.environ["AI_EDITOR_FEED_URL"], tries=3))
except (OSError, ValueError) as e:
    feed = None
    reason = f"{type(e).__name__}: {e}"[:160]
    print("сборщик недоступен:", reason)
    (RUN / "warnings.txt").write_text(f"сборщик на RU VPS недоступен с {feed_last:%d.%m %H:%M} ({reason}) — прогон только по сайту и VK/Telegram",
                                      encoding="utf-8")
    out.append(f"## ⚠ Лента сборщика НЕДОСТУПНА ({reason}). Первоисточники и СМИ в этом прогоне не видны — "
               f"работай по VK/Telegram и сайту; засечённое сборщиком с {feed_last:%d.%m %H:%M} придёт в следующем успешном прогоне.\n")
if feed is not None:
    bad = [s["source"] for s in feed["sources"] if s["status"] != 200]
    out.append(f"Сборщик сформирован {sam(feed['generated_at']):%H:%M}; источники не 200: {bad or 'нет'}\n")
    out.append(f"## Новое про Сызрань в ленте сборщика (засечено после {feed_last:%d.%m %H:%M})\n")
    n = 0
    for i in feed["items"]:
        if i["syzran"] and feed_last < sam(i["detected_at"]) <= UNTIL:
            p = sam(i["published_at"])
            n += 1
            n_new += 1
            sources[i["url"]] = {"name": i["source"], "title": i["title"], "text": i["text"] or "",
                                 "published": p.strftime("%d.%m.%Y %H:%M") if p else ""}
            out.append(f"### [{i['kind']}] {i['source']} | {p.strftime('%d.%m %H:%M') if p else 'без даты'} | {i['title']}\n"
                       f"{i['url']}\n{(i['text'] or '')[:TEXT_MAX]}\n")
    if not n:
        out.append("(нет)\n")
    (RUN / "feed_last.txt").write_text(now.isoformat(timespec="seconds"))  # finish.py переносит в state/ только при успехе

# --- VK/Telegram: новые посты пабликов (social.py; то, чего ещё не видели, — за сутки)
out.append("## Новое в VK/Telegram\n")
posts = social.collect(now) if not os.environ.get("AI_EDITOR_UNTIL") else []  # песочница с прошлым окном — без соцсетей
for p in posts:
    n_new += 1
    when = p["published"].strftime("%d.%m %H:%M") if p["published"] else "без даты"
    text = " ".join(p["text"].split())
    sources[p["url"]] = {"name": p["source"], "title": p["title"], "text": text,
                         "published": p["published"].strftime("%d.%m.%Y %H:%M") if p["published"] else ""}
    out.append(f"### {p['source']} | {when} | {p['title']}\n{p['url']}\n{text[:TEXT_MAX]}\n")
if not posts:
    out.append("(нет)\n")

# --- сайт: последние 40 новостей; лиды — только за 12 ч; НОВОЕ = id больше, чем в прошлый прогон
root = ET.fromstring(get(SITE_URL))
max_file = STATE / "site_max_id.txt"
prev_max = int(max_file.read_text()) if max_file.exists() else 0
site_new = 0
cur_max = prev_max
out.append("## Сайт syzran-small.ru: последние 40 новостей (ПЛАН = в очереди редакции; НОВОЕ = появилось с прошлого прогона; лид — только за 12 ч)\n")
for it in root.findall("./channel/item")[:40]:
    d = parsedate_to_datetime(it.findtext("pubDate")).astimezone(SAM)
    if os.environ.get("AI_EDITOR_UNTIL") and d > UNTIL:  # песочница: сайт на момент конца окна
        continue
    nid = int(it.findtext("link").rsplit("-", 1)[-1])
    cur_max = max(cur_max, nid)
    is_new = nid > prev_max
    site_new += is_new
    lead = " ".join((it.findtext("home-text") or "").split())[:220] if (is_new or now - d < dt.timedelta(hours=12)) else ""
    out.append(f"- {'НОВОЕ ' if is_new else ''}{'ПЛАН ' if d > now else ''}{d:%d.%m %H:%M} news-{nid} | {it.findtext('title')}" + (f" — {lead}" if lead else ""))
(RUN / "site_max_id.txt").write_text(str(cur_max))  # finish.py переносит в state/ только при успехе

# --- наши предложения: компактная сводка (полный JSON — state/proposals.json, читать только для update)
props = json.loads((STATE / "proposals.json").read_text(encoding="utf-8")) if (STATE / "proposals.json").exists() else []
out.append(f"\n## Наши предложения на странице сейчас ({len(props)}); полные поля — state/proposals.json (читать, только если нужно update)\n")
for p in props:
    age = (now - dt.datetime.fromisoformat(p["detected_at"])).total_seconds() / 3600
    first = p.get("lead", "").split(". ")[0][:160]
    out.append(f"- {p['id']} | {p['block']} | в выдаче {age:.1f} ч | {p['headlines'][0]} — {first}")

(RUN / "started.txt").write_text(now.isoformat(timespec="seconds"))
(RUN / "sources.json").write_text(json.dumps(sources, ensure_ascii=False), encoding="utf-8")
(RUN / "input.md").write_text("\n".join(out) + "\n", encoding="utf-8")
print(f"input.md: {sum(len(x) for x in out)} символов")

# Нового нет — Claude не зовём: страница обновится с этой строкой (run.sh видит код 3)
if n_new == 0 and site_new == 0:
    (RUN / "changes.json").write_text(json.dumps({
        "latest": f"ИИ-редактор: с {last:%H:%M} новых сызранских новостей и публикаций на сайте нет — предложения без изменений (итоговые баллы пересчитаны).",
        "log": "ИИ-редактор: нового нет, Claude не вызывался", "drop": [], "add": [], "update": [], "skipped": []},
        ensure_ascii=False), encoding="utf-8")
    print("нового нет — Claude не нужен")
    raise SystemExit(3)
