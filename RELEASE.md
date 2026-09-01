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

Despite the name, this does not release anything - it runs the checks and
builds locally so you can see the release is in a fit state:

```bash
make release
```

This will:
1. Run linting checks
2. Verify code formatting
3. Run all tests
4. Validate the version configuration
5. Clean build artifacts
6. Build distribution packages

Releasing is `make version-bump` followed by pushing the tag, which hands off
to CI. See [The Release Runs Itself](#5-the-release-runs-itself).

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

#### Understanding Version Management

**IMPORTANT**: This project uses `setuptools_scm` to manage versions from git tags.
The version is **NOT** stored in any Python files or config files.

**DO NOT** edit the `version` field in `setup.cfg`'s `[pyscaffold]` section!
That field stores the PyScaffold tool version (4.6), not the package version.

#### Version Bump Process

The bump script owns the version heading, the changelog commit and the tag.
Do not write any of them by hand - `scripts/extract_changelog.py` parses the
heading it produces to build the GitHub release notes, and a hand-written
duplicate silently breaks that.

1. Make sure `CHANGELOG.rst` describes the release under `Unreleased`.

   Add entries only - no `Version X.Y.Z` heading, no date. Normally each PR
   has already added its own entry, so this is a review rather than a write:

   ```rst
   Unreleased
   ==========

   Fixed
   -----
   - **Something was broken.** It is no longer broken.
   ```

   If you edit anything here, commit it before continuing: the script
   refuses to run on a dirty working directory.

2. Run the bump script:

   ```bash
   # For a patch release (X.Y.Z -> X.Y.Z+1)
   make version-bump BUMP=patch

   # For a minor release (X.Y.Z -> X.Y+1.0)
   make version-bump BUMP=minor

   # For a major release (X.Y.Z -> X+1.0.0)
   make version-bump BUMP=major

   # Or specify an explicit version
   make version-bump BUMP=3.1.5
   ```

   The script will:
   - Refuse to run unless the working directory is clean
   - Refuse to run if the branch is behind its upstream (it warns, but
     continues, if the branch is ahead or has no upstream)
   - Get the current version from git tags
   - Calculate the new version and validate the progression (prevents large
     jumps)
   - Insert `Version X.Y.Z (YYYY-MM-DD)` under `Unreleased` in `CHANGELOG.rst`
   - Commit that as `Update changelog for vX.Y.Z`
   - Create the annotated tag `vX.Y.Z`

3. Push the commit, then the tag:

   ```bash
   git push origin main
   git push origin vX.Y.Z
   ```

   Push the commit first. The tag triggers the release, and the release notes
   come from the changelog at that commit.

#### Manual Version Tagging (Not Recommended)

If you need to create a tag manually:

```bash
git tag -a vX.Y.Z -m "Release version X.Y.Z"
git push origin vX.Y.Z
```

**Warning**: Manual tagging bypasses the clean-tree, not-behind-upstream and
version progression checks, and does not touch the changelog - so unless you
added the `Version X.Y.Z (YYYY-MM-DD)` heading yourself,
`scripts/extract_changelog.py` finds no matching section and the GitHub release
notes fall back to the bare line `Release X.Y.Z`. Use the version bump script
instead.

### 5. The Release Runs Itself

Pushing a `v*` tag starts `.github/workflows/release.yml`, which is the only
thing that publishes. In order, it:

1. **Pre-release Checks** - `ruff check`, `ruff format --check`, and `pytest`
   against an install of `-e ".[testing]"`
2. **Build and Publish to PyPI** - `python -m build`, `twine check`, then
   `pypa/gh-action-pypi-publish` via PyPI trusted publishing (no API tokens
   are stored anywhere)
3. **Create GitHub Release** - release notes extracted from the `Version
   X.Y.Z` section of `CHANGELOG.rst`

Each job depends on the one before it, so a failing check publishes nothing.

Watch it:

```bash
gh run watch $(gh run list --workflow=release.yml --limit 1 --json databaseId --jq '.[0].databaseId')
```

Then confirm the result:

```bash
gh release view vX.Y.Z
pip index versions nwp500-python
```

#### Do Not Publish By Hand

`make publish` and `make publish-test` still exist as an emergency fallback,
but a normal release must not use them. The workflow has already uploaded the
artifacts by the time you could, and PyPI refuses to accept a version twice -
so running them after a successful release fails, and running them before it
makes the workflow fail instead. Publishing is CI's job.

#### If the Release Fails After You Pushed the Tag

The tag is the trigger, so a failing pre-release check leaves a tag on the
remote pointing at a commit that was never released. Nothing was published -
the publish job is gated behind the checks - so the version number is still
free. Fix the problem, then move the tag:

```bash
# after committing the fix and pushing main
git tag -d vX.Y.Z
git push origin :refs/tags/vX.Y.Z
git tag -a vX.Y.Z -m "Release version X.Y.Z"
git push origin vX.Y.Z
```

Confirm first that nothing was published - if the publish job did succeed,
that version is gone for good and you need a new patch version instead:

```bash
gh run view <run-id> --json jobs --jq '.jobs[] | "\(.name): \(.conclusion)"'
pip index versions nwp500-python
```

### 6. Building Locally (Optional)

Building locally is a sanity check, not part of publishing:

```bash
make build
```

This creates:
- `dist/nwp500_python-X.Y.Z.tar.gz` (source distribution)
- `dist/nwp500_python-X.Y.Z-py3-none-any.whl` (wheel)

The version comes from `git describe`, so building on an untagged commit
produces a development version like `9.3.1.dev3+g1a2b3c4` - that is expected,
and it is a quick way to confirm the tag you just created is what
`setuptools_scm` sees.

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

- [ ] Everything intended for the release is merged to `main`
- [ ] `CHANGELOG.rst` describes it all under `Unreleased`, with no
      hand-written `Version X.Y.Z` heading
- [ ] All code is formatted: `make format`
- [ ] Linting passes: `make lint`
- [ ] All tests pass: `make test`
- [ ] Version configuration is valid: `make validate-version`
- [ ] Documentation is up to date
- [ ] Examples work correctly
- [ ] Working directory is clean and `main` is in sync with the remote
      (the bump script enforces both)
- [ ] Build succeeds: `make build`

Then bump, push, and let the workflow publish - see
[The Release Runs Itself](#5-the-release-runs-itself).

## Publishing Credentials

There are none to set up. The release workflow publishes through
[PyPI trusted publishing](https://docs.pypi.org/trusted-publishers/): PyPI is
configured to trust `release.yml` in this repository, and the job mints a
short-lived token through the `pypi` GitHub environment using its
`id-token: write` permission. No API token is stored in the repository, in
GitHub secrets, or on your machine.

`TWINE_USERNAME`/`TWINE_PASSWORD` and `~/.pypirc` are only relevant if you
ever need the emergency `make publish` fallback, which a normal release must
not use.

## Continuous Integration

Two workflows already cover this:

**`.github/workflows/ci.yml`** - on pushes and pull requests:

| Job | What it does |
|-----|--------------|
| Lint and Format Check | `tox -e lint` (`ruff check` and `ruff format --check`) |
| Security Check | `ruff check --select S src/` |
| Test on Python 3.14 | `tox -e default` - pytest and pyright, with the `cli` and `testing` extras |
| Test without CLI extras | pytest against an `-e ".[testing]"` install, matching what `release.yml` does |
| Build Distribution | `python -m build` plus `twine check` |

**`.github/workflows/release.yml`** - on a `v*` tag: pre-release checks, then
build and publish to PyPI, then create the GitHub release.

`Test without CLI extras` exists because `tox` installs the `cli` extra while
`release.yml` does not. Without it, a test module that imports `click` outside
its `ImportError` guard passes every pull request and fails only once the
release tag has been pushed.

## Quick Commands Reference

| Command | Description |
|---------|-------------|
| `make version-bump` | Bump version (requires BUMP=patch/minor/major/X.Y.Z) |
| `make help` | Show all available commands |
| `make install-dev` | Install with dev dependencies |
| `make format` | Format code with ruff |
| `make lint` | Check code with ruff |
| `make test` | Run tests |
| `make check-release` | Run all pre-release checks |
| `make release` | Full release build process |
| `make build` | Build distribution packages locally (CI builds what is published) |
| `make clean` | Remove build artifacts |
| `make publish-test` | Emergency fallback only - upload to TestPyPI by hand |
| `make publish` | Emergency fallback only - upload to PyPI by hand |

## More Information

- [Ruff Documentation](https://docs.astral.sh/ruff/)
- [Python Packaging User Guide](https://packaging.python.org/)
- [Twine Documentation](https://twine.readthedocs.io/)
- [Semantic Versioning](https://semver.org/)
