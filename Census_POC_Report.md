# Census Batch Geocoder - Proof of Concept Report

## Executive Summary

This proof of concept validates the US Census Bureau's batch geocoding API as a viable solution for geocoding approximately 1 million US addresses. The test was conducted using 718 sample addresses from the LCV dataset.

**Key Finding:** The Census geocoder achieved an **87.9% match rate** with **82.5% exact matches**, making it a strong candidate for the US address geocoding requirements.

## Test Results

### Match Statistics

| Category | Count | Percentage |
|----------|-------|------------|
| **Exact Matches** | 592 | 82.5% |
| **Non-Exact Matches** | 39 | 5.4% |
| **Ties** | 5 | 0.7% |
| **No Match** | 82 | 11.4% |
| **Total Records** | 718 | 100% |

**Overall Match Rate: 87.9%**

### Processing Performance

- **Batch Size:** 718 records
- **Processing Time:** 15.7 seconds
- **Rate:** ~46 records/second
- **Extrapolated for 1M records:** ~6 hours (in 100 batches)

## Requirements Analysis

### Requirement 1: Cost and Rate Limits

**Status: SATISFIED**

- **Cost:** FREE (no usage fees)
- **Batch Size:** Up to 10,000 records per batch
- **For 1M records:** 100 batches required
- **No rate limiting issues** observed during testing

**Comparison to alternatives:**
| Service | Cost for 1M Records | Processing Time |
|---------|---------------------|-----------------|
| Census | $0 | ~6 hours |
| Google | ~$5,000 | Variable |
| OpenStreetMap | $0 | ~11.5 days |

### Requirement 2: Address Standardization

**Status: SATISFIED**

The Census geocoder returns standardized addresses in USPS format. Examples of corrections observed:

| Original Input | Standardized Output |
|----------------|---------------------|
| 118 Stornoway St | 118 STORNAWAY ST (spelling correction) |
| 4001 Pelham Rd Apt 294 | 4001 PELHAM CT (street type correction) |
| 108 Foggy Meadow Ln | 108 FOGGY MEADOW DR (suffix correction) |
| 807 Tinkerbell Dr | 807 TINKERBELL LN (suffix correction) |
| 2457 Glover Rd Johns Island SC | 2457 GLOVER RD (removed duplicate city) |

The API returns:
- Uppercase standardized street name
- Standardized city name
- State abbreviation
- ZIP code

### Requirement 3: Accuracy Feedback

**Status: SATISFIED**

The Census API provides clear accuracy indicators:

#### 1. Match Status
- **Match:** Address was successfully geocoded
- **No_Match:** Address could not be matched
- **Tie:** Multiple possible matches exist (requires manual review)

#### 2. Match Type (for matched addresses)
- **Exact:** Perfect match to TIGER/Line database
- **Non_Exact:** Match found but with corrections applied

#### 3. Standardized Address Comparison
The API returns the standardized address, allowing comparison with the original input to identify corrections.

#### Recommended Accuracy Scoring

| Match Type | Score | Action |
|------------|-------|--------|
| Exact Match | 100 | Accept automatically |
| Non-Exact Match | 70 | Review standardization changes |
| Tie | 30 | Manual review required |
| No Match | 0 | Alternative geocoder or manual correction |

**Recommended Threshold:** Accept scores >= 70 for automated processing

## Issues Identified

### Categories of Unmatched Addresses

| Issue Type | Count | Notes |
|------------|-------|-------|
| **PO Boxes** | 38 | Census cannot geocode PO Boxes (expected) |
| **Missing Street Numbers** | 7 | e.g., "1593, Rock Hill, SC" |
| **Incomplete Addresses** | Various | Missing city, state, or ZIP |
| **Invalid Street Names** | Various | e.g., "3972 Grousewood" (no street type) |

### Tie Cases (Multiple Matches)

5 addresses had multiple possible matches:

1. **3272 Channel Side Dr SW, Supply, NC 28462** - Possible duplicate addresses
2. **133 Towne Creek Trl, Anderson, SC 29621** - Multiple matches in area
3. **75 Riverchase Blvd Apt 1018, Beaufort, SC 29906** - Apartment complex
4. **5611 Highway 187, Anderson, SC 29625** - Highway address ambiguity
5. **106 ALABAMA St, , SC** - Incomplete address (missing city)

## Output Fields Available

The Census batch geocoder returns:

| Field | Description |
|-------|-------------|
| Record ID | Original ID from input |
| Input Address | As submitted |
| Match Status | Match, No_Match, Tie |
| Match Type | Exact, Non_Exact |
| Matched Address | Standardized USPS format |
| Longitude | Decimal degrees |
| Latitude | Decimal degrees |
| TIGER/Line ID | Street segment ID |
| TIGER/Line Side | L (left) or R (right) |
| State FIPS | State code |
| County FIPS | County code |
| Census Tract | Tract code |
| Census Block | Block code |

## Recommendations

### For Production Implementation

1. **Pre-processing:**
   - Identify and filter PO Box addresses (use separate handling)
   - Validate street numbers are present
   - Ensure all required fields (city, state, ZIP) are populated

2. **Batch Strategy:**
   - Process in batches of 10,000 records
   - Implement retry logic for failed API calls
   - Log all responses for audit

3. **Quality Assurance:**
   - Auto-accept exact matches (score 100)
   - Review non-exact matches to verify corrections are appropriate
   - Queue ties for manual review
   - Flag no-matches for address correction workflow

4. **For Non-US Addresses:**
   - Census only covers US addresses (including Puerto Rico and territories)
   - Alternative services needed for Canada (~50K), Mexico (~20K), and international (~2K)
   - Consider: Geocodio, HERE, or Google as supplements

### Suggested Accuracy Thresholds

| Score Range | Category | Action |
|-------------|----------|--------|
| 100 | High Confidence | Accept automatically |
| 70-99 | Medium Confidence | Accept, note standardization |
| 30-69 | Low Confidence | Flag for review |
| 0-29 | No Confidence | Manual intervention required |

## Files Generated

- `census_geocoder.py` - Main geocoding script
- `census_input_batch.csv` - Transformed input for Census API
- `census_raw_response.csv` - Raw API response
- `census_results_*.csv` - Parsed results with accuracy scores
- `census_results_*.json` - Full results with issue analysis
- `census_analysis_report.txt` - Text-format analysis report

## Conclusion

The Census batch geocoding API is a **strong fit** for the US address geocoding requirements:

1. **Cost:** FREE for unlimited usage
2. **Performance:** Handles 10,000 records per batch; 1M records processable in ~6 hours
3. **Quality:** 87.9% match rate with clear accuracy feedback
4. **Standardization:** Returns USPS-standardized addresses
5. **Accuracy Feedback:** Provides exact vs. non-exact classification

**Recommendation:** Proceed with Census geocoder for US addresses, with supplemental service(s) for non-US addresses.

## References

- [Census Geocoding Services API](https://geocoding.geo.census.gov/geocoder/Geocoding_Services_API.html)
- [Census Geocoder User Guide](https://www2.census.gov/geo/pdfs/maps-data/data/Census_Geocoder_User_Guide.pdf)
- [FCC BDC Help - Census Geocoder](https://help.bdc.fcc.gov/hc/en-us/articles/5341095744283-How-to-Use-the-Census-Geocoder)
