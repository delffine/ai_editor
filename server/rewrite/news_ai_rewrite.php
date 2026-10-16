// ---------------------------------------------------------------------
// Рерайт через ИИ (in=ai_rewrite). Редактор вставляет текст новости и
// выбирает режим: «Рерайт» -> 3 варианта заголовка, лид и текст в стиле
// редакции; «Проверка правописания» -> тот же текст с исправленными
// ошибками и опечатками. Кавычки в ответе - «ёлочки». Модель крутится на
// VPS ИИ-редактора (VPS_HOST, claude -p, очередь rewrite.php).
// Браузер ходит только сюда (in=ai_rewrite_ajax) - токен VPS в браузер не
// попадает, а сюда пускает только вошедшего админа (проверяет admin.php).
// Текст из браузера идёт в base64 (UTF-8), ответ VPS - JSON в чистом ASCII,
// поэтому перекодировка cp1251 <-> UTF-8 не нужна.
// ---------------------------------------------------------------------
define('AI_RW_URL', 'http://VPS_HOST:8808/ai-editor/rewrite.php');
define('AI_RW_TOKEN', 'CHANGE_ME');

function ai_rw_err($msg) {
    $msg = function_exists('mb_convert_encoding') ? mb_convert_encoding($msg, 'UTF-8', 'CP1251') : iconv('CP1251', 'UTF-8', $msg);
    return json_encode(array('status' => 'error', 'error' => $msg));
}

function ai_rw_call($params) {
    $params['token'] = AI_RW_TOKEN;
    $ch = curl_init(AI_RW_URL);
    curl_setopt($ch, CURLOPT_POST, 1);
    curl_setopt($ch, CURLOPT_POSTFIELDS, http_build_query($params));
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
    curl_setopt($ch, CURLOPT_CONNECTTIMEOUT, 10);
    curl_setopt($ch, CURLOPT_TIMEOUT, 20);
    $data = curl_exec($ch);
    $err = curl_error($ch);
    $code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);
    if ($data === false) return ai_rw_err('Нет связи с сервером ИИ-редактора: '.$err);
    if (substr(ltrim($data), 0, 1) != '{') return ai_rw_err('Сервер ИИ-редактора ответил не JSON (HTTP '.$code.')');
    return $data;
}

// Лог в стиле log/newsave: log/aieditГГГГММДД (cp1251, строки через \r) -
// отправка (режим, id, длина, IP, исходный текст) и итог (ответ ИИ или ошибка).
// Опрос status с ответом pending не пишется. Ошибки записи глушатся: warning
// испортил бы JSON-ответ.
function ai_rw_cp($s) {
    $s = str_replace("\xE2\x86\x92", '->', (string)$s); // стрелка из списка исправлений - её нет в cp1251
    if (function_exists('mb_convert_encoding')) return mb_convert_encoding($s, 'CP1251', 'UTF-8');
    $r = @iconv('UTF-8', 'CP1251//IGNORE', $s);
    return $r === false ? '' : $r;
}

function ai_rw_log($str) {
    $t = function_exists('formatdate') ? formatdate("H:i:s", time()) : date("H:i:s");
    $h = @fopen('log/aiedit'.date('Ymd'), 'a');
    if (!$h) return;
    @fwrite($h, $t.' '.$str." \r ---------------------------------------------------------------------- "."\r");
    @fclose($h);
}

function ai_rw_log_result($id, $resp) {
    $d = json_decode($resp, true);
    if (!is_array($d) || !isset($d['status']) || $d['status'] == 'pending') return;
    $ip = isset($_SERVER['REMOTE_ADDR']) ? $_SERVER['REMOTE_ADDR'] : '';
    if ($d['status'] != 'ok') {
        $err = isset($d['error']) ? $d['error'] : $d['status'];
        ai_rw_log("AI-ERROR - $id - $ip - ".ai_rw_cp($err));
        return;
    }
    $mode = isset($d['mode']) ? $d['mode'] : 'rewrite';
    $info = "AI-RESULT - $mode - $id - $ip - ".round((isset($d['ms']) ? $d['ms'] : 0) / 1000)." s, $".(isset($d['cost']) ? $d['cost'] : 0);
    if ($mode == 'proof') {
        $txt = ai_rw_cp($d['text'])." \r ".ai_rw_cp($d['notes']);
    } else {
        $txt = ai_rw_cp(implode(' | ', (array)$d['titles']))." \r ".ai_rw_cp($d['lead'])." \r ".ai_rw_cp($d['body']);
        if (!empty($d['notes'])) $txt .= " \r ".ai_rw_cp($d['notes']);
    }
    ai_rw_log($info." \r ".$txt);
}

function ai_rewrite_ajax() {
    while (ob_get_level()) ob_end_clean();
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    if (empty($_SESSION['ai_rw_key']) || !isset($_POST['key']) || $_POST['key'] !== $_SESSION['ai_rw_key']) {
        echo ai_rw_err('Сессия устарела - обновите страницу');
        exit;
    }
    $act = isset($_POST['act']) ? $_POST['act'] : '';
    if ($act == 'submit') {
        $text = base64_decode(isset($_POST['text64']) ? $_POST['text64'] : '');
        $mode = (isset($_POST['mode']) && $_POST['mode'] == 'proof') ? 'proof' : 'rewrite';
        $resp = ai_rw_call(array('action' => 'submit', 'mode' => $mode, 'text' => $text));
        $d = json_decode($resp, true);
        $ip = isset($_SERVER['REMOTE_ADDR']) ? $_SERVER['REMOTE_ADDR'] : '';
        $len = preg_match_all('/./su', $text, $m);
        if (is_array($d) && isset($d['status']) && $d['status'] == 'queued') {
            ai_rw_log("AI-SUBMIT - $mode - ".$d['id']." - $len симв. - $ip \r ".ai_rw_cp($text));
        } else {
            ai_rw_log("AI-SUBMIT-ERROR - $mode - $len симв. - $ip - ".ai_rw_cp(is_array($d) && isset($d['error']) ? $d['error'] : $resp));
        }
        echo $resp;
    } elseif ($act == 'status' && isset($_POST['id']) && preg_match('/^[0-9a-f]{16}$/', $_POST['id'])) {
        $resp = ai_rw_call(array('action' => 'status', 'id' => $_POST['id']));
        ai_rw_log_result($_POST['id'], $resp);
        echo $resp;
    } else {
        echo ai_rw_err('Неверный запрос');
    }
    exit;
}

// Предзаполнение формы add_news из рерайта и Предложки (POST ai_*); без них - пустые строки.
// Принятие из Предложки пишется в лог (AI-FEED-ACCEPT): какие предложения берут.
function ai_rw_prefill() {
    $f = array('title' => 'ai_title', 'home' => 'ai_home', 'body' => 'ai_body', 'src_name' => 'ai_src_name', 'src_url' => 'ai_src_url', 'keywords' => 'ai_keywords', 'foto' => 'ai_foto', 'cat' => 'ai_cat');
    $r = array();
    foreach ($f as $k => $p) {
        $r[$k] = isset($_POST[$p]) ? trim(stripslashes($_POST[$p])) : '';
    }
    $r['cat'] = intval($r['cat']);
    if (!empty($_POST['ai_feed_id']) && preg_match('/^[a-z0-9_-]{1,80}$/i', $_POST['ai_feed_id'])) {
        $ip = isset($_SERVER['REMOTE_ADDR']) ? $_SERVER['REMOTE_ADDR'] : '';
        ai_rw_log('AI-FEED-ACCEPT - '.$_POST['ai_feed_id'].' - '.(isset($_SESSION['admin_name']) ? $_SESSION['admin_name'] : '')." - $ip \r ".$r['title']." \r теги: ".$r['keywords']." \r превью: ".$r['foto']." \r рубрика: ".$r['cat']);
    }
    return $r;
}

// Теги для save_news (скрытое поле keywords в add_news, его заполняет только Предложка):
// берутся только теги из ../widgets/tagarray.php, буква в букву, не больше 3;
// строка - ", тег1, тег2", как при редактировании новости. Иначе - пусто, как раньше.
function ai_feed_keywords() {
    if (empty($_POST['keywords'])) return '';
    $tags = array();
    ob_start();
    @include('../widgets/tagarray.php');
    ob_end_clean();
    $r = array();
    foreach (explode(',', stripslashes($_POST['keywords'])) as $t) {
        $t = trim($t);
        if ($t === '' || !isset($tags[$t]) || preg_match('/[\'"\\\\]/', $t) || in_array($t, $r)) continue;
        $r[] = $t;
        if (count($r) == 3) break;
    }
    return $r ? ', '.implode(', ', $r) : '';
}

function ai_rw_h($s) {
    return htmlspecialchars($s, ENT_QUOTES, 'cp1251');
}

function ai_rewrite() {
    if (empty($_SESSION['ai_rw_key'])) $_SESSION['ai_rw_key'] = md5(uniqid(mt_rand(), true));
    include('header.php');
    echo '<font color="FF9933"><b>></font>&nbsp;<a href="admin.php?go=news&in=add_news">'._ADDNEWNEWS.'</a></b>'."\n"
    .'&nbsp;&nbsp;<font color="FF9933"><b>></font>&nbsp;<a href="admin.php?go=news&in=ai_rewrite">Рерайт (ИИ)</a></b>'."\n"
//  .'&nbsp;&nbsp;<font color="FF9933"><b>></font>&nbsp;<a href="admin.php?go=news&in=ai_feed">Предложка (ИИ)</a></b>'."\n"
    .'&nbsp;&nbsp;<font color="FF9933"><b>></font>&nbsp;<a href="admin.php?go=news&in=previmg">Банк превью-фото</a></b>'."\n"
    .'&nbsp;&nbsp;<font color="FF9933"><b>></font>&nbsp;<a href="admin.php?go=news&in=all_tag">Управление ТЭГами</a></b><br><br>'."\n";
?>
<style>
#airw td { vertical-align: top; }
#airw .w { width: 700px; font-family: Arial, sans-serif; font-size: 13px; }
#airw .hint { color: #777; font-size: 11px; }
#airw-status { margin-left: 10px; }
#airw-status.err { color: #C00; font-weight: bold; }
#airw-notes { color: #C00; }
</style>
<center>
<table id="airw" border="0" cellspacing="1" bgcolor="#EFEFEF" cellpadding="3">
<tr><td colspan="2"><b>Рерайт новости (ИИ)</b>
 <span class="hint" id="airw-about"></span></td></tr>
<tr bgcolor="#FFFFFF"><td>Исходный текст</td><td>
 <textarea id="airw-src" class="w" rows="14"></textarea><br>
 <span class="hint">Символов: <span id="airw-len">0</span> (<span id="airw-lim"></span>)</span></td></tr>
<tr bgcolor="#FFFFFF"><td></td><td>
 <select id="airw-mode" onchange="airwMode()">
  <option value="rewrite" selected>Рерайт</option>
  <option value="proof">Проверка правописания</option>
 </select>
 <input type="button" id="airw-go" value="Переписать" onclick="airwGo()"><span id="airw-status"></span></td></tr>
<tbody id="airw-res" style="display:none">
<tr bgcolor="#FFFFFF"><td>Заголовок</td><td id="airw-titles"></td></tr>
<tr bgcolor="#FFFFFF"><td>Лид</td><td>
 <textarea id="airw-lead" class="w" rows="7"></textarea><br>
 <input type="button" value="Копировать" onclick="airwCopy('airw-lead')"> <span class="hint" id="airw-lead-n"></span></td></tr>
<tr bgcolor="#FFFFFF"><td>Текст</td><td>
 <textarea id="airw-body" class="w" rows="9"></textarea><br>
 <input type="button" value="Копировать" onclick="airwCopy('airw-body')"> <span class="hint" id="airw-body-n"></span></td></tr>
<tr bgcolor="#FFFFFF" id="airw-notes-row"><td>Проверить</td><td id="airw-notes"></td></tr>
<tr bgcolor="#FFFFFF"><td></td><td>
 <input type="button" value="Создать новость из этого варианта" onclick="airwCreate()">
 <span class="hint">- откроется форма добавления с выбранным заголовком, лидом и текстом</span></td></tr>
</tbody>
<tbody id="airw-proof" style="display:none">
<tr bgcolor="#FFFFFF"><td>Исправленный<br>текст</td><td>
 <textarea id="airw-fixed" class="w" rows="14"></textarea><br>
 <input type="button" value="Копировать" onclick="airwCopy('airw-fixed')"></td></tr>
<tr bgcolor="#FFFFFF" id="airw-fixes-row"><td>Исправлено</td><td id="airw-fixes"></td></tr>
</tbody>
</table>
</center>
<form id="airw-form" action="admin.php" method="post" style="display:none">
<input type="hidden" name="go" value="news"><input type="hidden" name="in" value="add_news">
<input type="hidden" name="ai_title"><input type="hidden" name="ai_home"><input type="hidden" name="ai_body">
</form>
<script type="text/javascript">
var AIRW = {key: '<?php echo $_SESSION['ai_rw_key']; ?>', id: '', t0: 0};
var AIRW_MODES = {
    rewrite: {btn: 'Переписать', min: 100, wait: 'ИИ пишет...',
        about: '- вставьте текст новости из любого источника: ИИ перескажет его в стиле редакции. Факты сверяйте с исходником.'},
    proof: {btn: 'Проверить', min: 20, wait: 'ИИ проверяет...',
        about: '- вставьте текст: ИИ исправит орфографию, пунктуацию и опечатки, не меняя формулировок.'}
};
function airwEl(id) { return document.getElementById(id); }
function airwStatus(msg, err) { var s = airwEl('airw-status'); s.className = err ? 'err' : ''; s.innerHTML = ''; s.appendChild(document.createTextNode(msg)); }
function airwWords(s) { s = s.replace(/^\s+|\s+$/g, ''); return s ? s.split(/\s+/).length : 0; }
function airwPost(params, cb) {
    var xhr = new XMLHttpRequest(), q = ['go=news', 'in=ai_rewrite_ajax', 'key=' + AIRW.key], k;
    for (k in params) q.push(k + '=' + encodeURIComponent(params[k]));
    xhr.open('POST', 'admin.php', true);
    xhr.setRequestHeader('Content-Type', 'application/x-www-form-urlencoded');
    xhr.onreadystatechange = function () {
        if (xhr.readyState != 4) return;
        var d;
        try { d = JSON.parse(xhr.responseText); } catch (e) { d = {status: 'error', error: 'Сайт вернул не JSON (HTTP ' + xhr.status + ')'}; }
        cb(d);
    };
    xhr.send(q.join('&'));
}
function airwM() { return AIRW_MODES[airwEl('airw-mode').value] || AIRW_MODES.rewrite; }
function airwMode() {
    var m = airwM();
    airwEl('airw-go').value = m.btn;
    airwEl('airw-about').innerHTML = m.about;
    airwEl('airw-lim').innerHTML = 'от ' + m.min + ' до 15000';
}
function airwFail(msg) { airwStatus('Ошибка: ' + msg, true); airwEl('airw-go').disabled = false; }
function airwGo() {
    var t = airwEl('airw-src').value.replace(/^\s+|\s+$/g, '');
    var mode = airwEl('airw-mode').value, m = airwM();
    if (t.length < m.min) { airwStatus('Текст слишком короткий - нужно хотя бы ' + m.min + ' символов', true); return; }
    if (t.length > 15000) { airwStatus('Текст длиннее 15000 символов - сократите', true); return; }
    airwEl('airw-go').disabled = true;
    airwStatus('Отправляю...');
    AIRW.mode = mode;
    airwPost({act: 'submit', mode: mode, text64: btoa(unescape(encodeURIComponent(t)))}, function (d) {
        if (d.status != 'queued') { airwFail(d.error || 'неизвестная ошибка'); return; }
        AIRW.id = d.id; AIRW.t0 = new Date().getTime();
        setTimeout(airwPoll, 2000);
    });
}
function airwPoll() {
    airwPost({act: 'status', id: AIRW.id}, function (d) {
        var sec = Math.round((new Date().getTime() - AIRW.t0) / 1000);
        if (d.status == 'pending') {
            if (sec > 300) { airwFail('нет ответа за 5 минут, попробуйте ещё раз'); return; }
            airwStatus(d.worker_down ? 'Ждём... сервис рерайта на сервере не отвечает (' + sec + ' с)'
                : AIRW_MODES[AIRW.mode].wait + ' ' + sec + ' с' + (d.ahead ? ' (перед вами в очереди: ' + d.ahead + ')' : ''));
            setTimeout(airwPoll, 2000);
        } else if (d.status == 'ok') {
            if (d.mode == 'proof') airwShowProof(d); else airwShow(d);
            airwStatus('Готово за ' + sec + ' с'); airwEl('airw-go').disabled = false;
        } else {
            airwFail(d.status == 'unknown' ? 'задание потерялось, попробуйте ещё раз' : (d.error || 'неизвестная ошибка'));
        }
    });
}
function airwShow(d) {
    var box = airwEl('airw-titles'), i, inp, rb, br;
    box.innerHTML = '';
    for (i = 0; i < d.titles.length; i++) {
        rb = document.createElement('input'); rb.type = 'radio'; rb.name = 'airw-t'; rb.value = i; rb.checked = (i == 0);
        inp = document.createElement('input'); inp.type = 'text'; inp.id = 'airw-t' + i; inp.className = 'w'; inp.style.width = '590px'; inp.value = d.titles[i];
        br = document.createElement('input'); br.type = 'button'; br.value = 'Копировать';
        br.onclick = (function (id) { return function () { airwCopy(id); }; })(inp.id);
        box.appendChild(rb); box.appendChild(inp); box.appendChild(document.createTextNode(' ')); box.appendChild(br);
        box.appendChild(document.createElement('br'));
    }
    airwEl('airw-lead').value = d.lead;
    airwEl('airw-body').value = d.body;
    airwEl('airw-lead-n').innerHTML = 'слов: ' + airwWords(d.lead);
    airwEl('airw-body-n').innerHTML = 'слов: ' + airwWords(d.body);
    airwEl('airw-notes').innerHTML = '';
    airwEl('airw-notes').appendChild(document.createTextNode(d.notes || ''));
    airwEl('airw-notes-row').style.display = d.notes ? '' : 'none';
    airwEl('airw-proof').style.display = 'none';
    airwEl('airw-res').style.display = '';
}
function airwShowProof(d) {
    airwEl('airw-fixed').value = d.text;
    airwEl('airw-fixes').innerHTML = '';
    airwEl('airw-fixes').appendChild(document.createTextNode(d.notes || 'ошибок не найдено'));
    airwEl('airw-res').style.display = 'none';
    airwEl('airw-proof').style.display = '';
}
function airwCopy(id) {
    var el = airwEl(id);
    el.focus(); el.select();
    try { document.execCommand('copy'); } catch (e) {}
}
function airwHtml(s) {
    s = s.replace(/^\s+|\s+$/g, '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    return s.replace(/\r?\n\s*\r?\n/g, '<br><br>').replace(/\r?\n/g, '<br>');
}
function airwCreate() {
    var f = airwEl('airw-form'), rs = document.getElementsByName('airw-t'), i, n = 0;
    for (i = 0; i < rs.length; i++) if (rs[i].checked) n = i;
    f.ai_title.value = airwEl('airw-t' + n).value;
    f.ai_home.value = airwHtml(airwEl('airw-lead').value);
    f.ai_body.value = airwHtml(airwEl('airw-body').value);
    f.submit();
}
airwEl('airw-src').onkeyup = airwEl('airw-src').onchange = function () { airwEl('airw-len').innerHTML = this.value.length; };
airwMode();
</script>
<?php
    include('footer.php');
}

