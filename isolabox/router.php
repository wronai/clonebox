<?php
/**
 * Isolabox Router
 * Usage: php -S localhost:8000 router.php
 */

$uri = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH);

// Serve static files directly
$static_path = __DIR__ . '/public' . $uri;
if ($uri !== '/' && file_exists($static_path) && !is_dir($static_path)) {
    $ext = pathinfo($static_path, PATHINFO_EXTENSION);
    $mime_types = [
        'css' => 'text/css',
        'js' => 'application/javascript',
        'svg' => 'image/svg+xml',
        'png' => 'image/png',
        'jpg' => 'image/jpeg',
        'ico' => 'image/x-icon',
        'woff2' => 'font/woff2',
    ];
    if (isset($mime_types[$ext])) {
        header("Content-Type: {$mime_types[$ext]}");
        readfile($static_path);
        return;
    }
    return false;
}

// Route pages
$routes = [
    '/' => 'public/index.php',
    '/contact' => 'pages/contact.php',
    '/signup' => 'pages/signup.php',
    '/blog' => 'pages/blog.php',
    '/changelog' => 'pages/changelog.php',
    '/privacy' => 'pages/privacy.php',
    '/about' => 'pages/about.php',
];

$page = $routes[$uri] ?? null;

if ($page && file_exists(__DIR__ . '/' . $page)) {
    require __DIR__ . '/' . $page;
} else {
    http_response_code(404);
    require __DIR__ . '/pages/404.php';
}
