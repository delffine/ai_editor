# Слайды отчёта: python render.py <папка> --init   -> <папка>/narrative.json (черновик текстов, TODO)
#                python render.py <папка> <reports>  -> report.html + PDF в <reports>, stats_<неделя>.json рядом
# Цифры — только из stats.json; слова (заголовки, пояснения, «что изменилось», выводы) — из
# narrative.json. Пока в narrative.json есть TODO, PDF не собирается.
import json
import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # консоль Windows — cp1252

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
W = Path(sys.argv[1])
d = json.loads((W / "stats.json").read_text(encoding="utf-8"))
pct = lambda a, b: round(a / b * 100) if b else 0
props, site_week, taken, tw = d["proposals"], d["site_week"], d["taken"], d["taken_from_week"]
NAMES = {"urgent": "«Срочно»", "queue": "Очередь", "reserve": "Запас"}
SCORES = {"1.2+": "1.2 и выше", "0.9–1.2": "0.9–1.2", "<0.9": "ниже 0.9"}
WD = ["пн", "вт", "ср", "чт", "пт"]
period = f"{d['days'][0]}–{d['days'][-1]}"


def nth(a, b):
    return f"Каждая {['', 'первая', 'вторая', 'третья', 'четвёртая', 'пятая', 'шестая', 'седьмая', 'восьмая', 'девятая', 'десятая'][round(b / a)] if a and round(b / a) <= 10 else 'N-я'} новость сайта была в предложке"


def init():
    n = {
        "title": f"Итоги недели {period}: TODO главное событие недели",
        "headlines": {"main": nth(taken, site_week), "compare": "TODO: главное отличие от прошлой недели",
                      "funnel": f"От {d['materials']} материалов до {tw} публикаций", "days": f"~{round(props / 5)} предложений и ~{round(taken / 5)} попаданий в день",
                      "take": "TODO: что берут чаще", "speed": f"{taken - d['lead_buckets']['сайт раньше нас']} из {taken} — раньше, чем на сайте",
                      "sources": "TODO: какие источники берут", "changes": "TODO: что изменилось в системе", "system": "Надёжно и недорого",
                      "outro": "Что работает и что подкрутить"},
        "notes": {"compare": "TODO", "funnel": "TODO: самая большая причина отсева", "days": "TODO: особенности дней (сбои, понедельник)",
                  "take": "TODO", "speed": "TODO", "sources": "TODO", "fails": "TODO: что за сбои (по логам)"},
        "changes": [["ДД.ММ", "TODO: изменения в системе за неделю (README, история), со ссылкой на дату"]],
        "conclusions": [["TODO:", "вывод, опирающийся на цифру из stats.json"]],
        "next": "Следующий срез — через неделю.",
    }
    (W / "narrative.json").write_text(json.dumps(n, ensure_ascii=False, indent=1), encoding="utf-8")
    print(W / "narrative.json")


css = """
@page { size: 1456px 816px; margin: 0 }
:root { --surface:#fcfcfb; --card:#ffffff; --ink:#0b0b0b; --ink2:#52514e; --muted:#8a8984; --rule:#e4e3df;
  --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a; --gray:#c9c8c3; --tint:#eef3fc }
* { box-sizing:border-box; margin:0; padding:0 }
body { background:var(--surface); color:var(--ink); font-family:"Segoe UI", Arial, sans-serif }
.slide { width:1456px; height:816px; padding:64px 82px 0; position:relative; page-break-after:always; overflow:hidden; background:var(--surface) }
.kick { color:var(--s1); font-weight:700; letter-spacing:.08em; font-size:15px; text-transform:uppercase }
h1 { font-size:42px; font-weight:800; margin:14px 0 10px; letter-spacing:-.01em }
.sub { color:var(--ink2); font-size:20px }
.foot { position:absolute; left:82px; right:82px; bottom:22px; color:var(--muted); font-size:13px; display:flex; justify-content:space-between }
.grid { display:grid; grid-template-columns:repeat(3,1fr); gap:24px; margin-top:34px }
.tile { background:var(--card); border:1px solid var(--rule); border-radius:14px; padding:26px 28px; min-height:192px }
.tile.hi { background:var(--tint); border-color:var(--s1) }
.big { font-size:60px; font-weight:800; line-height:1 }
.big small { font-size:24px; color:var(--ink2); font-weight:700; margin-left:8px }
.tile p { color:var(--ink2); font-size:17px; margin-top:16px; line-height:1.45 }
.bars { margin-top:30px }
.row { display:grid; grid-template-columns:290px 1fr 150px; align-items:center; gap:18px; height:50px }
.row .l { text-align:right; font-size:19px }
.row .l span { display:block; font-size:13px; color:var(--muted) }
.bar { height:38px; border-radius:0 4px 4px 0 }
.row .v { font-size:19px; font-weight:700 }
.row .v span { font-weight:400; color:var(--muted); font-size:15px; margin-left:6px }
.note { color:var(--ink2); font-size:17px; line-height:1.5; margin-top:24px; max-width:1290px }
.stack { display:flex; height:38px; gap:2px; margin-top:16px; border-radius:4px; overflow:hidden }
.legend { display:flex; flex-wrap:wrap; gap:10px 34px; margin-top:16px; font-size:16px; color:var(--ink2) }
.legend i { display:inline-block; width:14px; height:14px; border-radius:3px; margin-right:8px; vertical-align:-2px }
table { border-collapse:collapse; width:100%; margin-top:28px; font-size:18px }
th { text-align:left; color:var(--muted); font-size:13px; letter-spacing:.08em; text-transform:uppercase; font-weight:600; padding:10px 12px; border-bottom:1px solid var(--rule) }
td { padding:9px 12px; border-bottom:1px solid var(--rule) }
td.n { text-align:right; font-variant-numeric:tabular-nums }
ul.out { list-style:none; margin-top:26px }
ul.out li { font-size:20px; line-height:1.5; padding:13px 0 13px 32px; border-bottom:1px solid var(--rule); position:relative }
ul.out li:before { content:""; position:absolute; left:4px; top:25px; width:11px; height:11px; border-radius:50%; background:var(--s1) }
.tl { display:grid; grid-template-columns:150px 1fr; gap:6px 24px; margin-top:28px; font-size:19px; line-height:1.45 }
.tl b { color:var(--s1) }
"""


def slide(kick, title, sub, body, foot, n):
    return (f'<section class="slide"><div class="kick">{kick}</div><h1>{title}</h1>' + (f'<div class="sub">{sub}</div>' if sub else "")
            + body + f'<div class="foot"><span>{foot}</span><span>{n}</span></div></section>')


def tile(big, small, text, hi=False):
    return f'<div class="tile{" hi" if hi else ""}"><div class="big">{big}{f"<small>{small}</small>" if small else ""}</div><p>{text}</p></div>'


def hbar(label, sub, val, mx, color, right):
    w = max(val / mx * 100, 0.6) if mx else 0
    return (f'<div class="row"><div class="l">{label}{f"<span>{sub}</span>" if sub else ""}</div>'
            f'<div><div class="bar" style="width:{w}%;background:{color}"></div></div><div class="v">{right}</div></div>')


def compare_rows(prev):
    def m(s):
        return {"Разобрано материалов": s["materials"], "Предложений": s["proposals"], "Взято редакцией": s["taken_from_week"],
                "Доля взятых": f"{pct(s['taken_from_week'], s['proposals'])}%",
                "Доля новостей сайта в предложке": f"{pct(s['taken'], s['site_week'])}%",
                "Медиана опережения": f"{round(s['lead_median'] or 0)} мин", "Сайт раньше нас": s["lead_buckets"]["сайт раньше нас"],
                "«Срочно»": s["by_block"]["urgent"][0], "Темы КТВ-ЛУЧ среди предложений": f"{pct(s['by_source']['КТВ-ЛУЧ'][0], s['proposals'])}%",
                "Прогонов / сбоев": f"{s['runs']} / {len(s['runs_fail'])}"}
    a, b = m(prev), m(d)
    return "".join(f'<tr><td>{k}</td><td class="n">{a[k]}</td><td class="n" style="font-weight:700">{b[k]}</td></tr>' for k in a)


def render(reports):
    n = json.loads((W / "narrative.json").read_text(encoding="utf-8"))
    if "TODO" in json.dumps(n, ensure_ascii=False):
        sys.exit("в narrative.json остались TODO — заполните тексты")
    H, N = n["headlines"], n["notes"]
    prev_files = sorted(p for p in Path(reports).glob("stats_*.json") if p.stem[6:] < d["week"])
    prev = json.loads(prev_files[-1].read_text(encoding="utf-8")) if prev_files else None
    sk = dict(d["skip_reasons"])
    evicted = sk.pop("вытеснено лимитом", 0)
    skipped = sum(sk.values())
    lead_med = round(d["lead_median"] or 0)
    S = []
    S.append(f'''<section class="slide" style="padding-top:236px;background:linear-gradient(135deg,#fcfcfb 60%,#eef3fc)">
<div class="kick">syzran-small.ru · младший ИИ-редактор</div><h1 style="font-size:64px;line-height:1.1;margin-top:18px">{n["title"]}</h1>
<div class="sub" style="font-size:24px;margin-top:22px">{period} · 5 рабочих дней, прогон каждые 30 минут с 7:05 до 21:35 (Самара)</div>
<div class="foot"><span>Данные: архив страницы предложений ({d["pages"]} версий), логи прогонов, лента rss-claude.php · данные до {d["data_until"]}</span><span>1</span></div></section>''')
    fails = len(d["runs_fail"])
    S.append(slide("Главное", H["main"], f"Редакция опубликовала {site_week} новостей; {taken} из них были и в предложке ИИ-редактора, "
                   f"{taken - d['lead_buckets']['сайт раньше нас']} — раньше, чем вышли на сайте.",
                   '<div class="grid">' + tile(d["materials"], "", "материалов разобрал ИИ-редактор из ленты сборщика, VK и Telegram")
                   + tile(props, "", f"предложений с рерайтом попали на страницу (~{round(props / 5)} в день)")
                   + tile(tw, f"/ {pct(tw, props)}%", f"предложений недели взяла редакция" + (f"; ещё {d['taken_carry']} — переходящие с прошлой недели" if d["taken_carry"] else ""), True)
                   + tile(f"{pct(taken, site_week)}%", "", f"новостей сайта за период совпали с предложениями ({taken} из {site_week})", True)
                   + tile(lead_med, "мин", "медианное опережение: на столько раньше предложение появилось на странице, чем новость на сайте")
                   + tile(d["runs"] - fails, f"/ {d['runs']}", f"прогонов отработали; {fails} сбоев. {N['fails']}") + "</div>",
                   "«Взяла» = ИИ-редактор при сверке нашёл на сайте новость с теми же фактами и снял предложение. Совпадение ≠ доказательство, что взяли именно у нас.", 2))
    if prev:
        S.append(slide("Сравнение", H["compare"], f"Неделя {prev['days'][0]}–{prev['days'][-1]} против {period}.",
                       f'<table><tr><th>Показатель</th><th style="text-align:right">{prev["days"][0]}–{prev["days"][-1]}</th>'
                       f'<th style="text-align:right">{period}</th></tr>{compare_rows(prev)}</table><div class="note">{N["compare"]}</div>',
                       f"Неделя {period} — данные до {d['data_until']}.", len(S) + 1))
    kinds = [("уже на сайте", "var(--s1)"), ("только КТВ-ЛУЧ / нет первоисточника", "var(--s2)"), ("дубль нашего предложения", "var(--s3)"),
             ("не про Сызрань", "#6f6e69"), ("PR, анонсы, мало фактов", "var(--gray)")]
    S.append(slide("Воронка", H["funnel"], N["funnel"],
                   '<div class="bars">' + hbar("Разобрано материалов", "", d["materials"], d["materials"], "var(--gray)", d["materials"])
                   + hbar("Предложено редакции", "", props, d["materials"], "var(--s1)", f"{props}<span>{pct(props, d['materials'])}%</span>")
                   + hbar("Взято редакцией", "", tw, d["materials"], "var(--s2)", f"{tw}<span>{pct(tw, props)}% от предл.</span>") + "</div>"
                   + f'<div style="margin-top:34px;font-size:22px;font-weight:700">Почему отсеяно {skipped} материалов</div>'
                   + '<div class="stack">' + "".join(f'<div style="flex:{sk[k]};background:{c}"></div>' for k, c in kinds) + "</div>"
                   + '<div class="legend">' + "".join(f'<span><i style="background:{c}"></i>{k} — {sk[k]} ({pct(sk[k], skipped)}%)</span>' for k, c in kinds) + "</div>"
                   + f'<div class="note">Отдельно: {evicted} своих предложений ИИ-редактор вытеснил лимитом (очередь 10, запас 8).</div>',
                   "Отсев — по разделу «Отсеяно в этом прогоне». Классификация причин — по ключевым словам, ±5–10%.", len(S) + 1))
    mx = max(max(x["site"], x["props"], x["taken"]) for x in d["by_day"]) or 1
    groups = ""
    for i, x in enumerate(d["by_day"]):
        cols = "".join(f'<div style="width:52px;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;height:360px">'
                       f'<div style="font-weight:700;font-size:17px;margin-bottom:6px">{x[k]}</div>'
                       f'<div style="width:52px;height:{x[k] / mx * 330}px;background:{c};border-radius:4px 4px 0 0"></div></div>'
                       for k, c in (("site", "var(--gray)"), ("props", "var(--s1)"), ("taken", "var(--s2)")))
        groups += (f'<div style="display:flex;flex-direction:column;align-items:center"><div style="display:flex;gap:2px;align-items:flex-end">{cols}</div>'
                   f'<div style="margin-top:12px;font-size:17px;color:var(--ink2)">{WD[i]} {x["day"]}</div></div>')
    S.append(slide("По дням", H["days"], "", '<div class="legend" style="margin-top:6px"><span><i style="background:var(--gray)"></i>опубликовано на сайте</span>'
                   '<span><i style="background:var(--s1)"></i>новых предложений</span><span><i style="background:var(--s2)"></i>взято редакцией</span></div>'
                   f'<div style="display:flex;justify-content:space-around;align-items:flex-end;margin-top:24px;border-bottom:1px solid var(--muted)">{groups}</div>'
                   f'<div class="note" style="margin-top:18px">{N["days"]}</div>',
                   "«Взято» — по времени, когда ИИ-редактор снял предложение как опубликованное; новости, вышедшие на сайте до начала недели, не считались.", len(S) + 1))
    bb, bs = d["by_block"], d["by_score"]
    left = "".join(hbar(NAMES[k], f"{bb[k][0]} предл.", pct(bb[k][1], bb[k][0]), 100, "var(--s1)", f"{pct(bb[k][1], bb[k][0])}%<span>{bb[k][1]}</span>") for k in bb)
    right = "".join(hbar(SCORES[k], f"{bs[k][0]} предл.", pct(bs[k][1], bs[k][0]), 100, "var(--s1)", f"{pct(bs[k][1], bs[k][0])}%<span>{bs[k][1]}</span>") for k in bs)
    S.append(slide("Что берут", H["take"], "Доля взятых редакцией предложений по разделу страницы и по базовому баллу.",
                   '<div style="display:grid;grid-template-columns:1fr 1fr;gap:40px;margin-top:30px"><div><div style="font-size:21px;font-weight:700">По разделу</div>'
                   f'<div class="bars" style="margin-top:12px">{left}</div></div><div><div style="font-size:21px;font-weight:700">По базовому баллу ИИ-редактора</div>'
                   f'<div class="bars" style="margin-top:12px">{right}</div></div></div><div class="note">{N["take"]}</div>', "Шкала долей — 0–100% на всех полосах.", len(S) + 1))
    lb = d["lead_buckets"]
    mxb = max(lb.values()) or 1
    S.append(slide("Скорость", H["speed"], "Время от появления предложения на странице до выхода новости на сайте (по pubDate, самарское время).",
                   '<div class="bars">' + "".join(hbar(k, "", c, mxb, "var(--gray)" if i == 0 else "var(--s1)", c) for i, (k, c) in enumerate(lb.items())) + "</div>"
                   + f'<div class="note">Медиана — {lead_med} минут. {N["speed"]} Оговорка: pubDate — время выхода, а не начала работы над новостью.</div>',
                   f"Одна новость сайта считается один раз ({taken}).", len(S) + 1))
    trs = "".join(f'<tr><td>{k}</td><td class="n">{a}</td><td class="n">{b} · {pct(b, a)}%</td>'
                  f'<td style="width:330px"><div style="height:22px;width:{pct(b, a) * 3.3}px;background:var(--s1);border-radius:0 4px 4px 0"></div></td></tr>'
                  for k, (a, b) in d["by_source"].items())
    S.append(slide("Источники", H["sources"], "Первоисточник в карточке предложения и доля взятых редакцией.",
                   f'<table><tr><th>Источник</th><th style="text-align:right">Предложено</th><th style="text-align:right">Взято</th><th>Доля взятых</th></tr>{trs}</table>'
                   f'<div class="note">{N["sources"]}</div>', "Классификация — по первой ссылке в поле «Источник».", len(S) + 1))
    fc = d["factcheck"]
    fcb = (f'<div style="margin-top:30px;font-size:21px;font-weight:700">Фактчек за неделю: {fc["items"]} новостей</div>'
           f'<div class="stack"><div style="flex:{fc["ok"]};background:var(--s3)"></div><div style="flex:{fc["fixed"]};background:var(--s1)"></div>'
           f'<div style="flex:{fc["left"]};background:var(--s2)"></div></div><div class="legend"><span><i style="background:var(--s3)"></i>без замечаний — {fc["ok"]}</span>'
           f'<span><i style="background:var(--s1)"></i>нашёл расхождение, исправлено — {fc["fixed"]}</span><span><i style="background:var(--s2)"></i>замечание оставлено дежурному — {fc["left"]}</span></div>') if fc["items"] else ""
    S.append(slide("Что изменилось за неделю", H["changes"], "", '<div class="tl">' + "".join(f"<b>{a}</b><span>{b}</span>" for a, b in n["changes"]) + "</div>" + fcb,
                   f"Рерайт (ИИ) в админке за неделю: успешных запросов — {d['admin_rewrite']['ok']}, ошибок — {d['admin_rewrite']['error']}.", len(S) + 1))
    S.append(slide("Как работает система", H["system"], "", '<div class="grid">'
                   + tile(d["runs"], "", f"прогонов по cron; {d['runs_empty']} раз «нового нет» — Claude не вызывался")
                   + tile(d["duration_median_min"], "мин", f"медиана длительности (среднее {d['duration_mean_min']} мин, максимум {d['duration_max_min']} мин); медиана {round(d['turns_median'] or 0)} шагов отбора")
                   + tile(fails, "", f"сбоев. {N['fails']}")
                   + tile(f"${round(d['cost'])}", "", f"эквивалент цены API за неделю (≈ ${d['cost'] / max(1, d['runs_claude']):.2f} за прогон с Claude). Фактически — в рамках подписки")
                   + tile(f"{d['hits_share']}%", "", f"просмотров новостей сайта за период пришлось на {taken} совпавших новостей")
                   + tile(f"{round(d['hits_taken_median'] or 0):,}".replace(",", " "), "", f"медиана просмотров взятой новости — против {round(d['hits_other_median'] or 0):,} у остальных".replace(",", " "))
                   + "</div>", "Стоимость — поле total_cost_usd из ответа Claude Code (отбор + рерайт + фактчек).", len(S) + 1))
    S.append(slide("Выводы", H["outro"], "", '<ul class="out">' + "".join(f"<li><strong>{a}</strong> {b}</li>" for a, b in n["conclusions"]) + "</ul>", n["next"], len(S) + 1))
    page = f'<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>Итоги недели {period}</title><style>{css}</style></head><body>{"".join(S)}</body></html>'
    (W / "report.html").write_text(page, encoding="utf-8")
    pdf = (Path(reports) / f"ai_editor_week_{d['week']}_{d['days'][-1][3:5]}-{d['days'][-1][:2]}.pdf").resolve()
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", f"--print-to-pdf={pdf}", (W / "report.html").resolve().as_uri()],
                   capture_output=True, timeout=120)
    (Path(reports) / f"stats_{d['week']}.json").write_text(json.dumps({k: v for k, v in d.items() if k not in ("taken_rows", "skipped_samples")},
                                                                     ensure_ascii=False, indent=1), encoding="utf-8")
    # каждый слайд отдельной картинкой — проверить вёрстку глазами
    for i in range(len(S)):
        shot = W / f"slide_{i + 1:02d}.png"
        tmp = W / "one.html"
        tmp.write_text(page.replace("<body>", f'<body style="margin-top:-{816 * i}px">'), encoding="utf-8")
        subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--window-size=1456,816", f"--screenshot={shot.resolve()}",
                        tmp.resolve().as_uri()], capture_output=True, timeout=60)
    print(pdf, pdf.exists() and pdf.stat().st_size, f"слайдов {len(S)}; картинки — {W}/slide_*.png")


if __name__ == "__main__":
    init() if sys.argv[2:] == ["--init"] else render(sys.argv[2])
