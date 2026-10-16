// ---------------------------------------------------------------------
// Предложка ИИ-редактора (in=ai_feed). Лента предложений последнего прогона
// ИИ-редактора (блоки «Срочно», «В очередь», «Запас») - та же, что на
// http://VPS_HOST:8808/ai-editor/. Забирается с VPS при открытии
// страницы (rewrite.php action=feed, токен AI_RW_TOKEN из блока рерайта).
// Ответ VPS - JSON в чистом ASCII, в страницу он вставляется как есть
// (после json_decode/json_encode) - перекодировка cp1251 не нужна. HTML с VPS
// не принимается: страницу собирает JS из текстовых полей.
// «Принять для публикации» -> форма add_news с выбранным заголовком, лидом,
// текстом, первым источником, рубрикой и превью из банка (ai_rw_prefill); теги - скрытым полем keywords
// (в форме их не видно, save_news сверяет с tagarray.php - ai_feed_keywords).
// ---------------------------------------------------------------------
function ai_feed() {
    include('header.php');
    echo '<font color="FF9933"><b>></font>&nbsp;<a href="admin.php?go=news&in=add_news">'._ADDNEWNEWS.'</a></b>'."\n"
    .'&nbsp;&nbsp;<font color="FF9933"><b>></font>&nbsp;<a href="admin.php?go=news&in=ai_rewrite">Рерайт (ИИ)</a></b>'."\n"
//  .'&nbsp;&nbsp;<font color="FF9933"><b>></font>&nbsp;<a href="admin.php?go=news&in=ai_feed">Предложка (ИИ)</a></b>'."\n"
    .'&nbsp;&nbsp;<font color="FF9933"><b>></font>&nbsp;<a href="admin.php?go=news&in=previmg">Банк превью-фото</a></b>'."\n"
    .'&nbsp;&nbsp;<font color="FF9933"><b>></font>&nbsp;<a href="admin.php?go=news&in=all_tag">Управление ТЭГами</a></b><br><br>'."\n";
    $d = json_decode(ai_rw_call(array('action' => 'feed')), true);
    $js = is_array($d) ? json_encode($d) : false;
    if ($js === false) $js = ai_rw_err('Не удалось разобрать ленту предложений');
?>
<style>
#aif { width: 760px; text-align: left; font-family: Arial, sans-serif; font-size: 13px; }
#aif table { width: 100%; margin-bottom: 14px; }
#aif td { vertical-align: top; }
#aif td.k { width: 90px; color: #555; }
#aif h3 { margin: 18px 0 8px; padding: 4px 8px; font-size: 15px; color: #FFF; }
#aif h3.urgent { background: #C00; }
#aif h3.queue { background: #369; }
#aif h3.reserve { background: #777; }
#aif .hint { color: #777; font-size: 11px; }
#aif .warn { color: #C00; font-weight: bold; }
#aif .note { color: #C00; }
#aif label { display: block; margin-bottom: 3px; cursor: pointer; }
#aif p { margin: 0 0 6px; }
</style>
<center><div id="aif"></div></center>
<form id="aif-form" action="admin.php" method="post" style="display:none">
<input type="hidden" name="go" value="news"><input type="hidden" name="in" value="add_news">
<input type="hidden" name="ai_title"><input type="hidden" name="ai_home"><input type="hidden" name="ai_body">
<input type="hidden" name="ai_src_name"><input type="hidden" name="ai_src_url"><input type="hidden" name="ai_feed_id"><input type="hidden" name="ai_keywords"><input type="hidden" name="ai_foto"><input type="hidden" name="ai_cat">
</form>
<script type="text/javascript">
var AIF = <?php echo $js; ?>;
var AIF_BLOCKS = [['urgent', 'Срочно - ставить вместо следующей'], ['queue', 'В очередь (по итоговому баллу)'], ['reserve', 'Запас - закрыть дыры']];
function aifEl(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text) e.appendChild(document.createTextNode(text));
    return e;
}
function aifParas(s) {
    var box = document.createElement('div'), ps = s.replace(/^\s+|\s+$/g, '').split(/\r?\n\s*\r?\n/), i;
    for (i = 0; i < ps.length; i++) box.appendChild(aifEl('p', '', ps[i]));
    return box;
}
function aifAge(m) { return m < 60 ? m + ' мин' : Math.floor(m / 60) + ' ч ' + (m % 60) + ' мин'; }
function aifRow(t, k, v) {
    var tr = t.insertRow(-1), a = tr.insertCell(-1), b = tr.insertCell(-1);
    tr.bgColor = '#FFFFFF'; a.className = 'k'; a.appendChild(document.createTextNode(k)); b.appendChild(v);
    return b;
}
// Источник - куски текста и ссылки в исходном порядке; первая ссылка - главный источник
function aifUrl(s) { return /^https?:\/\//.test(s || '') ? s : ''; }
function aifSources(p) {
    var box = document.createElement('div'), i, s, a;
    for (i = 0; i < p.sources.length; i++) {
        s = p.sources[i];
        if (i) box.appendChild(document.createTextNode(/^[,;.)]/.test(s.t) ? '' : ' '));
        if (aifUrl(s.url)) {
            a = aifEl('a', '', s.t);
            a.href = s.url; a.target = '_blank'; a.rel = 'noopener noreferrer';
            box.appendChild(a);
        } else {
            box.appendChild(document.createTextNode(s.t));
        }
    }
    return box;
}
function aifMainSource(p) {
    for (var i = 0; i < p.sources.length; i++) if (aifUrl(p.sources[i].url)) return {name: p.sources[i].t, url: p.sources[i].url};
    return {name: '', url: ''};
}
// Превью из банка сайта (/images/news/) - миниатюра и подсказка, как в «Банке превью-фото»
function aifFoto(p) {
    var box = document.createElement('div'), img = document.createElement('img');
    img.src = '/images/news/' + encodeURIComponent(p.foto); img.width = 150; img.style.verticalAlign = 'top';
    box.appendChild(img);
    box.appendChild(aifEl('span', 'hint', ' ' + p.foto + (p.foto_caption ? ' - ' + p.foto_caption : '')));
    return box;
}
function aifCard(p, ageAdd) {
    var t = document.createElement('table'), hd, c, i, lb, rb, btn, age;
    t.border = 0; t.cellSpacing = 1; t.cellPadding = 4; t.bgColor = '#EFEFEF';
    hd = t.insertRow(-1).insertCell(-1); hd.colSpan = 2;
    hd.appendChild(aifEl('b', '', p.label));
    age = p.block == 'reserve' ? '' : ', базовый ' + p.base + ', в выдаче ' + aifAge(p.age_min + ageAdd);
    hd.appendChild(aifEl('span', 'hint', '  балл ' + p.score + age + (p.expires ? ', актуально до ' + p.expires.substr(8, 2) + '.' + p.expires.substr(5, 2) + ' ' + p.expires.substr(11, 5) : '')));
    c = aifRow(t, 'Заголовок', document.createElement('div'));
    for (i = 0; i < p.headlines.length; i++) {
        lb = document.createElement('label');
        rb = document.createElement('input'); rb.type = 'radio'; rb.name = 'aif-' + p.id; rb.value = i; rb.checked = (i == 0);
        lb.appendChild(rb); lb.appendChild(document.createTextNode(' ' + p.headlines[i]));
        c.firstChild.appendChild(lb);
    }
    aifRow(t, 'Лид', aifParas(p.lead));
    if (p.body) aifRow(t, 'Текст', aifParas(p.body));
    aifRow(t, 'Источник', aifSources(p));
    if (p.cat) aifRow(t, 'Рубрика', aifEl('span', '', p.cat_name));
    if (p.tags && p.tags.length) aifRow(t, 'Теги', aifEl('span', '', p.tags.join(', ')));
    if (p.foto) aifRow(t, 'Превью', aifFoto(p));
    if (p.note) aifRow(t, 'Проверить', aifEl('span', 'note', p.note));
    if (p.score_why) aifRow(t, 'Балл', aifEl('span', 'hint', p.score_why));
    btn = document.createElement('input'); btn.type = 'button'; btn.value = 'Принять для публикации';
    btn.onclick = function () { aifAccept(p); };
    c = aifRow(t, '', btn);
    c.appendChild(aifEl('span', 'hint', ' - откроется форма добавления новости с выбранным заголовком, лидом, текстом, источником, рубрикой и превью'));
    return t;
}
function aifHtml(s) {
    s = s.replace(/^\s+|\s+$/g, '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    return s.replace(/\r?\n\s*\r?\n/g, '<br><br>').replace(/\r?\n/g, '<br>');
}
function aifAccept(p) {
    var f = document.getElementById('aif-form'), rs = document.getElementsByName('aif-' + p.id), i, n = 0, src = aifMainSource(p);
    for (i = 0; i < rs.length; i++) if (rs[i].checked) n = i;
    f.ai_title.value = p.headlines[n];
    f.ai_home.value = aifHtml(p.lead);
    f.ai_body.value = p.body ? aifHtml(p.body) : '';
    f.ai_src_name.value = src.name;
    f.ai_src_url.value = src.url;
    f.ai_feed_id.value = p.id;
    f.ai_keywords.value = p.tags && p.tags.length ? ', ' + p.tags.join(', ') : '';
    f.ai_foto.value = p.foto || '';
    f.ai_cat.value = p.cat || 0;
    f.submit();
}
// Страница сама не обновляется: подсказка, когда на VPS будет новая лента (время самарское,
// с запасом - считает finish.py) и что пора нажать F5, если это время прошло
function aifNext(next, updated) {
    var t = next.substr(11, 5), d = next.substr(0, 10) == updated.substr(0, 10) ? '' : next.substr(8, 2) + '.' + next.substr(5, 2) + ' ', at = Date.parse(next);
    if (at && new Date().getTime() > at) return aifEl('span', 'warn', 'Лента должна была обновиться ' + d + 'в ' + t + ' - обновите страницу (F5).');
    return aifEl('span', '', 'Следующее обновление запланировано на ' + d + t + ' - после этого обновите страницу (F5).');
}
function aifShow() {
    var box = document.getElementById('aif'), top = aifEl('p'), b, i, n, items, ageAdd = 0, up;
    box.appendChild(top);
    if (AIF.status != 'ok') { top.className = 'warn'; top.appendChild(document.createTextNode('Ошибка: ' + (AIF.error || 'неизвестная'))); return; }
    up = Date.parse(AIF.updated);
    if (up) ageAdd = Math.max(0, Math.round((new Date().getTime() - up) / 60000));
    top.appendChild(aifEl('b', '', 'Обновлено ' + AIF.updated.substr(8, 2) + '.' + AIF.updated.substr(5, 2) + ' в ' + AIF.updated.substr(11, 5)
        + (ageAdd > 120 ? ' - ' + aifAge(ageAdd) + ' назад' : '') + '. '));
    if (ageAdd > 120) top.appendChild(aifEl('span', 'warn', 'Лента давно не обновлялась (прогоны по будням каждые 30 мин, 7:05-21:35). '));
    top.appendChild(document.createElement('br'));
    if (AIF.next) top.appendChild(aifNext(AIF.next, AIF.updated));
    top.appendChild(document.createElement('br'));
    top.appendChild(document.createTextNode(AIF.latest + ' '));
    b = aifEl('a', '', 'Полная страница ИИ-редактора');
    b.href = 'http://VPS_HOST:8808/ai-editor/'; b.target = '_blank';
    top.appendChild(b);
    for (n = 0; n < AIF_BLOCKS.length; n++) {
        box.appendChild(aifEl('h3', AIF_BLOCKS[n][0], AIF_BLOCKS[n][1]));
        items = 0;
        for (i = 0; i < AIF.items.length; i++) {
            if (AIF.items[i].block != AIF_BLOCKS[n][0]) continue;
            box.appendChild(aifCard(AIF.items[i], ageAdd));
            items++;
        }
        if (!items) box.appendChild(aifEl('p', 'hint', 'Пусто.'));
    }
}
aifShow();
</script>
<?php
    include('footer.php');
}
