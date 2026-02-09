<?php
require_once __DIR__ . '/../config/config.php';
require_once __DIR__ . '/../includes/functions.php';
$page_title = '404 — Page Not Found | ' . SITE_NAME;
require_once __DIR__ . '/../includes/header.php';
?>
<main>
    <section class="section" style="min-height: 60vh; display: flex; align-items: center;">
        <div class="container" style="text-align: center;">
            <h1 style="font-size: 6rem; font-family: var(--font-mono); color: var(--accent); margin-bottom: var(--space-md);">404</h1>
            <p style="color: var(--text-secondary); font-size: 1.15rem; margin-bottom: var(--space-xl);">This page doesn't exist. Maybe it's in an isolated VM somewhere.</p>
            <a href="/" class="btn btn--primary">Back to Home</a>
        </div>
    </section>
</main>
<?php require_once __DIR__ . '/../includes/footer.php'; ?>
