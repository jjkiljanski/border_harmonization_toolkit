# border_harmonization_toolkit

## General Description

This toolkit allows for the creation of an administrative history of an area on the Country-Region-District level. It creates a data model of the adm. history on the basis of standardized inputs, and allows to use it for history-summaries generation, data standardization, imputation, and harmonization (between different borders).

The toolkit was written for the purpose of the creation of the **biggest existent quantitative database on the history of Poland** summarizing district-level economic and social data from the interwar period (1921-1939). The district-level datasets from interwar Poland as well as inputs allowing to reconstruct the full administrative history of Poland between 1921 and 1939, and harmonize all the datasets to chosen borders are stored in the `data` folder. An example use of the data for the sake of computation of historic district-level GDP is stored in the `examples` folder.

## The Toolkit's Structure

This toolkit consists of several components:
1. `core.core.AdministrativeHistory` - reconstructs an administrative history data model. All other modules use adm. history created and stored in an instance of this class.
2. `visualization.streamlit_app.py` - a GUI allowing to view the administrative history data model and standardize district-level datasets (e.g. unification of district and region/voivodeship names).
3. `core.processor.AdministrativeHistoryProcessor` - cleans, imputes, and harmonizes district-level datasets. It automatically constructs concordance matrices based on AdministrativeHistory class instance.
4. `core.plotter.AdministrativeHistoryPlotter` - provides plotting tools for adm. history data model and datasets.
5. `core.api.AdministrativeHistoryAPI` - simple API entry to load the ready datasets processed with the use of an AdministrativeHistoryProcessor for downstream use.

The historic Poland-specific data is stored in two folders:
1. `data/adm_histories/interwar_poland` - data inputs allowing to reconstruct the full administrative history of interwar Poland on the district level.
2. `data/datasets/interwar_poland_database` - digitized data of over 300,000 data points describing different dimensions of Poland's interwar society and economy on the district level.

The file `examples/interwar_poland_gdp/gdp_computation.ipynb` contains the full code used to compute Interwar Poland's district-level GDP timeseries on the basis of the harmonized inputs.

## Detailed Tool Descriptions
Please, refer to the detailed descriptions of the specific tools and of the data inputs' formats in the relevant subfolders.

## Acknowledgements
This toolkit was developed for my master Thesis "Economic Geography of Interwar Poland" at the Humboldt University of Berlin and later for the creation of analysis within the grant "Długookresowe zmiana nierówności ekonomicznych i mobilności międzypokoleniowej w Polsce. [Long-term changes in economic inequality and inter-generational mobility in Poland]" at the Warsaw School of Economics. I extend special thanks to my master prof. Marcin Wroński (Warsaw School Economics) for the idea of district-level GDP estimates, his guidance and support during the preparation of all local GDP estimates, and to prof. Nikolaus Wolf (Humboldt University of Berlin) for igniting my interest in economic history and for his support as my master thesis supervisor.