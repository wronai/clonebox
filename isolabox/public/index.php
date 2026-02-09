<?php
/**
 * Isolabox - Isolated Environments for AI Agents
 * Main landing page with routing
 */
require_once __DIR__ . '/../config/config.php';
require_once __DIR__ . '/../includes/functions.php';

// Routing logic for Apache
$uri = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH);

// Route pages
$routes = [
    '/contact' => 'pages/contact.php',
    '/signup' => 'pages/signup.php',
    '/blog' => 'pages/blog.php',
    '/changelog' => 'pages/changelog.php',
    '/privacy' => 'pages/privacy.php',
    '/about' => 'pages/about.php',
];

// Check if this is a route other than home
if ($uri !== '/' && isset($routes[$uri])) {
    $page = $routes[$uri];
    if (file_exists(__DIR__ . '/../' . $page)) {
        require __DIR__ . '/../' . $page;
        exit;
    }
}

// If not a valid route and not home, show 404
if ($uri !== '/' && !isset($routes[$uri])) {
    http_response_code(404);
    require __DIR__ . '/../pages/404.php';
    exit;
}

// Continue with home page
$page_title = 'Isolabox — Isolated Environments for AI Agents';
$page_description = 'Self-hosted VM sandboxing platform for secure AI agent deployment. Open-source, fast, enterprise-ready.';

// Pricing tiers
$pricing = get_pricing_tiers();
$roadmap = get_roadmap();
$features = get_features();
$competitors = get_competitor_comparison();

require_once __DIR__ . '/../includes/header.php';
?>

<main>
    <!-- HERO -->
    <section class="hero" id="hero">
        <div class="hero__grid">
            <div class="hero__noise"></div>
            <div class="hero__content">
                <div class="hero__badge">Open Source · Self-Hosted · Enterprise Ready</div>
                <h1 class="hero__title">
                    <span class="hero__title-line">Isolated</span>
                    <span class="hero__title-line hero__title-line--accent">environments</span>
                    <span class="hero__title-line">for AI agents</span>
                </h1>
                <p class="hero__subtitle">
                    Spin up secure VM sandboxes in seconds. Let your AI agents execute code, 
                    browse the web, and interact with tools — without risking your infrastructure.
                </p>
                <div class="hero__actions">
                    <a href="#pricing" class="btn btn--primary">
                        <span>Get Started Free</span>
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12h14M12 5l7 7-7 7"/></svg>
                    </a>
                    <a href="https://github.com/wronai/clonebox" class="btn btn--ghost" target="_blank">
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z"/></svg>
                        <span>View on GitHub</span>
                    </a>
                </div>
                <div class="hero__stats">
                    <div class="hero__stat">
                        <span class="hero__stat-number">&lt;60s</span>
                        <span class="hero__stat-label">VM boot time</span>
                    </div>
                    <div class="hero__stat">
                        <span class="hero__stat-number">10K+</span>
                        <span class="hero__stat-label">Lines of code</span>
                    </div>
                    <div class="hero__stat">
                        <span class="hero__stat-number">100%</span>
                        <span class="hero__stat-label">Self-hosted</span>
                    </div>
                </div>
            </div>
            <div class="hero__terminal">
                <div class="terminal">
                    <div class="terminal__bar">
                        <span class="terminal__dot terminal__dot--red"></span>
                        <span class="terminal__dot terminal__dot--yellow"></span>
                        <span class="terminal__dot terminal__dot--green"></span>
                        <span class="terminal__title">terminal</span>
                    </div>
                    <div class="terminal__body">
                        <pre><code><span class="t-prompt">$</span> pip install clonebox
<span class="t-comment"># Detect your environment</span>
<span class="t-prompt">$</span> clonebox detect
<span class="t-output">Found: Docker, PostgreSQL, nginx, Node.js
  Projects: ~/myapp, ~/ai-agent
  Apps: VS Code, Firefox, Slack</span>

<span class="t-comment"># Clone to isolated VM</span>
<span class="t-prompt">$</span> clonebox clone . --user --run
<span class="t-success">✓ VM "dev-clone-01" ready in 47s
✓ 12 packages installed
✓ 3 services running
✓ GUI available via SPICE</span>

<span class="t-comment"># Let your AI agent work safely</span>
<span class="t-prompt">$</span> clonebox sandbox --agent openai
<span class="t-success">✓ Agent sandbox active
✓ Firewall: egress-only
✓ Snapshot: pre-agent-run</span></code></pre>
                    </div>
                </div>
            </div>
        </div>
    </section>

    <!-- PROBLEM / SOLUTION -->
    <section class="section section--dark" id="why">
        <div class="container">
            <div class="section__header">
                <span class="section__label">The Problem</span>
                <h2 class="section__title">AI agents need <em>real computers</em>, not just APIs</h2>
            </div>
            <div class="problem-grid">
                <div class="problem-card problem-card--bad">
                    <div class="problem-card__icon">⚠️</div>
                    <h3>Without Isolabox</h3>
                    <ul>
                        <li>Agents run on your production machine</li>
                        <li>One bad command = host compromise</li>
                        <li>No audit trail of agent actions</li>
                        <li>Manual environment setup takes hours</li>
                        <li>Cloud-only solutions = vendor lock-in</li>
                    </ul>
                </div>
                <div class="problem-card problem-card--good">
                    <div class="problem-card__icon">🛡️</div>
                    <h3>With Isolabox</h3>
                    <ul>
                        <li>Each agent gets an isolated VM sandbox</li>
                        <li>Snapshot & rollback after every run</li>
                        <li>Full audit logging of every action</li>
                        <li>Clone your workstation in 60 seconds</li>
                        <li>Self-hosted — your data stays yours</li>
                    </ul>
                </div>
            </div>
        </div>
    </section>

    <!-- FEATURES -->
    <section class="section" id="features">
        <div class="container">
            <div class="section__header">
                <span class="section__label">Capabilities</span>
                <h2 class="section__title">Everything you need for secure agent deployment</h2>
            </div>
            <div class="features-grid">
                <?php foreach ($features as $feature): ?>
                <div class="feature-card">
                    <div class="feature-card__icon"><?= $feature['icon'] ?></div>
                    <h3 class="feature-card__title"><?= htmlspecialchars($feature['title']) ?></h3>
                    <p class="feature-card__desc"><?= htmlspecialchars($feature['description']) ?></p>
                    <?php if (!empty($feature['tag'])): ?>
                    <span class="feature-card__tag"><?= htmlspecialchars($feature['tag']) ?></span>
                    <?php endif; ?>
                </div>
                <?php endforeach; ?>
            </div>
        </div>
    </section>

    <!-- COMPARISON -->
    <section class="section section--dark" id="compare">
        <div class="container">
            <div class="section__header">
                <span class="section__label">Comparison</span>
                <h2 class="section__title">How Isolabox stacks up</h2>
            </div>
            <div class="table-wrapper">
                <table class="comparison-table">
                    <thead>
                        <tr>
                            <th>Feature</th>
                            <?php foreach ($competitors as $name => $data): ?>
                            <th class="<?= $name === 'Isolabox' ? 'highlight' : '' ?>"><?= htmlspecialchars($name) ?></th>
                            <?php endforeach; ?>
                        </tr>
                    </thead>
                    <tbody>
                        <?php
                        $features_list = ['Self-hosted', 'Open Source', 'AI Agent Focus', 'VM Isolation', 'Container Support', 'GUI/Desktop', 'Audit Logging', 'Snapshot/Rollback', 'Usage Pricing'];
                        foreach ($features_list as $feat):
                        ?>
                        <tr>
                            <td><?= htmlspecialchars($feat) ?></td>
                            <?php foreach ($competitors as $name => $data): ?>
                            <td class="<?= $name === 'Isolabox' ? 'highlight' : '' ?>">
                                <?php
                                $val = $data[$feat] ?? '—';
                                if ($val === true) echo '<span class="check">✓</span>';
                                elseif ($val === false) echo '<span class="cross">✗</span>';
                                elseif ($val === 'partial') echo '<span class="partial">◐</span>';
                                else echo htmlspecialchars($val);
                                ?>
                            </td>
                            <?php endforeach; ?>
                        </tr>
                        <?php endforeach; ?>
                    </tbody>
                </table>
            </div>
        </div>
    </section>

    <!-- PRICING -->
    <section class="section" id="pricing">
        <div class="container">
            <div class="section__header">
                <span class="section__label">Pricing</span>
                <h2 class="section__title">Start free. Scale when ready.</h2>
                <p class="section__subtitle">No credit card required. Community edition is free forever.</p>
            </div>
            <div class="pricing-grid">
                <?php foreach ($pricing as $tier): ?>
                <div class="pricing-card <?= $tier['featured'] ? 'pricing-card--featured' : '' ?>">
                    <?php if ($tier['featured']): ?>
                    <div class="pricing-card__badge">Most Popular</div>
                    <?php endif; ?>
                    <div class="pricing-card__header">
                        <h3 class="pricing-card__name"><?= htmlspecialchars($tier['name']) ?></h3>
                        <div class="pricing-card__price">
                            <span class="pricing-card__amount"><?= htmlspecialchars($tier['price']) ?></span>
                            <?php if ($tier['period']): ?>
                            <span class="pricing-card__period"><?= htmlspecialchars($tier['period']) ?></span>
                            <?php endif; ?>
                        </div>
                        <p class="pricing-card__desc"><?= htmlspecialchars($tier['description']) ?></p>
                    </div>
                    <ul class="pricing-card__features">
                        <?php foreach ($tier['features'] as $f): ?>
                        <li>
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg>
                            <?= htmlspecialchars($f) ?>
                        </li>
                        <?php endforeach; ?>
                    </ul>
                    <a href="<?= htmlspecialchars($tier['cta_url']) ?>" class="btn <?= $tier['featured'] ? 'btn--primary' : 'btn--outline' ?> btn--full">
                        <?= htmlspecialchars($tier['cta_text']) ?>
                    </a>
                </div>
                <?php endforeach; ?>
            </div>
            <div class="pricing-addons">
                <h3>Add-on Services</h3>
                <div class="addons-grid">
                    <div class="addon">
                        <span class="addon__price">$200/h</span>
                        <span class="addon__name">Architecture Consulting</span>
                        <span class="addon__desc">Design your agent infrastructure</span>
                    </div>
                    <div class="addon">
                        <span class="addon__price">$5,000</span>
                        <span class="addon__name">Deployment Package</span>
                        <span class="addon__desc">Full setup + training for your team</span>
                    </div>
                    <div class="addon">
                        <span class="addon__price">$150/h</span>
                        <span class="addon__name">Security Audit</span>
                        <span class="addon__desc">Penetration testing & compliance review</span>
                    </div>
                    <div class="addon">
                        <span class="addon__price">Custom</span>
                        <span class="addon__name">Custom Integration</span>
                        <span class="addon__desc">LangChain, CrewAI, AutoGen plugins</span>
                    </div>
                </div>
            </div>
        </div>
    </section>

    <!-- ROADMAP -->
    <section class="section section--dark" id="roadmap">
        <div class="container">
            <div class="section__header">
                <span class="section__label">Roadmap</span>
                <h2 class="section__title">Where we're heading</h2>
            </div>
            <div class="roadmap">
                <?php foreach ($roadmap as $i => $phase): ?>
                <div class="roadmap__phase <?= $phase['status'] === 'current' ? 'roadmap__phase--active' : '' ?> <?= $phase['status'] === 'done' ? 'roadmap__phase--done' : '' ?>">
                    <div class="roadmap__marker">
                        <?php if ($phase['status'] === 'done'): ?>
                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg>
                        <?php elseif ($phase['status'] === 'current'): ?>
                            <span class="roadmap__pulse"></span>
                        <?php else: ?>
                            <span class="roadmap__dot"></span>
                        <?php endif; ?>
                    </div>
                    <div class="roadmap__content">
                        <div class="roadmap__meta">
                            <span class="roadmap__version"><?= htmlspecialchars($phase['version']) ?></span>
                            <span class="roadmap__date"><?= htmlspecialchars($phase['date']) ?></span>
                            <?php if ($phase['status'] === 'current'): ?>
                            <span class="roadmap__status-badge">In Progress</span>
                            <?php elseif ($phase['status'] === 'done'): ?>
                            <span class="roadmap__status-badge roadmap__status-badge--done">Released</span>
                            <?php endif; ?>
                        </div>
                        <h3 class="roadmap__title"><?= htmlspecialchars($phase['title']) ?></h3>
                        <ul class="roadmap__items">
                            <?php foreach ($phase['items'] as $item): ?>
                            <li><?= htmlspecialchars($item) ?></li>
                            <?php endforeach; ?>
                        </ul>
                    </div>
                </div>
                <?php endforeach; ?>
            </div>
        </div>
    </section>

    <!-- USE CASES -->
    <section class="section" id="usecases">
        <div class="container">
            <div class="section__header">
                <span class="section__label">Use Cases</span>
                <h2 class="section__title">Built for teams who ship AI</h2>
            </div>
            <div class="usecases-grid">
                <div class="usecase">
                    <div class="usecase__icon">🤖</div>
                    <h3>AI Agent Sandboxing</h3>
                    <p>Give LangChain, CrewAI, or AutoGen agents a full VM to execute code, browse the web, and interact with tools — safely isolated from your infrastructure.</p>
                </div>
                <div class="usecase">
                    <div class="usecase__icon">🏢</div>
                    <h3>Enterprise Compliance</h3>
                    <p>SOC 2, HIPAA, GDPR. Full audit trails, RBAC, SSO integration. Your data stays on-prem — no cloud vendor has access.</p>
                </div>
                <div class="usecase">
                    <div class="usecase__icon">🧪</div>
                    <h3>Dev/Test Environments</h3>
                    <p>Clone your workstation in 60 seconds. Test destructive operations, experiment freely, rollback instantly. Perfect for CI/CD pipelines.</p>
                </div>
                <div class="usecase">
                    <div class="usecase__icon">🔐</div>
                    <h3>Security Research</h3>
                    <p>Analyze malware, test exploits, run honeypots — all in throwaway VMs with network isolation and snapshot forensics.</p>
                </div>
            </div>
        </div>
    </section>

    <!-- CTA -->
    <section class="section section--cta" id="cta">
        <div class="container">
            <div class="cta-content">
                <h2>Ready to isolate your AI agents?</h2>
                <p>Join the growing community of developers shipping AI safely.</p>
                <div class="cta-actions">
                    <a href="https://github.com/wronai/clonebox" class="btn btn--primary btn--large" target="_blank">
                        <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z"/></svg>
                        Star on GitHub
                    </a>
                    <a href="#pricing" class="btn btn--outline btn--large">View Pricing</a>
                </div>
                <div class="cta-install">
                    <code>pip install clonebox</code>
                    <button class="copy-btn" onclick="navigator.clipboard.writeText('pip install clonebox')">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>
                    </button>
                </div>
            </div>
        </div>
    </section>
</main>

<?php require_once __DIR__ . '/../includes/footer.php'; ?>
