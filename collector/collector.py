#!/usr/bin/env python3
"""Сборщик новостей о Сызрани для ИИ-редактора (syzran-small.ru).

Один файл, только стандартная библиотека Python 3.8+ — ничего ставить не нужно.
Запускается по cron на VPS с российским IP: обходит RSS-ленты первоисточников
и СМИ + главную КТВ-ЛУЧ и кладёт всё свежее в один JSON, который отдаёт nginx.

    python3 collector.py --probe                     # разовая проверка доступа к источникам
    python3 collector.py --out /var/www/html/x/news.json   # сбор (для cron)

Состояние (когда какую новость увидели впервые) — в collector_state.json рядом
со скриптом.
"""
import argparse
import html
import json
import os
import re
import ssl
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

VERSION = "2026-09-25.2"
WINDOW_HOURS = 48          # сколько часов новостей держать в JSON
STATE_KEEP_HOURS = 96      # сколько помнить «время засечки»
FULLTEXT_MAX = 40          # сколько сызранских статей за прогон дотягивать целиком
TIMEOUT = 20
RETRIES = 3
RETRY_PAUSE = 5
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")

# kind: primary — первоисточник; media — СМИ (своё + перепечатки);
# aggregator — только чтобы найти тему, первоисточником не бывает.
# city: True — чисто городской источник, всё его — про Сызрань.
# verify: False — сертификат областного департамента ИТ (браузеры РФ доверяют, Python — нет).
# clamp: True — сайт ставит время в ленту «наперёд».
SOURCES = [
    {"name": "ГУ МВД по Самарской области", "kind": "primary", "type": "rss", "url": "https://63.xn--b1aew.xn--p1ai/news/rss"},
    {"name": "Прокуратура Самарской области", "kind": "primary", "type": "rss", "url": "https://epp.genproc.gov.ru/ru/proc_63/rss/"},
    {"name": "ГУ МЧС по Самарской области", "kind": "primary", "type": "rss", "url": "https://63.mchs.gov.ru/deyatelnost/press-centr/novosti/rss"},
    {"name": "Администрация г.о. Сызрань", "kind": "primary", "type": "rss", "url": "https://adm-syzran.ru/?id=4&type=9818",
     "city": True, "verify": False, "clamp": True},
    # Открываются только с российского IP (проверено --probe 25.09.2026):
    {"name": "Правительство Самарской области", "kind": "primary", "type": "rss", "url": "https://www.samregion.ru/feed/"},
    {"name": "Минтранс Самарской области", "kind": "primary", "type": "rss", "url": "https://mintrans.samregion.ru/feed/"},
    {"name": "СК по Самарской области", "kind": "primary", "type": "html_list", "url": "https://samara.sledcom.ru/news",
     "link_pattern": r"/news/item/(?P<id>\d+)/?$", "max_items": 20},
    {"name": "Дума г.о. Сызрань", "kind": "primary", "type": "rss", "url": "https://syzran.samgd.ru/?format=feed&type=rss",
     "city": True, "verify": False},
    {"name": "КТВ-ЛУЧ", "kind": "media", "type": "rss", "url": "https://ktv-ray.ru/feed.rss"},
    {"name": "КТВ-ЛУЧ (главная)", "kind": "media", "type": "html_list", "url": "https://ktv-ray.ru/",
     "link_pattern": r"^/novost/[^/]+/(?P<id>\d+)/?$", "max_items": 25},
    {"name": "Волга Ньюс", "kind": "media", "type": "rss", "url": "https://volga.news/rss"},
    {"name": "63.ru", "kind": "media", "type": "rss", "url": "https://63.ru/rss-feeds/rss.xml"},
    {"name": "Самарская газета", "kind": "media", "type": "rss", "url": "https://sgpress.ru/feed"},
    {"name": "ГТРК Самара", "kind": "media", "type": "rss", "url": "https://tvsamara.ru/rss/"},
    {"name": "Самарское обозрение", "kind": "media", "type": "rss", "url": "https://oboz.info/feed/"},
    {"name": "Коммерсантъ-Волга", "kind": "media", "type": "rss", "url": "https://www.kommersant.ru/rss/regions/samara.xml"},
    {"name": "БезФормата — Сызрань", "kind": "aggregator", "type": "rss", "url": "https://sizran.bezformata.com/rss.xml"},
    {"name": "Самара 450", "kind": "aggregator", "type": "rss", "url": "https://450media.ru/rss"},
    {"name": "Google News: Сызрань", "kind": "aggregator", "type": "rss",
     "url": "https://news.google.com/rss/search?q=%D0%A1%D1%8B%D0%B7%D1%80%D0%B0%D0%BD%D1%8C&hl=ru&gl=RU&ceid=RU:ru"},
]

# Сайты, которые с казахстанского IP не открываются: --probe проверяет их
# отсюда и ищет RSS; найденное потом переносится в SOURCES.
PROBE_PAGES = [
    ("Роспотребнадзор-63", "https://63.rospotrebnadzor.ru/"),
    ("Сызранская епархия", "https://syzran-eparhia.ru/novosti/novosti-eparkhii.html"),
    ("Сызранский горсуд", "https://sizransky--sam.sudrf.ru/"),
    ("Самарская ППК", "https://samppk.ru/"),
    ("Приволжское УГМС", "https://pogoda-sv.ru/"),
]
PROBE_PATHS = ["/rss", "/rss/", "/rss.xml", "/feed", "/feed/", "/news/rss", "/news/rss/", "/news/rss.xml",
               "/rss/news", "/index.rss", "/?format=feed&type=rss"]

SSL_OFF = ssl.create_default_context()
SSL_OFF.check_hostname = False
SSL_OFF.verify_mode = ssl.CERT_NONE


def now_utc():
    return datetime.now(timezone.utc)


def fetch(url, verify=True, limit=3_000_000):
    """(status, final_url, text); повторы при обрыве соединения."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ru-RU,ru;q=0.9"})
    last = ""
    for attempt in range(1, RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT, context=None if verify else SSL_OFF) as r:
                raw = r.read(limit)
                cs = r.headers.get_content_charset()
                if not cs:
                    m = re.search(rb'charset=["\']?([\w-]+)', raw[:2000])
                    cs = m.group(1).decode() if m else "utf-8"
                return r.status, r.geturl(), raw.decode(cs, "replace")
        except urllib.error.HTTPError as e:
            return e.code, url, ""
        except Exception as e:  # обрыв, таймаут, SSL
            last = f"{type(e).__name__}: {e}"
            if attempt < RETRIES:
                time.sleep(RETRY_PAUSE)
    return 0, url, last


def clean(text):
    text = re.sub(r"<!\[CDATA\[|\]\]>", "", text or "")
    text = re.sub(r"<(br|/p|/div|/li)\b[^>]*>", " ", text, flags=re.I)
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    return re.sub(r"\s+", " ", text).strip()


def parse_date(s):
    if not s:
        return None
    s = s.strip()
    try:
        d = parsedate_to_datetime(s)
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone(timedelta(hours=3)))
    if d.year < 100:  # МЧС пишет год двумя цифрами
        d = d.replace(year=d.year + 2000)
    return d.astimezone(timezone.utc)


def local(tag):
    return tag.rsplit("}", 1)[-1]


def parse_feed(text):
    """RSS 2.0 / Atom -> [(title, link, summary, pub_dt)]; при битом XML — регулярками."""
    out = []
    try:
        root = ET.fromstring(text.encode("utf-8"))
        for el in root.iter():
            if local(el.tag) not in ("item", "entry"):
                continue
            f = {}
            for ch in el:
                name = local(ch.tag)
                if name == "link" and ch.get("href"):
                    f.setdefault("link", ch.get("href"))
                elif ch.text:
                    f.setdefault(name, ch.text)
            summary = f.get("full-text") or f.get("encoded") or f.get("description") or f.get("summary") or f.get("content") or ""
            out.append((clean(f.get("title")), (f.get("link") or "").strip(), clean(summary),
                        parse_date(f.get("pubDate") or f.get("published") or f.get("updated") or f.get("date"))))
        return out
    except ET.ParseError:
        pass
    for it in re.findall(r"<item\b.*?</item>", text, re.S):
        g = lambda t: (re.search(rf"<{t}\b[^>]*>(.*?)</{t}>", it, re.S) or [None, ""])[1]
        out.append((clean(g("title")), clean(g("link")), clean(g("description")), parse_date(clean(g("pubDate")))))
    return out


def parse_html_list(src, text, base):
    pat = re.compile(src["link_pattern"])
    best = {}
    for href, inner in re.findall(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', text, re.S):
        m = pat.search(href)
        if not m:
            continue
        title = clean(inner)
        nid = int(m.group("id"))
        if len(title) > len(best.get(nid, ("", ""))[1]):
            best[nid] = (urllib.parse.urljoin(base, href), title)
    res = []
    for nid in sorted(best, reverse=True)[: src.get("max_items", 20)]:
        link, title = best[nid]
        if len(title) >= 15:
            res.append((title, link, "", None))
    return res


def article_text(url, verify=True):
    """Грубое извлечение текста статьи: абзацы <p> длиннее 40 символов."""
    st, _, page = fetch(url, verify=verify, limit=1_500_000)
    if st != 200:
        return ""
    page = re.sub(r"<(script|style|nav|footer|header)\b.*?</\1>", " ", page, flags=re.S | re.I)
    paras = [clean(p) for p in re.findall(r"<p\b[^>]*>(.*?)</p>", page, re.S | re.I)]
    return " ".join(p for p in paras if len(p) > 40)[:8000]


def is_syzran(src, title, summary):
    return bool(src.get("city")) or "сызран" in f"{title} {summary}".lower()


def load_state(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def write_atomic(path, data):
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def collect(out_path):
    started = now_utc()
    state_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "collector_state.json")
    state = load_state(state_path)  # url -> {"detected_at": iso, "text": "..."}
    items, report = [], []
    window_start = started - timedelta(hours=WINDOW_HOURS)
    fulltext_budget = FULLTEXT_MAX

    for src in SOURCES:
        verify = src.get("verify", True)
        st, final, text = fetch(src["url"], verify=verify)
        if st != 200:
            report.append({"source": src["name"], "status": st, "error": text[:200] if st == 0 else ""})
            continue
        entries = parse_html_list(src, text, final) if src["type"] == "html_list" else parse_feed(text)
        kept = 0
        for title, link, summary, pub in entries:
            if not title or not link:
                continue
            if pub and src.get("clamp") and pub > started:
                pub = started
            if pub and pub < window_start:
                continue
            seen = state.setdefault(link, {"detected_at": started.isoformat()})
            detected = datetime.fromisoformat(seen["detected_at"])
            if not pub and detected < window_start:
                continue
            syz = is_syzran(src, title, summary)
            full = seen.get("text", "")
            if syz and not full and len(summary) < 600 and fulltext_budget > 0 and "news.google.com" not in link:
                fulltext_budget -= 1
                full = article_text(link, verify=verify)
                seen["text"] = full
            items.append({
                "source": src["name"],
                "kind": src["kind"],
                "published_at": pub.isoformat() if pub else None,
                "detected_at": seen["detected_at"],
                "title": title,
                "text": full if len(full) > len(summary) else summary,
                "url": link,
                "syzran": syz,
            })
            kept += 1
        report.append({"source": src["name"], "status": 200, "entries": len(entries), "kept": kept})

    cutoff = (started - timedelta(hours=STATE_KEEP_HOURS)).isoformat()
    state = {k: v for k, v in state.items() if v.get("detected_at", "") >= cutoff}
    write_atomic(state_path, state)

    # Одна новость из двух каналов (КТВ-ЛУЧ: RSS и главная) — оставляем ту, где
    # есть дата публикации, и более полный текст.
    by_url = {}
    for it in items:
        prev = by_url.get(it["url"])
        if prev is None:
            by_url[it["url"]] = it
            continue
        keep = it if (it["published_at"] and not prev["published_at"]) else prev
        other = prev if keep is it else it
        if len(other["text"]) > len(keep["text"]):
            keep["text"] = other["text"]
        keep["syzran"] = keep["syzran"] or other["syzran"]
        by_url[it["url"]] = keep
    items = list(by_url.values())
    items.sort(key=lambda i: i["published_at"] or i["detected_at"], reverse=True)
    write_atomic(out_path, {
        "generated_at": started.isoformat(),
        "collector_version": VERSION,
        "window_hours": WINDOW_HOURS,
        "sources": report,
        "items": items,
    })
    ok = sum(1 for r in report if r["status"] == 200)
    print(f"{started:%Y-%m-%d %H:%M} UTC: источников ок {ok}/{len(SOURCES)}, новостей {len(items)} "
          f"(про Сызрань {sum(i['syzran'] for i in items)}) -> {out_path}")


def probe():
    print(f"collector {VERSION}: проверка доступа с этого сервера\n")
    print("== Источники из SOURCES")
    for src in SOURCES:
        st, _, text = fetch(src["url"], verify=src.get("verify", True))
        n = len(parse_html_list(src, text, src["url"]) if src["type"] == "html_list" else parse_feed(text)) if st == 200 else 0
        print(f"  {'OK ' if st == 200 and n else 'ERR'} {st:3} записей={n:3}  {src['name']}" + (f"  [{text[:80]}]" if st == 0 else ""))
        if src["type"] == "html_list" and st == 200 and not n:
            sample = [h for h in dict.fromkeys(re.findall(r'href="([^"]+)"', text)) if "news" in h or "novost" in h][:10]
            print("      шаблон ссылок не совпал; ссылки на странице:", *sample, sep="\n        ")
    print("\n== Сайты, закрытые с казахстанского IP: доступ и поиск RSS")
    for name, url in PROBE_PAGES:
        st, final, page = fetch(url, verify=False)
        print(f"  {st:3} {name}: {url}" + (f"  [{page[:80]}]" if st == 0 else ""))
        if st != 200:
            continue
        cands = [urllib.parse.urljoin(final, html.unescape(h)) for h in
                 re.findall(r'<link[^>]+type="application/(?:rss|atom)\+xml"[^>]*href="([^"]+)"', page)]
        root = "{0.scheme}://{0.netloc}".format(urllib.parse.urlsplit(final))
        found = 0
        shown = set()
        for c in list(dict.fromkeys(cands + [root + p for p in PROBE_PATHS])):
            s2, f2, t2 = fetch(c, verify=False, limit=500_000)
            if s2 == 200 and f2 not in shown and re.search(r"<(rss|feed|rdf:RDF)\b", t2[:3000]):
                shown.add(f2)
                ents = parse_feed(t2)
                last = max((e[3] for e in ents if e[3]), default=None)
                print(f"      RSS: {f2}  записей={len(ents)}  свежая={last:%d.%m.%Y}" if last else f"      RSS: {f2}  записей={len(ents)}")
                found += 1
                if found >= 2:
                    break
        if not found:
            print("      RSS не найдена")
    print("\nГотово. Пришлите этот вывод целиком.")


def main():
    ap = argparse.ArgumentParser(description="Сборщик новостей о Сызрани -> JSON")
    ap.add_argument("--out", help="куда положить news.json (папка, которую отдаёт nginx)")
    ap.add_argument("--probe", action="store_true", help="проверить доступ к источникам и найти RSS")
    a = ap.parse_args()
    if a.probe:
        probe()
    elif a.out:
        collect(a.out)
    else:
        ap.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
