<?php
/**
 * Isolabox Configuration
 */

// Load environment variables
function loadEnv($path) {
    if (!file_exists($path)) {
        return;
    }
    
    $lines = file($path, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES);
    foreach ($lines as $line) {
        if (strpos(trim($line), '#') === 0) {
            continue;
        }
        
        list($name, $value) = explode('=', $line, 2);
        $name = trim($name);
        $value = trim($value);
        
        if (!array_key_exists($name, $_SERVER) && !array_key_exists($name, $_ENV)) {
            putenv(sprintf('%s=%s', $name, $value));
            $_ENV[$name] = $value;
            $_SERVER[$name] = $value;
        }
    }
}

// Load .env from config directory
loadEnv(__DIR__ . '/../.env');

// Site Configuration
define('SITE_NAME', getenv('SITE_NAME') ?: 'Isolabox');
define('SITE_URL', getenv('SITE_URL') ?: 'https://isolabox.com');
define('SITE_TAGLINE', getenv('SITE_TAGLINE') ?: 'Isolated Environments for AI Agents');
define('SITE_VERSION', getenv('SITE_VERSION') ?: '1.1.2');
define('GITHUB_URL', getenv('GITHUB_URL') ?: 'https://github.com/wronai/clonebox');
define('DOCS_URL', getenv('DOCS_URL') ?: 'https://docs.isolabox.com');
define('DISCORD_URL', getenv('DISCORD_URL') ?: 'https://discord.gg/isolabox');

// Contact
define('CONTACT_EMAIL', getenv('CONTACT_EMAIL') ?: 'hello@isolabox.com');
define('SALES_EMAIL', getenv('SALES_EMAIL') ?: 'sales@isolabox.com');
define('SUPPORT_EMAIL', getenv('SUPPORT_EMAIL') ?: 'support@isolabox.com');

// Social
define('TWITTER_URL', getenv('TWITTER_URL') ?: 'https://twitter.com/isolabox');
define('LINKEDIN_URL', getenv('LINKEDIN_URL') ?: 'https://linkedin.com/company/isolabox');

// Analytics
define('GA_ID', getenv('GA_ID') ?: '');
define('PLAUSIBLE_DOMAIN', getenv('PLAUSIBLE_DOMAIN') ?: 'isolabox.com');

// Host Configuration
define('HOST', 'localhost');
define('PORT', getenv('PORT') ?: '8080');
define('WEB_HOST', getenv('WEB_HOST') ?: '0.0.0.0');
define('WEB_PORT', getenv('WEB_PORT') ?: '80');
define('DB_HOST', getenv('DB_HOST') ?: 'localhost');
define('DB_PORT', getenv('DB_PORT') ?: '5432');
define('REDIS_HOST', getenv('REDIS_HOST') ?: 'localhost');
define('REDIS_PORT', getenv('REDIS_PORT') ?: '6379');
define('API_HOST', getenv('API_HOST') ?: 'localhost');
define('API_PORT', getenv('API_PORT') ?: '3000');

// Docker Service Names
define('WEB_SERVICE_NAME', getenv('WEB_SERVICE_NAME') ?: 'isolabox-web');
define('DB_SERVICE_NAME', getenv('DB_SERVICE_NAME') ?: 'isolabox-db');
define('REDIS_SERVICE_NAME', getenv('REDIS_SERVICE_NAME') ?: 'isolabox-redis');
define('API_SERVICE_NAME', getenv('API_SERVICE_NAME') ?: 'isolabox-api');

// Application URLs
define('BASE_URL', (getenv('APP_ENV') === 'production') ? SITE_URL : "http://" . HOST . ":" . PORT);
define('API_URL', "http://" . API_HOST . ":" . API_PORT);
define('DB_URL', DB_HOST . ":" . DB_PORT);
