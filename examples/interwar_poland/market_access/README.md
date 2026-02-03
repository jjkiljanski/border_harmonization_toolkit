# Market access in Interwar Poland — example application

This repository is an **example application** showing how pre-computed historical transport networks can be used to estimate **district-level market access** and its changes over time.

The core contribution of this project is **not the construction of the transport network itself**, but the use of an existing database of travel-time matrices together with population data to implement a gravity-style market access framework.

## Data sources

The inputs used in this repository were generated elsewhere:

- **Administrative boundaries**  
  `districts_1934_10_1.geojson` — district map of Interwar Poland generated using this repository at commit `3b2ccce`.

- **Population data**  
  - `rural_population.csv` — rural population computed using `gdp_computation.ipynb` (commit `3b2ccce`)  
  - `city_population.csv` — city population computed using `gdp_computation.ipynb` (commit `3b2ccce`)

- **Travel-time (distance) matrices**  
  Routable travel-time matrices between district and city centroids were generated in a separate repository:  
  https://github.com/jjkiljanski/railway_history_pl_1842_1939 (commit `4ca8a15`)

  All assumptions regarding railway networks, timetables, and routing are documented in that repository’s README.

## What this repository does

Using the above inputs, this project:

- combines city- and district-level population data,
- collapses point-to-point travel times into population-weighted **district-to-district** travel times,
- computes **gravity-style market access measures** for districts in 1913, 1924, and 1939,
- and evaluates changes in market access over time.

The notebook is intended as a **transparent, reproducible example** of the combination of the border-harmonization-toolkit with the railway-history database for the historic transport accessibility analysis.