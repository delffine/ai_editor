"""Встраивает Предложку (ИИ) в модуль новостей админки syzran-small.ru.

python patch_news.py <news.php оригинал> <news.php результат>
Оригинал в windows-1251 с CRLF; результат — тоже. Вставляет блоки
news_ai_common.php и news_ai_feed.php перед switch($in), case, ссылку
«Предложка (ИИ)» в навигацию модуля и предзаполнение формы
add_news (заголовок, лид, текст, источник, рубрика, превью; теги — скрытым полем keywords,
их проверяет save_news).
"""
import sys
from pathlib import Path

src, dst = Path(sys.argv[1]), Path(sys.argv[2])
raw = src.read_bytes()
text = raw.decode("cp1251")
assert text.encode("cp1251") == raw, "cp1251 roundtrip"
assert "ai_feed" not in text, "уже встроено"
NL = "\r\n"
block = ("\n".join(Path(__file__).with_name(f).read_text(encoding="utf-8")
                   for f in ("news_ai_common.php", "news_ai_feed.php"))
         .replace("\r\n", "\n").replace("\n", NL))


def sub(s, old, new, count=1):
    n = s.count(old)
    assert n == count, f"ожидалось {count} вхождений, найдено {n}: {old[:60]!r}"
    return s.replace(old, new)


# 1. блок функций — перед диспетчером
text = sub(text, "switch($in) {", block + NL + "switch($in) {")

# 2. case
text = sub(text, '    case "add_news":' + NL,
           '    case "ai_feed":' + NL + '    ai_feed();' + NL + '    break;' + NL + NL
           + '    case "add_news":' + NL)

# 3. ссылка в навигации модуля (перед «Банк превью-фото»; в блоке ai_feed она уже есть)
nav = """    .'&nbsp;&nbsp;<font color="FF9933"><b>></font>&nbsp;<a href="admin.php?go=news&in=previmg">Банк превью-фото</a></b>'."\\n\""""
link = """    .'&nbsp;&nbsp;<font color="FF9933"><b>></font>&nbsp;<a href="admin.php?go=news&in=ai_feed">Предложка (ИИ)</a></b>'."\\n\""""
n = text.count(nav + NL)
text = text.replace(nav + NL, link + NL + nav + NL)
text = text.replace(link + NL + link + NL, link + NL)  # блок ai_feed уже со ссылкой
print("ссылок в навигации:", n)

# 4. предзаполнение add_news
a = text.index("function add_news() {")
b = text.index("function save_news() {")
f = text[a:b]
f = sub(f, "    include('header.php');" + NL,
        "    include('header.php');" + NL + "    $ai = ai_prefill(); // из Предложки (in=ai_feed)" + NL)
f = sub(f, """<textarea name="title" rows="1" cols="70" style="width:500px"></textarea>""",
        """<textarea name="title" rows="1" cols="70" style="width:500px">'.ai_h($ai['title']).'</textarea>""")
f = sub(f, "'home_text'," + NL + "                       /*value*/ '',",
        "'home_text'," + NL + "                       /*value*/ $ai['home'],")
f = sub(f, "'body_text'," + NL + "                       /*value*/ '',",
        "'body_text'," + NL + "                       /*value*/ $ai['body'],")
f = sub(f, """<textarea name="home_text" rows="7" cols="50" style="width=500px"></textarea>""",
        """<textarea name="home_text" rows="7" cols="50" style="width=500px">'.ai_h($ai['home']).'</textarea>""")
f = sub(f, """<textarea name="body_text" rows="20" cols="50" style="width=500px"></textarea>""",
        """<textarea name="body_text" rows="20" cols="50" style="width=500px">'.ai_h($ai['body']).'</textarea>""")
f = sub(f, """<input type="text" name="import_name" size="70" style="width=500px">""",
        """<input type="text" name="import_name" size="70" style="width=500px" value="'.ai_h($ai['src_name']).'">""")
f = sub(f, """<input type="text" name="import_url" size="70" style="width=500px">""",
        """<input type="text" name="import_url" size="70" style="width=500px" value="'.ai_h($ai['src_url']).'">""")
f = sub(f, """<input type="hidden" name="author" value="'.$_SESSION['admin_name'].'">""",
        """<input type="hidden" name="author" value="'.$_SESSION['admin_name'].'">"""
        """<input type="hidden" name="keywords" value="'.ai_h($ai['keywords']).'">""")
f = sub(f, """<input type="text" name="foto" id="foto" size="50" style="width=200px">""",
        """<input type="text" name="foto" id="foto" size="50" style="width=200px" value="'.ai_h($ai['foto']).'">""")
f = sub(f, """echo '<option value="'.($i).'">'.$cats[$i].'</option>';""",
        """echo '<option value="'.($i).'"'.($i == $ai['cat'] ? ' selected' : '').'>'.$cats[$i].'</option>';""")
text = text[:a] + f + text[b:]

# 5. теги из Предложки в save_news (вместо заглушки $keywords = '')
a = text.index("function save_news() {")
b = text.index("function view_news() {")
f = sub(text[a:b], "//    $keywords = stripslashes($_POST['keywords']);" + NL,
        "//    $keywords = stripslashes($_POST['keywords']);" + NL
        + "    $keywords = ai_feed_keywords(); // теги из Предложки (in=ai_feed), только из tagarray.php" + NL)
text = text[:a] + f + text[b:]

dst.write_bytes(text.encode("cp1251"))
print("записано:", dst)
