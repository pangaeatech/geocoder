"""
Census Batch Geocoder Proof of Concept

This script geocodes US addresses using the Census Bureau's batch geocoding API.
It transforms input data to the required format, submits batches, and analyzes results.

Census API Documentation:
- https://geocoding.geo.census.gov/geocoder/Geocoding_Services_API.html
- https://www2.census.gov/geo/pdfs/maps-data/data/Census_Geocoder_User_Guide.pdf

Match Types returned by Census API:
- Match: Address was matched (can be exact or non-exact)
- No_Match: Address could not be matched
- Tie: Multiple possible matches found

Match Quality (for matched addresses):
- Exact: Geocoder found an exact match
- Non_Exact: Geocoder found a match but not precisely the same as input
"""

import csv
import io
import os
import sys
import json
import time
import requests
from dataclasses import dataclass, field, asdict
from typing import Optional
from pathlib import Path
from datetime import datetime


# Census Geocoder API endpoint
CENSUS_BATCH_URL = "https://geocoding.geo.census.gov/geocoder/geographies/addressbatch"

# Batch size limit (Census allows up to 10,000)
MAX_BATCH_SIZE = 10000


@dataclass
class GeocodingResult:
    """Represents a single geocoding result from the Census API."""

    # Input fields
    record_id: str
    input_address: str

    # Match status
    match_status: str  # Match, No_Match, Tie
    match_type: Optional[str] = None  # Exact, Non_Exact

    # Output address (standardized)
    matched_address: Optional[str] = None

    # Coordinates
    longitude: Optional[float] = None
    latitude: Optional[float] = None

    # TIGER/Line data
    tigerline_id: Optional[str] = None
    tigerline_side: Optional[str] = None

    # Geography codes
    state_fips: Optional[str] = None
    county_fips: Optional[str] = None
    tract: Optional[str] = None
    block: Optional[str] = None

    # Original input for reference
    original_street: str = ""
    original_city: str = ""
    original_state: str = ""
    original_zip: str = ""

    # Analysis fields
    accuracy_score: int = 0
    issues: list = field(default_factory=list)

    def calculate_accuracy_score(self):
        """
        Calculate an accuracy score based on match type and other factors.

        Score breakdown:
        - Exact match: 100
        - Non-exact match: 70
        - Tie: 30
        - No match: 0

        Deductions:
        - Missing coordinates: -20
        - Missing standardized address: -10
        """
        if self.match_status == "Match":
            if self.match_type == "Exact":
                self.accuracy_score = 100
            else:
                self.accuracy_score = 70
                self.issues.append("Non-exact match - address may have been corrected")
        elif self.match_status == "Tie":
            self.accuracy_score = 30
            self.issues.append("Multiple possible matches - manual review required")
        else:
            self.accuracy_score = 0
            self.issues.append("No match found")

        # Deductions
        if self.match_status == "Match":
            if not self.latitude or not self.longitude:
                self.accuracy_score -= 20
                self.issues.append("Missing coordinates")
            if not self.matched_address:
                self.accuracy_score -= 10
                self.issues.append("Missing standardized address")

        return self.accuracy_score


@dataclass
class BatchResult:
    """Represents results from a batch geocoding operation."""

    total_records: int = 0
    matched_exact: int = 0
    matched_non_exact: int = 0
    ties: int = 0
    no_match: int = 0
    processing_time_seconds: float = 0.0
    results: list = field(default_factory=list)

    @property
    def match_rate(self) -> float:
        """Calculate the overall match rate."""
        if self.total_records == 0:
            return 0.0
        return (self.matched_exact + self.matched_non_exact) / self.total_records * 100

    @property
    def exact_match_rate(self) -> float:
        """Calculate the exact match rate."""
        if self.total_records == 0:
            return 0.0
        return self.matched_exact / self.total_records * 100

    def summary(self) -> dict:
        """Return a summary of the batch results."""
        return {
            "total_records": self.total_records,
            "matched_exact": self.matched_exact,
            "matched_non_exact": self.matched_non_exact,
            "ties": self.ties,
            "no_match": self.no_match,
            "match_rate_percent": round(self.match_rate, 2),
            "exact_match_rate_percent": round(self.exact_match_rate, 2),
            "processing_time_seconds": round(self.processing_time_seconds, 2)
        }


def load_mock_data(filepath: str) -> list[dict]:
    """
    Load and parse the mock LCV data CSV file.

    Expected columns:
    VANID, AddressLine1, AddressLine2, AddressLine3, City, State/Province,
    Zip/Postal, Zip4, CountryCode, CountryName
    """
    records = []

    with open(filepath, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Only include US addresses
            if row.get('CountryCode', '').strip().upper() == 'US':
                records.append(row)

    print(f"Loaded {len(records)} US address records from {filepath}")
    return records


def transform_to_census_format(records: list[dict]) -> str:
    """
    Transform mock data records to Census batch geocoder format.

    Census format: Unique ID, Street address, City, State, ZIP

    Returns CSV string ready for submission.
    """
    output = io.StringIO()
    writer = csv.writer(output)

    for record in records:
        # Combine address lines
        address_parts = []
        for line in ['AddressLine1', 'AddressLine2', 'AddressLine3']:
            value = record.get(line, '').strip()
            if value:
                address_parts.append(value)

        street_address = ' '.join(address_parts)

        # Get other fields
        unique_id = record.get('VANID', '')
        city = record.get('City', '').strip()
        state = record.get('State/Province', '').strip()
        zipcode = record.get('Zip/Postal', '').strip()

        # Write row (Census format: ID, Street, City, State, ZIP)
        writer.writerow([unique_id, street_address, city, state, zipcode])

    return output.getvalue()


def submit_batch(csv_data: str, benchmark: str = "Public_AR_Current",
                 vintage: str = "Current_Current") -> str:
    """
    Submit a batch of addresses to the Census geocoding API.

    Args:
        csv_data: CSV string with addresses in Census format
        benchmark: Benchmark version (default: Public_AR_Current)
        vintage: Vintage for geography lookup (default: Current_Current)

    Returns:
        Raw response text from the API
    """
    files = {
        'addressFile': ('addresses.csv', csv_data, 'text/csv')
    }

    data = {
        'benchmark': benchmark,
        'vintage': vintage
    }

    print(f"Submitting batch to Census API...")
    print(f"  Benchmark: {benchmark}")
    print(f"  Vintage: {vintage}")

    response = requests.post(CENSUS_BATCH_URL, files=files, data=data, timeout=300)
    response.raise_for_status()

    return response.text


def parse_census_response(response_text: str, original_records: list[dict]) -> list[GeocodingResult]:
    """
    Parse the Census batch geocoder response.

    Census output columns:
    1. Record ID
    2. Input Address (as submitted)
    3. Match Status (Match, No_Match, Tie)
    4. Match Type (Exact, Non_Exact) - only present for Match status
    5. Matched Address (standardized)
    6. Coordinates (longitude,latitude)
    7. TIGER/Line ID
    8. TIGER/Line Side
    9. State FIPS
    10. County FIPS
    11. Census Tract
    12. Census Block
    """
    # Create lookup for original records
    original_lookup = {str(r['VANID']): r for r in original_records}

    results = []
    reader = csv.reader(io.StringIO(response_text))

    for row in reader:
        if not row or len(row) < 3:
            continue

        record_id = row[0].strip('"')
        input_address = row[1].strip('"') if len(row) > 1 else ""
        match_status = row[2].strip('"') if len(row) > 2 else "No_Match"

        result = GeocodingResult(
            record_id=record_id,
            input_address=input_address,
            match_status=match_status
        )

        # Parse match type and additional fields based on match status
        if match_status == "Match":
            result.match_type = row[3].strip('"') if len(row) > 3 else None
            result.matched_address = row[4].strip('"') if len(row) > 4 else None

            # Parse coordinates (format: longitude,latitude or separate fields)
            if len(row) > 5:
                coords = row[5].strip('"')
                if ',' in coords:
                    try:
                        lon, lat = coords.split(',')
                        result.longitude = float(lon)
                        result.latitude = float(lat)
                    except (ValueError, IndexError):
                        pass
                else:
                    try:
                        result.longitude = float(coords) if coords else None
                        result.latitude = float(row[6].strip('"')) if len(row) > 6 and row[6].strip('"') else None
                    except ValueError:
                        pass

            # Parse TIGER/Line data
            offset = 7 if result.latitude else 6
            if len(row) > offset:
                result.tigerline_id = row[offset].strip('"') if row[offset].strip('"') else None
            if len(row) > offset + 1:
                result.tigerline_side = row[offset + 1].strip('"') if row[offset + 1].strip('"') else None

            # Parse geography codes
            if len(row) > offset + 2:
                result.state_fips = row[offset + 2].strip('"') if row[offset + 2].strip('"') else None
            if len(row) > offset + 3:
                result.county_fips = row[offset + 3].strip('"') if row[offset + 3].strip('"') else None
            if len(row) > offset + 4:
                result.tract = row[offset + 4].strip('"') if row[offset + 4].strip('"') else None
            if len(row) > offset + 5:
                result.block = row[offset + 5].strip('"') if row[offset + 5].strip('"') else None

        elif match_status == "Tie":
            result.match_type = "Tie"

        # Add original input data for reference
        if record_id in original_lookup:
            orig = original_lookup[record_id]
            address_parts = []
            for line in ['AddressLine1', 'AddressLine2', 'AddressLine3']:
                value = orig.get(line, '').strip()
                if value:
                    address_parts.append(value)

            result.original_street = ' '.join(address_parts)
            result.original_city = orig.get('City', '').strip()
            result.original_state = orig.get('State/Province', '').strip()
            result.original_zip = orig.get('Zip/Postal', '').strip()

        # Calculate accuracy score
        result.calculate_accuracy_score()

        results.append(result)

    return results


def analyze_results(results: list[GeocodingResult]) -> BatchResult:
    """Analyze geocoding results and generate statistics."""
    batch_result = BatchResult(
        total_records=len(results),
        results=results
    )

    for result in results:
        if result.match_status == "Match":
            if result.match_type == "Exact":
                batch_result.matched_exact += 1
            else:
                batch_result.matched_non_exact += 1
        elif result.match_status == "Tie":
            batch_result.ties += 1
        else:
            batch_result.no_match += 1

    return batch_result


def identify_address_issues(results: list[GeocodingResult]) -> dict:
    """
    Identify common address issues from non-matching or non-exact results.

    Returns a dictionary categorizing different types of issues.
    """
    issues = {
        "po_boxes": [],
        "missing_street_number": [],
        "incomplete_address": [],
        "standardization_corrections": [],
        "no_match_addresses": [],
        "ties": []
    }

    for result in results:
        original_street = result.original_street.upper()

        # Check for PO Boxes
        if any(po in original_street for po in ['PO BOX', 'P.O. BOX', 'P O BOX', 'POST OFFICE']):
            issues["po_boxes"].append({
                "id": result.record_id,
                "address": result.original_street,
                "city": result.original_city,
                "state": result.original_state
            })

        # Check for missing street number (address starts with non-digit)
        elif original_street and not original_street[0].isdigit():
            issues["missing_street_number"].append({
                "id": result.record_id,
                "address": result.original_street
            })

        # Categorize by match status
        if result.match_status == "No_Match":
            issues["no_match_addresses"].append({
                "id": result.record_id,
                "input_address": f"{result.original_street}, {result.original_city}, {result.original_state} {result.original_zip}",
                "issues": result.issues
            })

        elif result.match_status == "Tie":
            issues["ties"].append({
                "id": result.record_id,
                "input_address": f"{result.original_street}, {result.original_city}, {result.original_state} {result.original_zip}"
            })

        elif result.match_type == "Non_Exact" and result.matched_address:
            # Track what was corrected
            issues["standardization_corrections"].append({
                "id": result.record_id,
                "original": f"{result.original_street}, {result.original_city}, {result.original_state} {result.original_zip}",
                "standardized": result.matched_address
            })

    return issues


def save_results(results: list[GeocodingResult], batch_result: BatchResult,
                 issues: dict, output_dir: str = "."):
    """Save geocoding results to CSV and JSON files."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Save detailed results to CSV
    csv_path = Path(output_dir) / f"census_results_{timestamp}.csv"
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            'record_id', 'match_status', 'match_type', 'accuracy_score',
            'original_address', 'matched_address',
            'latitude', 'longitude',
            'state_fips', 'county_fips', 'tract', 'block',
            'issues'
        ])

        for result in results:
            original_addr = f"{result.original_street}, {result.original_city}, {result.original_state} {result.original_zip}"
            writer.writerow([
                result.record_id,
                result.match_status,
                result.match_type or '',
                result.accuracy_score,
                original_addr,
                result.matched_address or '',
                result.latitude or '',
                result.longitude or '',
                result.state_fips or '',
                result.county_fips or '',
                result.tract or '',
                result.block or '',
                '; '.join(result.issues) if result.issues else ''
            ])

    print(f"\nResults saved to: {csv_path}")

    # Save full results to JSON
    json_path = Path(output_dir) / f"census_results_{timestamp}.json"
    output_data = {
        "summary": batch_result.summary(),
        "issues_analysis": {
            "po_boxes_count": len(issues["po_boxes"]),
            "missing_street_number_count": len(issues["missing_street_number"]),
            "no_match_count": len(issues["no_match_addresses"]),
            "ties_count": len(issues["ties"]),
            "standardization_corrections_count": len(issues["standardization_corrections"])
        },
        "detailed_issues": issues,
        "results": [asdict(r) for r in results]
    }

    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2)

    print(f"Full results saved to: {json_path}")

    return csv_path, json_path


def generate_report(batch_result: BatchResult, issues: dict) -> str:
    """Generate a human-readable analysis report."""
    report = []
    report.append("=" * 70)
    report.append("CENSUS BATCH GEOCODING - PROOF OF CONCEPT REPORT")
    report.append("=" * 70)
    report.append("")

    # Summary statistics
    report.append("SUMMARY STATISTICS")
    report.append("-" * 40)
    report.append(f"Total Records Processed: {batch_result.total_records}")
    report.append(f"Processing Time: {batch_result.processing_time_seconds:.2f} seconds")
    report.append("")

    # Match breakdown
    report.append("MATCH BREAKDOWN")
    report.append("-" * 40)
    report.append(f"Exact Matches:     {batch_result.matched_exact:>6} ({batch_result.exact_match_rate:.1f}%)")
    report.append(f"Non-Exact Matches: {batch_result.matched_non_exact:>6} ({batch_result.matched_non_exact/batch_result.total_records*100:.1f}%)")
    report.append(f"Ties:              {batch_result.ties:>6} ({batch_result.ties/batch_result.total_records*100:.1f}%)")
    report.append(f"No Match:          {batch_result.no_match:>6} ({batch_result.no_match/batch_result.total_records*100:.1f}%)")
    report.append("-" * 40)
    report.append(f"OVERALL MATCH RATE: {batch_result.match_rate:.1f}%")
    report.append("")

    # Accuracy assessment
    report.append("ACCURACY ASSESSMENT (Requirement 3)")
    report.append("-" * 40)
    report.append("The Census Geocoder provides clear accuracy feedback through:")
    report.append("")
    report.append("1. MATCH STATUS:")
    report.append("   - Match: Address was successfully geocoded")
    report.append("   - No_Match: Address could not be matched")
    report.append("   - Tie: Multiple possible matches exist")
    report.append("")
    report.append("2. MATCH TYPE (for matched addresses):")
    report.append("   - Exact: Perfect match to TIGER/Line database")
    report.append("   - Non_Exact: Match found but with corrections applied")
    report.append("")
    report.append("3. STANDARDIZED ADDRESS:")
    report.append("   - Returns the official USPS-standardized address format")
    report.append("   - Allows comparison with original input to see corrections")
    report.append("")

    # Address standardization (Requirement 2)
    report.append("ADDRESS STANDARDIZATION (Requirement 2)")
    report.append("-" * 40)
    report.append(f"Addresses with standardization corrections: {len(issues['standardization_corrections'])}")
    if issues['standardization_corrections'][:5]:
        report.append("")
        report.append("Example corrections:")
        for i, correction in enumerate(issues['standardization_corrections'][:5], 1):
            report.append(f"  {i}. Original:     {correction['original']}")
            report.append(f"     Standardized: {correction['standardized']}")
            report.append("")

    # Issue analysis
    report.append("ADDRESS ISSUES IDENTIFIED")
    report.append("-" * 40)
    report.append(f"PO Box addresses (cannot be geocoded):    {len(issues['po_boxes'])}")
    report.append(f"Missing street numbers:                   {len(issues['missing_street_number'])}")
    report.append(f"Total unmatched addresses:                {len(issues['no_match_addresses'])}")
    report.append(f"Addresses with ties (need manual review): {len(issues['ties'])}")
    report.append("")

    # Sample of no-match addresses
    if issues['no_match_addresses'][:10]:
        report.append("Sample of unmatched addresses:")
        for addr in issues['no_match_addresses'][:10]:
            report.append(f"  - {addr['input_address']}")
        report.append("")

    # Recommendations
    report.append("RECOMMENDATIONS")
    report.append("-" * 40)
    report.append("1. Exact matches (score 100): Can be used directly with high confidence")
    report.append("2. Non-exact matches (score 70): Review standardized address vs original")
    report.append("3. Ties (score 30): Require manual review to select correct match")
    report.append("4. No matches (score 0): Need address correction or alternative geocoder")
    report.append("")
    report.append("THRESHOLD RECOMMENDATIONS:")
    report.append("- Score >= 70: Acceptable for automated processing")
    report.append("- Score 30-69: Flag for review")
    report.append("- Score < 30: Requires manual intervention or alternate service")
    report.append("")

    # Census API notes
    report.append("CENSUS API NOTES")
    report.append("-" * 40)
    report.append("- Batch size limit: 10,000 records")
    report.append("- For 1M records: 100 batches required")
    report.append("- Cost: FREE (no usage fees)")
    report.append("- Rate limits: Reasonable for batch processing")
    report.append("- Coverage: US addresses only (including PR and territories)")
    report.append("")
    report.append("=" * 70)

    return "\n".join(report)


def main():
    """Main entry point for the Census geocoding proof of concept."""
    print("Census Batch Geocoding - Proof of Concept")
    print("=" * 50)

    # Configuration
    input_file = "Mock LCV Data.csv"
    output_dir = "."

    # Check if input file exists
    if not os.path.exists(input_file):
        print(f"Error: Input file not found: {input_file}")
        sys.exit(1)

    # Step 1: Load mock data
    print("\n[1/5] Loading mock data...")
    records = load_mock_data(input_file)

    if not records:
        print("No US records found in input file.")
        sys.exit(1)

    # Step 2: Transform to Census format
    print("\n[2/5] Transforming data to Census batch format...")
    census_csv = transform_to_census_format(records)

    # Save the transformed input for reference
    input_path = Path(output_dir) / "census_input_batch.csv"
    with open(input_path, 'w', encoding='utf-8') as f:
        f.write(census_csv)
    print(f"Census-formatted input saved to: {input_path}")

    # Step 3: Submit to Census API
    print("\n[3/5] Submitting batch to Census Geocoding API...")
    start_time = time.time()

    try:
        response_text = submit_batch(census_csv)
        processing_time = time.time() - start_time
        print(f"Batch processed in {processing_time:.2f} seconds")

        # Save raw response
        raw_response_path = Path(output_dir) / "census_raw_response.csv"
        with open(raw_response_path, 'w', encoding='utf-8') as f:
            f.write(response_text)
        print(f"Raw response saved to: {raw_response_path}")

    except requests.exceptions.RequestException as e:
        print(f"Error submitting batch: {e}")
        sys.exit(1)

    # Step 4: Parse and analyze results
    print("\n[4/5] Parsing and analyzing results...")
    results = parse_census_response(response_text, records)
    batch_result = analyze_results(results)
    batch_result.processing_time_seconds = processing_time
    issues = identify_address_issues(results)

    # Step 5: Generate output
    print("\n[5/5] Generating output files and report...")
    save_results(results, batch_result, issues, output_dir)

    report = generate_report(batch_result, issues)

    # Save report
    report_path = Path(output_dir) / "census_analysis_report.txt"
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report)
    print(f"Analysis report saved to: {report_path}")

    # Print summary to console
    print("\n" + report)

    return batch_result


if __name__ == "__main__":
    main()
