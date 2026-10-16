# Посчитать неделю: python analyze.py <папка>  (папка от fetch_data.py) -> <папка>/stats.json
# Источник правды — архив страниц предложений: карточки (блок, балл, источник), раздел
# «Отсеяно в этом прогоне», список «Редакция взяла наши предложения»; плюс логи прогонов
# (длительность, стоимость, вердикты фактчека), лог рерайта админки и лента сайта.
import datetime as dt
import html
import json
import re
import statistics as st
import sys
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # консоль Windows — cp1252

SAM = dt.timezone(dt.timedelta(hours=4))
W = Path(sys.argv[1])
meta = json.loads((W / "meta.json").read_text(encoding="utf-8"))
D0 = dt.datetime.fromisoformat(meta["week"]).replace(tzinfo=SAM)
D1 = D0 + dt.timedelta(days=5)
DAYS = [D0 + dt.timedelta(days=i) for i in range(5)]
SKIP_KINDS = ("уже на сайте", "только КТВ-ЛУЧ / нет первоисточника", "дубль нашего предложения", "не про Сызрань",
              "PR, анонсы, мало фактов")


def txt(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def label_key(label):
    return re.sub(r"^\[[^\]]*\]\s*", "", label)


def reason_kind(r):
    """Причина отсева по ключевым словам (±5–10%). Порядок проверок важен."""
    r = r.lower()
    if re.search(r"убрал из (очереди|запаса)", r):
        return "вытеснено лимитом"
    if re.search(r"предложени[еия] [a-z0-9-]{6,}|уже в резерве|уже в запасе|уже выставленн|нашем предложени|нашего предложени"
                 r"|наш дубл|в предложк|та же новость, что|тот же материал, что|повтор", r):
        return "дубль нашего предложения"
    if re.search(r"опубликован|news-\d|уже на сайте|уже есть на сайте|в очереди редакции|сайт дал|сайт уже|запланирован", r):
        return "уже на сайте"
    if re.search(r"не про сызран|без сызранск|нет сызранск|не сызранск|не относится к сызран|правило 4|город издания|другого город"
                 r"|сызрань только упомина|только упомина|про [а-я]+ район|не в сызрани|нет привязки к сызран|слабая связь с сызран"
                 r"|не о сызрани", r):
        return "не про Сызрань"
    if re.search(r"только ктв|первоисточник[а]? (не найден|нет)|первоисточника нет|не наш[её]л|нет фактур|только заголов", r):
        return "только КТВ-ЛУЧ / нет первоисточника"
    return "PR, анонсы, мало фактов"


def src_kind(u):
    u = u.lower()
    if "ktv-ray" in u or "ktv_ray" in u:
        return "КТВ-ЛУЧ"
    if "vk.com" in u or "vk.ru" in u or "t.me" in u:
        return "VK/Telegram"
    if "bezformata" in u or "450media" in u or "news.google" in u:
        return "Агрегаторы"
    return "Официальные и прочие СМИ"


# --- страницы
pages = sorted((W / "pages" / "archive").glob("digest_*.html")) + [W / "pages" / "index.html"]
props, skipped, taken, carry, page_times = {}, {}, {}, set(), []
for f in pages:
    if not f.exists():
        continue
    s = f.read_text(encoding="utf-8")
    m = re.search(r"Дайджест обновлён:</strong>\s*(\d\d\.\d\d\.\d{4} \d\d:\d\d)", s)
    if not m:
        continue
    t = dt.datetime.strptime(m.group(1), "%d.%m.%Y %H:%M").replace(tzinfo=SAM)
    if t < D0:  # последняя страница прошлой недели: её предложения — переходящие
        carry.update(label_key(txt(h)) for h in re.findall(r"<h3>(.*?)</h3>", s, re.S))
        continue
    if t >= D1 or t in page_times:
        continue
    page_times.append(t)
    block = None
    for part in re.split(r'(<h2 class="block [a-z]+">)', s):
        b = re.match(r'<h2 class="block ([a-z]+)">', part)
        if b:
            block = b.group(1)
            continue
        if block in ("urgent", "queue", "reserve"):
            for a in re.findall(r"<article>(.*?)</article>", part, re.S):
                label = txt(re.search(r"<h3>(.*?)</h3>", a, re.S).group(1))
                key = label_key(label)
                ol = re.search(r"<ol>(.*?)</ol>", a, re.S)
                heads = [txt(x) for x in re.findall(r"<li>(.*?)</li>", ol.group(1), re.S)] if ol else []
                sc = re.search(r'<span class="score">([\d.]+)</span>(?: базовый ([\d.]+))?', a)
                src = re.search(r'<strong>Источник:</strong>\s*<a href="([^"]+)">', a)
                p = props.setdefault(key, {"key": key, "first": t, "block": block, "heads": set(),
                                           "base": float(sc.group(2) or sc.group(1)) if sc else None,
                                           "update": label.startswith("[ОБНОВЛЕНИЕ"), "src": src.group(1) if src else ""})
                p["heads"].update(heads)
        if block == "skip":
            for li in re.findall(r"<li>(.*?)</li>", part, re.S):
                r = re.match(r"\s*<strong>(.*?)</strong>(.*)", li, re.S)
                if r:
                    k = txt(r.group(2))
                    if not re.match(r"\d\d\.\d\d \d\d:\d\d", k):
                        skipped.setdefault(k, txt(r.group(1)) + " " + k)
    for d, hd, nid in re.findall(r'<li>(\d\d-\d\d \d\d:\d\d): (.*?) → <a href="https://www\.syzran-small\.ru/news-(\d+)">', s):
        taken.setdefault(nid, (dt.datetime.strptime(f"{D0.year}-{d}", "%Y-%m-%d %H:%M").replace(tzinfo=SAM), txt(hd)))

# --- сайт
site = {}
for it in ET.parse(W / "site.xml").getroot().findall("./channel/item"):
    site[it.findtext("link").rsplit("-", 1)[-1]] = {"pub": parsedate_to_datetime(it.findtext("pubDate")).astimezone(SAM),
                                                   "hits": int(it.findtext("hits") or 0)}
now = dt.datetime.now(SAM)
end = min(D1, now)
site_week = {k: v for k, v in site.items() if D0 <= v["pub"] < end}
if min((v["pub"] for v in site.values()), default=end) > D0:
    print("⚠ лента сайта не покрывает начало недели — увеличьте limit в fetch_data.py")

# --- взятые: снято за неделю и вышло на сайте на этой неделе
week_props = [p for p in props.values() if D0 <= p["first"] < D1 and p["key"] not in carry]
week_keys = {p["key"] for p in week_props}
rows = []
for nid, (when, hd) in taken.items():
    if not (D0 <= when < D1 and nid in site_week):
        continue
    p = next((p for p in props.values() if hd in p["heads"] or hd == p["key"]), None)
    rows.append({"nid": nid, "when": when, "head": hd, "prop": p and p["key"], "carry": bool(p and p["key"] not in week_keys),
                 "first": p and p["first"], "lead_min": (site[nid]["pub"] - p["first"]).total_seconds() / 60 if p else None,
                 "hits": site[nid]["hits"]})
taken_keys = {r["prop"] for r in rows if r["prop"]}
taken_nids = {r["nid"] for r in rows}


def share(pred):
    sel = [p for p in week_props if pred(p)]
    return [len(sel), sum(1 for p in sel if p["key"] in taken_keys)]


# --- логи прогонов
runs = []
for d in DAYS:
    f = W / "logs" / f"run_{d:%Y-%m-%d}.log"
    if not f.exists():
        continue
    for chunk in f.read_text(encoding="utf-8").split("===== ")[1:]:
        m = re.match(r"(\S+ \S+) старт", chunk)
        if not m:
            continue
        r = {"t": m.group(1), "empty": "нового нет" in chunk, "published": '"status":"ok"' in chunk}
        c = re.search(r"claude exit=(\d+) is_error (\w+) turns (\d+) ms (\d+) cost ([\d.]+)", chunk)
        if c:
            r.update(turns=int(c.group(3)), ms=int(c.group(4)), cost=float(c.group(5)), err=c.group(2) == "True" or c.group(1) != "0")
        s2 = re.search(r"рерайт\+фактчек: (\d+) новостей за (\d+) с, cost ([\d.]+); (.*)", chunk)
        if s2:
            r.update(st_cost=float(s2.group(3)), verdicts=[x.split(": ")[1] for x in s2.group(4).split(", ") if ": " in x])
        r["fail"] = bool("Traceback" in chunk or "упал" in chunk or r.get("err") or not r["published"])
        runs.append(r)
ms = [r["ms"] for r in runs if "ms" in r]
verd = [v for r in runs for v in r.get("verdicts", [])]

# --- рерайт в админке
rw = {"ok": 0, "error": 0}
for f in (W / "logs").glob("rewrite_*.log"):
    for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"(\d{4}-\d\d-\d\d) \S+ \S+ (ok|error)\b", line)
        if m and D0.date() <= dt.date.fromisoformat(m.group(1)) < D1.date():
            rw[m.group(2)] += 1

sk = {k: 0 for k in SKIP_KINDS + ("вытеснено лимитом",)}
for v in skipped.values():
    sk[reason_kind(v)] += 1
lead = sorted(r["lead_min"] for r in rows if r["lead_min"] is not None)
fmt = lambda x: x.strftime("%d.%m %H:%M") if isinstance(x, dt.datetime) else x
out = {
    "week": meta["week"], "days": [f"{d:%d.%m}" for d in DAYS], "data_until": fmt(min(now, max(page_times, default=now))),
    "pages": len(page_times),
    "proposals": len(week_props), "proposals_updates": sum(p["update"] for p in week_props),
    "materials": len(week_props) + sum(v for k, v in sk.items() if k != "вытеснено лимитом"),
    "skip_reasons": sk,
    "taken": len(rows), "taken_from_week": sum(1 for r in rows if not r["carry"]), "taken_carry": sum(1 for r in rows if r["carry"]),
    "site_week": len(site_week),
    "lead_minutes": lead, "lead_median": st.median(lead) if lead else None,
    "lead_buckets": {k: sum(1 for x in lead if f(x)) for k, f in (
        ("сайт раньше нас", lambda x: x < 0), ("0–30 мин", lambda x: 0 <= x < 30), ("30–60 мин", lambda x: 30 <= x < 60),
        ("1–2 ч", lambda x: 60 <= x < 120), ("2–6 ч", lambda x: 120 <= x < 360), ("больше 6 ч", lambda x: x >= 360))},
    "by_day": [{"day": f"{d:%d.%m}", "site": sum(1 for v in site_week.values() if d <= v["pub"] < d + dt.timedelta(days=1)),
                "props": sum(1 for p in week_props if d <= p["first"] < d + dt.timedelta(days=1)),
                "taken": sum(1 for r in rows if d <= r["when"] < d + dt.timedelta(days=1))} for d in DAYS],
    "by_block": {b: share(lambda p, b=b: p["block"] == b) for b in ("urgent", "queue", "reserve")},
    "by_score": {"1.2+": share(lambda p: p["base"] is not None and p["base"] >= 1.2),
                 "0.9–1.2": share(lambda p: p["base"] is not None and 0.9 <= p["base"] < 1.2),
                 "<0.9": share(lambda p: p["base"] is not None and p["base"] < 0.9)},
    "by_source": {k: share(lambda p, k=k: src_kind(p["src"]) == k) for k in ("КТВ-ЛУЧ", "VK/Telegram", "Официальные и прочие СМИ", "Агрегаторы")},
    "runs": len(runs), "runs_empty": sum(r["empty"] for r in runs), "runs_claude": len(ms),
    "runs_fail": [r["t"] for r in runs if r["fail"]],
    "duration_median_min": round(st.median(ms) / 60000, 1) if ms else None, "duration_mean_min": round(st.mean(ms) / 60000, 1) if ms else None,
    "duration_max_min": round(max(ms) / 60000) if ms else None,
    "turns_median": st.median([r["turns"] for r in runs if "turns" in r]) if ms else None,
    "cost": round(sum(r.get("cost", 0) + r.get("st_cost", 0) for r in runs), 2),
    "cost_by_day": {f"{d:%d.%m}": round(sum(r.get("cost", 0) + r.get("st_cost", 0) for r in runs if r["t"].startswith(f"{d:%Y-%m-%d}")), 2) for d in DAYS},
    "factcheck": {"items": len(verd), "ok": verd.count("ok"),
                  "fixed": sum(1 for v in verd if v.endswith("/ok") and v != "ok"),
                  "left": sum(1 for v in verd if not v.endswith("ok"))},
    "admin_rewrite": rw,
    "hits_share": round(sum(site_week[n]["hits"] for n in taken_nids) / max(1, sum(v["hits"] for v in site_week.values())) * 100, 1),
    "hits_taken_median": st.median([site_week[n]["hits"] for n in taken_nids]) if taken_nids else None,
    "hits_other_median": st.median([v["hits"] for k, v in site_week.items() if k not in taken_nids]) if site_week else None,
    "urgent_titles": [p["key"] for p in week_props if p["block"] == "urgent"],
    "taken_rows": [{k: fmt(v) for k, v in r.items()} for r in sorted(rows, key=lambda r: r["when"])],
    "skipped_samples": {k: [v[:160] for v in skipped.values() if reason_kind(v) == k][:8] for k in sk},
}
(W / "stats.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps({k: v for k, v in out.items() if k not in ("taken_rows", "skipped_samples", "lead_minutes")}, ensure_ascii=False))
