"""
Analysis script for geocoding results.
Examines accuracy, identifies patterns in failures, and generates a report.
"""

import json
import csv
from collections import defaultdict
from math import radians, sin, cos, sqrt, atan2


def load_results(json_file: str) -> list:
    """Load geocoding results from JSON file."""
    with open(json_file, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_original_data(csv_file: str) -> dict:
    """Load original CSV data as dict keyed by VANID."""
    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        return {row['VANID']: row for row in reader}


def analyze_no_matches(results: list) -> dict:
    """Analyze patterns in NO_MATCH results."""
    no_matches = [r for r in results if r['match_type'] == 'NO_MATCH']

    patterns = {
        'apartment_unit': 0,
        'suite': 0,
        'abbreviated_street': 0,
        'short_city_name': 0,
        'unusual_characters': 0,
        'missing_zip': 0,
        'lot_number': 0,
        'non_standard_address': 0,
        'other': 0
    }

    examples = defaultdict(list)

    for r in no_matches:
        addr = r['input_address']
        categorized = False

        # Check for apartment/unit indicators
        if any(x in addr.upper() for x in ['APT', 'UNIT', '# ', '#', 'STE', 'SUITE', 'ROOM', 'RM ']):
            patterns['apartment_unit'] += 1
            examples['apartment_unit'].append(addr)
            categorized = True

        # Check for abbreviated street types that might cause issues
        if any(x in addr.upper() for x in ['HWY', 'BLVD', 'CIR', 'CT ', 'LN ', 'TRL', 'XING']):
            if not categorized:
                patterns['abbreviated_street'] += 1
                examples['abbreviated_street'].append(addr)
                categorized = True

        # Check for lot numbers
        if 'LOT' in addr.upper():
            patterns['lot_number'] += 1
            examples['lot_number'].append(addr)
            categorized = True

        # Check for shortened city names
        if any(x in addr for x in ['Mt ', 'Mt. ', 'St ', 'N ', 'S ', 'E ', 'W ']):
            if not categorized:
                patterns['short_city_name'] += 1
                examples['short_city_name'].append(addr)
                categorized = True

        # Check for unusual characters
        if any(x in addr for x in ['/', '#', '&', '@']):
            if not categorized:
                patterns['unusual_characters'] += 1
                examples['unusual_characters'].append(addr)
                categorized = True

        # Non-standard addresses (like road numbers, county roads, etc.)
        if any(x in addr.upper() for x in ['ROAD S-', 'COUNTY ROAD', 'STATE ROAD', 'PRIVATE DR']):
            patterns['non_standard_address'] += 1
            examples['non_standard_address'].append(addr)
            categorized = True

        if not categorized:
            patterns['other'] += 1
            examples['other'].append(addr)

    return {'patterns': patterns, 'examples': examples, 'total': len(no_matches)}


def analyze_match_quality(results: list) -> dict:
    """Analyze match quality for successful geocodes."""
    matched = [r for r in results if r['lat'] is not None]

    quality_stats = {
        'total_matched': len(matched),
        'by_type': defaultdict(int),
        'confidence_distribution': {
            '90-100': 0,
            '70-89': 0,
            '50-69': 0,
            '30-49': 0,
            '0-29': 0
        },
        'osm_class_distribution': defaultdict(int),
        'osm_type_distribution': defaultdict(int)
    }

    for r in matched:
        quality_stats['by_type'][r['match_type']] += 1
        quality_stats['osm_class_distribution'][r['osm_class']] += 1
        quality_stats['osm_type_distribution'][r['osm_type']] += 1

        conf = r['confidence']
        if conf >= 90:
            quality_stats['confidence_distribution']['90-100'] += 1
        elif conf >= 70:
            quality_stats['confidence_distribution']['70-89'] += 1
        elif conf >= 50:
            quality_stats['confidence_distribution']['50-69'] += 1
        elif conf >= 30:
            quality_stats['confidence_distribution']['30-49'] += 1
        else:
            quality_stats['confidence_distribution']['0-29'] += 1

    return quality_stats


def check_address_standardization(results: list, original_data: dict) -> list:
    """Check how addresses were standardized/corrected."""
    standardization_examples = []

    for r in results:
        if r['address_details'] and r['lat'] is not None:
            vanid = r['vanid']
            orig = original_data.get(vanid, {})

            # Compare original city with returned city
            orig_city = orig.get('City', '').strip().upper()
            returned_city = ''
            if r['address_details']:
                returned_city = r['address_details'].get('city', '') or r['address_details'].get('town', '') or ''
                returned_city = returned_city.upper()

            orig_state = orig.get('State/Province', '').strip().upper()
            returned_state = r['address_details'].get('state', '').upper() if r['address_details'] else ''

            # Check for mismatches
            if orig_city and returned_city and orig_city != returned_city:
                standardization_examples.append({
                    'vanid': vanid,
                    'type': 'city_mismatch',
                    'original': orig_city,
                    'returned': returned_city,
                    'input_address': r['input_address'],
                    'display_name': r['display_name']
                })

            if orig_state and returned_state:
                # Normalize state comparison
                orig_state_norm = orig_state.replace('SOUTH CAROLINA', 'SC').strip()
                returned_state_norm = 'SC' if 'SOUTH CAROLINA' in returned_state else returned_state

                if orig_state_norm != returned_state_norm and 'SC' not in orig_state_norm:
                    standardization_examples.append({
                        'vanid': vanid,
                        'type': 'state_mismatch',
                        'original': orig_state,
                        'returned': returned_state,
                        'input_address': r['input_address'],
                        'display_name': r['display_name']
                    })

    return standardization_examples


def generate_report(results: list, original_data: dict) -> str:
    """Generate a comprehensive analysis report."""
    total = len(results)

    # Basic statistics
    match_types = defaultdict(int)
    for r in results:
        match_types[r['match_type']] += 1

    # Analyze no matches
    no_match_analysis = analyze_no_matches(results)

    # Analyze match quality
    quality_analysis = analyze_match_quality(results)

    # Check standardization
    standardization_issues = check_address_standardization(results, original_data)

    # Build report
    report = []
    report.append("=" * 70)
    report.append("OPENSTREETMAP NOMINATIM GEOCODING - ANALYSIS REPORT")
    report.append("=" * 70)
    report.append("")

    # Summary
    report.append("## SUMMARY")
    report.append("-" * 40)
    report.append(f"Total addresses processed: {total}")
    report.append("")
    report.append("Match Type Distribution:")
    for mt, count in sorted(match_types.items(), key=lambda x: -x[1]):
        pct = (count / total) * 100
        report.append(f"  {mt:25s}: {count:4d} ({pct:5.1f}%)")

    # Calculate geocoding success rate (excluding PO Boxes)
    non_po_boxes = total - match_types.get('SKIPPED', 0)
    successful = match_types.get('ROOFTOP', 0) + match_types.get('RANGE_INTERPOLATED', 0)
    if non_po_boxes > 0:
        success_rate = (successful / non_po_boxes) * 100
        report.append("")
        report.append(f"Geocoding Success Rate (excl. PO Boxes): {success_rate:.1f}%")
        report.append(f"  - High precision (ROOFTOP): {match_types.get('ROOFTOP', 0)}")
        report.append(f"  - Medium precision (RANGE_INTERPOLATED): {match_types.get('RANGE_INTERPOLATED', 0)}")

    # Confidence Analysis
    report.append("")
    report.append("## CONFIDENCE ANALYSIS")
    report.append("-" * 40)
    report.append("Confidence Distribution (matched addresses only):")
    for range_name, count in quality_analysis['confidence_distribution'].items():
        if quality_analysis['total_matched'] > 0:
            pct = (count / quality_analysis['total_matched']) * 100
            report.append(f"  {range_name}%: {count:4d} ({pct:5.1f}%)")

    # OSM Type Analysis
    report.append("")
    report.append("## OSM CLASSIFICATION")
    report.append("-" * 40)
    report.append("OSM Class Distribution (top 5):")
    sorted_classes = sorted(quality_analysis['osm_class_distribution'].items(), key=lambda x: -x[1])[:5]
    for cls, count in sorted_classes:
        report.append(f"  {cls}: {count}")

    report.append("")
    report.append("OSM Type Distribution (top 5):")
    sorted_types = sorted(quality_analysis['osm_type_distribution'].items(), key=lambda x: -x[1])[:5]
    for typ, count in sorted_types:
        report.append(f"  {typ}: {count}")

    # No Match Analysis
    report.append("")
    report.append("## NO MATCH ANALYSIS")
    report.append("-" * 40)
    report.append(f"Total NO_MATCH results: {no_match_analysis['total']}")
    report.append("")
    report.append("Patterns identified in failed geocodes:")
    for pattern, count in sorted(no_match_analysis['patterns'].items(), key=lambda x: -x[1]):
        if count > 0:
            report.append(f"  {pattern:25s}: {count:4d}")

    # Examples of each pattern
    report.append("")
    report.append("## EXAMPLES OF FAILED GEOCODES")
    report.append("-" * 40)
    for pattern, examples in no_match_analysis['examples'].items():
        if examples:
            report.append(f"\n{pattern.upper().replace('_', ' ')} ({len(examples)} cases):")
            for ex in examples[:3]:  # Show first 3 examples
                report.append(f"  - {ex[:70]}...")

    # Address Standardization Issues
    report.append("")
    report.append("## ADDRESS STANDARDIZATION NOTES")
    report.append("-" * 40)
    if standardization_issues:
        city_mismatches = [s for s in standardization_issues if s['type'] == 'city_mismatch']
        state_mismatches = [s for s in standardization_issues if s['type'] == 'state_mismatch']

        report.append(f"City name discrepancies found: {len(city_mismatches)}")
        if city_mismatches:
            report.append("Examples:")
            for ex in city_mismatches[:5]:
                report.append(f"  - Input: {ex['original']} -> Returned: {ex['returned']}")

        report.append("")
        report.append(f"State discrepancies found: {len(state_mismatches)}")
        if state_mismatches:
            report.append("Examples:")
            for ex in state_mismatches[:5]:
                report.append(f"  - Input: {ex['original']} -> Returned: {ex['returned']}")
    else:
        report.append("No significant standardization issues detected.")

    # Accuracy Feedback Recommendations
    report.append("")
    report.append("## ACCURACY FEEDBACK RECOMMENDATIONS")
    report.append("-" * 40)
    report.append("""
Based on the analysis, the following accuracy indicators are recommended:

1. HIGH CONFIDENCE (90%+):
   - OSM type: 'house', 'building', 'apartments'
   - OSM class: 'place', 'building'
   - These represent building-level geocodes

2. MEDIUM CONFIDENCE (70-89%):
   - OSM type: 'residential', 'road', 'street'
   - OSM class: 'highway'
   - These are street-level interpolations

3. LOW CONFIDENCE (30-69%):
   - OSM type: 'postcode', 'suburb', 'neighbourhood'
   - These represent area-level geocodes

4. VERY LOW CONFIDENCE (<30%):
   - OSM type: 'city', 'town', 'administrative'
   - OSM class: 'boundary'
   - These are city/county centroids, NOT address-level

5. NO MATCH:
   - Address not found in OSM database
   - Common causes: new subdivisions, apartment complexes,
     unusual street naming, PO Boxes
""")

    # Issues identified
    report.append("")
    report.append("## ISSUES & LIMITATIONS IDENTIFIED")
    report.append("-" * 40)
    report.append("""
1. HIGH NO_MATCH RATE (39.3%):
   - Many SC addresses not in OSM database
   - Newer subdivisions/developments missing
   - Rural addresses poorly covered

2. APARTMENT/UNIT ADDRESSES:
   - OSM doesn't handle apartment numbers well
   - Often returns street-level instead of unit-level

3. RATE LIMITING:
   - 1 request/second makes bulk geocoding slow
   - 718 addresses took ~17 minutes
   - 1 million addresses would take ~11.5 days

4. NO BATCH API:
   - Each address requires separate HTTP request
   - No bulk/batch endpoint available

5. DATA QUALITY VARIES:
   - Urban areas better covered than rural
   - Some streets missing house numbers
""")

    return "\n".join(report)


if __name__ == "__main__":
    results = load_results("geocoding_results.json")
    original_data = load_original_data("Mock LCV Data.csv")

    report = generate_report(results, original_data)

    # Print report
    print(report)

    # Save report to file
    with open("geocoding_analysis_report.txt", "w", encoding="utf-8") as f:
        f.write(report)

    print("\n\nReport saved to: geocoding_analysis_report.txt")
