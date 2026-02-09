<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title><?= htmlspecialchars($page_title ?? SITE_NAME) ?></title>
    <meta name="description" content="<?= htmlspecialchars($page_description ?? SITE_TAGLINE) ?>">
    
    <!-- Open Graph -->
    <meta property="og:title" content="<?= htmlspecialchars($page_title ?? SITE_NAME) ?>">
    <meta property="og:description" content="<?= htmlspecialchars($page_description ?? SITE_TAGLINE) ?>">
    <meta property="og:type" content="website">
    <meta property="og:url" content="<?= SITE_URL ?>">
    <meta property="og:image" content="<?= SITE_URL ?>/assets/images/og-image.png">
    
    <!-- Twitter -->
    <meta name="twitter:card" content="summary_large_image">
    
    <!-- Favicon -->
    <link rel="icon" type="image/svg+xml" href="/assets/images/favicon.svg">
    
    <!-- Fonts -->
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Outfit:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
    
    <!-- Styles -->
    <link rel="stylesheet" href="/assets/css/style.css">

    <?php if (GA_ID): ?>
    <script async src="https://www.googletagmanager.com/gtag/js?id=<?= GA_ID ?>"></script>
    <?php endif; ?>
    <?php if (PLAUSIBLE_DOMAIN): ?>
    <script defer data-domain="<?= PLAUSIBLE_DOMAIN ?>" src="https://plausible.io/js/script.js"></script>
    <?php endif; ?>
</head>
<body>
    <header class="nav">
        <div class="nav__inner">
            <a href="/" class="nav__logo">
                <svg class="nav__logo-icon" width="32" height="32" viewBox="0 0 32 32" fill="none">
                    <rect width="32" height="32" rx="8" fill="url(#logo-grad)"/>
                    <path d="M10 12h12v2H10zm0 3h12v2H10zm0 3h8v2h-8z" fill="white" opacity="0.9"/>
                    <circle cx="24" cy="10" r="3" fill="#4ade80"/>
                    <defs><linearGradient id="logo-grad" x1="0" y1="0" x2="32" y2="32"><stop stop-color="#0f172a"/><stop offset="1" stop-color="#1e293b"/></linearGradient></defs>
                </svg>
                <span class="nav__logo-text"><?= SITE_NAME ?></span>
            </a>
            <nav class="nav__links">
                <?php foreach (get_nav_items() as $item): ?>
                <a href="<?= htmlspecialchars($item['url']) ?>" class="nav__link"><?= htmlspecialchars($item['label']) ?></a>
                <?php endforeach; ?>
            </nav>
            <div class="nav__actions">
                <a href="<?= GITHUB_URL ?>" class="btn btn--ghost btn--sm" target="_blank">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z"/></svg>
                    GitHub
                </a>
                <a href="#pricing" class="btn btn--primary btn--sm">Get Started</a>
            </div>
            <button class="nav__burger" aria-label="Menu" onclick="document.body.classList.toggle('nav-open')">
                <span></span><span></span><span></span>
            </button>
        </div>
    </header>
