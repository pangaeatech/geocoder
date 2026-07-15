"""
Geocodio Batch Geocoding Proof of Concept

This script reads address data from a CSV file, formats it for the Geocodio API,
performs batch geocoding, and analyzes the accuracy of results.
"""

import csv
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import urllib.request
import urllib.parse
import urllib.error


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


@dataclass
class GeocodingResult:
    """Represents a single geocoding result with accuracy metrics."""
    vanid: str
    original_address: str
    formatted_address: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    accuracy: Optional[float]
    accuracy_type: Optional[str]
    source: Optional[str]
    match_status: str  # 'matched', 'no_match', 'error', 'skipped'
    error_message: Optional[str] = None
    address_components: Optional[dict] = None


class GeocodioGeocoder:
    """Handles batch geocoding via the Geocodio API."""

    BASE_URL = "https://api.geocod.io/v1.7/geocode"
    BATCH_SIZE = 10000  # Geocodio's max batch size

    # Accuracy types from best to worst
    ACCURACY_TYPES = {
        'rooftop': 1.0,
        'point': 0.95,
        'range_interpolation': 0.8,
        'nearest_rooftop_match': 0.7,
        'street_center': 0.5,
        'place': 0.3,
        'county': 0.2,
        'state': 0.1,
    }

    def __init__(self, api_key: str):
        self.api_key = api_key

    def geocode_batch(self, addresses: list[dict]) -> list[dict]:
        """
        Send a batch of addresses to Geocodio for geocoding.

        Args:
            addresses: List of dicts with 'id' and 'address' keys

        Returns:
            List of result dictionaries from the API
        """
        # Format addresses as a dict keyed by ID for easy matching
        address_payload = {
            addr['id']: addr['address'] for addr in addresses
        }

        url = f"{self.BASE_URL}?api_key={self.api_key}"

        data = json.dumps(address_payload).encode('utf-8')

        request = urllib.request.Request(
            url,
            data=data,
            headers={'Content-Type': 'application/json'},
            method='POST'
        )

        try:
            with urllib.request.urlopen(request, timeout=600) as response:
                result = json.loads(response.read().decode('utf-8'))
                return result.get('results', {})
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8') if e.fp else str(e)
            raise Exception(f"Geocodio API error ({e.code}): {error_body}")
        except urllib.error.URLError as e:
            raise Exception(f"Network error: {e.reason}")

    def parse_result(self, vanid: str, original_address: str, api_result: dict) -> GeocodingResult:
        """Parse a single API result into a GeocodingResult."""
        response = api_result.get('response', {})
        results = response.get('results', [])

        if not results:
            return GeocodingResult(
                vanid=vanid,
                original_address=original_address,
                formatted_address=None,
                latitude=None,
                longitude=None,
                accuracy=None,
                accuracy_type=None,
                source=None,
                match_status='no_match',
                error_message='No results returned'
            )

        # Take the best result (first one)
        best = results[0]
        location = best.get('location', {})

        return GeocodingResult(
            vanid=vanid,
            original_address=original_address,
            formatted_address=best.get('formatted_address'),
            latitude=location.get('lat'),
            longitude=location.get('lng'),
            accuracy=best.get('accuracy'),
            accuracy_type=best.get('accuracy_type'),
            source=best.get('source'),
            match_status='matched',
            address_components=best.get('address_components')
        )


def read_csv_addresses(filepath: str) -> list[dict]:
    """
    Read addresses from the CSV file and format them for geocoding.

    Returns list of dicts with 'id', 'address', and 'raw_data' keys.
    """
    addresses = []

    with open(filepath, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)

        for row in reader:
            vanid = row.get('VANID', '').strip()

            # Build address string from components
            address_parts = []

            # Primary address line
            addr1 = row.get('AddressLine1', '').strip()
            addr2 = row.get('AddressLine2', '').strip()
            addr3 = row.get('AddressLine3', '').strip()

            # Combine address lines
            full_street = ' '.join(filter(None, [addr1, addr2, addr3]))
            if full_street:
                address_parts.append(full_street)

            # City
            city = row.get('City', '').strip()
            if city:
                address_parts.append(city)

            # State
            state = row.get('State/Province', '').strip()
            if state:
                address_parts.append(state)

            # Zip code (combine zip and zip4 if available)
            zip_code = row.get('Zip/Postal', '').strip()
            zip4 = row.get('Zip4', '').strip()
            if zip_code:
                if zip4:
                    address_parts.append(f"{zip_code}-{zip4}")
                else:
                    address_parts.append(zip_code)

            full_address = ', '.join(address_parts)

            addresses.append({
                'id': vanid,
                'address': full_address,
                'raw_data': row
            })

    return addresses


def identify_problematic_addresses(addresses: list[dict]) -> list[dict]:
    """
    Identify addresses that may have issues before geocoding.

    Returns list of addresses with 'issues' key added.
    """
    problematic = []

    for addr in addresses:
        issues = []
        address = addr['address']
        raw = addr['raw_data']

        # Check for PO Boxes
        addr_upper = address.upper()
        if 'PO BOX' in addr_upper or 'P.O. BOX' in addr_upper or 'P O BOX' in addr_upper:
            issues.append('PO Box address - cannot geocode to precise location')

        # Check for missing street address
        addr1 = raw.get('AddressLine1', '').strip()
        if not addr1:
            issues.append('Missing street address')
        elif addr1.isdigit():
            issues.append('Street address appears to be number only (missing street name)')

        # Check for missing city
        if not raw.get('City', '').strip():
            issues.append('Missing city')

        # Check for missing state
        if not raw.get('State/Province', '').strip():
            issues.append('Missing state')

        # Check for missing zip
        if not raw.get('Zip/Postal', '').strip():
            issues.append('Missing zip code')

        # Check for embedded location info in address
        if ' SC ' in addr1.upper() or ' NC ' in addr1.upper():
            issues.append('Address may contain embedded city/state info')

        # Check for non-standard characters or formatting
        if 'N/A' in addr1.upper():
            issues.append('Address contains N/A')

        if issues:
            addr['issues'] = issues
            problematic.append(addr)

    return problematic


def save_results_to_csv(results: list[GeocodingResult], filepath: str):
    """Save geocoding results to a CSV file."""
    fieldnames = [
        'vanid', 'original_address', 'formatted_address',
        'latitude', 'longitude', 'accuracy', 'accuracy_type',
        'source', 'match_status', 'error_message'
    ]

    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for result in results:
            writer.writerow({
                'vanid': result.vanid,
                'original_address': result.original_address,
                'formatted_address': result.formatted_address,
                'latitude': result.latitude,
                'longitude': result.longitude,
                'accuracy': result.accuracy,
                'accuracy_type': result.accuracy_type,
                'source': result.source,
                'match_status': result.match_status,
                'error_message': result.error_message
            })


def analyze_results(results: list[GeocodingResult]) -> dict:
    """Analyze geocoding results and return summary statistics."""
    total = len(results)
    matched = [r for r in results if r.match_status == 'matched']
    no_match = [r for r in results if r.match_status == 'no_match']
    skipped = [r for r in results if r.match_status == 'skipped']
    errors = [r for r in results if r.match_status == 'error']

    # Accuracy type breakdown (this is the reliable metric)
    accuracy_counts = {}
    for r in matched:
        acc_type = r.accuracy_type or 'unknown'
        accuracy_counts[acc_type] = accuracy_counts.get(acc_type, 0) + 1

    # Quality tiers based on accuracy_type (NOT score)
    # - Exact: rooftop (precise building-level match)
    # - Good: range_interpolation, nearest_rooftop_match (reliable estimate)
    # - Poor: street_center, place, county, state (needs review)
    exact_types = {'rooftop'}
    good_types = {'range_interpolation', 'nearest_rooftop_match'}
    poor_types = {'street_center', 'place', 'county', 'state'}

    exact_match = [r for r in matched if r.accuracy_type in exact_types]
    good_match = [r for r in matched if r.accuracy_type in good_types]
    poor_match = [r for r in matched if r.accuracy_type in poor_types]

    return {
        'total': total,
        'matched': len(matched),
        'no_match': len(no_match),
        'skipped': len(skipped),
        'errors': len(errors),
        'match_rate': len(matched) / total * 100 if total > 0 else 0,
        'accuracy_types': accuracy_counts,
        'exact_match': len(exact_match),
        'good_match': len(good_match),
        'poor_match': len(poor_match),
    }


def print_analysis(analysis: dict, problematic: list[dict]):
    """Print a formatted analysis report."""
    print("\n" + "=" * 60)
    print("GEOCODING RESULTS ANALYSIS")
    print("=" * 60)

    print(f"\nOverall Statistics:")
    print(f"  Total addresses: {analysis['total']}")
    print(f"  Successfully matched: {analysis['matched']} ({analysis['match_rate']:.1f}%)")
    print(f"  No match found: {analysis['no_match']}")
    print(f"  Skipped: {analysis['skipped']}")
    print(f"  Errors: {analysis['errors']}")

    print(f"\nAccuracy Type Breakdown:")
    for acc_type, count in sorted(analysis['accuracy_types'].items(),
                                   key=lambda x: GeocodioGeocoder.ACCURACY_TYPES.get(x[0], 0),
                                   reverse=True):
        print(f"  {acc_type}: {count}")

    print(f"\nMatch Quality (based on accuracy_type, NOT score):")
    print(f"  EXACT (rooftop):              {analysis['exact_match']} - auto-accept")
    print(f"  GOOD (interpolation/nearest): {analysis['good_match']} - likely accurate")
    print(f"  POOR (street/place/county):   {analysis['poor_match']} - needs review")

    print(f"\nProblematic Addresses Identified Before Geocoding: {len(problematic)}")

    # Group by issue type
    issue_counts = {}
    for addr in problematic:
        for issue in addr.get('issues', []):
            issue_counts[issue] = issue_counts.get(issue, 0) + 1

    if issue_counts:
        print("  Issues found:")
        for issue, count in sorted(issue_counts.items(), key=lambda x: -x[1]):
            print(f"    - {issue}: {count}")

    print("\n" + "=" * 60)


def main():
    """Main entry point for the geocoding proof of concept."""
    # Configuration
    csv_path = "Mock LCV Data.csv"
    output_path = "geocoding_results.csv"

    # Check for API key
    api_key = os.environ.get('GEOCODIO_API_KEY')
    if not api_key:
        print("=" * 60)
        print("GEOCODIO API KEY REQUIRED")
        print("=" * 60)
        print("\nTo use this script, you need a Geocodio API key.")
        print("1. Sign up at https://www.geocod.io/")
        print("2. Get your API key from the dashboard")
        print("3. Set it as an environment variable:")
        print("   Windows: set GEOCODIO_API_KEY=your_key_here")
        print("   Linux/Mac: export GEOCODIO_API_KEY=your_key_here")
        print("\nOr modify this script to hardcode the key (not recommended for production)")
        print("=" * 60)

        # For demo purposes, still analyze the addresses
        print("\nRunning address analysis without API call...\n")

        # Read and analyze addresses
        addresses = read_csv_addresses(csv_path)
        print(f"Loaded {len(addresses)} addresses from {csv_path}")

        # Identify problematic addresses
        problematic = identify_problematic_addresses(addresses)

        # Create mock results for analysis
        results = []
        for addr in addresses:
            is_po_box = 'PO BOX' in addr['address'].upper()
            has_issues = addr in problematic

            results.append(GeocodingResult(
                vanid=addr['id'],
                original_address=addr['address'],
                formatted_address=None,
                latitude=None,
                longitude=None,
                accuracy=None,
                accuracy_type=None,
                source=None,
                match_status='skipped' if is_po_box else 'pending',
                error_message='PO Box - skipped' if is_po_box else None
            ))

        # Print analysis of address quality
        print("\n" + "=" * 60)
        print("ADDRESS QUALITY ANALYSIS (Pre-Geocoding)")
        print("=" * 60)

        print(f"\nTotal addresses: {len(addresses)}")
        print(f"Addresses with potential issues: {len(problematic)}")

        # Group by issue type
        issue_counts = {}
        for addr in problematic:
            for issue in addr.get('issues', []):
                issue_counts[issue] = issue_counts.get(issue, 0) + 1

        print("\nIssues breakdown:")
        for issue, count in sorted(issue_counts.items(), key=lambda x: -x[1]):
            print(f"  - {issue}: {count}")

        # Show sample problematic addresses
        print("\nSample problematic addresses:")
        for addr in problematic[:10]:
            print(f"  VANID {addr['id']}:")
            print(f"    Address: {addr['address']}")
            print(f"    Issues: {', '.join(addr.get('issues', []))}")

        if len(problematic) > 10:
            print(f"  ... and {len(problematic) - 10} more")

        return

    # Initialize geocoder
    geocoder = GeocodioGeocoder(api_key)

    # Read addresses
    print(f"Reading addresses from {csv_path}...")
    addresses = read_csv_addresses(csv_path)
    print(f"Loaded {len(addresses)} addresses")

    # Identify problematic addresses
    problematic = identify_problematic_addresses(addresses)
    print(f"Identified {len(problematic)} potentially problematic addresses")

    # Process all addresses including PO Boxes
    geocodable = addresses
    skipped_results = []

    print(f"Geocoding {len(geocodable)} addresses...")

    # Geocode in batches
    all_results = list(skipped_results)

    for i in range(0, len(geocodable), GeocodioGeocoder.BATCH_SIZE):
        batch = geocodable[i:i + GeocodioGeocoder.BATCH_SIZE]
        print(f"Processing batch {i // GeocodioGeocoder.BATCH_SIZE + 1} ({len(batch)} addresses)...")

        try:
            api_results = geocoder.geocode_batch(batch)

            for addr in batch:
                vanid = addr['id']
                if vanid in api_results:
                    result = geocoder.parse_result(vanid, addr['address'], api_results[vanid])
                else:
                    result = GeocodingResult(
                        vanid=vanid,
                        original_address=addr['address'],
                        formatted_address=None,
                        latitude=None,
                        longitude=None,
                        accuracy=None,
                        accuracy_type=None,
                        source=None,
                        match_status='error',
                        error_message='No result returned from API'
                    )
                all_results.append(result)

        except Exception as e:
            print(f"Error processing batch: {e}")
            for addr in batch:
                all_results.append(GeocodingResult(
                    vanid=addr['id'],
                    original_address=addr['address'],
                    formatted_address=None,
                    latitude=None,
                    longitude=None,
                    accuracy=None,
                    accuracy_type=None,
                    source=None,
                    match_status='error',
                    error_message=str(e)
                ))

        # Rate limiting - be nice to the API
        if i + GeocodioGeocoder.BATCH_SIZE < len(geocodable):
            time.sleep(1)

    # Save results (only if we have successful matches)
    successful = [r for r in all_results if r.match_status == 'matched']
    if successful:
        print(f"Saving results to {output_path}...")
        save_results_to_csv(all_results, output_path)
    else:
        print(f"No successful results - not overwriting {output_path}")

    # Analyze and print results
    analysis = analyze_results(all_results)
    print_analysis(analysis, problematic)

    print(f"\nResults saved to {output_path}")


if __name__ == "__main__":
    main()
