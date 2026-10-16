"""Список тегов сайта для ИИ-редактора: tagarray.php (cp1251, с сайта:
widgets/tagarray.php, его пересобирает админка in=tagarrey) -> tags.md.

python build_tags.py <tagarray.php> <tags.md>

Отбрасываются ошибочные теги: с запятыми, пробелами по краям, двойными
пробелами, кавычками. Из вариантов, различающихся только регистром,
остаётся более частый. tags.md добавляется к системному промпту (run.sh),
его же читает finish.py для проверки тегов. После пересборки — scp на VPS.
"""
import re
import sys
from pathlib import Path

src, dst = Path(sys.argv[1]), Path(sys.argv[2])
raw = src.read_bytes().decode("cp1251")
pairs = [(t, int(n)) for t, n in re.findall(r'\$tags\["(.*?)"\]\s*=\s*(\d+);', raw, re.S)]
bad = [t for t, n in pairs if not t.strip() or t != t.strip() or re.search(r'[,\'"\\\n]|  ', t)]
good = {}
for t, n in pairs:
    if t in bad:
        continue
    k = t.lower()
    if k not in good or n > good[k][1]:
        good[k] = (t, n)
tags = sorted(good.values(), key=lambda x: (-x[1], x[0].lower()))
dst.write_text(
    "# Теги сайта (поле tags в предложениях)\n\n"
    "Теги — ключевые слова новости на сайте. Бери **только** теги из этого списка, **буква в букву** "
    "(регистр, пробелы), не больше 3 на новость, от самого точного. Лучше не поставить тег вовсе, "
    "чем поставить лишний или неточный: тег должен прямо описывать новость (место, тема, "
    "ведомство или персона, о которой она). В скобках — сколько раз тег использован на сайте.\n\n"
    + "; ".join(f"{t} ({n})" for t, n in tags) + "\n", encoding="utf-8", newline="\n")  # LF: файл для Linux
print(f"тегов: {len(tags)} (всего {len(pairs)}, отброшено ошибочных {len(bad)}, дублей по регистру "
      f"{len(pairs) - len(bad) - len(tags)}): {bad}")
