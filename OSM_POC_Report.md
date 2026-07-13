# OpenStreetMap (Nominatim) Geocoding POC Report

## Executive Summary

This report documents the proof-of-concept testing of OpenStreetMap's Nominatim geocoding API against 718 test addresses from the Mock LCV Data dataset. The testing evaluates OSM's suitability for the geocoding requirements outlined in Issue #27234.

### Key Findings

| Metric | Value |
|--------|-------|
| Total Addresses | 718 |
| Successful Geocodes | 399 (55.6%) |
| High Precision (ROOFTOP) | 383 (53.3%) |
| No Match | 282 (39.3%) |
| PO Boxes (Skipped) | 37 (5.2%) |
| Average Confidence (matched) | 88.7% |
| Processing Time | 17 min 32 sec |
| Rate | ~1.47 sec/address |

**Verdict: OSM Nominatim is NOT suitable as the primary geocoding solution for 1 million US addresses due to high failure rate (39.3%) and rate limiting constraints.**

---

## Subtask 1: Geocoding the Test Data

### Methodology

1. Created Python script (`osm_geocoder.py`) to:
   - Read addresses from CSV
   - Format addresses for Nominatim API
   - Call API with 1-second rate limiting (per OSM usage policy)
   - Save results with accuracy metadata

2. API Configuration:
   - Endpoint: `https://nominatim.openstreetmap.org/search`
   - Parameters: `format=json`, `addressdetails=1`, `limit=1`
   - User-Agent: `GeocoderPOC/1.0`

### Difficulties Encountered

1. **Rate Limiting**: OSM enforces strict 1 request/second limit
   - 718 addresses took ~17.5 minutes
   - **1 million addresses would take ~11.5 days of continuous processing**

2. **No Batch API**: Unlike Census Bureau, OSM has no batch endpoint
   - Each address requires individual HTTP request
   - No way to parallelize without violating TOS

3. **Inconsistent Address Parsing**:
   - Apartment/Unit numbers often caused failures
   - Abbreviated street types (Ct, Cir, Blvd) sometimes not recognized
   - Rural addresses poorly handled

4. **PO Box Limitation**: PO Boxes cannot be geocoded to coordinates

---

## Subtask 2: Data Cleaning and Verification

### Accuracy Analysis

#### Match Type Distribution

| Match Type | Count | Percentage | Description |
|------------|-------|------------|-------------|
| ROOFTOP | 383 | 53.3% | Building-level precision |
| NO_MATCH | 282 | 39.3% | Address not found |
| SKIPPED | 37 | 5.2% | PO Boxes (not geocodable) |
| RANGE_INTERPOLATED | 8 | 1.1% | Street-level interpolation |
| UNKNOWN | 6 | 0.8% | Unclassifiable match |
| APPROXIMATE | 2 | 0.3% | City/area centroid only |

#### Confidence Distribution (Matched Only)

| Confidence Range | Count | Percentage |
|-----------------|-------|------------|
| 90-100% | 383 | 96.0% |
| 70-89% | 8 | 2.0% |
| 50-69% | 0 | 0.0% |
| 30-49% | 8 | 2.0% |
| 0-29% | 0 | 0.0% |

### Accuracy Feedback Mechanism (Requirement 3)

The Nominatim API provides several fields useful for accuracy feedback:

#### 1. OSM Class/Type Classification

| OSM Class | OSM Type | Precision Level | Recommended Confidence |
|-----------|----------|-----------------|----------------------|
| place | house | Building | 90%+ |
| building | detached, yes | Building | 90%+ |
| highway | residential, secondary | Street | 70-85% |
| place | postcode | ZIP centroid | 40-50% |
| boundary | administrative | City/County centroid | 30-40% |

#### 2. Importance Score
- Range: 0.0 to 1.0
- Higher values indicate more significant/unique matches
- Can be used to weight confidence

#### 3. Bounding Box
- Provides geographic extent of the match
- Smaller bounding boxes = more precise matches
- Large bounding boxes indicate area-level matches

### Patterns in Failed Geocodes (NO_MATCH)

Analysis of 282 failed geocodes revealed these patterns:

| Pattern | Count | Example |
|---------|-------|---------|
| Address not in OSM database | 200+ | New subdivisions, rural roads |
| Apartment/Unit addresses | 45+ | "100 Gail Ct, Apt 43" |
| Non-standard address format | 6 | "County Road S-22-266" |
| Missing street number | 3 | "HARVESTER Cir" |
| Lot numbers | 3 | "1440 N Matthews Rd, Lot 4" |

### Address Standardization Issues

The API returned different city/locality names in some cases:

| Input City | Returned City | Notes |
|------------|---------------|-------|
| Greenville, SC | Gantt | Suburb/CDP substituted |
| Greenville, SC | Mauldin | Adjacent city |
| Greenville, SC | Taylors | CDP name |
| Charleston, SC | James Island | Island community |
| Saint Stephen | St. Stephen | Abbreviation variation |

**State abbreviations were expanded** (e.g., SC -> South Carolina), which is acceptable for standardization.

### Examples of Accuracy Issues

#### Example 1: City Centroid Instead of Address
**Input:** `1593, Rock Hill, SC, 29732, United States`
**Result:** Matched to Rock Hill city centroid (no street name provided)
- Lat/Long: 34.9248667, -81.0250784
- Match Type: APPROXIMATE
- Confidence: 40%
- **Issue:** Input was missing proper street name, only had house number

#### Example 2: Successful High-Precision Match
**Input:** `1 Studebaker Ct, Charleston, SC, 29414, United States`
**Result:** Exact building match
- Lat/Long: 32.844381, -80.077586
- Display: "1, Studebaker Court, Charleston, Charleston County..."
- Match Type: ROOFTOP
- Confidence: 90%
- OSM Type: house

#### Example 3: Street-Level Interpolation
**Input:** `1430 Venning Rd, Mt Pleasant, SC, 29464`
**Result:** Street-level match
- Match Type: RANGE_INTERPOLATED
- Confidence: 71%
- **Issue:** Exact address not in database, position estimated along street

---

## Comparison to Requirements

### Requirement 1: Cost and Rate Limiting

| Factor | OSM Nominatim | Assessment |
|--------|---------------|------------|
| Cost | Free | PASS |
| Rate Limit | 1 req/sec | FAIL |
| Time for 1M addresses | ~11.5 days | FAIL |
| Batch API | Not available | FAIL |

**Conclusion:** While free, the rate limiting makes OSM impractical for 1 million addresses.

### Requirement 2: Address Standardization

| Factor | Assessment |
|--------|------------|
| Street name standardization | Partial (when matched) |
| City normalization | Mixed results |
| State expansion | Works well |
| ZIP code validation | Returns matched ZIP |
| International format support | Limited |

**Conclusion:** Standardization is inconsistent. Successful matches return standardized data, but 39% of addresses failed to match entirely.

### Requirement 3: Accuracy Feedback

| Factor | OSM Support | Assessment |
|--------|-------------|------------|
| Confidence scoring | Via match type + importance | Available |
| Match precision level | Via OSM class/type | Good |
| Component-level validation | Via address_details | Partial |
| Distance from actual | Not provided | Not available |

**Conclusion:** OSM provides useful accuracy indicators through `class`, `type`, and `importance` fields. However, it doesn't explicitly flag which input components are incorrect.

---

## Recommendations

### For This Contract (1M US Addresses)

**OSM Nominatim is NOT recommended as the primary solution.**

Reasons:
1. 39.3% failure rate is too high for production use
2. Rate limiting makes processing time impractical (~11.5 days)
3. No batch API available
4. Rural and newer addresses poorly covered

### Alternative Approaches

1. **US Census Geocoder** (Recommended for US addresses)
   - Free, no rate limits
   - Batch API accepts 10,000 addresses per request
   - 1 million addresses = 100 batches
   - Already identified as reasonable in parent task

2. **Self-Hosted Nominatim**
   - Download OSM data and run locally
   - No rate limits
   - Requires server infrastructure (~500GB disk, 64GB RAM for US)
   - Same data quality issues remain

3. **Hybrid Approach**
   - Census Geocoder for primary US addresses
   - OSM Nominatim for fallback/verification
   - Different services for CA/MX/International

### For Accuracy Feedback Implementation

Based on this POC, recommend the following confidence thresholds:

| Match Type | Confidence | Action |
|------------|------------|--------|
| ROOFTOP (building) | 90-100% | Auto-accept |
| RANGE_INTERPOLATED | 70-85% | Review if critical |
| APPROXIMATE (area) | 30-50% | Manual review required |
| NO_MATCH | 0% | Retry with different service |

---

## Files Generated

| File | Description |
|------|-------------|
| `osm_geocoder.py` | Main geocoding script |
| `analyze_results.py` | Results analysis script |
| `geocoding_results.csv` | Geocoding results (tabular) |
| `geocoding_results.json` | Geocoding results (detailed) |
| `geocoding_analysis_report.txt` | Automated analysis output |
| `OSM_POC_Report.md` | This report |

---

## Conclusion

OpenStreetMap's Nominatim API, while free and providing good accuracy feedback mechanisms, is **not suitable as the primary geocoding solution** for this contract due to:

1. **High failure rate** (39.3% of addresses not found)
2. **Severe rate limiting** (1 request/second = 11.5 days for 1M addresses)
3. **No batch API** available
4. **Inconsistent coverage** (urban > rural, established > new developments)

The Census Geocoder should remain the primary solution for US addresses, with OSM potentially serving as a secondary verification source or for non-US addresses where Census data is unavailable.
