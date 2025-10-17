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
- **Build docs**: `tox -e docs` (Sphinx docs in `docs/`)
- **Preview docs**: `python3 -m http.server --directory docs/_build/html`

### Before Committing Changes
Always run `make ci-lint` before finalizing changes to ensure your code will pass CI checks. This runs the exact same linting configuration as the CI pipeline, preventing "passes locally but fails in CI" issues.

## Patterns & Conventions
- **Async context managers** for authentication: `async with NavienAuthClient(email, password) as auth_client:`
- **Environment variables** for credentials: `NAVIEN_EMAIL`, `NAVIEN_PASSWORD`
- **Device status fields** use conversion formulas (see `docs/DEVICE_STATUS_FIELDS.rst`)
- **MQTT topics**: `cmd/{deviceType}/{deviceId}/ctrl` for control, `cmd/{deviceType}/{deviceId}/st` for status
- **Command queuing**: Commands sent while disconnected are queued and sent when reconnected
- **No base64 encoding/decoding** of MQTT payloads; all payloads are JSON-encoded/decoded

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

---

If any section is unclear or missing important project-specific details, please provide feedback so this guide can be improved for future AI agents.
