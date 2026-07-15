# Geocoding Proof of Concept Analysis Report

## Overview

This report analyzes the geocoding results from the LCV test data (718 addresses) using the Geocodio API.

## Summary Statistics

| Metric | Count | Percentage |
|--------|-------|------------|
| Total Addresses | 718 | 100% |
| Successfully Matched | 718 | 100% |
| High Confidence (≥0.8) | 702 | 97.8% |
| Medium Confidence (0.5-0.8) | 13 | 1.8% |
| Low Confidence (<0.5) | 3 | 0.4% |

### Accuracy Type Breakdown

| Accuracy Type | Count | Percentage | Description |
|---------------|-------|------------|-------------|
| `rooftop` | 633 | 88.2% | Exact building/parcel location |
| `range_interpolation` | 24 | 3.3% | Estimated position along street |
| `nearest_rooftop_match` | 3 | 0.4% | Closest known building |
| `street_center` | 17 | 2.4% | Street centerline only |
| `place` | 41 | 5.7% | City/town centroid |

## Accuracy Feedback (Requirement 3)

Geocodio provides excellent accuracy feedback through two mechanisms:

### 1. Accuracy Score (0.0 - 1.0)
- **1.0**: Exact match, high confidence
- **0.8-0.99**: Good match with minor variations
- **0.5-0.79**: Partial match, manual review recommended
- **<0.5**: Poor match, likely incorrect

### 2. Accuracy Type
Describes HOW the geocoding was performed:
- **rooftop**: Building/parcel level precision (best)
- **range_interpolation**: Address estimated along street
- **nearest_rooftop_match**: Closest known address used
- **street_center**: Only matched to street (no specific address)
- **place**: Only matched to city/region (address not found)

## Issues Identified

### Pre-Geocoding Issues (47 addresses)

| Issue Type | Count |
|------------|-------|
| PO Box addresses | 38 |
| Missing zip code | 7 |
| Number-only address | 1 |
| Missing city | 1 |
| Missing state | 1 |
| Contains N/A | 1 |

### Low Accuracy Results Analysis

#### Very Low Accuracy (<0.5) - 3 addresses

1. **VANID 100665805**: `2563 PERCENT Dr, Sc, SC`
   - Accuracy: 0.2 (street_center)
   - Result: `Pierre Cir, McCormick, SC 29835`
   - Issue: "PERCENT Dr" is likely a typo/OCR error. State duplicated ("Sc, SC")

2. **VANID 101196350**: `21427 PO Box, Washington, DC`
   - Accuracy: 0.36 (street_center)
   - Result: `P St NW, Washington, DC 20036`
   - Issue: PO Box format reversed (number before "PO Box")

3. **VANID 100669493**: `2601 Career Ave, North Charleston, SC`
   - Accuracy: 0.48 (street_center)
   - Result: `Carrere Ct, Charleston, SC 29403`
   - Issue: "Career Ave" may be typo for "Carrere Ct", missing zip

#### Place-Level Only (0.5) - 3 addresses

1. **VANID 100662078**: `1593, Rock Hill, SC, 29732`
   - Issue: No street name, only house number

2. **VANID 100666190**: `1669 Notre Dame Rd Rear, Ninety Six, SC`
   - Issue: Address not found in database, "Rear" suffix unusual

3. **VANID 100683569**: `8 Briarpatch Dr, Goose Creek, SC`
   - Issue: Missing zip code, address not found

#### Street-Level (0.5-0.7) - 10 addresses

Common patterns:
- Unusual address formats (e.g., "State Road S-26-530")
- Potential typos (e.g., "JUSTIN RD" → "Austin Rd")
- Street type mismatches (e.g., "Rd" vs "Ln", "St" vs "Ct")
- Missing street suffix

#### Corrected Matches (0.7-0.99)

Some addresses were corrected/normalized:
- `101 PEARTREE CIRCLE` → `101 Pear Tree Cir` (0.94)
- `115 Summit Estates Leesville SC` → `115 Summit Estates Ct, Leesville, SC` (0.94)
- `Watarhickoryway` → `Water Hickory Way` (0.74)

## PO Box Handling

- Most PO Boxes geocode with accuracy 1.0 but accuracy_type `place`
- They return city centroid coordinates
- **Important**: PO Boxes cannot be geocoded to precise physical locations
- Recommendation: Flag PO Boxes separately for manual review

## Recommendations

### For Threshold Setting

Based on the results, suggested accuracy thresholds:

| Accuracy | Action |
|----------|--------|
| ≥ 0.9 with `rooftop` | Auto-accept |
| 0.8-0.9 or `range_interpolation` | Accept with note |
| 0.5-0.8 | Manual review recommended |
| < 0.5 | Likely incorrect, requires manual review |
| `place` type | Address not found, only city-level |

### For Data Quality

1. **Pre-process addresses** to identify:
   - PO Boxes (flag for special handling)
   - Missing components (city, state, zip)
   - Number-only addresses
   - Embedded city/state in address lines

2. **Post-process results** to flag:
   - Accuracy < 0.8 for manual review
   - `street_center` or `place` accuracy types
   - Large discrepancies between input/output (city changes, etc.)

## Cost Analysis

Geocodio pricing (as of testing):
- 2,500 free lookups/day
- $0.50/1,000 after free tier

For 1 million addresses:
- First 2,500: Free
- Remaining 997,500: ~$499

**Note**: This is significantly cheaper than Google's ~$5,000 estimate.

## Comparison with NAD

Initial testing with the National Address Database (NAD) via ArcGIS FeatureServer revealed:
- Frequent API timeouts
- Rate limiting issues
- Incomplete coverage (many NO_MATCH results)
- NAD is better suited for bulk downloads rather than API queries

Geocodio provides a more reliable and cost-effective solution for this use case.
