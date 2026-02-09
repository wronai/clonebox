    <footer class="footer">
        <div class="footer__inner">
            <div class="footer__grid">
                <div class="footer__brand">
                    <a href="/" class="nav__logo">
                        <span class="nav__logo-text"><?= SITE_NAME ?></span>
                    </a>
                    <p class="footer__tagline"><?= SITE_TAGLINE ?></p>
                    <p class="footer__copy">&copy; <?= date('Y') ?> <?= SITE_NAME ?>. Built in Gdańsk, Poland 🇵🇱</p>
                </div>
                <div class="footer__col">
                    <h4>Product</h4>
                    <a href="#features">Features</a>
                    <a href="#pricing">Pricing</a>
                    <a href="#roadmap">Roadmap</a>
                    <a href="#compare">Comparison</a>
                    <a href="/changelog">Changelog</a>
                </div>
                <div class="footer__col">
                    <h4>Resources</h4>
                    <a href="<?= DOCS_URL ?>">Documentation</a>
                    <a href="<?= GITHUB_URL ?>">GitHub</a>
                    <a href="<?= GITHUB_URL ?>/issues">Bug Reports</a>
                    <a href="/blog">Blog</a>
                    <a href="/api">API Reference</a>
                </div>
                <div class="footer__col">
                    <h4>Company</h4>
                    <a href="/about">About</a>
                    <a href="mailto:<?= CONTACT_EMAIL ?>">Contact</a>
                    <a href="<?= DISCORD_URL ?>">Discord</a>
                    <a href="<?= TWITTER_URL ?>">Twitter / X</a>
                    <a href="/privacy">Privacy Policy</a>
                </div>
            </div>
        </div>
    </footer>

    <script src="/assets/js/main.js"></script>
</body>
</html>
