# CloneBox Makefile

.PHONY: help install install-dev test test-verbose lint format clean build upload publish docs run

# Default target
help:
	@echo "CloneBox - Clone your workstation to an isolated VM"
	@echo ""
	@echo "Available targets:"
	@echo "  install      Install clonebox in development mode"
	@echo "  install-dev  Install with dev dependencies"
	@echo "  test         Run unit tests (excludes e2e)"
	@echo "  test-unit    Run fast unit tests only"
	@echo "  test-e2e     Run end-to-end tests (requires libvirt/KVM)"
	@echo "  test-all     Run all tests including e2e"
	@echo "  test-verbose Run tests with verbose output"
	@echo "  test-cov     Run tests with coverage"
	@echo "  lint         Run linters (ruff, mypy)"
	@echo "  format       Format code with black and ruff"
	@echo "  clean        Clean build artifacts"
	@echo "  build        Build package"
	@echo "  upload       Upload to PyPI (requires twine)"
	@echo "  publish      Build and upload to PyPI"
	@echo "  docs         Generate documentation"
	@echo "  run          Run clonebox (interactive mode)"

# Installation
install:
	@if [ -d ".venv" ]; then \
		.venv/bin/pip install -e . --upgrade; \
	else \
		echo "Creating virtual environment..."; \
		python3 -m venv .venv; \
		.venv/bin/pip install -e . --upgrade; \
	fi

install-dev:
	@if [ -d ".venv" ]; then \
		.venv/bin/pip install -e ".[dev,test]" --upgrade || .venv/bin/pip install -e . --upgrade pytest ruff mypy black build bump2version pytest-cov pytest-timeout pytest-asyncio; \
		.venv/bin/pre-commit install || true; \
	else \
		echo "Creating virtual environment..."; \
		python3 -m venv .venv; \
		.venv/bin/pip install -e ".[dev,test]" --upgrade || .venv/bin/pip install -e . --upgrade pytest ruff mypy black build bump2version pytest-cov pytest-timeout pytest-asyncio; \
		.venv/bin/pre-commit install || true; \
	fi

# Testing
test:
	@if [ -d ".venv" ]; then \
		.venv/bin/pytest tests/ -m "not e2e" -q --tb=short; \
	else \
		echo "No virtual environment found. Run 'make install-dev' first."; \
		exit 1; \
	fi

test-unit:
	@if [ -d ".venv" ]; then \
		.venv/bin/pytest tests/ -m "not e2e and not slow" -q --tb=short; \
	else \
		echo "No virtual environment found. Run 'make install-dev' first."; \
		exit 1; \
	fi

test-e2e:
	@if [ -d ".venv" ]; then \
		.venv/bin/pytest tests/e2e/ -m "e2e" -v --tb=short; \
	else \
		echo "No virtual environment found. Run 'make install-dev' first."; \
		exit 1; \
	fi

test-all:
	@if [ -d ".venv" ]; then \
		.venv/bin/pytest tests/ -v --tb=short; \
	else \
		echo "No virtual environment found. Run 'make install-dev' first."; \
		exit 1; \
	fi

test-verbose:
	@if [ -d ".venv" ]; then \
		.venv/bin/pytest tests/ -m "not e2e" -v --tb=short; \
	else \
		echo "No virtual environment found. Run 'make install-dev' first."; \
		exit 1; \
	fi

test-cov:
	@if [ -d ".venv" ]; then \
		.venv/bin/pytest tests/ -m "not e2e" --cov=clonebox --cov-report=html --cov-report=term; \
	else \
		echo "No virtual environment found. Run 'make install-dev' first."; \
		exit 1; \
	fi

# Code quality
lint:
	@if [ -d ".venv" ]; then \
		.venv/bin/ruff check src/clonebox tests/; \
		.venv/bin/ruff format --check src/clonebox tests/; \
		.venv/bin/mypy src/clonebox --ignore-missing-imports; \
	else \
		echo "No virtual environment found. Run 'make install-dev' first."; \
		exit 1; \
	fi

format:
	@if [ -d ".venv" ]; then \
		.venv/bin/ruff format src/clonebox tests/; \
		.venv/bin/ruff check --fix src/clonebox tests/; \
	else \
		echo "No virtual environment found. Run 'make install-dev' first."; \
		exit 1; \
	fi

# Version bump
bump-patch:
	@if [ -d ".venv" ]; then \
		.venv/bin/bump2version patch; \
	else \
		echo "No virtual environment found. Run 'make install-dev' first."; \
		exit 1; \
	fi

bump-minor:
	@if [ -d ".venv" ]; then \
		.venv/bin/bump2version minor; \
	else \
		echo "No virtual environment found. Run 'make install-dev' first."; \
		exit 1; \
	fi

bump-major:
	@if [ -d ".venv" ]; then \
		.venv/bin/bump2version major; \
	else \
		echo "No virtual environment found. Run 'make install-dev' first."; \
		exit 1; \
	fi

# Build and distribution
clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf .pytest_cache/
	rm -rf .coverage
	rm -rf htmlcov/
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

build: clean
	@if [ -d ".venv" ]; then \
		.venv/bin/python -m build; \
	else \
		echo "No virtual environment found. Run 'make install-dev' first."; \
		exit 1; \
	fi

upload: build
	@if [ -d ".venv" ]; then \
		.venv/bin/python -m twine upload dist/*; \
	else \
		echo "No virtual environment found. Run 'make install-dev' first."; \
		exit 1; \
	fi

upload-test: build
	@if [ -d ".venv" ]; then \
		.venv/bin/python -m twine upload --repository testpypi dist/*; \
	else \
		echo "No virtual environment found. Run 'make install-dev' first."; \
		exit 1; \
	fi

publish: bump-patch clean
	@if [ -d ".venv" ]; then \
		echo "Building package..."; \
		.venv/bin/python -m build; \
		echo "Uploading to PyPI..."; \
		.venv/bin/python -m twine upload dist/*; \
		echo "Published successfully!"; \
	else \
		echo "No virtual environment found. Run 'make install-dev' first."; \
		exit 1; \
	fi

# Documentation
docs:
	@echo "Documentation is in README.md"

# Development
run:
	@if [ -d ".venv" ]; then \
		.venv/bin/python -m clonebox; \
	else \
		echo "No virtual environment found. Run 'make install-dev' first."; \
		exit 1; \
	fi

# Quick test commands
test-clone:
	@if [ -d ".venv" ]; then \
		PYTHONPATH=src .venv/bin/python -m clonebox clone . --user --run --replace; \
	else \
		echo "No virtual environment found. Run 'make install-dev' first."; \
		exit 1; \
	fi

test-detect:
	@if [ -d ".venv" ]; then \
		.venv/bin/python -m clonebox detect --yaml --dedupe; \
	else \
		echo "No virtual environment found. Run 'make install-dev' first."; \
		exit 1; \
	fi

# Check all
check: lint test
	@echo "All checks passed!"
