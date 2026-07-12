"""
Analyze geocoding results and generate a detailed report.

This script reads the geocoding output CSV and produces a comprehensive
analysis of accuracy, data quality issues, and recommendations.
"""

import csv
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class IssueCategory:
    """Tracks issues by category."""
    name: str
    description: str
    count: int = 0
    examples: list = None

    def __post_init__(self):
        if self.examples is None:
            self.examples = []

    def add_example(self, vanid: str, address: str, result: str, max_examples: int = 3):
        """Add an example if we haven't hit the max."""
        if len(self.examples) < max_examples:
            self.examples.append({
                "vanid": vanid,
                "address": address,
                "result": result
            })
        self.count += 1


def analyze_results(input_file: str, output_file: Optional[str] = None):
    """Analyze geocoding results and generate a report."""

    # Read results
    with open(input_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        results = list(reader)

    total = len(results)

    # Categorize issues
    issues = {
        "po_box": IssueCategory(
            "PO Box Addresses",
            "Cannot be geocoded to a physical location - resolve to city/zip centroid"
        ),
        "missing_street_number": IssueCategory(
            "Missing Street Number",
            "Address has street name but no number - can only geocode to street/city level"
        ),
        "missing_street_name": IssueCategory(
            "Missing Street Name",
            "Only has a number without street name - cannot determine location"
        ),
        "partial_match": IssueCategory(
            "Partial Address Match",
            "Google found a match but not for the exact address provided"
        ),
        "interpolated": IssueCategory(
            "Interpolated Location",
            "Location estimated between two known points (less precise than rooftop)"
        ),
        "api_error": IssueCategory(
            "API/Network Errors",
            "Request failed due to technical issues"
        ),
        "invalid_address": IssueCategory(
            "Invalid/Unusual Address",
            "Address format is unusual or contains invalid data"
        ),
        "misspelling": IssueCategory(
            "Potential Misspelling",
            "Address may have misspellings or concatenated words"
        ),
    }

    # Counters
    location_types = defaultdict(int)
    accuracy_buckets = {"90-100": 0, "70-89": 0, "50-69": 0, "20-49": 0, "0-19": 0}
    status_counts = defaultdict(int)
    total_score = 0
    successful = 0

    # Analyze each result
    for row in results:
        status = row.get("status", "")
        status_counts[status] += 1

        location_type = row.get("location_type", "")
        if location_type:
            location_types[location_type] += 1

        try:
            score = int(row.get("accuracy_score", 0))
        except ValueError:
            score = 0

        if status == "OK":
            successful += 1
            total_score += score

            # Bucket the score
            if score >= 90:
                accuracy_buckets["90-100"] += 1
            elif score >= 70:
                accuracy_buckets["70-89"] += 1
            elif score >= 50:
                accuracy_buckets["50-69"] += 1
            elif score >= 20:
                accuracy_buckets["20-49"] += 1
            else:
                accuracy_buckets["0-19"] += 1

        original = row.get("original_address", "")
        formatted = row.get("formatted_address", "")
        vanid = row.get("vanid", "")
        partial_match = row.get("partial_match", "").lower() == "true"
        street_number = row.get("street_number", "")

        # Categorize issues
        if status in ["ERROR", "REQUEST_DENIED", "ZERO_RESULTS"]:
            issues["api_error"].add_example(vanid, original, row.get("error_message", ""))

        elif original.upper().startswith("PO BOX"):
            issues["po_box"].add_example(vanid, original, formatted)

        elif location_type == "APPROXIMATE":
            # Check if it's a partial match due to data issues
            if not street_number:
                # Check if original has a street-like pattern
                parts = original.split(",")[0].strip().split()
                if parts and parts[0].isdigit() and len(parts) == 1:
                    issues["missing_street_name"].add_example(vanid, original, formatted)
                elif "N/A" in original.upper():
                    issues["invalid_address"].add_example(vanid, original, formatted)
                else:
                    issues["missing_street_number"].add_example(vanid, original, formatted)

        elif location_type == "GEOMETRIC_CENTER":
            if not street_number:
                # Check for common patterns
                first_part = original.split(",")[0].strip()
                if first_part.upper() in ["N/A N/A", "N/A"]:
                    issues["invalid_address"].add_example(vanid, original, formatted)
                elif not any(c.isdigit() for c in first_part.split()[0] if first_part.split()):
                    issues["missing_street_number"].add_example(vanid, original, formatted)
                else:
                    issues["partial_match"].add_example(vanid, original, formatted)

        elif location_type == "RANGE_INTERPOLATED":
            issues["interpolated"].add_example(vanid, original, formatted)

        elif partial_match:
            # Check for potential misspellings
            first_part = original.split(",")[0].strip().upper()
            if " " not in first_part.split(" ", 1)[-1] if len(first_part.split(" ", 1)) > 1 else "":
                issues["misspelling"].add_example(vanid, original, formatted)
            else:
                issues["partial_match"].add_example(vanid, original, formatted)

    # Generate report
    report_lines = []
    report_lines.append("=" * 80)
    report_lines.append("GEOCODING PROOF OF CONCEPT - DETAILED ANALYSIS REPORT")
    report_lines.append("=" * 80)
    report_lines.append("")

    # Executive Summary
    report_lines.append("EXECUTIVE SUMMARY")
    report_lines.append("-" * 40)
    report_lines.append(f"Total Records Processed: {total}")
    report_lines.append(f"Successful Geocodes: {successful} ({successful/total*100:.1f}%)")
    report_lines.append(f"Failed Geocodes: {total - successful} ({(total-successful)/total*100:.1f}%)")
    if successful > 0:
        report_lines.append(f"Average Accuracy Score: {total_score/successful:.1f}/100")
    report_lines.append("")

    # Location Type Distribution
    report_lines.append("LOCATION TYPE DISTRIBUTION (Accuracy Indicator)")
    report_lines.append("-" * 40)
    report_lines.append("ROOFTOP:            Exact building location (most accurate)")
    report_lines.append("RANGE_INTERPOLATED: Estimated between two precise points")
    report_lines.append("GEOMETRIC_CENTER:   Center of a route/polygon")
    report_lines.append("APPROXIMATE:        City/ZIP centroid (least accurate)")
    report_lines.append("")
    for lt in ["ROOFTOP", "RANGE_INTERPOLATED", "GEOMETRIC_CENTER", "APPROXIMATE"]:
        count = location_types.get(lt, 0)
        if successful > 0:
            pct = count / successful * 100
            bar = "#" * int(pct / 2)
            report_lines.append(f"  {lt:20} {count:4} ({pct:5.1f}%) {bar}")
    report_lines.append("")

    # Accuracy Score Distribution
    report_lines.append("ACCURACY SCORE DISTRIBUTION")
    report_lines.append("-" * 40)
    report_lines.append("Score 90-100: High confidence - exact or near-exact location")
    report_lines.append("Score 70-89:  Good confidence - minor uncertainty")
    report_lines.append("Score 50-69:  Moderate confidence - street-level accuracy")
    report_lines.append("Score 20-49:  Low confidence - area-level only")
    report_lines.append("Score 0-19:   Very low confidence - manual review needed")
    report_lines.append("")
    for bucket, count in accuracy_buckets.items():
        if successful > 0:
            pct = count / successful * 100
            bar = "#" * int(pct / 2)
            report_lines.append(f"  {bucket:8} {count:4} ({pct:5.1f}%) {bar}")
    report_lines.append("")

    # Recommendations by score
    high_conf = accuracy_buckets["90-100"]
    med_conf = accuracy_buckets["70-89"] + accuracy_buckets["50-69"]
    low_conf = accuracy_buckets["20-49"] + accuracy_buckets["0-19"]
    report_lines.append("RECOMMENDATIONS BY CONFIDENCE LEVEL")
    report_lines.append("-" * 40)
    report_lines.append(f"  Auto-accept (90-100):  {high_conf:4} records ({high_conf/successful*100:.1f}%)")
    report_lines.append(f"  Light review (50-89):  {med_conf:4} records ({med_conf/successful*100:.1f}%)")
    report_lines.append(f"  Manual review (0-49):  {low_conf:4} records ({low_conf/successful*100:.1f}%)")
    report_lines.append("")

    # Issue Categories
    report_lines.append("DATA QUALITY ISSUES IDENTIFIED")
    report_lines.append("-" * 40)
    for key, issue in issues.items():
        if issue.count > 0:
            report_lines.append(f"\n{issue.name}: {issue.count} records")
            report_lines.append(f"  Description: {issue.description}")
            if issue.examples:
                report_lines.append("  Examples:")
                for ex in issue.examples[:3]:
                    report_lines.append(f"    VANID {ex['vanid']}:")
                    report_lines.append(f"      Input:  {ex['address'][:70]}")
                    report_lines.append(f"      Result: {ex['result'][:70]}")
    report_lines.append("")

    # Key Findings
    report_lines.append("=" * 80)
    report_lines.append("KEY FINDINGS")
    report_lines.append("=" * 80)
    report_lines.append("")

    po_box_count = issues["po_box"].count
    incomplete_count = issues["missing_street_number"].count + issues["missing_street_name"].count
    invalid_count = issues["invalid_address"].count

    findings = []

    if high_conf / successful * 100 >= 85:
        findings.append(f"1. EXCELLENT OVERALL ACCURACY: {high_conf/successful*100:.1f}% of addresses "
                       f"geocoded with high confidence (90-100 score)")

    if po_box_count > 0:
        findings.append(f"2. PO BOX LIMITATION: {po_box_count} records ({po_box_count/total*100:.1f}%) "
                       f"are PO Boxes which cannot be geocoded to physical locations. "
                       f"These resolve to city/ZIP centroids.")

    if incomplete_count > 0:
        findings.append(f"3. INCOMPLETE ADDRESS DATA: {incomplete_count} records "
                       f"({incomplete_count/total*100:.1f}%) have missing street numbers or names. "
                       f"Consider data cleaning before geocoding.")

    if invalid_count > 0:
        findings.append(f"4. INVALID ADDRESS FORMATS: {invalid_count} records contain "
                       f"placeholder or invalid data (e.g., 'N/A N/A'). "
                       f"These need manual correction.")

    rooftop_count = location_types.get("ROOFTOP", 0)
    if rooftop_count / successful * 100 >= 85:
        findings.append(f"5. HIGH PRECISION RATE: {rooftop_count/successful*100:.1f}% of successful "
                       f"geocodes achieved ROOFTOP precision (exact building location)")

    for i, finding in enumerate(findings, 1):
        report_lines.append(finding)
        report_lines.append("")

    # Accuracy Feedback Mechanism Recommendations
    report_lines.append("=" * 80)
    report_lines.append("ACCURACY FEEDBACK MECHANISM (Requirement 3)")
    report_lines.append("=" * 80)
    report_lines.append("")
    report_lines.append("Google's Geocoding API provides the following accuracy indicators:")
    report_lines.append("")
    report_lines.append("1. LOCATION_TYPE (Primary Indicator)")
    report_lines.append("   - ROOFTOP: Exact address, building-level precision")
    report_lines.append("   - RANGE_INTERPOLATED: Interpolated between street addresses")
    report_lines.append("   - GEOMETRIC_CENTER: Center of street/region")
    report_lines.append("   - APPROXIMATE: City/ZIP/state centroid only")
    report_lines.append("")
    report_lines.append("2. PARTIAL_MATCH Flag")
    report_lines.append("   - True: Google couldn't match the exact address provided")
    report_lines.append("   - May indicate misspellings, wrong city/state, etc.")
    report_lines.append("")
    report_lines.append("3. RESULT_TYPES")
    report_lines.append("   - 'street_address': Most precise (specific building)")
    report_lines.append("   - 'route': Street-level only")
    report_lines.append("   - 'locality': City-level only")
    report_lines.append("   - 'postal_code': ZIP code centroid")
    report_lines.append("")
    report_lines.append("RECOMMENDED THRESHOLDS FOR MANUAL REVIEW:")
    report_lines.append("   - Score < 50: ALWAYS requires manual review")
    report_lines.append("   - Score 50-69: Flag for review if address is critical")
    report_lines.append("   - Score 70-89: Generally acceptable, spot-check recommended")
    report_lines.append("   - Score >= 90: Can be auto-accepted for most use cases")
    report_lines.append("")

    # Output report
    report = "\n".join(report_lines)
    print(report)

    if output_file:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"\nReport saved to: {output_file}")


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Analyze geocoding results")
    parser.add_argument("input", help="Input CSV file with geocoding results")
    parser.add_argument("--output", "-o", help="Output file for report (optional)")

    args = parser.parse_args()

    if not Path(args.input).exists():
        print(f"ERROR: Input file not found: {args.input}")
        return 1

    analyze_results(args.input, args.output)
    return 0


if __name__ == "__main__":
    exit(main())
