<?php
/**
 * Isolabox Helper Functions
 */

function get_pricing_tiers(): array {
    return [
        [
            'name' => 'Community',
            'price' => '$0',
            'period' => 'forever',
            'description' => 'For individual developers and small teams. Full-featured, self-hosted.',
            'featured' => false,
            'features' => [
                'Unlimited VMs on your hardware',
                'CLI + Python SDK',
                'VM & Container runtimes',
                'Snapshot & rollback',
                'Health monitoring',
                'Web dashboard',
                'Community support (Discord)',
                'Apache 2.0 license',
            ],
            'cta_text' => 'Install Free',
            'cta_url' => GITHUB_URL,
        ],
        [
            'name' => 'Pro',
            'price' => '$99',
            'period' => '/month + usage',
            'description' => 'For teams building production AI agents. Managed service + support.',
            'featured' => true,
            'features' => [
                'Everything in Community',
                'SSO / SAML / LDAP',
                'Role-based access control (RBAC)',
                'Audit logging & compliance exports',
                'Up to 100 concurrent VMs',
                '24-hour sandbox sessions',
                'Email support (24h SLA)',
                'Usage: $0.05/vCPU/hour',
            ],
            'cta_text' => 'Start 14-day Trial',
            'cta_url' => '/signup?plan=pro',
        ],
        [
            'name' => 'Enterprise',
            'price' => 'Custom',
            'period' => null,
            'description' => 'For organizations needing on-prem, compliance, and dedicated support.',
            'featured' => false,
            'features' => [
                'Everything in Pro',
                'BYOC / on-prem deployment',
                'Multi-tenancy',
                'SOC 2 / HIPAA compliance',
                'Custom policy engine',
                'Unlimited concurrent VMs',
                'Dedicated support + SLA',
                'Custom integrations & training',
            ],
            'cta_text' => 'Contact Sales',
            'cta_url' => '/contact?type=enterprise',
        ],
    ];
}

function get_roadmap(): array {
    return [
        [
            'version' => 'v1.0',
            'date' => 'Q4 2024',
            'title' => 'Foundation',
            'status' => 'done',
            'items' => [
                'Core VM creation & management (libvirt/QEMU)',
                'Cloud-init auto-provisioning',
                'Bind mount system for selective cloning',
                'Auto-detection of services, apps, paths',
                'SPICE GUI support with virt-viewer',
                'Basic CLI with interactive wizard',
            ],
        ],
        [
            'version' => 'v1.1',
            'date' => 'Q1 2025',
            'title' => 'Production Ready',
            'status' => 'done',
            'items' => [
                'Container runtime (Podman/Docker)',
                'Web dashboard (FastAPI + HTMX)',
                'Snapshot management & restore',
                'P2P encrypted VM sharing (AES-256)',
                'Health check system',
                'Profile system (ml-dev, web-stack)',
                '95%+ test coverage',
            ],
        ],
        [
            'version' => 'v1.2',
            'date' => 'Q2 2025',
            'title' => 'Agent-First',
            'status' => 'current',
            'items' => [
                'YAML-based policy engine',
                'NeMo Guardrails integration',
                'Resource limits & quotas',
                'Secrets management (Bitwarden/1Password)',
                'Browser session management (Playwright)',
                'LangChain / CrewAI / AutoGen plugins',
            ],
        ],
        [
            'version' => 'v1.3',
            'date' => 'Q3 2025',
            'title' => 'Enterprise & Observability',
            'status' => 'planned',
            'items' => [
                'SSO / SAML / LDAP authentication',
                'RBAC with fine-grained permissions',
                'Audit logging with compliance exports',
                'OpenTelemetry + Langfuse integration',
                'Multi-VM orchestration & cluster mode',
                'Human-in-the-loop approval framework',
            ],
        ],
        [
            'version' => 'v2.0',
            'date' => 'Q1 2026',
            'title' => 'Firecracker & Scale',
            'status' => 'planned',
            'items' => [
                'Firecracker microVM backend (~125ms boot)',
                'Multi-tenant isolation',
                'Kubernetes operator',
                'Cloud provider support (AWS, GCP, Azure)',
                'Windows WSL2 support',
                'gVisor container sandbox option',
            ],
        ],
    ];
}

function get_features(): array {
    return [
        [
            'icon' => '⚡',
            'title' => 'Clone in 60 Seconds',
            'description' => 'Auto-detect your running services, apps, and configs. Create an isolated VM clone without copying your entire disk.',
            'tag' => '',
        ],
        [
            'icon' => '🔒',
            'title' => 'Hardware-Level Isolation',
            'description' => 'Full VM isolation via libvirt/QEMU. Not containers — real hardware boundaries between your agent and your host.',
            'tag' => 'Security',
        ],
        [
            'icon' => '📸',
            'title' => 'Snapshot & Rollback',
            'description' => 'Take snapshots before risky operations. Restore to any previous state in seconds. Full audit trail included.',
            'tag' => '',
        ],
        [
            'icon' => '🐳',
            'title' => 'Dual Runtime',
            'description' => 'Choose between full VMs (libvirt/QEMU) for maximum isolation or containers (Podman/Docker) for speed. Mix and match.',
            'tag' => '',
        ],
        [
            'icon' => '🖥️',
            'title' => 'GUI Desktop Support',
            'description' => 'Full desktop environment via SPICE. Your AI agent can interact with GUI apps, browsers, and visual tools.',
            'tag' => 'Unique',
        ],
        [
            'icon' => '🔗',
            'title' => 'P2P Encrypted Sharing',
            'description' => 'Share VM environments between team members with AES-256 encryption. Onboard new devs in minutes, not days.',
            'tag' => 'New',
        ],
        [
            'icon' => '📊',
            'title' => 'Web Dashboard',
            'description' => 'Monitor all VMs and containers from a single dashboard. Health checks, resource usage, and live status at a glance.',
            'tag' => '',
        ],
        [
            'icon' => '🏥',
            'title' => 'Self-Healing',
            'description' => 'Automatic health monitoring with configurable probes (HTTP, TCP, command). Auto-repair for common issues.',
            'tag' => '',
        ],
        [
            'icon' => '📋',
            'title' => 'Audit Logging',
            'description' => 'Every VM operation is logged. Track who did what, when. Export for SOC 2, HIPAA, or GDPR compliance.',
            'tag' => 'Enterprise',
        ],
        [
            'icon' => '🎛️',
            'title' => 'Profile System',
            'description' => 'Pre-built profiles for common stacks: ml-dev, web-stack, data-science. Create and share custom profiles.',
            'tag' => '',
        ],
        [
            'icon' => '🔄',
            'title' => 'Orchestration',
            'description' => 'Multi-VM orchestration with dependency management. Define your fleet in YAML, deploy with one command.',
            'tag' => '',
        ],
        [
            'icon' => '🔑',
            'title' => 'Secrets Management',
            'description' => 'Inject secrets from Bitwarden, 1Password, or environment variables. No plaintext credentials in your VMs.',
            'tag' => 'Coming Soon',
        ],
    ];
}

function get_competitor_comparison(): array {
    return [
        'Isolabox' => [
            'Self-hosted' => true,
            'Open Source' => true,
            'AI Agent Focus' => true,
            'VM Isolation' => true,
            'Container Support' => true,
            'GUI/Desktop' => true,
            'Audit Logging' => true,
            'Snapshot/Rollback' => true,
            'Usage Pricing' => '$0 self-hosted',
        ],
        'E2B' => [
            'Self-hosted' => false,
            'Open Source' => 'partial',
            'AI Agent Focus' => true,
            'VM Isolation' => true,
            'Container Support' => false,
            'GUI/Desktop' => false,
            'Audit Logging' => 'partial',
            'Snapshot/Rollback' => true,
            'Usage Pricing' => '$0.05/vCPU/h',
        ],
        'Modal' => [
            'Self-hosted' => false,
            'Open Source' => false,
            'AI Agent Focus' => 'partial',
            'VM Isolation' => false,
            'Container Support' => true,
            'GUI/Desktop' => false,
            'Audit Logging' => 'partial',
            'Snapshot/Rollback' => false,
            'Usage Pricing' => '$0.14/vCPU/h',
        ],
        'Daytona' => [
            'Self-hosted' => true,
            'Open Source' => true,
            'AI Agent Focus' => true,
            'VM Isolation' => true,
            'Container Support' => true,
            'GUI/Desktop' => false,
            'Audit Logging' => false,
            'Snapshot/Rollback' => true,
            'Usage Pricing' => '$0.067/vCPU/h',
        ],
        'Fly.io' => [
            'Self-hosted' => false,
            'Open Source' => false,
            'AI Agent Focus' => false,
            'VM Isolation' => true,
            'Container Support' => true,
            'GUI/Desktop' => false,
            'Audit Logging' => false,
            'Snapshot/Rollback' => false,
            'Usage Pricing' => 'from $0.0035/h',
        ],
    ];
}

function get_nav_items(): array {
    return [
        ['label' => 'Features', 'url' => '#features'],
        ['label' => 'Compare', 'url' => '#compare'],
        ['label' => 'Pricing', 'url' => '#pricing'],
        ['label' => 'Roadmap', 'url' => '#roadmap'],
        ['label' => 'Docs', 'url' => DOCS_URL],
    ];
}
