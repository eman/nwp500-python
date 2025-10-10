.PHONY: help install install-dev lint format test clean build release check-release ci-lint ci-format ci-check

help:  ## Show this help message
	@echo 'Usage: make [target]'
	@echo ''
	@echo 'Available targets:'
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-20s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install:  ## Install the package
	pip install -e .

install-dev:  ## Install the package with development dependencies
	pip install -e ".[dev]"

setup-dev:  ## Set up minimal development environment (ruff for linting)
	python3 scripts/setup-dev.py

lint:  ## Run ruff linter (check only)
	ruff check src/ tests/ examples/

format:  ## Format code with ruff
	ruff check --fix src/ tests/ examples/
	ruff format src/ tests/ examples/

format-check:  ## Check code formatting without making changes
	ruff format --check src/ tests/ examples/

# CI Sync Commands - Mirror exact CI environment locally
ci-lint:  ## Run linting exactly as CI does (via tox lint)
	python3 scripts/lint.py

ci-format:  ## Run formatting exactly as CI does (via tox format)
	python3 scripts/format.py

ci-check: ci-lint  ## Run the same checks as CI (ensures local/CI consistency)
	@echo "🎉 All CI checks passed locally!"

test:  ## Run tests with pytest
	pytest

test-cov:  ## Run tests with coverage report
	pytest --cov=nwp500 --cov-report=html --cov-report=term-missing

clean:  ## Remove build artifacts and cache files
	rm -rf build dist *.egg-info .eggs
	rm -rf .pytest_cache .ruff_cache .coverage htmlcov
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete

build: clean  ## Build distribution packages
	python -m build

check-release: lint format-check test  ## Run all checks before release (lint, format check, tests)
	@echo "✓ All checks passed! Ready for release."

release: check-release build  ## Prepare and build a release (run checks, then build)
	@echo "✓ Release build complete!"
	@echo "To publish to TestPyPI: make publish-test"
	@echo "To publish to PyPI: make publish"

publish-test:  ## Publish to TestPyPI
	python -m twine check dist/*
	python -m twine upload --repository testpypi dist/*

publish:  ## Publish to PyPI
	python -m twine check dist/*
	python -m twine upload dist/*

tox:  ## Run all tox environments
	tox

tox-lint:  ## Run tox lint environment
	tox -e lint

tox-format:  ## Run tox format environment
	tox -e format

docs:  ## Build documentation
	tox -e docs

docs-clean:  ## Clean documentation build
	rm -rf docs/_build
