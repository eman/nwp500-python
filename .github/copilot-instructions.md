# Copilot Instructions for nwp500-python

## Project Architecture
- The codebase is organized around two main components:
  - **API Client (`src/nwp500/api_client.py`)**: Handles RESTful communication with the Navien cloud API for device management, status, and control.
  - **MQTT Client (`src/nwp500/mqtt_client.py`)**: Manages real-time device communication using AWS IoT Core and MQTT protocol. Uses AWS credentials from authentication.
- **Authentication (`src/nwp500/auth.py`)**: Provides JWT and AWS credential management for both API and MQTT clients.
- **Data Models (`src/nwp500/models.py`)**: Defines type-safe device, status, and command structures with automatic unit conversions.
- **Events (`src/nwp500/events.py`)**: Implements an event-driven callback system for device and system updates.

## Developer Workflows
- **Install dependencies**: `pip install -e .` (development mode)
- **Run tests**: `pytest` (unit tests in `tests/`)
- **Lint/format**: `ruff format --check src/ tests/ examples/` (use `ruff format ...` to auto-format)
- **CI-compatible linting**: `make ci-lint` (run before finalizing changes to ensure CI will pass)
- **CI-compatible formatting**: `make ci-format` (auto-fix formatting issues)
- **Type checking**: `python3 -m mypy src/nwp500 --config-file pyproject.toml` (static type analysis)
- **Build docs**: `tox -e docs` (Sphinx docs in `docs/`)
- **Preview docs**: `python3 -m http.server --directory docs/_build/html`
- **Version management**: `make version-bump BUMP=patch|minor|major` (creates git tags, see Version Management section)

### Version Management

**CRITICAL**: This project uses `setuptools_scm` to derive versions from git tags. 

**Never manually edit version numbers!** The `version` field in `setup.cfg`'s `[pyscaffold]` section is the PyScaffold TOOL version (4.6), NOT the package version. Changing it will cause incorrect releases.

#### Creating a New Release

1. **Update CHANGELOG.rst** with the new version and changes
2. **Commit the changelog**: `git add CHANGELOG.rst && git commit -m "Update changelog for vX.Y.Z"`
3. **Bump version**: Use the version bump script:
   ```bash
   make version-bump BUMP=patch   # For bug fixes (3.1.4 -> 3.1.5)
   make version-bump BUMP=minor   # For new features (3.1.4 -> 3.2.0)
   make version-bump BUMP=major   # For breaking changes (3.1.4 -> 4.0.0)
   ```
4. **Push the tag**: `git push origin vX.Y.Z`

The version bump script:
- Gets the current version from git tags
- Validates the new version progression (prevents large jumps)
- Prompts for confirmation with checklist
- Creates a git tag (e.g., `v3.1.5`)

**Validation**: Run `make validate-version` to check for version-related mistakes before committing.

### Before Committing Changes
Always run these checks before finalizing changes to ensure your code will pass CI:
1. **Linting**: `make ci-lint` - Ensures code style matches CI requirements
2. **Type checking**: `python3 -m mypy src/nwp500 --config-file pyproject.toml` - Catches type errors
3. **Tests**: `pytest` - Ensures functionality isn't broken

This prevents "passes locally but fails in CI" issues.

**Important**: When updating CHANGELOG.rst or any file with dates, always use `date +"%Y-%m-%d"` to get the correct current date. Never hardcode or guess dates.

### Before Completing a Task - REQUIRED VALIDATION

**ALWAYS run these checks before considering a task complete:**

1. **Linting**: `make ci-lint` - MUST pass before completion
2. **Type checking**: `python3 -m mypy src/nwp500 --config-file pyproject.toml` - MUST pass before completion
3. **Unit tests**: `pytest` - MUST pass before completion (unless tests don't exist for the feature)

**Do not mark a task as complete or create a PR without running all three checks.**

These checks prevent "works locally but fails in CI" issues and catch integration problems early.

Report the results of these checks in your final summary, including:
- Number of tests passed/failed
- Any linting errors fixed
- Any type errors resolved

### After Completing a Task
Document validation results:
- **Linting**: All checks passed
- **Type checking**: No errors found  
- **Tests**: X/X passed (or "N/A - no existing tests for this feature")

## Patterns & Conventions
- **Async context managers** for authentication: `async with NavienAuthClient(email, password) as auth_client:`
- **Environment variables** for credentials: `NAVIEN_EMAIL`, `NAVIEN_PASSWORD`
- **Device status fields** use conversion formulas (see `docs/DEVICE_STATUS_FIELDS.rst`)
- **MQTT topics**: `cmd/{deviceType}/{deviceId}/ctrl` for control, `cmd/{deviceType}/{deviceId}/st` for status
- **Command queuing**: Commands sent while disconnected are queued and sent when reconnected
- **No base64 encoding/decoding** of MQTT payloads; all payloads are JSON-encoded/decoded
- **Exception handling**: Use specific exception types instead of catch-all `except Exception`. Common types:
  - `AwsCrtError` - AWS IoT Core/MQTT errors
  - `AuthenticationError`, `TokenRefreshError` - Authentication errors
  - `RuntimeError` - Runtime state errors (not connected, etc.)
  - `ValueError` - Invalid values or parameters
  - `TypeError`, `AttributeError`, `KeyError` - Data structure errors
  - `asyncio.CancelledError` - Task cancellation
  - Only catch exceptions you can handle; let unexpected exceptions propagate

## Backward Compatibility Policy

**DO NOT maintain backward compatibility.** This library is young and has no external clients.

- **Breaking changes are acceptable**: Make the best design decisions without worrying about breaking existing code
- **Remove deprecated code immediately**: Don't add deprecation warnings or transitional code - just remove it
- **Remove duplicate functionality**: If there are two ways to do the same thing, remove one
- **Clean up legacy patterns**: Remove old patterns, helper variables, or compatibility shims
- **Update documentation**: When making breaking changes:
  1. Document the change in `CHANGELOG.rst` under the appropriate version
  2. Explain what was removed/changed and why
  3. Provide clear migration guidance showing the old way vs. new way
  4. Update affected examples to use the new pattern
  5. Update relevant documentation files
- **Version bumping**: Breaking changes require a major version bump (see Version Management section)

**Example changelog entry for breaking changes:**
```rst
Version X.0.0 (YYYY-MM-DD)
==========================

**BREAKING CHANGES**: Description of what broke

Removed
-------
- **Old Pattern**: Removed `old_function()` in favor of cleaner `new_function()`
  
  .. code-block:: python
  
     # OLD (removed)
     result = client.old_function(arg)
     
     # NEW
     result = client.new_function(arg)

- **Duplicate Functionality**: Removed constructor callbacks in favor of event emitter pattern
  - Removed `on_connection_interrupted` constructor parameter
  - Use `client.on('connection_interrupted', handler)` instead
```

## Integration Points
- **AWS IoT Core**: MQTT client uses `awscrt` and `awsiot` libraries for connection and messaging
- **aiohttp**: Used for async HTTP requests to the Navien API
- **pydantic**: Used for data validation and models

## Key Files & Directories
- `src/nwp500/` - Main library code
- `examples/` - Example scripts for API and MQTT usage
- `tests/` - Unit tests
- `docs/` - Sphinx documentation (see `DEVICE_STATUS_FIELDS.rst`, `MQTT_CLIENT.rst`, etc.)

## Troubleshooting
- If authentication fails, check environment variables and credentials
- If tests hang, check network connectivity and API endpoint status
- For MQTT, ensure AWS credentials are valid and endpoint is reachable

## Communication Style
- **Progress updates**: Save summaries for the end of work. Don't provide interim status reports.
- **Final summaries**: Keep them concise. Example format:
  ```
  ## Final Results
  **Starting point:** X errors
  **Ending point:** 0 errors
  **Tests:** All passing
  
  ## What Was Fixed
  - Module 1 - Brief description (N errors)
  - Module 2 - Brief description (N errors)
  ```
- **No markdown files**: Don't create separate summary files. Provide summaries inline when requested.
- **Focus on execution**: Perform the work, then summarize results at the end.

---

If any section is unclear or missing important project-specific details, please provide feedback so this guide can be improved for future AI agents.
