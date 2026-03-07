# border_harmonization_toolkit

⚠️ **Notice:** This project is under active development.  
The current version is not final and may change frequently.

You can check out a live DEMO website with project outcomes [here](https://jjkiljanski.github.io/interwar_poland_database_website/).

## Installation

To install the toolkit in editable (development) mode, first clone the repository, enter its folder, and run:

```bash
git clone https://github.com/jjkiljanski/border_harmonization_toolkit.git
cd border_harmonization_toolkit
pip install -e .
```

## General Description

This toolkit allows for the creation of an administrative history of an area on the Country-Region-District level. It creates a data model of the adm. history on the basis of standardized inputs, and allows to use it for history-summaries generation, data standardization, imputation, and harmonization (between different borders).

The toolkit was written for the purpose of the creation of the **biggest existent quantitative database on the history of Poland** summarizing district-level economic and social data from the interwar period (1921-1939). The `data` folder stores:
1. Inputs allowing to reconstruct the full administrative history of Poland between 1921 and 1939 in the `data/adm_histories/interwar_poland` folder;
2. Standardized district-level datasets from interwar Poland (over 450,000 data points describing different dimensions of Poland's interwar society and economy) together with the datasets' metadata in the `data/datasets/interwar_poland_database` folder;
3.  Config allowing to harmonize all the raw data files digitized from original sources to chosen borders in the `data/datasets/interwar_poland_database/processing_config.json` file.

The file `examples/interwar_poland_gdp/gdp_computation.ipynb` uses the collected data for the **computation of historic district-level 1924-1938 GDP series for Poland**. The estimates constitute **one of the earliest district-level GDP estimates for the early 20th century**.

## The Toolkit's Structure

This toolkit consists of several components:
1. `core.core.AdministrativeHistory` - reconstructs an administrative history data model. All other modules use adm. history created and stored in an instance of this class.
2. `visualization.streamlit_app.py` - a GUI allowing to view the administrative history data model and standardize district-level datasets (e.g. unification of district and region/voivodeship names).
3. `core.processor.AdministrativeHistoryProcessor` - cleans, imputes, and harmonizes district-level datasets. It automatically constructs concordance matrices based on AdministrativeHistory class instance.
4. `core.plotter.AdministrativeHistoryPlotter` - provides plotting tools for adm. history data model and datasets.
5. `core.api.AdministrativeHistoryAPI` - simple API entry to load the ready datasets processed with the use of an AdministrativeHistoryProcessor for downstream use.

The packages of use-specific data are stored in two folders:
1. `data/adm_histories` - stores packages of data inputs allowing to reconstruct the full administrative history of a country or a set of countries on the country-region-district level. Currently, only the package with the administrative history of interwar Poland is available.
2. `data/datasets` - stores packages of district-level datasets together with their metadata, and the processing config defining the way the data are imputed and harmonized.
Currently, only the package with database on interwar Poland is available.

The examples of database usecases are stored in the `examples` folder.
The only available example package `examples/interwar_poland_gdp/` contains the full code used to compute Interwar Poland's district-level GDP timeseries on the basis of the harmonized inputs.

## Detailed Tool Descriptions
Please, refer to the detailed descriptions of the specific tools and of the data inputs' formats in `src/administrative_history/README.md`.

## Acknowledgements
This toolkit was developed for my master Thesis "Economic Geography of Interwar Poland" at the Humboldt University of Berlin and later for the creation of analysis within the grant "Długookresowe zmiana nierówności ekonomicznych i mobilności międzypokoleniowej w Polsce. [Long-term changes in economic inequality and inter-generational mobility in Poland]" at the Warsaw School of Economics. I extend special thanks to prof. Marcin Wroński (Warsaw School Economics) for the idea of district-level GDP estimation, his guidance and support during the preparation of all local GDP estimates, and to prof. Nikolaus Wolf (Humboldt University of Berlin) for igniting my interest in economic history and for his support and guidance as my master thesis supervisor.
