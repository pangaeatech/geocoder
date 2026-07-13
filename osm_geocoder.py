"""
OpenStreetMap Nominatim Geocoder for Address Data
This script geocodes addresses from a CSV file using the Nominatim API.
Rate limited to 1 request per second as per OSM usage policy.
"""

import csv
import json
import time
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime
from typing import Optional


def build_address_string(row: dict) -> str:
    """Build a full address string from CSV row components."""
    parts = []

    # Address line 1
    addr1 = row.get('AddressLine1', '').strip()
    if addr1 and addr1.upper() not in ['N/A', 'N/A N/A']:
        parts.append(addr1)

    # Address line 2 (apartment, suite, etc.)
    addr2 = row.get('AddressLine2', '').strip()
    if addr2:
        parts.append(addr2)

    # City
    city = row.get('City', '').strip()
    if city:
        parts.append(city)

    # State
    state = row.get('State/Province', '').strip()
    if state:
        parts.append(state)

    # Zip
    zip_code = row.get('Zip/Postal', '').strip()
    if zip_code:
        parts.append(zip_code)

    # Country
    country = row.get('CountryName', '').strip()
    if country:
        parts.append(country)

    return ', '.join(parts)


def geocode_address(address: str, user_agent: str = "GeocoderPOC/1.0") -> Optional[dict]:
    """
    Geocode a single address using Nominatim API.
    Returns the first result or None if no results found.
    """
    base_url = "https://nominatim.openstreetmap.org/search"

    params = {
        'q': address,
        'format': 'json',
        'addressdetails': 1,
        'limit': 1
    }

    url = f"{base_url}?{urllib.parse.urlencode(params)}"

    headers = {
        'User-Agent': user_agent
    }

    try:
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode('utf-8'))
            if data and len(data) > 0:
                return data[0]
            return None
    except urllib.error.HTTPError as e:
        print(f"HTTP Error {e.code}: {e.reason}")
        return None
    except urllib.error.URLError as e:
        print(f"URL Error: {e.reason}")
        return None
    except Exception as e:
        print(f"Error geocoding address: {e}")
        return None


def determine_match_quality(result: dict) -> dict:
    """
    Analyze the geocoding result to determine match quality.
    Returns a dict with quality indicators.
    """
    if result is None:
        return {
            'match_type': 'NO_MATCH',
            'confidence': 0,
            'description': 'No geocoding result returned'
        }

    osm_type = result.get('type', 'unknown')
    osm_class = result.get('class', 'unknown')
    importance = float(result.get('importance', 0))

    # Determine match type based on OSM class and type
    # Higher precision types
    high_precision = ['house', 'building', 'apartments', 'residential', 'house_number']
    medium_precision = ['street', 'road', 'path', 'footway', 'service']
    low_precision = ['postcode', 'postal_code', 'suburb', 'neighbourhood', 'city_block']
    very_low_precision = ['city', 'town', 'village', 'hamlet', 'municipality',
                          'county', 'state', 'country', 'administrative']

    if osm_type in high_precision or osm_class == 'building':
        match_type = 'ROOFTOP'
        base_confidence = 90
    elif osm_type in medium_precision or osm_class == 'highway':
        match_type = 'RANGE_INTERPOLATED'
        base_confidence = 70
    elif osm_type in low_precision:
        match_type = 'GEOMETRIC_CENTER'
        base_confidence = 50
    elif osm_type in very_low_precision or osm_class == 'boundary':
        match_type = 'APPROXIMATE'
        base_confidence = 30
    else:
        match_type = 'UNKNOWN'
        base_confidence = 40

    # Adjust confidence based on importance score
    confidence = min(100, base_confidence + int(importance * 20))

    description = f"OSM class: {osm_class}, type: {osm_type}, importance: {importance:.3f}"

    return {
        'match_type': match_type,
        'confidence': confidence,
        'osm_class': osm_class,
        'osm_type': osm_type,
        'importance': importance,
        'description': description
    }


def process_csv(input_file: str, output_file: str, results_json: str):
    """
    Process the CSV file and geocode all addresses.
    """
    results = []

    # Read input CSV
    with open(input_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    total = len(rows)
    print(f"Starting geocoding of {total} addresses")
    print(f"Estimated time: ~{total} seconds ({total // 60} minutes {total % 60} seconds)")
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("-" * 60)

    start_time = time.time()

    for i, row in enumerate(rows):
        vanid = row.get('VANID', '')
        address_string = build_address_string(row)

        # Skip if no valid address
        if not address_string or address_string.startswith('N/A') or address_string.startswith('PO Box'):
            result = {
                'vanid': vanid,
                'input_address': address_string,
                'lat': None,
                'lon': None,
                'display_name': None,
                'match_type': 'SKIPPED' if address_string.startswith('PO Box') else 'INVALID_INPUT',
                'confidence': 0,
                'osm_class': None,
                'osm_type': None,
                'importance': None,
                'address_details': None,
                'error': 'PO Box - not geocodable' if address_string.startswith('PO Box') else 'Invalid or empty address'
            }
            results.append(result)
            print(f"[{i+1}/{total}] SKIPPED: {vanid} - {address_string[:50]}...")
            continue

        # Geocode the address
        geo_result = geocode_address(address_string)
        quality = determine_match_quality(geo_result)

        if geo_result:
            result = {
                'vanid': vanid,
                'input_address': address_string,
                'lat': float(geo_result.get('lat', 0)),
                'lon': float(geo_result.get('lon', 0)),
                'display_name': geo_result.get('display_name', ''),
                'match_type': quality['match_type'],
                'confidence': quality['confidence'],
                'osm_class': quality['osm_class'],
                'osm_type': quality['osm_type'],
                'importance': quality['importance'],
                'address_details': geo_result.get('address', {}),
                'bounding_box': geo_result.get('boundingbox', []),
                'error': None
            }
            status = f"{quality['match_type']} (conf: {quality['confidence']}%)"
        else:
            result = {
                'vanid': vanid,
                'input_address': address_string,
                'lat': None,
                'lon': None,
                'display_name': None,
                'match_type': 'NO_MATCH',
                'confidence': 0,
                'osm_class': None,
                'osm_type': None,
                'importance': None,
                'address_details': None,
                'error': 'No geocoding result'
            }
            status = "NO MATCH"

        results.append(result)

        # Progress output
        elapsed = time.time() - start_time
        avg_per_request = elapsed / (i + 1)
        remaining = avg_per_request * (total - i - 1)
        print(f"[{i+1}/{total}] {status}: {vanid} - {address_string[:40]}... (ETA: {int(remaining)}s)")

        # Rate limiting: 1 request per second
        time.sleep(1)

    # Write results to JSON
    with open(results_json, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2)

    # Write results to CSV
    fieldnames = ['vanid', 'input_address', 'lat', 'lon', 'display_name',
                  'match_type', 'confidence', 'osm_class', 'osm_type',
                  'importance', 'error']

    with open(output_file, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(results)

    # Print summary
    print("\n" + "=" * 60)
    print("GEOCODING COMPLETE")
    print("=" * 60)

    total_time = time.time() - start_time
    print(f"Total time: {int(total_time // 60)} minutes {int(total_time % 60)} seconds")
    print(f"Average time per address: {total_time / total:.2f} seconds")

    # Statistics
    match_types = {}
    confidence_sum = 0
    matched_count = 0

    for r in results:
        mt = r['match_type']
        match_types[mt] = match_types.get(mt, 0) + 1
        if r['confidence'] > 0:
            confidence_sum += r['confidence']
            matched_count += 1

    print(f"\nMatch Type Distribution:")
    for mt, count in sorted(match_types.items(), key=lambda x: -x[1]):
        pct = (count / total) * 100
        print(f"  {mt}: {count} ({pct:.1f}%)")

    if matched_count > 0:
        avg_confidence = confidence_sum / matched_count
        print(f"\nAverage confidence (matched only): {avg_confidence:.1f}%")

    print(f"\nResults saved to:")
    print(f"  CSV: {output_file}")
    print(f"  JSON: {results_json}")

    return results


if __name__ == "__main__":
    input_csv = "Mock LCV Data.csv"
    output_csv = "geocoding_results.csv"
    results_json = "geocoding_results.json"

    process_csv(input_csv, output_csv, results_json)
