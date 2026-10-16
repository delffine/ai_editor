<?php
// RSS-лента последних новостей для ИИ-редактора.
// ?limit=N — сколько новостей отдать (по умолчанию 30, максимум 5000).

// Текст из БД -> чистый текст: без BB-кодов, HTML-тегов и сущностей,
// переводы строк и абзацы -> пробелы (чтобы не склеивались предложения).
function clear($text) {
    $text = stripslashes((string) $text);

    // Картинки выбрасываем целиком, у ссылок и цитат оставляем текст
    $text = preg_replace('~\[img[^\]]*\].*?\[/img\]~is', '', $text);
    $text = preg_replace('~\[/?(b|i|u|s|color|size|font|center|left|right|quote|url)(=[^\]]*)?\]~i', '', $text);

    // Абзацы и переносы — в пробел до удаления тегов
    $text = preg_replace('~<\s*(br|/p|/div|/li|/h\d)\b[^>]*>~i', ' ', $text);
    $text = strip_tags($text);
    $text = str_replace(array("\r", "\n", "\t"), ' ', $text);

    // &#8209;, &nbsp;, &laquo; и т.п. -> обычные символы
    $text = html_entity_decode($text, ENT_QUOTES | ENT_HTML5, 'UTF-8');
    $text = str_replace("\xC2\xA0", ' ', $text);

    return trim(preg_replace('~\s+~u', ' ', $text));
}

// Экранирование для XML — для ВСЕХ полей
function x($text) {
    return htmlspecialchars((string) $text, ENT_XML1 | ENT_QUOTES, 'UTF-8');
}

// Время в ленте — как у редакции (в CMS задан самарский пояс); скрипт
// работает вне движка и иначе взял бы пояс сервера (МСК).
date_default_timezone_set('Europe/Samara');

$limit = isset($_GET['limit']) ? (int) $_GET['limit'] : 30;
if ($limit < 1 || $limit > 5000) {
    $limit = 30;
}

$db = mysqli_connect("x", "x", "x", "x");
if (!$db) {
    http_response_code(500);
    exit;
}

$result = mysqli_query($db, "SELECT * FROM aaa_mod_news ORDER BY id DESC LIMIT " . $limit);
if (!$result) {
    http_response_code(500);
    mysqli_close($db);
    exit;
}

header("Content-Type: text/xml; charset=utf-8");
echo "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n";
echo "<rss version=\"2.0\">\n";
echo "<channel>\n";
echo "<title>syzran-small</title>\n";
echo "<link>https://www.syzran-small.ru</link>\n";
echo "<description>syzran-small</description>\n";
echo "<language>ru-ru</language>\n";

while ($row = mysqli_fetch_row($result)) {
    echo "<item>\n";
    echo "<title>" . x(clear($row[3])) . "</title>\n";
    echo "<link>https://www.syzran-small.ru/news-" . (int) $row[0] . "</link>\n";
    echo "<pubDate>" . date("r", (int) $row[7]) . "</pubDate>\n";
    echo "<hits>" . (int) $row[11] . "</hits>\n";
    echo "<home-text>" . x(clear($row[5])) . "</home-text>\n";
    echo "<body-text>" . x(clear($row[6])) . "</body-text>\n";
    echo "<import_name>" . x(clear($row[9])) . "</import_name>\n";
    echo "<import_url>" . x(trim((string) $row[10])) . "</import_url>\n";
    echo "</item>\n";
}

mysqli_close($db);
echo "</channel>\n";
echo "</rss>\n";
