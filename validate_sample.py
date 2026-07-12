"""
Validate geocoding accuracy by reverse geocoding a sample of results.

This script takes the geocoding results, reverse geocodes a sample of them,
and compares the original address to what Google returns for those coordinates.
"""

import csv
import os
import random
import time
from difflib import SequenceMatcher

import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("GOOGLE_GEOCODING_API_KEY")
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"


def reverse_geocode(lat: float, lng: float) -> dict:
    """Reverse geocode coordinates to get address."""
    params = {
        "latlng": f"{lat},{lng}",
        "key": API_KEY,
    }
    response = requests.get(GEOCODE_URL, params=params, timeout=10)
    return response.json()


def similarity(a: str, b: str) -> float:
    """Calculate string similarity (0-1)."""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def validate_sample(input_file: str, sample_size: int = 20):
    """Validate a random sample of ROOFTOP results."""

    with open(input_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        results = [r for r in reader if r.get("location_type") == "ROOFTOP"]

    # Sample random ROOFTOP results
    sample = random.sample(results, min(sample_size, len(results)))

    print(f"Validating {len(sample)} ROOFTOP results via reverse geocoding...")
    print("=" * 80)

    validations = []

    for i, row in enumerate(sample):
        vanid = row["vanid"]
        original = row["original_address"]
        forward_result = row["formatted_address"]
        lat = float(row["latitude"])
        lng = float(row["longitude"])

        print(f"\n[{i+1}/{len(sample)}] VANID {vanid}")
        print(f"  Original:    {original[:70]}")
        print(f"  Forward:     {forward_result[:70]}")

        # Reverse geocode
        reverse_data = reverse_geocode(lat, lng)

        if reverse_data.get("status") == "OK" and reverse_data.get("results"):
            reverse_result = reverse_data["results"][0].get("formatted_address", "")
            reverse_type = reverse_data["results"][0].get("geometry", {}).get("location_type", "")

            print(f"  Reverse:     {reverse_result[:70]}")

            # Compare forward and reverse results
            sim_score = similarity(forward_result, reverse_result)
            match_status = "MATCH" if sim_score > 0.9 else "CLOSE" if sim_score > 0.7 else "DIFFERS"

            print(f"  Similarity:  {sim_score:.1%} ({match_status})")

            validations.append({
                "vanid": vanid,
                "original": original,
                "forward": forward_result,
                "reverse": reverse_result,
                "similarity": sim_score,
                "match_status": match_status
            })
        else:
            print(f"  Reverse:     FAILED - {reverse_data.get('status')}")
            validations.append({
                "vanid": vanid,
                "original": original,
                "forward": forward_result,
                "reverse": "FAILED",
                "similarity": 0,
                "match_status": "ERROR"
            })

        time.sleep(0.1)  # Rate limiting

    # Summary
    print("\n" + "=" * 80)
    print("VALIDATION SUMMARY")
    print("=" * 80)

    matches = sum(1 for v in validations if v["match_status"] == "MATCH")
    close = sum(1 for v in validations if v["match_status"] == "CLOSE")
    differs = sum(1 for v in validations if v["match_status"] == "DIFFERS")
    errors = sum(1 for v in validations if v["match_status"] == "ERROR")

    print(f"MATCH (>90% similar):   {matches} ({matches/len(validations)*100:.1f}%)")
    print(f"CLOSE (70-90% similar): {close} ({close/len(validations)*100:.1f}%)")
    print(f"DIFFERS (<70% similar): {differs} ({differs/len(validations)*100:.1f}%)")
    print(f"ERRORS:                 {errors} ({errors/len(validations)*100:.1f}%)")

    avg_similarity = sum(v["similarity"] for v in validations) / len(validations)
    print(f"\nAverage similarity: {avg_similarity:.1%}")

    if differs > 0:
        print("\nRecords that DIFFER (may need review):")
        for v in validations:
            if v["match_status"] == "DIFFERS":
                print(f"  VANID {v['vanid']}: {v['similarity']:.1%}")
                print(f"    Forward: {v['forward'][:60]}")
                print(f"    Reverse: {v['reverse'][:60]}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="Geocoding results CSV")
    parser.add_argument("--sample", "-n", type=int, default=20, help="Sample size")
    args = parser.parse_args()

    validate_sample(args.input, args.sample)
