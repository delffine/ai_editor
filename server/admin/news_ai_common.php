// ---------------------------------------------------------------------
// Общие функции ИИ-блоков модуля новостей: запрос к VPS ИИ-редактора,
// журнал log/aieditГГГГММДД, предзаполнение формы add_news, теги для save_news.
// Браузер ходит только в news.php (сюда пускает только вошедшего админа,
// проверяет admin.php) - токен VPS в браузер не попадает. Ответ VPS - JSON
// в чистом ASCII, поэтому перекодировка cp1251 <-> UTF-8 не нужна.
// ---------------------------------------------------------------------
define('AI_URL', 'http://VPS_HOST:8808/ai-editor/feed.php');
define('AI_TOKEN', 'CHANGE_ME');

function ai_err($msg) {
    $msg = function_exists('mb_convert_encoding') ? mb_convert_encoding($msg, 'UTF-8', 'CP1251') : iconv('CP1251', 'UTF-8', $msg);
    return json_encode(array('status' => 'error', 'error' => $msg));
}

function ai_call($params) {
    $params['token'] = AI_TOKEN;
    $ch = curl_init(AI_URL);
    curl_setopt($ch, CURLOPT_POST, 1);
    curl_setopt($ch, CURLOPT_POSTFIELDS, http_build_query($params));
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
    curl_setopt($ch, CURLOPT_CONNECTTIMEOUT, 10);
    curl_setopt($ch, CURLOPT_TIMEOUT, 20);
    $data = curl_exec($ch);
    $err = curl_error($ch);
    $code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);
    if ($data === false) return ai_err('Нет связи с сервером ИИ-редактора: '.$err);
    if (substr(ltrim($data), 0, 1) != '{') return ai_err('Сервер ИИ-редактора ответил не JSON (HTTP '.$code.')');
    return $data;
}

// Лог в стиле log/newsave: log/aieditГГГГММДД (cp1251, строки через \r).
// Ошибки записи глушатся: warning испортил бы страницу.
function ai_log($str) {
    $t = function_exists('formatdate') ? formatdate("H:i:s", time()) : date("H:i:s");
    $h = @fopen('log/aiedit'.date('Ymd'), 'a');
    if (!$h) return;
    @fwrite($h, $t.' '.$str." \r ---------------------------------------------------------------------- "."\r");
    @fclose($h);
}

// Предзаполнение формы add_news из Предложки (POST ai_*); без них - пустые строки.
// Принятие из Предложки пишется в лог (AI-FEED-ACCEPT): какие предложения берут.
function ai_prefill() {
    $f = array('title' => 'ai_title', 'home' => 'ai_home', 'body' => 'ai_body', 'src_name' => 'ai_src_name', 'src_url' => 'ai_src_url', 'keywords' => 'ai_keywords', 'foto' => 'ai_foto', 'cat' => 'ai_cat');
    $r = array();
    foreach ($f as $k => $p) {
        $r[$k] = isset($_POST[$p]) ? trim(stripslashes($_POST[$p])) : '';
    }
    $r['cat'] = intval($r['cat']);
    if (!empty($_POST['ai_feed_id']) && preg_match('/^[a-z0-9_-]{1,80}$/i', $_POST['ai_feed_id'])) {
        $ip = isset($_SERVER['REMOTE_ADDR']) ? $_SERVER['REMOTE_ADDR'] : '';
        ai_log('AI-FEED-ACCEPT - '.$_POST['ai_feed_id'].' - '.(isset($_SESSION['admin_name']) ? $_SESSION['admin_name'] : '')." - $ip \r ".$r['title']." \r теги: ".$r['keywords']." \r превью: ".$r['foto']." \r рубрика: ".$r['cat']);
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

function ai_h($s) {
    return htmlspecialchars($s, ENT_QUOTES, 'cp1251');
}
