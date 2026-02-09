<?php
/**
 * Isolabox Test Runner
 * Lightweight test framework — no dependencies required.
 * 
 * Usage:
 *   php tests/run_tests.php                    # Run against http://web (Docker)
 *   php tests/run_tests.php http://localhost:8000  # Run against local dev
 *   BASE_URL=http://web php tests/run_tests.php    # Env var
 */

$base_url = $argv[1] ?? getenv('BASE_URL') ?: 'http://localhost:8000';
$base_url = rtrim($base_url, '/');

// ─── Minimal test framework ───────────────────────────────────────────

class TestRunner {
    private int $passed = 0;
    private int $failed = 0;
    private int $skipped = 0;
    private array $failures = [];
    private array $results = [];
    private float $start;
    private string $base_url;

    public function __construct(string $base_url) {
        $this->base_url = $base_url;
        $this->start = microtime(true);
    }

    public function assert(bool $condition, string $name, string $detail = ''): void {
        if ($condition) {
            $this->passed++;
            $this->results[] = ['status' => 'PASS', 'name' => $name];
            echo "  \033[32m✓\033[0m {$name}\n";
        } else {
            $this->failed++;
            $this->failures[] = ['name' => $name, 'detail' => $detail];
            $this->results[] = ['status' => 'FAIL', 'name' => $name, 'detail' => $detail];
            echo "  \033[31m✗\033[0m {$name}\n";
            if ($detail) echo "    \033[33m→ {$detail}\033[0m\n";
        }
    }

    public function skip(string $name, string $reason = ''): void {
        $this->skipped++;
        $this->results[] = ['status' => 'SKIP', 'name' => $name];
        echo "  \033[33m⊘\033[0m {$name}" . ($reason ? " ({$reason})" : "") . "\n";
    }

    public function group(string $name): void {
        echo "\n\033[1;36m▸ {$name}\033[0m\n";
    }

    public function fetch(string $path, array $options = []): array {
        $url = $this->base_url . $path;
        $ch = curl_init($url);
        curl_setopt_array($ch, [
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_HEADER => true,
            CURLOPT_FOLLOWLOCATION => true,
            CURLOPT_TIMEOUT => 10,
            CURLOPT_CONNECTTIMEOUT => 5,
            CURLOPT_USERAGENT => 'IsolaboxTestRunner/1.0',
        ]);
        if (isset($options['method']) && $options['method'] === 'HEAD') {
            curl_setopt($ch, CURLOPT_NOBODY, true);
        }
        $response = curl_exec($ch);
        $info = curl_getinfo($ch);
        $error = curl_error($ch);
        curl_close($ch);

        $header_size = $info['header_size'] ?? 0;
        $headers_raw = substr($response, 0, $header_size);
        $body = substr($response, $header_size);

        $headers = [];
        foreach (explode("\r\n", $headers_raw) as $line) {
            if (str_contains($line, ':')) {
                [$key, $val] = explode(':', $line, 2);
                $headers[strtolower(trim($key))] = trim($val);
            }
        }

        return [
            'status' => (int)($info['http_code'] ?? 0),
            'body' => $body,
            'headers' => $headers,
            'url' => $url,
            'time' => $info['total_time'] ?? 0,
            'size' => $info['size_download'] ?? 0,
            'error' => $error,
        ];
    }

    public function summary(): int {
        $elapsed = round(microtime(true) - $this->start, 2);
        $total = $this->passed + $this->failed + $this->skipped;
        
        echo "\n\033[1m" . str_repeat('─', 60) . "\033[0m\n";
        echo "\033[1mResults: {$total} tests in {$elapsed}s\033[0m\n";
        echo "  \033[32m{$this->passed} passed\033[0m";
        if ($this->failed > 0) echo "  \033[31m{$this->failed} failed\033[0m";
        if ($this->skipped > 0) echo "  \033[33m{$this->skipped} skipped\033[0m";
        echo "\n";

        if ($this->failures) {
            echo "\n\033[31mFailures:\033[0m\n";
            foreach ($this->failures as $i => $f) {
                echo "  " . ($i + 1) . ". {$f['name']}\n";
                if ($f['detail']) echo "     {$f['detail']}\n";
            }
        }

        // Write JUnit XML report
        $this->writeJunitXml();

        // Write JSON report
        $this->writeJsonReport($elapsed);

        return $this->failed > 0 ? 1 : 0;
    }

    private function writeJunitXml(): void {
        $xml = '<?xml version="1.0" encoding="UTF-8"?>' . "\n";
        $xml .= '<testsuites name="isolabox" tests="' . count($this->results) . '" failures="' . $this->failed . '">' . "\n";
        $xml .= '  <testsuite name="website">' . "\n";
        foreach ($this->results as $r) {
            $name = htmlspecialchars($r['name']);
            $xml .= '    <testcase name="' . $name . '">';
            if ($r['status'] === 'FAIL') {
                $detail = htmlspecialchars($r['detail'] ?? '');
                $xml .= '<failure message="' . $detail . '"/>';
            } elseif ($r['status'] === 'SKIP') {
                $xml .= '<skipped/>';
            }
            $xml .= "</testcase>\n";
        }
        $xml .= "  </testsuite>\n</testsuites>\n";
        @file_put_contents('test-results/junit.xml', $xml);
    }

    private function writeJsonReport(float $elapsed): void {
        $report = [
            'timestamp' => date('c'),
            'base_url' => $this->base_url,
            'duration_seconds' => $elapsed,
            'summary' => [
                'total' => $this->passed + $this->failed + $this->skipped,
                'passed' => $this->passed,
                'failed' => $this->failed,
                'skipped' => $this->skipped,
            ],
            'results' => $this->results,
        ];
        @file_put_contents('test-results/report.json', json_encode($report, JSON_PRETTY_PRINT));
    }
}

// ─── Test suites ──────────────────────────────────────────────────────

$t = new TestRunner($base_url);

echo "\033[1;37m╔══════════════════════════════════════════════╗\033[0m\n";
echo "\033[1;37m║     Isolabox Test Suite                       ║\033[0m\n";
echo "\033[1;37m║     Target: {$base_url}               \033[0m\n";
echo "\033[1;37m╚══════════════════════════════════════════════╝\033[0m\n";

// ─── 1. Server Health ─────────────────────────────────────────────────

$t->group('Server Health');

$home = $t->fetch('/');
$t->assert($home['status'] === 200, 'Homepage returns 200', "Got: {$home['status']}");
$t->assert($home['error'] === '', 'No connection errors', $home['error']);
$t->assert($home['time'] < 5.0, 'Homepage loads in under 5s', "Took: {$home['time']}s");
$t->assert($home['size'] > 10000, 'Homepage has substantial content', "Size: {$home['size']} bytes");

// ─── 2. HTML Structure ───────────────────────────────────────────────

$t->group('HTML Structure');

$body = $home['body'];
$t->assert(str_contains($body, '<!DOCTYPE html>'), 'Has DOCTYPE');
$t->assert(str_contains($body, '<html lang="en">'), 'Has html lang attribute');
$t->assert(str_contains($body, '<meta charset="UTF-8">'), 'Has charset meta');
$t->assert(str_contains($body, '<meta name="viewport"'), 'Has viewport meta');
$t->assert(str_contains($body, '<meta name="description"'), 'Has description meta');
$t->assert(str_contains($body, 'og:title'), 'Has Open Graph title');
$t->assert(str_contains($body, 'og:description'), 'Has Open Graph description');
$t->assert(str_contains($body, 'twitter:card'), 'Has Twitter card meta');

// ─── 3. Content Sections ─────────────────────────────────────────────

$t->group('Content Sections');

$t->assert(str_contains($body, 'id="hero"'), 'Hero section exists');
$t->assert(str_contains($body, 'id="why"'), 'Problem/Solution section exists');
$t->assert(str_contains($body, 'id="features"'), 'Features section exists');
$t->assert(str_contains($body, 'id="compare"'), 'Comparison section exists');
$t->assert(str_contains($body, 'id="pricing"'), 'Pricing section exists');
$t->assert(str_contains($body, 'id="roadmap"'), 'Roadmap section exists');
$t->assert(str_contains($body, 'id="usecases"'), 'Use cases section exists');
$t->assert(str_contains($body, 'id="cta"'), 'CTA section exists');

// ─── 4. Navigation ───────────────────────────────────────────────────

$t->group('Navigation');

$t->assert(str_contains($body, 'class="nav"'), 'Navigation bar exists');
$t->assert(str_contains($body, 'Isolabox'), 'Brand name in nav');
$t->assert(str_contains($body, 'href="#features"'), 'Features nav link');
$t->assert(str_contains($body, 'href="#pricing"'), 'Pricing nav link');
$t->assert(str_contains($body, 'href="#roadmap"'), 'Roadmap nav link');
$t->assert(str_contains($body, 'github.com/wronai/clonebox'), 'GitHub link present');

// ─── 5. Pricing Content ──────────────────────────────────────────────

$t->group('Pricing Content');

$t->assert(str_contains($body, 'Community'), 'Community tier exists');
$t->assert(str_contains($body, 'Pro'), 'Pro tier exists');
$t->assert(str_contains($body, 'Enterprise'), 'Enterprise tier exists');
$t->assert(str_contains($body, '$0'), 'Free tier price shown');
$t->assert(str_contains($body, '$99'), 'Pro tier price shown');
$t->assert(str_contains($body, 'Custom'), 'Enterprise custom pricing');
$t->assert(str_contains($body, 'Most Popular'), 'Featured tier badge');
$t->assert(str_contains($body, 'Install Free'), 'Community CTA text');
$t->assert(str_contains($body, 'Contact Sales'), 'Enterprise CTA text');

// Pricing features
$t->assert(str_contains($body, 'SSO / SAML / LDAP'), 'SSO feature in Pro');
$t->assert(str_contains($body, 'Apache 2.0 license'), 'License mentioned in Community');
$t->assert(str_contains($body, 'SOC 2 / HIPAA'), 'Compliance in Enterprise');

// Add-ons
$t->assert(str_contains($body, '$200/h'), 'Consulting price');
$t->assert(str_contains($body, '$5,000'), 'Deployment package price');
$t->assert(str_contains($body, 'Security Audit'), 'Security audit addon');

// ─── 6. Roadmap Content ──────────────────────────────────────────────

$t->group('Roadmap Content');

$t->assert(str_contains($body, 'v1.0'), 'v1.0 in roadmap');
$t->assert(str_contains($body, 'v1.1'), 'v1.1 in roadmap');
$t->assert(str_contains($body, 'v1.2'), 'v1.2 in roadmap');
$t->assert(str_contains($body, 'v2.0'), 'v2.0 in roadmap');
$t->assert(str_contains($body, 'Firecracker'), 'Firecracker mentioned');
$t->assert(str_contains($body, 'In Progress'), 'Current phase indicator');
$t->assert(str_contains($body, 'Released'), 'Released phase indicator');

// ─── 7. Competitor Comparison ─────────────────────────────────────────

$t->group('Competitor Comparison');

$t->assert(str_contains($body, 'comparison-table'), 'Comparison table exists');
$t->assert(str_contains($body, 'E2B'), 'E2B in comparison');
$t->assert(str_contains($body, 'Modal'), 'Modal in comparison');
$t->assert(str_contains($body, 'Daytona'), 'Daytona in comparison');
$t->assert(str_contains($body, 'Fly.io'), 'Fly.io in comparison');
$t->assert(substr_count($body, 'class="check"') >= 8, 'Isolabox has checkmarks',
    'Found: ' . substr_count($body, 'class="check"'));

// ─── 8. Features Grid ────────────────────────────────────────────────

$t->group('Features Grid');

$feature_count = substr_count($body, 'class="feature-card"');
$t->assert($feature_count === 12, "12 feature cards rendered", "Found: {$feature_count}");
$t->assert(str_contains($body, 'Clone in 60 Seconds'), 'Clone feature');
$t->assert(str_contains($body, 'Hardware-Level Isolation'), 'Isolation feature');
$t->assert(str_contains($body, 'Dual Runtime'), 'Dual runtime feature');
$t->assert(str_contains($body, 'GUI Desktop Support'), 'GUI feature');
$t->assert(str_contains($body, 'Audit Logging'), 'Audit feature');
$t->assert(str_contains($body, 'Secrets Management'), 'Secrets feature');

// ─── 9. Terminal / Hero Content ───────────────────────────────────────

$t->group('Hero & Terminal');

$t->assert(str_contains($body, 'pip install clonebox'), 'Install command in terminal');
$t->assert(str_contains($body, 'clonebox detect'), 'Detect command shown');
$t->assert(str_contains($body, 'clonebox clone'), 'Clone command shown');
$t->assert(str_contains($body, 'clonebox sandbox'), 'Sandbox command shown');
$t->assert(str_contains($body, '&lt;60s'), 'Boot time stat');
$t->assert(str_contains($body, '10K+'), 'Lines of code stat');
$t->assert(str_contains($body, 'Self-hosted'), 'Self-hosted stat');

// ─── 10. Static Assets ───────────────────────────────────────────────

$t->group('Static Assets');

$css = $t->fetch('/assets/css/style.css');
$t->assert($css['status'] === 200, 'CSS file loads', "Got: {$css['status']}");
$t->assert($css['size'] > 5000, 'CSS has substantial content', "Size: {$css['size']}");
$t->assert(str_contains($css['body'], '--accent'), 'CSS has custom properties');
$t->assert(str_contains($css['body'], '@media'), 'CSS has responsive breakpoints');

$js = $t->fetch('/assets/js/main.js');
$t->assert($js['status'] === 200, 'JS file loads', "Got: {$js['status']}");
$t->assert($js['size'] > 500, 'JS has content', "Size: {$js['size']}");

$favicon = $t->fetch('/assets/images/favicon.svg');
$t->assert($favicon['status'] === 200, 'Favicon loads', "Got: {$favicon['status']}");
$t->assert(str_contains($favicon['body'], '<svg'), 'Favicon is valid SVG');

// ─── 11. 404 Handling ─────────────────────────────────────────────────

$t->group('Error Handling');

$notfound = $t->fetch('/this-page-does-not-exist-at-all');
$t->assert($notfound['status'] === 404, '404 for unknown page', "Got: {$notfound['status']}");
$t->assert(str_contains($notfound['body'], '404'), '404 page shows error code');

// ─── 12. SEO & Accessibility ──────────────────────────────────────────

$t->group('SEO & Accessibility');

// Count heading hierarchy
preg_match_all('/<h1[^>]*>/', $body, $h1s);
$t->assert(count($h1s[0]) === 1, 'Exactly one H1 tag', 'Found: ' . count($h1s[0]));

preg_match_all('/<h2[^>]*>/', $body, $h2s);
$t->assert(count($h2s[0]) >= 5, 'Multiple H2 tags for sections', 'Found: ' . count($h2s[0]));

$t->assert(str_contains($body, 'aria-label'), 'Has ARIA labels');
$t->assert(str_contains($body, 'alt=') || str_contains($body, 'aria-label'), 'Accessibility attributes present');

// Footer
$t->assert(str_contains($body, '<footer'), 'Footer element exists');
$t->assert(str_contains($body, 'Gdańsk'), 'Location in footer');
$t->assert(str_contains($body, date('Y')), 'Current year in copyright');
$t->assert(str_contains($body, 'Privacy Policy'), 'Privacy policy link');
$t->assert(str_contains($body, 'Documentation'), 'Docs link in footer');

// ─── 13. Performance & Security Headers ──────────────────────────────

$t->group('Performance');

$t->assert($home['time'] < 2.0, 'Homepage under 2s TTFB', "Took: {$home['time']}s");

// Check for security headers (depends on Apache config)
$has_xframe = isset($home['headers']['x-frame-options']);
$has_xcontent = isset($home['headers']['x-content-type-options']);
if ($has_xframe) {
    $t->assert(true, 'X-Frame-Options header set');
} else {
    $t->skip('X-Frame-Options header', 'needs mod_headers');
}
if ($has_xcontent) {
    $t->assert(true, 'X-Content-Type-Options header set');
} else {
    $t->skip('X-Content-Type-Options header', 'needs mod_headers');
}

// ─── 14. Use Cases Section ────────────────────────────────────────────

$t->group('Use Cases');

$t->assert(str_contains($body, 'AI Agent Sandboxing'), 'AI sandboxing use case');
$t->assert(str_contains($body, 'Enterprise Compliance'), 'Enterprise compliance use case');
$t->assert(str_contains($body, 'Dev/Test Environments'), 'Dev/test use case');
$t->assert(str_contains($body, 'Security Research'), 'Security research use case');

// ─── 15. Links Integrity ─────────────────────────────────────────────

$t->group('Link Integrity');

// Extract all internal anchor links
preg_match_all('/href="#([^"]+)"/', $body, $anchors);
$anchor_targets = array_unique($anchors[1]);
foreach ($anchor_targets as $anchor) {
    $t->assert(
        str_contains($body, "id=\"{$anchor}\""),
        "Anchor #{$anchor} has matching target"
    );
}

// Check critical external links format
$t->assert(str_contains($body, 'target="_blank"'), 'External links open in new tab');
$t->assert(str_contains($body, 'https://github.com/wronai/clonebox'), 'GitHub URL is correct');

// ─── 16. PHP Data Functions ───────────────────────────────────────────

$t->group('Data Rendering');

// Verify all pricing tiers rendered
$pricing_cards = substr_count($body, 'class="pricing-card ') + substr_count($body, 'class="pricing-card"');
$t->assert($pricing_cards === 3, "3 pricing cards rendered", "Found: {$pricing_cards}");

// Verify roadmap phases
$roadmap_phases = substr_count($body, 'class="roadmap__phase ') + substr_count($body, 'class="roadmap__phase"');
$t->assert($roadmap_phases === 5, "5 roadmap phases rendered", "Found: {$roadmap_phases}");

// Verify use case cards
$usecase_cards = substr_count($body, 'class="usecase"');
$t->assert($usecase_cards === 4, "4 use case cards rendered", "Found: {$usecase_cards}");

// Verify addon cards
$addon_cards = substr_count($body, 'class="addon"');
$t->assert($addon_cards === 4, "4 addon cards rendered", "Found: {$addon_cards}");

// ─── Done ─────────────────────────────────────────────────────────────

exit($t->summary());
