import os
from pathlib import Path
import pandas as pd
import numpy as np
import copy
from administrative_history.utils.helper_functions import load_adm_history_config, load_processing_config
from administrative_history.core.core import AdministrativeHistory
from administrative_history.core.processor import AdministrativeHistoryProcessor
from administrative_history.core.api import AdministrativeHistoryAPI
from administrative_history.core.plotter import AdministrativeHistoryPlotter

##########################################################################
##########     Instances of administrative history classes      ##########
##########################################################################

# Load the administrative history, and processing configuration
config = load_adm_history_config("data/adm_histories/interwar_poland/adm_history_config.json")
processing_config = load_processing_config("data/datasets/interwar_poland_database/processing_config.json")

# Create an administrative history object
administrative_history = AdministrativeHistory(config, load_geometries=True)

# Create a data processor object
adm_history_processor = AdministrativeHistoryProcessor(processing_config, administrative_history)

# Create an api object
adm_history_api = AdministrativeHistoryAPI(adm_history_processor=adm_history_processor)

# Create a plotter object
adm_history_plotter = AdministrativeHistoryPlotter(administrative_history)

##########################################################################
##########         Custom definitions for computation           ##########
##########################################################################

# Define frequent references to the chosen adm. state used in the whole notebook
reference_date = adm_history_processor.harmonize_to_date
reference_adm_state = administrative_history.find_adm_state_by_date(reference_date)
all_districts_raw = reference_adm_state.all_district_names(homeland_only=True)
all_regions_raw = reference_adm_state.all_region_names(homeland_only=True)

##########################################################################

# Define a dict mapping voivodships to voivodship group.
r_to_r_group = {
    'BIAŁOSTOCKIE': 'CENTRAL',
    'KIELECKIE': 'CENTRAL',
    'KRAKOWSKIE': 'SOUTHERN',
    'LUBELSKIE': 'CENTRAL',
    'LWOWSKIE': 'SOUTHERN',
    'ŁÓDZKIE': 'CENTRAL',
    'M. ST. WARSZAWA': 'CENTRAL',
    'NOWOGRÓDZKIE': 'EASTERN',
    'POLESKIE': 'EASTERN',
    'POMORSKIE': 'WESTERN',
    'POZNAŃSKIE': 'WESTERN',
    'STANISŁAWOWSKIE': 'SOUTHERN',
    'ŚLĄSKIE': 'WESTERN',
    'TARNOPOLSKIE': 'SOUTHERN',
    'WARSZAWSKIE': 'CENTRAL',
    'WOŁYŃSKIE': 'EASTERN',
    'ZIEMIA WILEŃSKA': 'EASTERN'
    }

# Define colors for r_groups for plotting.
r_group_to_color = {
    'CENTRAL': '#0000a2',
    'SOUTHERN': '#e9c716',
    'EASTERN': '#bc272d',
    'WESTERN': '#50ad9f'
}

# Define example voivodships used for plotting.
r_to_example_r = {
    r:r if r in ['ŁÓDZKIE', 'LWOWSKIE', 'POZNAŃSKIE']
    else 'OTHER'
    for r in all_regions_raw
}

# Example voivodeships colors for plotting.
example_r_to_color = {
    'ŁÓDZKIE': '#0000a2',
    'LWOWSKIE': '#e9c716',
    'POZNAŃSKIE': '#bc272d',
    'OTHER': '#d3d3d3'
}

##########################################################################

# Grouping to collapse data for WARSZAWSKIE voivodship and M. ST. WARSZAWA (Warsaw capital, which had the legal status of a voivodship)
#   to one voivodship WARSZAWSKIE
warsaw_region_grouping = {
    'BIAŁOSTOCKIE': 'BIAŁOSTOCKIE',
    'KIELECKIE': 'KIELECKIE',
    'KRAKOWSKIE': 'KRAKOWSKIE',
    'LUBELSKIE': 'LUBELSKIE',
    'LWOWSKIE': 'LWOWSKIE',
    'M. ST. WARSZAWA': 'WARSZAWSKIE', # The difference is here
    'NOWOGRÓDZKIE': 'NOWOGRÓDZKIE',
    'POLESKIE': 'POLESKIE',
    'POMORSKIE': 'POMORSKIE',
    'POZNAŃSKIE': 'POZNAŃSKIE',
    'STANISŁAWOWSKIE': 'STANISŁAWOWSKIE',
    'TARNOPOLSKIE': 'TARNOPOLSKIE',
    'WARSZAWSKIE': 'WARSZAWSKIE',
    'WOŁYŃSKIE': 'WOŁYŃSKIE',
    'ZIEMIA WILEŃSKA': 'ZIEMIA WILEŃSKA',
    'ŁÓDZKIE': 'ŁÓDZKIE',
    'ŚLĄSKIE': 'ŚLĄSKIE'
    }

##########################################################################

"""
Grouping aggregating smaller cities with their districts.

Some city districts that were created in the interwar period didn't exist from
the beginning and so the differentiation between them and their surrounding
districts (e.g. Inowrocławski and Inowrocław (city)) is of poor quality.
In all of the estimtes, we sum up data from such district pairs and analyze
them together.
"""
d_city_mapping = {
    'BĘDZIŃSKI': 'BĘDZIŃSKI',
    'SOSNOWIEC': 'BĘDZIŃSKI',
    'ZAWIERCIAŃSKI': 'BĘDZIŃSKI',
    'BIELSKI (BIELSKO)': 'BIELSKO',
    'BIELSKO (MIASTO)': 'BIELSKO',
    'BIAŁYSTOK (MIASTO)': 'BIAŁOSTOCKI',
    'BIAŁOSTOCKI': 'BIAŁOSTOCKI',
    'BYDGOSZCZ (MIASTO)': 'BYDGOSKI',
    'BYDGOSKI': 'BYDGOSKI',
    'CZĘSTOCHOWA (MIASTO)': 'CZĘSTOCHOWSKI',
    'CZĘSTOCHOWSKI': 'CZĘSTOCHOWSKI',
    'GDYNIA (MIASTO)': 'MORSKI',
    'GNIEZNO (MIASTO)': 'GNIEŹNIEŃSKI',
    'GNIEŹNIEŃSKI': 'GNIEŹNIEŃSKI',
    'MORSKI': 'MORSKI',
    'GRUDZIĄDZ (MIASTO)': 'GRUDZIĄDZKI',
    'GRUDZIĄDZKI': 'GRUDZIĄDZKI',
    'INOWROCŁAW (MIASTO)': 'INOWROCŁAWSKI',
    'INOWROCŁAWSKI': 'INOWROCŁAWSKI',
    'KATOWICE (MIASTO)': 'KATOWICE',
    'KATOWICKI': 'KATOWICE',
    'LUBLIN (MIASTO)': 'LUBELSKI',
    'LUBELSKI': 'LUBELSKI',
    'RADOMSKI': 'RADOMSKI',
    'RADOM (MIASTO)': 'RADOMSKI',
    'TORUŃ (MIASTO)': 'TORUŃSKI',
    'TORUŃSKI': 'TORUŃSKI',
    'POŁUDNIOWO-WARSZAWSKI': 'M. ST. WARSZAWA',
    'PÓŁNOCNO-WARSZAWSKI': 'M. ST. WARSZAWA',
    'PRASKO-WARSZAWSKI': 'M. ST. WARSZAWA',
    'ŚRÓDMIEJSKO-WARSZAWSKI': 'M. ST. WARSZAWA',
}

# Other districts are mapped to themselves
d_city_mapping = {dist:d_city_mapping[dist] if dist in d_city_mapping.keys() else dist for dist in all_districts_raw}

"""
List of big cities. I omit the cities below 150 000 citizens according to 1931 census:
 - 'BYDGOSZCZ (MIASTO)' (117 000)
 - 'CZĘSTOCHOWA (MIASTO)' (117 000)
 - 'LUBLIN' (112 000)
 - 'BIAŁYSTOK (MIASTO)' (91 000)
 - 'BIELSKO' (84 000) ('BIELSKO (MIASTO)' and 'BIELSKI (BIELSKO)' together)
 - 'RADOM (MIASTO)' (78 000)
 - 'GRUDZIĄDZ (MIASTO)' (54 000)
 - 'TORUŃ (MIASTO)' (54 000)
 - 'INOWROCŁAW (MIASTO)' (34 000)
 - 'GDYNIA (MIASTO)' (33 000)
 - 'GNIEZNO (MIASTO)' (31 000)
 """

big_cities = [
    'KATOWICE', # 341 000 ('KATOWICKI' and 'KATOWICE (MIASTO)' together)
    'KRAKÓW', # 220 000
    'LWÓW', # 312 000
    'ŁÓDŹ', # 605 000
    'POZNAŃ (MIASTO)', # 246 000
    'M. ST. WARSZAWA', # 1 172 000 (all Warsaw district together)
    'WILNO (MIASTO)' # 195 000
]

# For plotting
big_cities_to_color = {
    'Big City': '#0a0903ff',
    'Not a Big City': '#ff8200ff'
}

# For plotting
sector_colors = {
    'Agriculture': '#2ca02c',      # Green
    'Industry': 'purple',         # Red
    'Private_Services': '#1f77b4', # Light Blue
    'Public_Services': '#084594'   # Dark Blue
}

##########################################################################

"""
Create lists of all districts and regions used in the Notebook
(they are raw districts and regions grouped according to warsaw_region_grouping
and d_city_mapping).
"""
all_districts = list({d_city_mapping[dist] for dist in all_districts_raw})
all_regions = list({warsaw_region_grouping[region] for region in all_regions_raw})

# Load region-district pairs in the reference_adm_state
r_d_pairs_reference_adm_state = reference_adm_state.to_address_list(only_homeland=True)

# Create a dict mapping raw (not grouped with d_city_mapping) districts to regions
d_to_r_raw = {}
for region, dist in r_d_pairs_reference_adm_state:
    d_to_r_raw[dist] = region

# Create a dict mapping grouped district to regions
d_to_r = {d_city_mapping[dist]: warsaw_region_grouping[d_to_r_raw[dist]] for dist in d_to_r_raw.keys()}

# Define a dict mapping districts in the go-to administrative state to voivodship group.
d_to_r_group = {}
for dist, region in d_to_r.items():
    d_to_r_group[dist] = r_to_r_group[region]

# Define a dict mapping to example region
d_to_example_r = {}
for dist, region in d_to_r.items():
    d_to_example_r[dist] = r_to_example_r[region]

##########################################################################

# Dist mapping a district name to whether the district is a big city
is_big_city = {
    dist: 'Big City' if dist in big_cities else 'Not a Big City'
    for dist in all_districts
}

##########################################################################

# Create empty dfs
empty_dist_df = pd.DataFrame(all_districts, columns = ['District'])
empty_dist_df.set_index('District', inplace=True)
empty_region_df = pd.DataFrame(all_regions, columns = ['Region'])
empty_region_df.set_index('Region', inplace=True)

all_years = list(range(1924, 1939))

# Create a df dict to store production estimates for each year
empty_year_df_dict = {}
for year in all_years:
    empty_year_df_dict[year] = empty_dist_df.copy()

production_by_year = copy.deepcopy(empty_year_df_dict)