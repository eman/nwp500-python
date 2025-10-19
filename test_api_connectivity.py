#!/usr/bin/env python3
"""Test API connectivity and endpoints."""

import asyncio
import os
import sys

import aiohttp

sys.path.insert(0, "src")

from nwp500.auth import NavienAuthClient
from nwp500.config import API_BASE_URL


async def test_connectivity():
    """Test basic API connectivity."""
    
    email = os.getenv("NAVIEN_EMAIL")
    password = os.getenv("NAVIEN_PASSWORD")
    
    if not email or not password:
        print("❌ NAVIEN_EMAIL and NAVIEN_PASSWORD environment variables must be set")
        return
    
    print(f"Testing API connectivity to: {API_BASE_URL}")
    print("=" * 70)
    
    # Test 1: Basic HTTP connectivity
    print("\n1. Testing basic HTTP connectivity...")
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(API_BASE_URL, timeout=aiohttp.ClientTimeout(total=5)) as response:
                print(f"   ✅ Server responded with status: {response.status}")
    except asyncio.TimeoutError:
        print("   ⚠️  Timeout connecting to server")
    except Exception as e:
        print(f"   ⚠️  Connection error: {type(e).__name__}: {e}")
    
    # Test 2: Authentication
    print("\n2. Testing authentication...")
    try:
        async with NavienAuthClient(email, password, timeout=10) as auth_client:
            print(f"   ✅ Authenticated as: {auth_client.user_email}")
            
            # Test 3: List devices endpoint
            print("\n3. Testing /device/list endpoint...")
            try:
                from nwp500 import NavienAPIClient
                api_client = NavienAPIClient(auth_client=auth_client)
                devices = await asyncio.wait_for(api_client.list_devices(), timeout=10)
                print(f"   ✅ Found {len(devices)} device(s)")
                
                # Test 4: Device info endpoint (if we have devices)
                if devices:
                    print("\n4. Testing /device/info endpoint...")
                    device = devices[0]
                    mac = device.device_info.mac_address
                    additional = device.device_info.additional_value
                    
                    try:
                        info = await asyncio.wait_for(
                            api_client.get_device_info(mac, additional),
                            timeout=10
                        )
                        print(f"   ✅ Got device info for: {info.device_info.device_name}")
                    except asyncio.TimeoutError:
                        print("   ❌ TIMEOUT: /device/info endpoint not responding")
                        print("   This endpoint may be broken or deprecated")
                    except Exception as e:
                        print(f"   ❌ Error: {type(e).__name__}: {e}")
                else:
                    print("\n4. Skipping device info test (no devices found)")
                    
            except asyncio.TimeoutError:
                print("   ❌ TIMEOUT: /device/list endpoint not responding")
            except Exception as e:
                print(f"   ❌ Error: {type(e).__name__}: {e}")
                
    except asyncio.TimeoutError:
        print("   ❌ TIMEOUT: Authentication timed out")
    except Exception as e:
        print(f"   ❌ Authentication failed: {type(e).__name__}: {e}")
    
    print("\n" + "=" * 70)
    print("Test complete")


if __name__ == "__main__":
    asyncio.run(test_connectivity())
