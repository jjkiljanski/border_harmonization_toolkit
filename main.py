from data_models import *
from core.core import AdministrativeHistory
from core.processor import AdministrativeHistoryProcessor
from utils.helper_functions import *

from visualization.adm_unit_plots import plot_district_map

import os
import csv
import pandas as pd

########## Load and initiate administrative changes list ###########
# Load configs
config = load_adm_history_config("config.json")
processing_config = load_processing_config("input/initial_region_state_list.json")

input_path = "input/cities_raw_data/population.csv"
output_path = "output/processed_data/dist_population_from_cities.csv"

try:
    # ✅ Load the data
    df = pd.read_csv(input_path, sep=";", encoding="utf-8")
    print(f"📂 Loaded input data: {df.shape[0]} rows, {df.shape[1]} columns")

    # ✅ Replace non-numeric values with NaN in all non-City columns
    for col in df.columns:
        if col != "City":
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # ✅ Define the mapping date
    mapping_date = datetime(1934, 10, 1)

except FileNotFoundError:
    print(f"❌ Input file not found at: {input_path}")
except Exception as e:
    print(f"⚠️ Error during processing: {e}")

administrative_history = AdministrativeHistory(config, load_geometries=True)
adm_history_processor = AdministrativeHistoryProcessor(processing_config, administrative_history)

# ✅ Map to districts
dist_df = adm_history_processor.map_city_data_to_dists(df, mapping_date, geojson_path="output/cities_used_for_population_estimates.geojson")

# ✅ Save result
dist_df.to_csv(output_path, sep=";", encoding="utf-8", index=False)
print(f"✅ Saved harmonized district population data to: {output_path}")

#administrative_history.generate_adm_state_plots()

########## Example uses of the implemented methods ##########

#administrative_history.process_raw_data()

""" Recover and export the gdf generated for a date (e.g. 1.10.1934)
deduced_gdf = administrative_history.dist_registry._plot_layer(datetime(1921,2,19))
deduced_gdf.to_file(r"E:\Studia\Studia magisterskie\Masterarbeit - Wirtschaftwissenschaft\dane\mapy\mapa 1922\districts_1921_02_19.shp", driver="ESRI Shapefile", encoding="utf-8")
"""


""" Print all adm. states in the adm. history
administrative_history.print_all_states()
"""


""" Create an administrative history summary
administrative_history.dist_registry.summary(with_alt_names=True)
"""


""" Plot changes histogram
dist_changes_hist_plot = administrative_history.plot_dist_changes_by_year(black_and_white=False)
dist_changes_hist_plot.write_html("output/dist_changes_hist_plot.html")
"""


""" Plotly district plot
fig_plotly = plot_district_map(administrative_history.dist_registry, datetime(1931,4,18))
fig_plotly.write_html("output/district_map_1931_plotly.html")
"""


""" Matplotlib district plot
fig_matplotlib = administrative_history.dist_registry.plot("abc", datetime(1931,4,18), shownames = False)
fig_matplotlib.savefig("output/district_map_1931_matplotlib.png", bbox_inches="tight", pad_inches=0.1)
"""


""" Example conversion matrix and conversion dict
############# Create an example conversion dict and conversion matrix and save them to CSV #############
date_from = datetime(1924,1,1)
date_to = datetime(1938,4,1)
conversion_dict = adm_history_processor._construct_conversion_dict(date_from, date_to, verbose = True)

# Ensure output directory for matrices exists
os.makedirs("output/conversion_matrices", exist_ok=True)

# Save an example conversion dict as CSV
with open('output/conversion_matrices/example_dict.csv', mode='w', newline='', encoding='utf-8') as f:
    writer = csv.writer(f)
    writer.writerow(['From_District', 'To_District', 'Proportion'])  # header
    for from_dist, to_dists in conversion_dict.items():
        for to_dist, proportion in to_dists.items():
            writer.writerow([from_dist, to_dist, proportion])

# Create an example conversion matrix
conversion_matrix = adm_history_processor.construct_conversion_matrix(date_from, date_to, verbose = True)

# Save to CSV
conversion_matrix.to_csv('output/conversion_matrices/example_matrix.csv', index=True)
"""


""" Identify state based on the (Region, District) csv column
# Loop through all files in the input/states_to_identify folder
folder_path = 'input/states_to_identify/'
state_info = [
    ('powiaty_1921.csv', datetime(1921,2,20)),
    ('powiaty_1931.csv', datetime(1931,4,18))
    ]

for filename, state_date in state_info:
    file_path = folder_path + filename
    # Read the CSV
    df = load_and_standardize_csv(file_path, administrative_history.region_registry, administrative_history.dist_registry, use_unique_seat_names = True)
    # Create list of (REGION, DISTRICT) pairs in uppercase
    r_d_pairs = list(zip(df['Region'], df['District']))

    # Find relevant administrative state:
    state_to_compare = administrative_history.find_adm_state_by_date(state_date)

    # Compare the state with the list of addresses from csv:
    state_to_compare.compare_to_r_d_list(r_d_pairs, verbose=True)
    #administrative_history.identify_state(r_d_pairs)
    #administrative_history.states_list[23].compare_to_r_d_list(r_d_pairs, verbose = True)
"""