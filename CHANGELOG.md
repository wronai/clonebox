## [1.1.13] - 2026-02-01

### Summary

refactor(tests): code relationship mapping with 2 supporting modules

### Core

- update src/clonebox/cloner.py

### Test

- update tests/test_cloner.py
- update tests/test_network.py


## [1.1.12] - 2026-02-01

### Summary

refactor(goal): CLI interface improvements

### Core

- update src/clonebox/cli.py

### Other

- update verify_cloudinit.py


## [1.1.11] - 2026-02-01

### Summary

feat(tests): configuration management system

### Core

- update src/clonebox/cloner.py
- update src/clonebox/di.py
- update src/clonebox/models.py
- update src/clonebox/validator.py

### Test

- update tests/test_cloner.py
- update tests/test_coverage_boost_final.py
- update tests/test_network.py


## [1.1.10] - 2026-02-01

### Summary

feat(build): CLI interface improvements

### Core

- update src/clonebox/cli.py
- update src/clonebox/cloner.py

### Other

- build: update Makefile


## [1.1.9] - 2026-01-31

### Summary

feat(goal): CLI interface improvements

### Core

- update src/clonebox/cli.py
- update src/clonebox/cloner.py


## [1.1.8] - 2026-01-31

### Summary

feat(goal): CLI interface improvements

### Core

- update src/clonebox/cli.py
- update src/clonebox/cloner.py


## [1.1.7] - 2026-01-31

### Summary

feat(goal): CLI interface improvements

### Core

- update src/clonebox/cli.py
- update src/clonebox/validator.py


## [1.1.6] - 2026-01-31

### Summary

feat(config): CLI interface improvements

### Core

- update src/clonebox/cli.py
- update src/clonebox/models.py
- update src/clonebox/validator.py

### Test

- update tests/test_models.py

### Build

- update pyproject.toml


## [1.1.5] - 2026-01-31

### Summary

feat(tests): CLI interface improvements

### Core

- update src/clonebox/backends/libvirt_backend.py
- update src/clonebox/backends/qemu_disk.py
- update src/clonebox/backends/subprocess_runner.py
- update src/clonebox/cli.py
- update src/clonebox/cloner.py
- update src/clonebox/di.py
- update src/clonebox/health/__init__.py
- update src/clonebox/health/manager.py
- update src/clonebox/health/models.py
- update src/clonebox/health/probes.py
- ... and 14 more

### Docs

- docs: update README
- docs: update CLONEBOX_IMPLEMENTATION_SUMMARY.md
- docs: update CLONEBOX_IMPROVEMENTS_ROADMAP.md
- docs: update README

### Test

- update tests/e2e/test_p2p_workflow.py
- update tests/test_cloner.py
- update tests/test_cloner_simple.py
- update tests/test_coverage_boost_final.py
- update tests/test_network.py

### Build

- update pyproject.toml

### Other

- update TODO/clonebox_architecture.mermaid
- update project.functions.toon
- update project.toon


## [1.1.4] - 2026-01-31

### Summary

feat(docs): CLI interface improvements

### Core

- update src/clonebox/cli.py
- update src/clonebox/monitor.py

### Docs

- docs: update TODO.md
- docs: update 01-secrets-isolation.md
- docs: update 02-rollback-mechanism.md
- docs: update 03-snapshot-management.md
- docs: update 04-health-checks.md
- docs: update 05-resource-limits.md
- docs: update 06-dependency-injection.md
- docs: update test.md

### Test

- update tests/e2e/test_p2p_workflow.py

### Other

- update scripts/clonebox-completion.bash
- update scripts/clonebox-completion.zsh


## [1.1.3] - 2026-01-31

### Summary

feat(docs): CLI interface improvements

### Core

- update src/clonebox/cli.py
- update src/clonebox/exporter.py
- update src/clonebox/importer.py
- update src/clonebox/p2p.py

### Docs

- docs: update README
- docs: update 01-secrets-isolation.md
- docs: update 02-rollback-mechanism.md
- docs: update 03-snapshot-management.md
- docs: update 04-health-checks.md
- docs: update 05-resource-limits.md
- docs: update 06-dependency-injection.md
- docs: update README

### Test

- update tests/e2e/test_p2p_workflow.py


## [1.1.2] - 2026-01-31

### Summary

feat(None): configuration management system

### Other

- update project.functions.toon
- update project.toon
- config: update ml-dev.yaml


## [1.1.1] - 2026-01-31

### Summary

refactor(docs): configuration management system

### Core

- update src/clonebox/cloner.py
- update src/clonebox/dashboard.py

### Docs

- docs: update README

### Build

- update pyproject.toml

### Other

- update project.functions.toon
- update project.toon
- config: update web-stack.yaml


## [0.1.30] - 2026-01-31

### Summary

feat(build): configuration management system

### Test

- update tests/test_coverage_boost_final.py

### Build

- update pyproject.toml

### Ci

- config: update ci.yml


## [0.1.29] - 2026-01-31

### Summary

feat(tests): configuration management system

### Core

- update src/clonebox/cloner.py

### Test

- update tests/test_coverage_boost_final.py


## [0.1.28] - 2026-01-31

### Summary

feat(docs): configuration management system

### Docs

- docs: update README

### Test

- update tests/test_coverage_boost_final.py

### Other

- update img_1.png


## [0.1.27] - 2026-01-31

### Summary

refactor(tests): code quality metrics with 4 supporting modules

### Test

- update tests/test_comprehensive_coverage.py


## [0.1.26] - 2026-01-31

### Summary

fix(tests): configuration management system

### Test

- update tests/test_cloner_comprehensive.py
- update tests/test_cloner_simple.py
- update tests/test_coverage_boost.py
- update tests/test_dashboard_coverage.py


## [0.1.25] - 2026-01-31

### Summary

feat(docs): CLI interface improvements

### Core

- update src/clonebox/cli.py

### Docs

- docs: update README
- docs: update QUICK_REFERENCE.md

### Ci

- config: update ci.yml


## [0.1.24] - 2026-01-31

### Summary

feat(docs): configuration management system

### Core

- update src/clonebox/cloner.py

### Docs

- docs: update CONTRIBUTING.md
- docs: update README
- docs: update TODO.md
- docs: update QUICK_REFERENCE.md
- docs: update README

### Test

- update tests/test_cloner.py

### Other

- config: update clonebox.yaml
- scripts: update clonebox-logs.sh
- update scripts/clonebox-monitor.default
- update scripts/clonebox-monitor.service
- scripts: update clonebox-monitor.sh


## [0.1.23] - 2026-01-31

### Summary

feat(examples): CLI interface improvements

### Core

- update src/clonebox/cli.py
- update src/clonebox/cloner.py

### Test

- update tests/test_cloner.py

### Build

- update pyproject.toml

### Other

- update .env.example


## [0.1.22] - 2026-01-31

### Summary

feat(docs): CLI interface improvements

### Core

- update src/clonebox/cli.py
- update src/clonebox/cloner.py
- update src/clonebox/validator.py

### Docs

- docs: update README

### Test

- update tests/test_validator.py


## [0.1.21] - 2026-01-31

### Summary

feat(docs): deep code analysis engine with 2 supporting modules

### Core

- update src/clonebox/cloner.py

### Docs

- docs: update README


## [0.1.20] - 2026-01-31

### Summary

feat(tests): CLI interface improvements

### Core

- update src/clonebox/cli.py
- update src/clonebox/cloner.py
- update src/clonebox/dashboard.py
- update src/clonebox/detector.py
- update src/clonebox/profiles.py
- update src/clonebox/validator.py

### Test

- update tests/conftest.py
- update tests/e2e/test_container_workflow.py
- update tests/test_detector.py
- update tests/test_profiles.py
- update tests/test_validator.py


## [0.1.19] - 2026-01-31

### Summary

refactor(config): CLI interface improvements

### Core

- update src/clonebox/__init__.py
- update src/clonebox/cli.py
- update src/clonebox/profiles.py

### Build

- update pyproject.toml

### Other

- update project.functions.toon
- update project.toon
- config: update ml-dev.yaml


## [0.1.18] - 2026-01-30

### Summary

feat(goal): CLI interface improvements

### Core

- update src/clonebox/cli.py


## [0.1.17] - 2026-01-30

### Summary

refactor(goal): CLI interface improvements

### Core

- update src/clonebox/cli.py


## [0.1.16] - 2026-01-30

### Summary

feat(goal): CLI interface improvements

### Core

- update src/clonebox/cli.py
- update src/clonebox/cloner.py

### Other

- update project.functions.toon
- update project.toon


## [0.1.15] - 2026-01-30

### Summary

feat(tests): CLI interface improvements

### Core

- update src/clonebox/cli.py
- update src/clonebox/models.py

### Test

- update tests/conftest.py
- update tests/test_cli.py
- update tests/test_cloner.py
- update tests/test_detector.py
- update tests/test_models.py

### Build

- update pyproject.toml

### Ci

- config: update ci.yml

### Other

- update project.functions.toon
- update project.toon


## [0.1.14] - 2026-01-30

### Summary

feat(goal): CLI interface improvements

### Core

- update src/clonebox/cli.py
- update src/clonebox/validator.py


## [0.1.10] - 2026-01-30

### Summary

feat(goal): CLI interface improvements

### Core

- update src/clonebox/cli.py
- update src/clonebox/cloner.py

### Docs

- docs: update README

### Other

- update src/clonebox/__pycache__/cli.cpython-313.pyc
- update src/clonebox/__pycache__/cloner.cpython-313.pyc


## [0.1.9] - 2026-01-30

### Summary

feat(goal): CLI interface improvements

### Core

- update src/clonebox/cli.py
- update src/clonebox/cloner.py

### Other

- update src/clonebox/__pycache__/cli.cpython-313.pyc
- update src/clonebox/__pycache__/cloner.cpython-313.pyc


## [0.1.8] - 2026-01-30

### Summary

fix(goal): CLI interface improvements

### Core

- update src/clonebox/cli.py
- update src/clonebox/cloner.py
- update src/clonebox/detector.py

### Test

- update tests/test_network.py

### Other

- update src/clonebox/__pycache__/cli.cpython-313.pyc
- update src/clonebox/__pycache__/cloner.cpython-313.pyc
- update src/clonebox/__pycache__/detector.cpython-313.pyc


## [0.1.7] - 2026-01-30

### Summary

feat(goal): CLI interface improvements

### Core

- update src/clonebox/cli.py
- update src/clonebox/cloner.py
- update src/clonebox/detector.py

### Docs

- docs: update README

### Other

- update img.png
- update src/clonebox/__pycache__/cli.cpython-313.pyc
- update src/clonebox/__pycache__/cloner.cpython-313.pyc
- update src/clonebox/__pycache__/detector.cpython-313.pyc


## [0.1.6] - 2026-01-30

### Summary

feat(goal): CLI interface improvements

### Core

- update src/clonebox/cli.py
- update src/clonebox/cloner.py
- update src/clonebox/detector.py

### Other

- update src/clonebox/__pycache__/cli.cpython-313.pyc
- update src/clonebox/__pycache__/cloner.cpython-313.pyc
- update src/clonebox/__pycache__/detector.cpython-313.pyc


## [0.1.5] - 2026-01-30

### Summary

feat(goal): CLI interface improvements

### Core

- update src/clonebox/cli.py

### Other

- update src/clonebox/__pycache__/cli.cpython-313.pyc


## [0.1.4] - 2026-01-30

### Summary

refactor(tests): CLI interface improvements

### Core

- update src/clonebox/__main__.py
- update src/clonebox/cli.py
- update src/clonebox/cloner.py
- update src/clonebox/detector.py

### Docs

- docs: update README

### Test

- update tests/test_cli.py
- update tests/test_cloner.py
- update tests/test_detector.py
- update tests/test_network.py

### Other

- build: update Makefile
- update src/clonebox/__pycache__/cli.cpython-313.pyc
- update src/clonebox/__pycache__/cloner.cpython-313.pyc
- update src/clonebox/__pycache__/detector.cpython-313.pyc


## [0.1.3] - 2026-01-30

### Summary

fix(goal): CLI interface improvements

### Core

- update src/clonebox/cli.py
- update src/clonebox/cloner.py

### Docs

- docs: update README

### Test

- update tests/test_cloner.py

### Other

- scripts: update fix-network.sh
- scripts: update setup.sh
- update src/clonebox/__pycache__/cli.cpython-313.pyc
- update src/clonebox/__pycache__/cloner.cpython-313.pyc


## [0.1.2] - 2026-01-30

### Summary

feat(tests): CLI interface improvements

### Core

- update src/clonebox/detector.py

### Docs

- docs: update README

### Test

- update tests/__init__.py
- update tests/test_cli.py
- update tests/test_cloner.py
- update tests/test_detector.py

### Other

- update src/clonebox/__pycache__/__init__.cpython-313.pyc
- update src/clonebox/__pycache__/cli.cpython-313.pyc
- update src/clonebox/__pycache__/cloner.cpython-313.pyc
- update src/clonebox/__pycache__/detector.cpython-313.pyc


## [0.1.1] - 2026-01-30

### Summary

feat(goal): configuration management system

### Core

- update src/clonebox/__init__.py
- update src/clonebox/cloner.py
- update src/clonebox/detector.py

### Build

- update pyproject.toml

### Config

- config: update goal.yaml

### Other

- update .idea/.gitignore


