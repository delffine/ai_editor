<?php
// Очередь рерайта для диалога в админке syzran-small.ru.
// POST token + action=submit + text [+ mode=rewrite|proof]  -> {"status":"queued","id":"…"}
// POST token + action=status + id    -> {"status":"pending"|"ok"|"error"|"unknown", …}
// POST token + action=feed           -> {"status":"ok","updated":…,"latest":…,"items":[…]} (Предложка)
// Сам рерайт делает воркер под deploy (~/ai-editor/rewrite_worker.py):
// он забирает .rewrite/in/<id>.json и пишет .rewrite/out/<id>.json.
// Токен — свой, не тот, что у publish.php; в браузер не попадает (его знает
// только прокси в админке сайта).
$SECRET = 'CHANGE_ME';

$QUEUE = __DIR__ . '/.rewrite';   // nginx не отдаёт пути с /. — каталог закрыт снаружи
$MAX_BYTES = 40000;               // ~15 тыс. символов кириллицы
$MAX_PER_HOUR = 40;
$MAX_PENDING = 5;
$WORKER_DEAD_SEC = 90;

header('Content-Type: application/json; charset=utf-8');

function reply($code, $data) {
    http_response_code($code);
    echo json_encode($data);      // кириллица — в \u-последовательностях: ответ чистый ASCII
    exit;
}

if ($_SERVER['REQUEST_METHOD'] !== 'POST') reply(405, ['status' => 'error', 'error' => 'method not allowed']);
if (!hash_equals($SECRET, (string) ($_POST['token'] ?? ''))) reply(403, ['status' => 'error', 'error' => 'forbidden']);

// Лента предложений для «Предложки (ИИ)» в админке: её пишет finish.py после каждого прогона
if (($_POST['action'] ?? '') === 'feed') {
    $feed = json_decode((string) @file_get_contents(__DIR__ . '/.feed.json'), true);
    if (!is_array($feed)) reply(503, ['status' => 'error', 'error' => 'Лента предложений ещё не сформирована']);
    reply(200, ['status' => 'ok'] + $feed);
}

$in = $QUEUE . '/in';
$out = $QUEUE . '/out';
if (!is_dir($in) || !is_dir($out)) reply(503, ['status' => 'error', 'error' => 'Сервис рерайта не запущен']);

$action = $_POST['action'] ?? '';

if ($action === 'status') {
    $id = (string) ($_POST['id'] ?? '');
    if (!preg_match('/^[0-9a-f]{16}$/', $id)) reply(400, ['status' => 'error', 'error' => 'bad id']);
    if (is_file("$out/$id.json")) {
        echo file_get_contents("$out/$id.json");
        exit;
    }
    if (is_file("$in/$id.json")) {
        $mine = filemtime("$in/$id.json");
        $ahead = 0;
        foreach (glob("$in/*.json") as $f) if (filemtime($f) < $mine) $ahead++;
        $alive = @filemtime("$QUEUE/worker.alive");
        $down = !$alive || time() - $alive > $WORKER_DEAD_SEC;
        reply(200, ['status' => 'pending', 'ahead' => $ahead, 'worker_down' => $down]);
    }
    reply(200, ['status' => 'unknown']);
}

if ($action !== 'submit') reply(400, ['status' => 'error', 'error' => 'bad action']);

$text = trim((string) ($_POST['text'] ?? ''));
if (!preg_match('//u', $text)) reply(400, ['status' => 'error', 'error' => 'Текст не в UTF-8']);
$mode = ($_POST['mode'] ?? '') === 'proof' ? 'proof' : 'rewrite';
// Длина в символах без mbstring (на VPS его нет); проверке правописания хватит и короткого текста
if (preg_match_all('/./su', $text) < ($mode === 'proof' ? 20 : 100)) reply(400, ['status' => 'error', 'error' => 'Слишком короткий текст']);
if (strlen($text) > $MAX_BYTES) reply(413, ['status' => 'error', 'error' => 'Слишком длинный текст']);
if (count(glob("$in/*.json")) >= $MAX_PENDING) reply(429, ['status' => 'error', 'error' => 'Очередь занята, попробуйте через минуту']);

// Лимит заданий в час: журнал отметок времени под flock
$fp = fopen("$QUEUE/rate.log", 'c+');
flock($fp, LOCK_EX);
$now = time();
$stamps = array_filter(array_map('intval', explode("\n", stream_get_contents($fp))),
    function ($t) use ($now) { return $t > $now - 3600; });
if (count($stamps) >= $MAX_PER_HOUR) {
    flock($fp, LOCK_UN);
    reply(429, ['status' => 'error', 'error' => "Лимит $MAX_PER_HOUR рерайтов в час исчерпан"]);
}
$stamps[] = $now;
ftruncate($fp, 0);
rewind($fp);
fwrite($fp, implode("\n", $stamps));
flock($fp, LOCK_UN);
fclose($fp);

$id = bin2hex(random_bytes(8));
$tmp = "$in/.$id.tmp";
if (file_put_contents($tmp, json_encode(['id' => $id, 'mode' => $mode, 'text' => $text, 'created' => $now])) === false
    || !rename($tmp, "$in/$id.json")) {
    reply(500, ['status' => 'error', 'error' => 'write failed']);
}
reply(200, ['status' => 'queued', 'id' => $id]);
