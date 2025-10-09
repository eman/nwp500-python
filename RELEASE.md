# Release Process

This document describes the release process for nwp500-python, including code quality checks, formatting, and publishing.

## Prerequisites

Install development dependencies:

```bash
pip install -e ".[dev]"
# or
make install-dev
```

## Quick Release

For a full automated release check and build:

```bash
make release
```

This will:
1. Run linting checks
2. Verify code formatting
3. Run all tests
4. Clean build artifacts
5. Build distribution packages

## Step-by-Step Release Process

### 1. Code Quality Checks

#### Format Code

Format all code with ruff:

```bash
make format
# or
tox -e format
```

This will:
- Automatically fix linting issues where possible
- Format code to comply with PEP 8 and project standards
- Sort imports according to isort rules

#### Check Linting

Check code without making changes:

```bash
make lint
# or
tox -e lint
```

#### Verify Formatting

Check that code is properly formatted:

```bash
make format-check
```

### 2. Run Tests

Run the test suite:

```bash
make test
# or
pytest
```

Run tests with coverage report:

```bash
make test-cov
```

### 3. Run All Checks

Run all quality checks at once:

```bash
make check-release
```

This runs:
- Linting checks
- Format verification
- Full test suite

### 4. Update Version and Changelog

1. Update version in relevant files (handled by setuptools_scm)
2. Update `CHANGELOG.rst` with changes for this release
3. Commit changes:

```bash
git add CHANGELOG.rst
git commit -m "Update changelog for vX.Y.Z"
```

### 5. Build Distribution

Clean and build distribution packages:

```bash
make build
```

This creates:
- `dist/nwp500_python-X.Y.Z.tar.gz` (source distribution)
- `dist/nwp500_python-X.Y.Z-py3-none-any.whl` (wheel)

### 6. Test the Build

Test the distribution on TestPyPI first:

```bash
make publish-test
```

Or manually:

```bash
python -m twine upload --repository testpypi dist/*
```

Test installation from TestPyPI:

```bash
pip install --index-url https://test.pypi.org/simple/ nwp500-python
```

### 7. Publish to PyPI

Once verified on TestPyPI, publish to production PyPI:

```bash
make publish
```

Or manually:

```bash
python -m twine upload dist/*
```

### 8. Tag the Release

Create and push a git tag:

```bash
git tag -a vX.Y.Z -m "Release version X.Y.Z"
git push origin vX.Y.Z
```

## Using Tox

You can also use tox directly for all steps:

```bash
# Run lint checks
tox -e lint

# Format code
tox -e format

# Run tests
tox

# Build package
tox -e build

# Clean artifacts
tox -e clean
```

## Ruff Configuration

Ruff is configured in `pyproject.toml` with the following rules:

- **Line length**: 88 characters (Black-compatible)
- **Target version**: Python 3.7+
- **Enabled rules**:
  - `E`, `W`: pycodestyle errors and warnings
  - `F`: Pyflakes
  - `I`: isort (import sorting)
  - `UP`: pyupgrade (Python version upgrades)
  - `B`: flake8-bugbear (common bugs)
  - `C4`: flake8-comprehensions
  - `SIM`: flake8-simplify

### Checking Specific Files

```bash
# Check specific file
ruff check src/nwp500/auth.py

# Format specific file
ruff format src/nwp500/auth.py

# Check and fix specific directory
ruff check --fix src/nwp500/
```

## Troubleshooting

### Linting Errors

If you encounter linting errors:

1. Try auto-fixing: `make format`
2. Review remaining errors: `make lint`
3. Manually fix any errors that can't be auto-fixed
4. Re-run checks: `make check-release`

### Test Failures

If tests fail:

1. Review the test output
2. Fix the issues in the code
3. Re-run tests: `make test`
4. Ensure all tests pass before release

### Build Errors

If build fails:

1. Clean build artifacts: `make clean`
2. Verify dependencies are installed: `pip install -e ".[dev]"`
3. Try building again: `make build`

## Pre-Release Checklist

Before releasing, ensure:

- [ ] All code is formatted: `make format`
- [ ] Linting passes: `make lint`
- [ ] All tests pass: `make test`
- [ ] Changelog is updated
- [ ] Version is bumped appropriately
- [ ] Documentation is up to date
- [ ] Examples work correctly
- [ ] Build succeeds: `make build`
- [ ] TestPyPI upload works: `make publish-test`

## Environment Variables for Publishing

Set these environment variables for Twine:

```bash
export TWINE_USERNAME=__token__
export TWINE_PASSWORD=pypi-your-api-token-here
```

Or use a `.pypirc` file:

```ini
[distutils]
index-servers =
    pypi
    testpypi

[pypi]
username = __token__
password = pypi-your-api-token

[testpypi]
repository = https://test.pypi.org/legacy/
username = __token__
password = pypi-your-test-api-token
```

## Continuous Integration

Consider setting up CI/CD to automatically:

1. Run linting on pull requests
2. Run tests on multiple Python versions
3. Check code formatting
4. Build and verify distributions
5. Publish releases automatically on git tags

Example GitHub Actions workflow could run:

```yaml
- name: Install dependencies
  run: pip install -e ".[dev]"

- name: Lint with ruff
  run: make lint

- name: Check formatting
  run: make format-check

- name: Run tests
  run: make test

- name: Build
  run: make build
```

## Quick Commands Reference

| Command | Description |
|---------|-------------|
| `make help` | Show all available commands |
| `make install-dev` | Install with dev dependencies |
| `make format` | Format code with ruff |
| `make lint` | Check code with ruff |
| `make test` | Run tests |
| `make check-release` | Run all pre-release checks |
| `make release` | Full release build process |
| `make build` | Build distribution packages |
| `make publish-test` | Upload to TestPyPI |
| `make publish` | Upload to PyPI |
| `make clean` | Remove build artifacts |

## More Information

- [Ruff Documentation](https://docs.astral.sh/ruff/)
- [Python Packaging User Guide](https://packaging.python.org/)
- [Twine Documentation](https://twine.readthedocs.io/)
- [Semantic Versioning](https://semver.org/)
