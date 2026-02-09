# Isolabox — Website & Offer

Marketing website for the Isolabox platform (powered by CloneBox + Sandboy).

## Quick Start

```bash
# Setup environment
cp .env.example .env
# Edit .env with your configuration

# Development server
cd isolabox
php -S localhost:8000 router.php

# Or with Docker
docker-compose up -d
# Visit http://localhost:8080
```

## Configuration

The application uses environment variables defined in `.env` file. Copy `.env.example` to `.env` and customize:

```bash
# Site Configuration
SITE_NAME=Isolabox
SITE_URL=https://isolabox.com
SITE_TAGLINE=Isolated Environments for AI Agents

# Host Configuration
PORT=8080              # External port
WEB_HOST=0.0.0.0       # Internal container host
WEB_PORT=80            # Internal container port

# Service Hosts (for future expansion)
DB_HOST=localhost      # Database host
DB_PORT=5432           # Database port
REDIS_HOST=localhost   # Redis host
REDIS_PORT=6379        # Redis port
API_HOST=localhost     # API host
API_PORT=3000          # API port

# Docker Service Names
WEB_SERVICE_NAME=isolabox-web
DB_SERVICE_NAME=isolabox-db
REDIS_SERVICE_NAME=isolabox-redis
API_SERVICE_NAME=isolabox-api

# Contact Information
CONTACT_EMAIL=hello@isolabox.com
SALES_EMAIL=sales@isolabox.com
SUPPORT_EMAIL=support@isolabox.com

# Social Media
TWITTER_URL=https://twitter.com/isolabox
LINKEDIN_URL=https://linkedin.com/company/isolabox

# Analytics
GA_ID=
PLAUSIBLE_DOMAIN=isolabox.com
```

### Environment-specific Configurations

**Development (default):**
```bash
# Uses docker-compose.override.yml automatically
docker-compose up -d
# Access at: http://localhost:8080
```

**Production:**
```bash
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
# Access at: http://localhost (ports 80/443)
```

## Project Structure

```
isolabox/
├── router.php                      # Clean URL router
├── docker-compose.yml              # Docker deployment
├── docker-compose.override.yml     # Development overrides
├── docker-compose.prod.yml         # Production overrides
├── .env                            # Environment variables (create from .env.example)
├── .env.example                    # Environment variables template
├── .dockerignore                   # Docker ignore rules
├── config/
│   └── config.php                  # Site-wide configuration (loads from .env)
├── includes/
│   ├── functions.php               # Data: pricing, roadmap, features, comparisons
│   ├── header.php                  # HTML head + navigation
│   └── footer.php                  # Footer + closing tags
├── public/                         # Document root
│   ├── index.php                   # Landing page (hero, features, pricing, roadmap)
│   ├── .htaccess                   # Apache rewrite rules
│   └── assets/
│       ├── css/
│       │   └── style.css           # Full design system (dark theme, responsive)
│       ├── js/
│       │   └── main.js             # Smooth scroll, animations, copy button
│       └── images/
│           └── favicon.svg         # SVG favicon
└── pages/                          # Additional pages
    ├── 404.php                     # Error page
    ├── contact.php                 # Contact / enterprise inquiry form
    ├── signup.php                  # Sign up flow
    ├── blog.php                    # Blog listing
    ├── changelog.php               # Version changelog
    ├── privacy.php                 # Privacy policy
    └── about.php                   # About the company
```

## Architecture Decisions

- **Pure PHP** — No framework dependencies. Runs anywhere with PHP 8.0+
- **No build step** — CSS and JS are vanilla, no compilation needed
- **Data-driven** — Pricing, roadmap, features defined as PHP arrays in `functions.php`
- **SEO-ready** — Semantic HTML, Open Graph meta, structured headings
- **Performance** — No external CSS framework, minimal JS, fonts preloaded
- **Responsive** — Mobile-first, tested at 320px, 768px, 1200px

## Customization

All content data lives in `includes/functions.php`:
- `get_pricing_tiers()` — Edit pricing, features per tier, CTAs
- `get_roadmap()` — Add/edit roadmap phases
- `get_features()` — 12 feature cards with icons, descriptions, tags
- `get_competitor_comparison()` — Comparison table data

Site config in `config/config.php` loads from environment variables:
- URLs, contact emails, social links, analytics IDs are defined in `.env`

## Deployment

### Apache
Point document root to `public/`. Enable `mod_rewrite`.

### Nginx
```nginx
server {
    root /var/www/isolabox/public;
    index index.php;
    
    location / {
        try_files $uri $uri/ /index.php?$query_string;
    }
    
    location ~ \.php$ {
        fastcgi_pass unix:/run/php/php8.3-fpm.sock;
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
        include fastcgi_params;
    }
}
```

### Cloudflare Pages + PHP
Not natively supported. Use a VPS or managed PHP hosting.

## Pages Included

| Page | URL | Description |
|------|-----|-------------|
| Landing | `/` | Full marketing page with 7 sections |
| Features | `/#features` | 12 feature cards |
| Compare | `/#compare` | 5-way competitor comparison table |
| Pricing | `/#pricing` | 3 tiers + 4 add-on services |
| Roadmap | `/#roadmap` | 5 phases from v1.0 to v2.0 |
| Use Cases | `/#usecases` | 4 primary use cases |
| 404 | `/anything-else` | Custom error page |
