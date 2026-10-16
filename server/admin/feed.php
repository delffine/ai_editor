<?php
// Лента предложений для «Предложки (ИИ)» в админке syzran-small.ru.
// POST token -> {"status":"ok","updated":…,"next":…,"latest":…,"items":[…]}
// Ленту пишет finish.py после каждого прогона (.feed.json рядом со скриптом;
// nginx не отдаёт файлы с точкой в начале имени). Токен в браузер не попадает:
// его знает только прокси в админке сайта (news_ai_common.php).
$SECRET = 'CHANGE_ME';

header('Content-Type: application/json; charset=utf-8');

function reply($code, $data) {
    http_response_code($code);
    echo json_encode($data);      // кириллица — в \u-последовательностях: ответ чистый ASCII
    exit;
}

if ($_SERVER['REQUEST_METHOD'] !== 'POST') reply(405, ['status' => 'error', 'error' => 'method not allowed']);
if (!hash_equals($SECRET, (string) ($_POST['token'] ?? ''))) reply(403, ['status' => 'error', 'error' => 'forbidden']);

$feed = json_decode((string) @file_get_contents(__DIR__ . '/.feed.json'), true);
if (!is_array($feed)) reply(503, ['status' => 'error', 'error' => 'Лента предложений ещё не сформирована']);
reply(200, ['status' => 'ok'] + $feed);
