# Examples

This directory contains example scripts demonstrating how to use the nwp500-python library.

## Prerequisites

Install the library in development mode:

```bash
cd ..
pip install -e .
```

Or install the required dependencies:

```bash
pip install aiohttp>=3.8.0 awsiotsdk>=1.21.0
```

## Authentication

All examples use the `NavienAuthClient` which requires credentials passed to the constructor. Authentication happens automatically when entering the async context.

### Setting Credentials

Set your credentials as environment variables:

```bash
export NAVIEN_EMAIL='your_email@example.com'
export NAVIEN_PASSWORD='your_password'
```

## Example Files

### Authentication Example

`authenticate.py` - Demonstrates basic authentication with the Navien Smart Control API.

**Usage:**
```bash
python authenticate.py
```

**What It Does:**
1. Authenticates with the Navien Smart Control API (automatically)
2. Displays user information (name, status, type)
3. Shows token information (access token, refresh token, expiration)
4. Demonstrates how to use tokens in API requests
5. Shows AWS credentials if available for IoT/MQTT connections

### API Client Examples

- `auth_constructor_example.py` - Shows the simplified authentication pattern
- `improved_auth_pattern.py` - Demonstrates the clean pattern for API and MQTT usage
- `test_api_client.py` - Comprehensive API client testing

### MQTT Examples

- `combined_callbacks.py` - Device status and feature monitoring
- `device_status_callback.py` - Real-time device status updates
- `device_feature_callback.py` - Device feature monitoring
- `mqtt_client_example.py` - Basic MQTT client usage
- `test_mqtt_connection.py` - MQTT connection testing
- `test_mqtt_messaging.py` - MQTT message handling

### Common Pattern

All examples follow this pattern:

```python
import asyncio
import os
from nwp500 import NavienAuthClient, NavienAPIClient

async def main():
    email = os.getenv("NAVIEN_EMAIL")
    password = os.getenv("NAVIEN_PASSWORD")
    
    # Authentication happens automatically
    async with NavienAuthClient(email, password) as auth_client:
        # Use the authenticated client
        api_client = NavienAPIClient(auth_client=auth_client)
        devices = await api_client.list_devices()
        print(f"Found {len(devices)} device(s)")

asyncio.run(main())
```

## Expected Output

When running any example with valid credentials, you should see output similar to:

```
✅ Authenticated as: John Doe
📧 Email: your_email@example.com
🔑 Token expires at: 2024-01-15 14:30:00
```

## Troubleshooting

**Error: name 'auth_response' is not defined**
- This means an example file hasn't been updated. Use `auth_client.current_user` and `auth_client.current_tokens` instead.

**Error: NavienAuthClient() missing 2 required positional arguments**
- Credentials are now required. Pass email and password to the constructor.

**Authentication fails**
- Verify your NAVIEN_EMAIL and NAVIEN_PASSWORD environment variables are set correctly
- Check that your credentials are valid
- Ensure internet connectivity
