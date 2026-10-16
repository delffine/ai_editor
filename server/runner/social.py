# VK и Telegram для входа прогона: свежие сызранские посты пабликов, которых нет в RSS.
# Только stdlib. VK — API wall.get (нужен VK_ACCESS_TOKEN в окружении), Telegram —
# публичное веб-превью t.me/s/<канал> (без токена). Перенесено 16.10.2026 из
# syzran-news (sources/vk_source.py, telegram_source.py, textclean.py, filters.py).
#
# collect(now) -> список новых постов (ссылки, которых ещё не видели), у каждого
# detected_at = now. Что уже видели — state/social_seen.json (ссылка -> когда
# впервые увидели), старше SEEN_HOURS забывается. Новая версия пишется в
# run/social_seen.json, в state/ её переносит finish.py только при успешном прогоне
# (как feed_last) — иначе посты из упавшего прогона пропали бы.
import datetime as dt
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
SEEN_FILE, SEEN_OUT = BASE / "state" / "social_seen.json", BASE / "run" / "social_seen.json"
FRESH_HOURS = 24   # пост старше суток — не новость
SEEN_HOURS = 72
TIMEOUT = 20
UA = "Mozilla/5.0 (compatible; SyzranNewsBot/1.0)"

# city=True — чисто городской паблик: слово «Сызрань» в постах не пишут, фильтр не нужен
SOURCES = [
    {"name": "КТВ-ЛУЧ (Telegram)", "tg": "ktv_ray"},
    {"name": "ГТРК Самара (Telegram)", "tg": "gtrksamara"},
    {"name": "Город Сызрань (VK)", "vk": "szradm", "city": True},
    {"name": "ГАИ Сызрани (VK)", "vk": "gai_syzran", "city": True},
    {"name": "Госавтоинспекция Самарской области (VK)", "vk": "gibddsamreg"},
    {"name": "Сызранский драмтеатр (VK)", "vk": "syzdrama", "city": True},
    {"name": "Управление культуры Сызрани (VK)", "vk": "cultura_syzran", "city": True},
    {"name": "Сызранский район (VK)", "vk": "syzrayon", "city": True},
    {"name": "Филиал СамГТУ в Сызрани (VK)", "vk": "sfsamgtu", "city": True},
    {"name": "Сызранский городской суд (VK)", "vk": "club221874654", "city": True},
    {"name": "ГУ МВД по Самарской области (VK)", "vk": "police163"},
    {"name": "Прокуратура Самарской области (VK)", "vk": "sam_proc"},
    {"name": "Комитет ЖКХ г.о. Сызрань (VK)", "vk": "kgkhsyzran", "city": True},
    {"name": "Аварийно-спасательная служба г. Сызрань (VK)", "vk": "public217592995", "city": True},
    {"name": "Поисково-спасательная служба Самарской области (VK)", "vk": "pss_so"},
]

_EMOJI = re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF\U00002B00-\U00002BFF️‍]+")
# строки-самореклама канала («Подписывайтесь…», ссылки на свои каналы) — целиком,
# вместе с короткой строкой-хвостом («…на нас в\nMAX»)
_PROMO = re.compile(r"^.*(подпис\w*|вступ\w+\s+в\s+груп|наш\s+кана|наш\s+телеграм|читайте\s+нас"
                    r"|t\.me/|vk\.com/|vk\.ru/|ok\.ru/).*$\n?(?:^.{1,25}$\n?)?", re.I | re.M)


def clean(text):
    text = _EMOJI.sub("", _PROMO.sub("", text or ""))
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n[ \t]*\n[ \t]*\n+", "\n\n", text).strip()


def vk_token():
    """Токен VK — в отдельном файле, не в ai-editor.env: тот run.sh экспортирует в
    окружение Claude Code (как и токен публикации, этот секрет агенту не нужен)."""
    f = Path.home() / ".config" / "ai-editor-vk.env"
    if not f.exists():
        return ""
    for line in f.read_text(encoding="utf-8").splitlines():
        if line.startswith("VK_ACCESS_TOKEN="):
            return line.split("=", 1)[1].strip().strip("\"'")
    return ""


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=TIMEOUT) as r:
        return r.read().decode("utf-8", "replace")


def fetch_vk(src, token):
    q = urllib.parse.urlencode({"domain": src["vk"], "count": 20, "access_token": token, "v": "5.199"})
    data = json.loads(get(f"https://api.vk.com/method/wall.get?{q}"))
    if "error" in data:
        raise RuntimeError(data["error"].get("error_msg"))
    for post in data.get("response", {}).get("items", []):
        text = clean(post.get("text"))
        if text:  # репост или фото без своего текста — брать нечего
            yield {"url": f"https://vk.com/wall{post.get('owner_id', post.get('from_id'))}_{post['id']}", "text": text,
                   "published": dt.datetime.fromtimestamp(post["date"], dt.timezone.utc)}


def fetch_tg(src):
    page = get(f"https://t.me/s/{src['tg']}")
    for block in page.split('class="tgme_widget_message_wrap')[1:]:
        m = re.search(r'class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', block, re.S)
        if not m:
            continue  # пост без текста (только фото/видео)
        raw = re.sub(r"<br\s*/?>", "\n", m.group(1))
        text = clean(html.unescape(re.sub(r"<[^>]+>", "", raw)))
        link = re.search(r'class="tgme_widget_message_date" href="([^"]+)"', block)
        when = re.search(r'<time[^>]*datetime="([^"]+)"', block)
        if text and link:
            yield {"url": link.group(1), "text": text,
                   "published": dt.datetime.fromisoformat(when.group(1)) if when else None}


def collect(now, log=print):
    """Новые сызранские посты за сутки. now — aware datetime (самарское время)."""
    seen = json.loads(SEEN_FILE.read_text(encoding="utf-8")) if SEEN_FILE.exists() else {}
    seen = {k: v for k, v in seen.items() if now - dt.datetime.fromisoformat(v) < dt.timedelta(hours=SEEN_HOURS)}
    token = os.environ.get("VK_ACCESS_TOKEN") or vk_token()
    out, errors = [], []
    for src in SOURCES:
        if "vk" in src and not token:
            errors.append(f"{src['name']}: нет VK_ACCESS_TOKEN")
            continue
        try:
            posts = list(fetch_vk(src, token) if "vk" in src else fetch_tg(src))
        except Exception as e:  # noqa: BLE001 — один паблик не валит сбор
            errors.append(f"{src['name']}: {type(e).__name__}: {e}"[:200])
            continue
        for p in posts:
            if p["url"] in seen:
                continue
            pub = p["published"]
            if pub and not dt.timedelta(hours=-1) <= now - pub <= dt.timedelta(hours=FRESH_HOURS):
                continue
            if not src.get("city") and "сызран" not in p["text"].lower():
                continue
            seen[p["url"]] = now.isoformat(timespec="seconds")
            out.append({"source": src["name"], "url": p["url"], "title": p["text"].split("\n")[0][:120],
                        "text": p["text"], "published": pub.astimezone(now.tzinfo) if pub else None,
                        "detected_at": now})
    SEEN_OUT.parent.mkdir(exist_ok=True)
    SEEN_OUT.write_text(json.dumps(seen, ensure_ascii=False), encoding="utf-8")
    if errors:
        log("VK/Telegram, не прочитано: " + "; ".join(errors))
    return out


if __name__ == "__main__":  # проверка: python3 social.py — печатает новое (state/ не трогает)
    sam = dt.timezone(dt.timedelta(hours=4))
    for p in collect(dt.datetime.now(sam), log=lambda s: print(s, file=sys.stderr)):
        print(f"{p['source']} | {p['published'] and p['published']:%d.%m %H:%M} | {p['title']}\n  {p['url']}")
