"""
Quick test script for the Geocodio API.

This script tests the API connection with a small sample of addresses
before running the full batch.
"""

import os
import json
import urllib.request
import urllib.error
from pathlib import Path


def load_env():
    """Load environment variables from .env file."""
    env_path = Path(__file__).parent / '.env'
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ.setdefault(key.strip(), value.strip())


load_env()


def test_single_address(api_key: str, address: str) -> dict:
    """Test geocoding a single address."""
    import urllib.parse
    encoded_address = urllib.parse.quote(address)
    url = f"https://api.geocod.io/v1.7/geocode?q={encoded_address}&api_key={api_key}"

    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            return json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return {'error': f"HTTP {e.code}: {e.read().decode('utf-8')}"}
    except urllib.error.URLError as e:
        return {'error': f"URL Error: {e.reason}"}


def test_batch(api_key: str, addresses: list[str]) -> dict:
    """Test batch geocoding."""
    url = f"https://api.geocod.io/v1.7/geocode?api_key={api_key}"
    data = json.dumps(addresses).encode('utf-8')

    request = urllib.request.Request(
        url,
        data=data,
        headers={'Content-Type': 'application/json'},
        method='POST'
    )

    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return {'error': f"HTTP {e.code}: {e.read().decode('utf-8')}"}
    except urllib.error.URLError as e:
        return {'error': f"URL Error: {e.reason}"}


def main():
    api_key = os.environ.get('GEOCODIO_API_KEY')
    if not api_key:
        print("Please set GEOCODIO_API_KEY environment variable")
        print("  Windows: set GEOCODIO_API_KEY=your_key_here")
        return

    print("Testing Geocodio API connection...\n")

    # Test 1: Single well-formed address
    print("Test 1: Single well-formed address")
    print("-" * 40)
    result = test_single_address(api_key, "1600 Pennsylvania Ave NW, Washington, DC 20500")

    if 'error' in result:
        print(f"ERROR: {result['error']}")
        return

    if result.get('results'):
        r = result['results'][0]
        print(f"  Input: 1600 Pennsylvania Ave NW, Washington, DC 20500")
        print(f"  Formatted: {r.get('formatted_address')}")
        print(f"  Lat/Lng: {r.get('location', {}).get('lat')}, {r.get('location', {}).get('lng')}")
        print(f"  Accuracy: {r.get('accuracy')} ({r.get('accuracy_type')})")
        print(f"  Source: {r.get('source')}")
    print()

    # Test 2: Sample from our dataset
    print("Test 2: Sample addresses from LCV data")
    print("-" * 40)
    test_addresses = [
        "1 N 2nd St, Hartsville, SC 29550-3300",
        "100 Ribaut Rd Rm 115, Beaufort, SC 29902-4453",
        "110 Tradd St, Charleston, SC 29401-2421",
        "1593, Rock Hill, SC 29732",  # Problematic - number only
        "106 ALABAMA St, SC",  # Problematic - missing city/zip
    ]

    batch_result = test_batch(api_key, test_addresses)

    if 'error' in batch_result:
        print(f"ERROR: {batch_result['error']}")
        return

    results = batch_result.get('results', [])
    for i, addr in enumerate(test_addresses):
        print(f"\n  Address {i+1}: {addr}")
        if i < len(results) and results[i].get('response', {}).get('results'):
            r = results[i]['response']['results'][0]
            print(f"    Formatted: {r.get('formatted_address')}")
            print(f"    Accuracy: {r.get('accuracy')} ({r.get('accuracy_type')})")

            # Check for address component differences
            components = r.get('address_components', {})
            if components:
                print(f"    Components: {components.get('number')} {components.get('street')}, "
                      f"{components.get('city')}, {components.get('state')} {components.get('zip')}")
        else:
            print(f"    No match found")

    print("\n" + "=" * 40)
    print("API connection successful!")
    print("You can now run the full geocoder: python geocoder.py")


if __name__ == "__main__":
    main()
