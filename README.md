# Geocodio Batch Geocoder Proof of Concept

A proof of concept for batch geocoding US addresses using the Geocodio API.

## Background

This project addresses the LCV pilot requirement to geocode ~1 million US addresses. Geocodio was chosen over the Census geocoder because:

1. **Better accuracy feedback** - Returns accuracy scores and accuracy types (rooftop, street_center, etc.)
2. **Address standardization** - Returns formatted addresses with parsed components
3. **Reasonable pricing** - $1/1000 lookups with 2,500 free daily lookups

## Setup

### 1. Get a Geocodio API Key

1. Sign up at https://www.geocod.io/
2. Get your API key from the dashboard
3. Set it as an environment variable:

```bash
# Windows
set GEOCODIO_API_KEY=your_key_here

# Linux/Mac
export GEOCODIO_API_KEY=your_key_here
```

### 2. Run the Test Script

Test the API connection with a few sample addresses:

```bash
python test_geocoder.py
```

### 3. Run the Full Geocoder

Process all addresses from the CSV file:

```bash
python geocoder.py
```

## Files

- `geocoder.py` - Main batch geocoding script
- `test_geocoder.py` - Quick API test script
- `Mock LCV Data.csv` - Test data (718 addresses)
- `geocoding_results.csv` - Output file (created after running)

## Test Data Analysis

The test dataset contains **718 addresses** with the following characteristics:

### Address Quality Issues Identified

| Issue | Count |
|-------|-------|
| PO Box addresses | 38 |
| Missing zip code | 7 |
| Missing street name (number only) | 1 |
| Missing city | 1 |
| Missing state | 1 |
| Contains N/A | 1 |

**Total problematic addresses: 47 (6.5%)**

### Sample Issues

| VANID | Address | Problem |
|-------|---------|---------|
| 100662078 | 1593, Rock Hill, SC, 29732 | Number only, no street name |
| 100684913 | 106 ALABAMA St, SC | Missing city and zip |
| 100684172 | N/A N/A, Chapin, SC, 29036 | Invalid address |
| Multiple | PO Box addresses | Cannot geocode to coordinates |

## Accuracy Metrics

Geocodio returns two key accuracy indicators:

### 1. Accuracy Score (0-1)

- **>= 0.8**: High confidence - use without review
- **0.5 - 0.8**: Medium confidence - may need spot checking
- **< 0.5**: Low confidence - requires manual review

### 2. Accuracy Type

| Type | Quality | Description |
|------|---------|-------------|
| `rooftop` | Best | Exact building location |
| `point` | Excellent | Known point location |
| `range_interpolation` | Good | Estimated along street segment |
| `nearest_rooftop_match` | Fair | Nearby known location |
| `street_center` | Poor | Center of street |
| `place` | Very Poor | City/town centroid |
| `county` | Bad | County centroid |
| `state` | Worst | State centroid |

## Pricing for 1 Million Addresses

| Option | Cost | Notes |
|--------|------|-------|
| Pay-as-you-go | ~$1,000 | $1/1000 after free tier |
| Flex 850 | $775/month | 850K credits/month + top-up |
| Volume discount | Negotiable | Starts at 500K credits |

For the LCV pilot (718 addresses), the **free tier is sufficient**.

## Next Steps

1. **Run the proof of concept** with the test data
2. **Review accuracy metrics** to establish confidence thresholds
3. **Identify patterns** in low-accuracy results
4. **Implement caching** to avoid re-geocoding known addresses
5. **Scale up** once accuracy thresholds are validated

## Requirements for Requirement 3: Accuracy Feedback

The Geocodio API satisfies Requirement 3 by providing:

1. **Accuracy score** (0-1) for confidence thresholds
2. **Accuracy type** for understanding match quality
3. **Formatted address** to compare against input
4. **Address components** to identify which parts matched/changed
5. **Source data** to understand where the match came from

This allows setting thresholds like:
- Auto-accept: `accuracy >= 0.8` AND `accuracy_type in ['rooftop', 'point']`
- Manual review: `accuracy < 0.5` OR `accuracy_type in ['place', 'county', 'state']`
