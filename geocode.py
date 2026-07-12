"""
Google Geocoding API Proof of Concept

This script geocodes addresses from a CSV file using Google's Geocoding API
and provides accuracy feedback for each result.
"""

import csv
import json
import os
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

API_KEY = os.getenv("GOOGLE_GEOCODING_API_KEY")
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"

# Rate limiting: Google allows 50 QPS, but we'll be conservative
REQUESTS_PER_SECOND = 10
REQUEST_DELAY = 1.0 / REQUESTS_PER_SECOND


@dataclass
class GeocodingResult:
    """Stores the result of a geocoding request."""
    vanid: str
    original_address: str

    # Geocoding results
    formatted_address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    # Accuracy indicators
    location_type: Optional[str] = None  # ROOFTOP, RANGE_INTERPOLATED, GEOMETRIC_CENTER, APPROXIMATE
    result_type: Optional[str] = None    # street_address, route, locality, etc.
    partial_match: bool = False          # True if Google only found a partial match

    # Standardized address components
    street_number: Optional[str] = None
    route: Optional[str] = None          # Street name
    locality: Optional[str] = None       # City
    administrative_area_level_1: Optional[str] = None  # State
    administrative_area_level_2: Optional[str] = None  # County
    postal_code: Optional[str] = None
    postal_code_suffix: Optional[str] = None
    country: Optional[str] = None

    # Status
    status: str = ""                     # OK, ZERO_RESULTS, OVER_QUERY_LIMIT, etc.
    error_message: Optional[str] = None

    # Computed accuracy score (0-100)
    accuracy_score: int = 0
    accuracy_notes: str = ""

    def compute_accuracy_score(self):
        """
        Compute an accuracy score based on location_type and other factors.

        Scoring:
        - ROOFTOP: 100 (exact location)
        - RANGE_INTERPOLATED: 80 (interpolated between two precise points)
        - GEOMETRIC_CENTER: 50 (center of a region like a route or neighborhood)
        - APPROXIMATE: 20 (approximate location, often a city/zip centroid)

        Deductions:
        - Partial match: -20 points
        - Missing street number: -10 points
        """
        notes = []

        if self.status != "OK":
            self.accuracy_score = 0
            self.accuracy_notes = f"Geocoding failed: {self.status}"
            return

        # Base score from location type
        location_type_scores = {
            "ROOFTOP": 100,
            "RANGE_INTERPOLATED": 80,
            "GEOMETRIC_CENTER": 50,
            "APPROXIMATE": 20,
        }
        score = location_type_scores.get(self.location_type, 0)
        notes.append(f"Location type: {self.location_type}")

        # Deduction for partial match
        if self.partial_match:
            score -= 20
            notes.append("Partial match (address may be incomplete/incorrect)")

        # Deduction for missing street number
        if not self.street_number:
            score -= 10
            notes.append("No street number in result")

        # Result type context
        if self.result_type:
            if "street_address" in self.result_type:
                notes.append("Result type: street_address (most precise)")
            elif "route" in self.result_type:
                notes.append("Result type: route (street-level)")
            elif "locality" in self.result_type:
                notes.append("Result type: locality (city-level only)")
            elif "postal_code" in self.result_type:
                notes.append("Result type: postal_code (zip code centroid)")

        self.accuracy_score = max(0, score)
        self.accuracy_notes = "; ".join(notes)


def build_address_string(row: dict) -> str:
    """Build a geocodable address string from CSV row data."""
    parts = []

    # Address lines
    for key in ["AddressLine1", "AddressLine2", "AddressLine3"]:
        if row.get(key) and row[key].strip():
            parts.append(row[key].strip())

    # City
    if row.get("City") and row["City"].strip():
        parts.append(row["City"].strip())

    # State
    if row.get("State/Province") and row["State/Province"].strip():
        parts.append(row["State/Province"].strip())

    # Zip code (combine Zip and Zip4 if available)
    zip_code = ""
    if row.get("Zip/Postal") and row["Zip/Postal"].strip():
        zip_code = row["Zip/Postal"].strip()
        if row.get("Zip4") and row["Zip4"].strip():
            zip_code += "-" + row["Zip4"].strip()
        parts.append(zip_code)

    # Country
    if row.get("CountryName") and row["CountryName"].strip():
        parts.append(row["CountryName"].strip())

    return ", ".join(parts)


def geocode_address(address: str, vanid: str) -> GeocodingResult:
    """
    Geocode a single address using the Google Geocoding API.

    Returns a GeocodingResult with all available data and accuracy metrics.
    """
    result = GeocodingResult(vanid=vanid, original_address=address)

    if not API_KEY:
        result.status = "ERROR"
        result.error_message = "GOOGLE_GEOCODING_API_KEY not set"
        return result

    params = {
        "address": address,
        "key": API_KEY,
    }

    try:
        response = requests.get(GEOCODE_URL, params=params, timeout=10)
        data = response.json()

        result.status = data.get("status", "UNKNOWN")

        if result.status == "OK" and data.get("results"):
            first_result = data["results"][0]

            # Formatted address
            result.formatted_address = first_result.get("formatted_address")

            # Location
            geometry = first_result.get("geometry", {})
            location = geometry.get("location", {})
            result.latitude = location.get("lat")
            result.longitude = location.get("lng")
            result.location_type = geometry.get("location_type")

            # Result types
            result.result_type = ",".join(first_result.get("types", []))

            # Partial match flag
            result.partial_match = first_result.get("partial_match", False)

            # Extract address components
            for component in first_result.get("address_components", []):
                types = component.get("types", [])
                short_name = component.get("short_name", "")

                if "street_number" in types:
                    result.street_number = short_name
                elif "route" in types:
                    result.route = short_name
                elif "locality" in types:
                    result.locality = short_name
                elif "administrative_area_level_1" in types:
                    result.administrative_area_level_1 = short_name
                elif "administrative_area_level_2" in types:
                    result.administrative_area_level_2 = short_name
                elif "postal_code" in types:
                    result.postal_code = short_name
                elif "postal_code_suffix" in types:
                    result.postal_code_suffix = short_name
                elif "country" in types:
                    result.country = short_name

        elif result.status == "ZERO_RESULTS":
            result.error_message = "No results found for this address"

        elif result.status == "OVER_QUERY_LIMIT":
            result.error_message = "API quota exceeded"

        elif result.status == "REQUEST_DENIED":
            result.error_message = data.get("error_message", "Request denied - check API key")

        elif result.status == "INVALID_REQUEST":
            result.error_message = data.get("error_message", "Invalid request")

    except requests.exceptions.Timeout:
        result.status = "ERROR"
        result.error_message = "Request timed out"
    except requests.exceptions.RequestException as e:
        result.status = "ERROR"
        result.error_message = str(e)
    except json.JSONDecodeError:
        result.status = "ERROR"
        result.error_message = "Invalid JSON response"

    # Compute accuracy score
    result.compute_accuracy_score()

    return result


def process_csv(input_file: str, output_file: str, limit: Optional[int] = None):
    """
    Process a CSV file of addresses and geocode each one.

    Args:
        input_file: Path to input CSV with address data
        output_file: Path to output CSV with geocoding results
        limit: Optional limit on number of records to process
    """
    results = []

    print(f"Reading addresses from: {input_file}")

    with open(input_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    total = len(rows) if limit is None else min(len(rows), limit)
    print(f"Processing {total} addresses...")

    for i, row in enumerate(rows[:total]):
        vanid = row.get("VANID", f"row_{i}")
        address = build_address_string(row)

        print(f"[{i+1}/{total}] Geocoding VANID {vanid}: {address[:60]}...")

        result = geocode_address(address, vanid)
        results.append(result)

        # Show accuracy info
        if result.status == "OK":
            print(f"         -> {result.location_type} | Score: {result.accuracy_score}")
        else:
            print(f"         -> {result.status}: {result.error_message}")

        # Rate limiting
        if i < total - 1:
            time.sleep(REQUEST_DELAY)

    # Write results to CSV
    print(f"\nWriting results to: {output_file}")

    fieldnames = [
        "vanid", "original_address", "formatted_address",
        "latitude", "longitude", "location_type", "result_type",
        "partial_match", "accuracy_score", "accuracy_notes",
        "street_number", "route", "locality",
        "administrative_area_level_1", "administrative_area_level_2",
        "postal_code", "postal_code_suffix", "country",
        "status", "error_message"
    ]

    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for result in results:
            writer.writerow(asdict(result))

    # Print summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)

    ok_results = [r for r in results if r.status == "OK"]
    print(f"Total processed: {len(results)}")
    print(f"Successful: {len(ok_results)}")
    print(f"Failed: {len(results) - len(ok_results)}")

    if ok_results:
        # Location type breakdown
        print("\nLocation Type Distribution:")
        location_types = {}
        for r in ok_results:
            lt = r.location_type or "UNKNOWN"
            location_types[lt] = location_types.get(lt, 0) + 1
        for lt, count in sorted(location_types.items(), key=lambda x: -x[1]):
            pct = (count / len(ok_results)) * 100
            print(f"  {lt}: {count} ({pct:.1f}%)")

        # Partial matches
        partial = sum(1 for r in ok_results if r.partial_match)
        print(f"\nPartial matches: {partial} ({(partial/len(ok_results))*100:.1f}%)")

        # Accuracy score distribution
        print("\nAccuracy Score Distribution:")
        score_buckets = {"90-100": 0, "70-89": 0, "50-69": 0, "20-49": 0, "0-19": 0}
        for r in ok_results:
            if r.accuracy_score >= 90:
                score_buckets["90-100"] += 1
            elif r.accuracy_score >= 70:
                score_buckets["70-89"] += 1
            elif r.accuracy_score >= 50:
                score_buckets["50-69"] += 1
            elif r.accuracy_score >= 20:
                score_buckets["20-49"] += 1
            else:
                score_buckets["0-19"] += 1
        for bucket, count in score_buckets.items():
            pct = (count / len(ok_results)) * 100
            print(f"  {bucket}: {count} ({pct:.1f}%)")

        avg_score = sum(r.accuracy_score for r in ok_results) / len(ok_results)
        print(f"\nAverage accuracy score: {avg_score:.1f}")


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Geocode addresses using Google Geocoding API")
    parser.add_argument("--input", "-i", default="Mock LCV Data.csv",
                        help="Input CSV file with addresses")
    parser.add_argument("--output", "-o", default=None,
                        help="Output CSV file for results (default: geocoding_results_TIMESTAMP.csv)")
    parser.add_argument("--limit", "-l", type=int, default=None,
                        help="Limit number of records to process (for testing)")

    args = parser.parse_args()

    # Default output filename with timestamp
    if args.output is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output = f"geocoding_results_{timestamp}.csv"

    # Check for API key
    if not API_KEY:
        print("ERROR: GOOGLE_GEOCODING_API_KEY not set")
        print("Please create a .env file with your API key:")
        print("  GOOGLE_GEOCODING_API_KEY=your_key_here")
        return 1

    # Check input file exists
    if not Path(args.input).exists():
        print(f"ERROR: Input file not found: {args.input}")
        return 1

    process_csv(args.input, args.output, args.limit)
    return 0


if __name__ == "__main__":
    exit(main())
