<?php
// Приём дайджеста от агента (AI-редактор) и запись в index.html рядом с этим
// скриптом. Токен нужен, чтобы принимать публикации только от доверенного
// отправителя — при компрометации сгенерировать новый и поменять здесь и
// там, откуда шлётся запрос.
$SECRET = 'CHANGE_ME';

date_default_timezone_set('Europe/Samara');

header('Content-Type: application/json; charset=utf-8');

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    http_response_code(405);
    echo json_encode(['error' => 'method not allowed']);
    exit;
}

$token = $_POST['token'] ?? '';
if (!hash_equals($SECRET, (string) $token)) {
    http_response_code(403);
    echo json_encode(['error' => 'forbidden']);
    exit;
}

$html = $_POST['html'] ?? '';
if ($html === '') {
    http_response_code(400);
    echo json_encode(['error' => 'empty html']);
    exit;
}

if (strlen($html) > 2 * 1024 * 1024) {
    http_response_code(413);
    echo json_encode(['error' => 'too large']);
    exit;
}

$target = __DIR__ . '/index.html';
$archiveDir = __DIR__ . '/archive';
$archivedAs = null;

// Старую версию не стираем — переносим в archive/ под именем с её
// собственным временем создания (mtime файла), а не текущим временем.
if (file_exists($target)) {
    if (!is_dir($archiveDir)) {
        mkdir($archiveDir, 0775, true);
    }
    $oldTime = filemtime($target) ?: time();
    $archivedAs = 'digest_' . date('Y-m-d_His', $oldTime) . '.html';
    copy($target, $archiveDir . '/' . $archivedAs);
}

// Метку времени публикации ставит сам сервер (а не то, что напишет в тексте
// генератор дайджеста) — так она всегда достоверна и в одном часовом поясе.
$publishedStamp = date('d.m.Y H:i');
$banner = "<p><strong>Дайджест обновлён:</strong> {$publishedStamp} (время редакции, Europe/Samara)</p>\n";

if (preg_match('/<h1[^>]*>.*?<\/h1>/is', $html)) {
    $html = preg_replace('/(<h1[^>]*>.*?<\/h1>)/is', '$1' . "\n" . $banner, $html, 1);
} else {
    $html = $banner . $html;
}

$written = file_put_contents($target, $html);

if ($written === false) {
    http_response_code(500);
    echo json_encode(['error' => 'write failed']);
    exit;
}

echo json_encode([
    'status' => 'ok',
    'bytes' => $written,
    'published_at' => $publishedStamp,
    'archived_previous_as' => $archivedAs,
]);
