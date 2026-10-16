"""Рубрики сайта для ИИ-редактора: rss-claude.xml (rss-claude.php?limit=5000) -> cats.md.

python build_cats.py <rss-claude.xml> <cats.md>

Номера рубрик — как в <select name="cat"> формы add_news (список со слов
редакции, 15.10.2026). Для каждой — сколько новостей из последних 5000 и
примеры свежих заголовков: по ним видно, что редакция туда относит.
cats.md добавляется к системному промпту (run.sh). После пересборки — scp на VPS.
"""
import collections
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

CATS = {1: "Общество", 2: "Культура", 3: "Спорт", 4: "Коммунальная сфера", 5: "Экономика и бизнес",
        6: "Правопорядок", 7: "Происшествия", 8: "Из жизни", 9: "Медицина", 10: "Образование",
        11: "Власть", 12: "Благоустройство", 13: "В регионе, в стране", 14: "Непознанное",
        15: "Оперативная информация", 16: "Туризм", 17: "Нацпроекты"}
EXAMPLES = 5
its = ET.parse(sys.argv[1]).getroot().findall("./channel/item")
n, ex = collections.Counter(), collections.defaultdict(list)
for it in its:  # от свежих к старым
    c = int((it.findtext("category") or "0").strip() or 0)
    n[c] += 1
    t = " ".join((it.findtext("title") or "").split())
    if c in CATS and len(ex[c]) < EXAMPLES and t not in ex[c]:
        ex[c].append(t)
out = ["# Рубрики сайта (поле cat в предложениях)", "",
       f"Номер рубрики сайта — одно число. В скобках — сколько новостей из последних {len(its)} "
       "редакция дала в эту рубрику, дальше — примеры их заголовков: ориентируйся на них. "
       "Не можешь выбрать уверенно — 0 (без рубрики, редактор выберет сам).", ""]
for c, name in CATS.items():
    out.append(f"{c} {name} ({n[c]}): " + " | ".join(ex[c]))
Path(sys.argv[2]).write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")  # LF: файл для Linux
print("рубрик:", len(CATS), "| без рубрики:", n[0], "из", len(its))
