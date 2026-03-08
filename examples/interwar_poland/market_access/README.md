# Market Access in Interwar Poland

This folder contains the current market-access workflow used for annual district estimates in Interwar Poland (1924-1938), including baseline and fixed14 scenarios.

The focus is application and reproducibility. Transport networks/distances are treated as precomputed inputs.

## Main Economic Setup

For district `i` in year `t`:

`MA_{i,t} = MA_{i,t}^{domestic} + MA_{i,t}^{foreign}`

Domestic component:

`MA_{i,t}^{domestic} = sum_{j != i} Mass_{j,t} * exp(beta_dom * ln(d_{ij,t}) + gamma_t * PartBorder_{ij}) + Mass_{i,t} * exp(beta_dom * ln(d_{ii,t}))`

Foreign component:

`MA_{i,t}^{foreign} = sum_{r in ForeignRegions} GDP_{r,t} * exp(beta_for * ln(D_{ir,t}))`

Parameters currently used:

- `beta_dom = -2.6705` (domestic distance coefficient)
- `beta_for = -0.5684` (foreign distance coefficient)
- `gamma_t`: year-specific partition-border coefficient from `partition_coefficients.csv`

Mass terms:

- Domestic destinations `Mass_{j,t}`: district GDP from `district_gdp.csv`
- Foreign destinations: region GDP from `foreign_region_gdp.csv`

### Partition-border assumption

`PartBorder_{ij} = 1` if origin and destination districts belonged to different historical partitions (German/Russian/Austro-Hungarian), else `0`.

Only partition difference matters, not the number of border crossings along a route.

### Self-term (`j = i`) assumption

Self-distance is area-based using district geometry:

`d_{ii} = (2/3) * sqrt(A_i / pi)`

where `A_i` is district area (km^2) computed from `districts_1934_10_1.geojson` after projection to EPSG:3035.

This self-term is included in `MA^{domestic}`.

## Distance Construction and Scenarios

### Point-to-district aggregation

Distance matrices are provided at point level (district centroids, city points, border crossings).
District-to-district and district-to-border distances are population-weighted over district point composition (district centroid + cities).

### Scenarios

- `baseline`: distance from `horse_km + rail_km` matrices
- `fixed14`: distance from precomputed `time_min` matrices

### Units

Notebook flag: `COMPUTE_IN_MILES` (default `True`).

- If `True`, km-based baseline distances are converted to miles before MA computation.
- `fixed14` matrices are in minutes.

## Foreign Link Assumption

Foreign accessibility is computed via:

1. district -> border-crossing distance (from matrix, population-weighted),
2. border-crossing -> foreign city/province connector (`length_km`) from `border_crossing_IIRP_connections.csv`.

`D_{ir,t}` is built as the sum of these two parts (with unit-consistent conversion by scenario).

When multiple border crossings can map to the same foreign target, the shortest route is used.

## Key Inputs

In `data/`:

- `districts_1934_10_1.geojson`
- `district_gdp.csv`
- `foreign_region_gdp.csv`
- `partition_dummies.csv`
- `partition_coefficients.csv`
- `border_crossing_IIRP_connections.csv`
- `city_population.csv`, `rural_population.csv` (used for distance weighting at point level)

In `data/distances/`:

- `distance_matrix_horse_km_long_{year}_baseline.csv`
- `distance_matrix_rail_km_long_{year}_baseline.csv`
- `distance_matrix_long_{year}_fixed14.csv`

for years 1924-1938.

## Outputs

Main outputs are written to:

- `outputs/market_access/` (tables, including annual MA and diagnostics)
- `outputs/market_access/distance_matrices/` (exported district-to-district matrices used in MA)
- `plots/new_formula/` (annual maps and 1938 vs 1924 changes, by scenario and MA variant)

Additional checks include:

- selected district-pair distance diagnostics,
- selected Warsaw-foreign route diagnostics,
- nearest-3 domestic contributor diagnostics.

## Implementation Notes

- Core economic functions are in the notebook `market_access_interwar_poland.ipynb`.
- IO/parsing/export/plot helper logic is in `market_access_helpers.py`.
