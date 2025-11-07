# Development Scripts

This directory contains helper scripts for development and release management.

## Version Management Scripts

### bump_version.py

Creates new releases by bumping version numbers and creating git tags.

**Usage:**
```bash
# Via Makefile (recommended)
make version-bump BUMP=patch   # 3.1.4 -> 3.1.5
make version-bump BUMP=minor   # 3.1.4 -> 3.2.0
make version-bump BUMP=major   # 3.1.4 -> 4.0.0
make version-bump BUMP=3.1.5   # Explicit version

# Direct invocation
python3 scripts/bump_version.py patch
python3 scripts/bump_version.py minor
python3 scripts/bump_version.py major
python3 scripts/bump_version.py 3.1.5
```

**Features:**
- Reads current version from git tags
- Calculates next version based on bump type
- Validates version progression (warns on large jumps)
- Prompts for confirmation with pre-release checklist
- Creates annotated git tag
- Shows next steps for publishing

**Important:** This project uses `setuptools_scm` to derive versions from git tags. Never manually edit version numbers in config files!

### validate_version.py

Validates version-related configuration to prevent common mistakes.

**Usage:**
```bash
# Via Makefile (recommended)
make validate-version

# Direct invocation
python3 scripts/validate_version.py
```

**Checks:**
- Verifies `setup.cfg` `[pyscaffold]` version hasn't been modified (should be 4.6)
- Ensures no hardcoded `__version__` strings in source code
- Confirms `setup.py` uses `setuptools_scm`

**When to run:**
- Before creating a release
- As part of `make check-release`
- In CI/CD pipelines (recommended)

## Code Quality Scripts

### lint.py

Runs ruff linting via tox, mirroring the CI environment exactly.

**Usage:**
```bash
# Via Makefile (recommended)
make ci-lint

# Direct invocation
python3 scripts/lint.py
```

This ensures local linting results match CI results, preventing "passes locally but fails in CI" issues.

### format.py

Formats code with ruff via tox, mirroring the CI environment exactly.

**Usage:**
```bash
# Via Makefile (recommended)
make ci-format

# Direct invocation
python3 scripts/format.py
```

This automatically fixes code formatting issues using the same configuration as CI.

### setup-dev.py

Sets up a minimal development environment with essential tools.

**Usage:**
```bash
# Via Makefile (recommended)
make setup-dev

# Direct invocation
python3 scripts/setup-dev.py
```

Installs minimal dependencies needed for development (ruff for linting/formatting).

## Common Workflows

### Creating a New Release

1. **Update changelog:**
   ```bash
   # Edit CHANGELOG.rst with new version and changes
   git add CHANGELOG.rst
   git commit -m "Update changelog for vX.Y.Z"
   ```

2. **Validate everything:**
   ```bash
   make check-release  # Runs lint, format-check, tests, and validate-version
   ```

3. **Bump version:**
   ```bash
   make version-bump BUMP=patch  # or minor/major
   ```

4. **Push tag:**
   ```bash
   git push origin vX.Y.Z
   ```

5. **Build and publish:**
   ```bash
   make build
   make publish-test  # Test on TestPyPI first
   make publish       # Publish to PyPI
   ```

### Before Committing

Always run these checks:
```bash
make ci-lint              # Check code style
make validate-version     # Check version config
python3 -m mypy src/nwp500 --config-file pyproject.toml  # Type checking
pytest                    # Run tests
```

Or run all checks at once:
```bash
make check-release
```

## Version Management Details

### How Versions Work

This project uses `setuptools_scm` which:
- Derives the package version from git tags
- Automatically handles development versions (e.g., `3.1.5.dev1+g1234567`)
- Requires no manual version editing in source files

### What NOT to Do

[ERROR] **Never edit the version in `setup.cfg`'s `[pyscaffold]` section!**
   - That field is the PyScaffold tool version (4.6), not the package version
   - Changing it to 4.7 was the bug that caused the version jump from 3.1.4 to 4.7

[ERROR] **Never add `__version__` to source code**
   - Version is derived from git tags, not hardcoded

[ERROR] **Never create tags manually without validation**
   - Use `make version-bump` which validates version progression

### What TO Do

[SUCCESS] Use `make version-bump BUMP=<type>` to create new versions

[SUCCESS] Run `make validate-version` before releases

[SUCCESS] Let `setuptools_scm` derive versions from git tags

[SUCCESS] Follow semantic versioning:
   - **Patch** (X.Y.Z+1): Bug fixes, no API changes
   - **Minor** (X.Y+1.0): New features, backward compatible
   - **Major** (X+1.0.0): Breaking changes

## Script Maintenance

### Adding New Scripts

1. Create script in `scripts/` directory
2. Make it executable: `chmod +x scripts/yourscript.py`
3. Add usage to this README
4. Add Makefile target if appropriate
5. Consider adding to `make check-release` if it's a validation script

### Testing Scripts

Test scripts manually before committing:
```bash
python3 scripts/validate_version.py  # Should pass
python3 scripts/bump_version.py      # Should show usage
python3 scripts/lint.py              # Should run linting
python3 scripts/format.py            # Should format code
```
