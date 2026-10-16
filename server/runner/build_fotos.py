"""Банк превью-фото сайта для ИИ-редактора: foto.txt -> fotos.md.

python build_fotos.py <foto.txt> <fotos.md> [<rss-claude.xml>]

foto.txt (UTF-8, выгрузка «Банка превью-фото» админки): блоки «имя файла /
подсказка / width=… height=…» (размеров может не быть). Подсказка вида
«1 дтп зима2»: первая цифра — приоритет при сортировке в банке (отбрасывается),
цифра в конце различает фото с одинаковой подсказкой. Необязательный
rss-claude.xml (rss-claude.php?limit=5000) — сколько раз фото ставили к
новостям. fotos.md добавляется к системному промпту (run.sh), его же читает
finish.py для проверки имени. После пересборки — scp на VPS.
"""
import collections
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

IMG = re.compile(r"\.(jpe?g|png|gif|webp)$", re.I)
lines = [l.strip() for l in Path(sys.argv[1]).read_text(encoding="utf-8-sig").splitlines()]
bank, i = {}, 0
while i < len(lines):
    if IMG.search(lines[i]) and re.fullmatch(r"[\w.\-]+", lines[i]):
        j = i + 1
        while j < len(lines) and not lines[j]:
            j += 1
        cap = lines[j] if j < len(lines) and not IMG.search(lines[j]) and not lines[j].startswith("width=") else ""
        cap = " ".join(re.sub(r"^\d+[ _]+", "", cap).split())
        if cap:
            bank[lines[i]] = cap
        i = j
    i += 1
used = collections.Counter()
if len(sys.argv) > 3:
    for it in ET.parse(sys.argv[3]).getroot().findall("./channel/item"):
        used[(it.findtext("foto") or "").strip()] += 1
rows = sorted(bank.items(), key=lambda x: (x[1].lower(), x[0]))
Path(sys.argv[2]).write_text(
    "# Банк превью-фото сайта (поле foto в предложениях)\n\n"
    "Шаблонные превью: имя файла — подсказка, что на фото (в скобках — сколько раз ставили к новостям "
    "за последние 5000). Картинок ты не видишь — только подсказки. Ставь превью, **только если подсказка "
    "прямо и однозначно подходит** к новости: та же тема (пожар, ДТП, нет воды, скорая, гороскоп, "
    "отбой опасности), то же ведомство или здание, тот же человек. Сезон учитывай («зима» — только "
    "зимой). Имя — **буква в букву** из списка, одно на новость. Сомневаешься — пусто: лучше без "
    "превью, чем с ошибочным (редактор подберёт сам).\n\n"
    + "\n".join(f"{n} — {c}" + (f" ({used[n]})" if used[n] else "") for n, c in rows) + "\n",
    encoding="utf-8", newline="\n")  # LF: файл для Linux
print(f"превью: {len(bank)}, с использованием: {sum(1 for n in bank if used[n])}")
