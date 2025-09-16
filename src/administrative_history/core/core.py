import json
from datetime import datetime
from pydantic import parse_obj_as, ValidationError
from typing import List
import shutil
from shapely.geometry import Point
import geopandas as gpd
import pandas as pd
import os
import time

from administrative_history.data_models.adm_timespan import *
from administrative_history.data_models.adm_unit import *
from administrative_history.data_models.adm_state import *
from administrative_history.data_models.adm_change import *
from administrative_history.data_models.econ_data_metadata import *
from administrative_history.data_models.processing_config import *

from administrative_history.utils.helper_functions import standardize_df

"""
This is the core component of the toolkit.

When an instance of AdministrativeHistory is created, the object reads in the input data
and creates the data model of the administrative history. It loads the district maps from
GeoJSONs or ESRI shapefiles and reconstructs the territories of the districts on the basis
of the maps where possible.

Example usage:
    # Load the configuration.
    config = load_adm_history_config("config.json")

    # Create an AdministrativeHistory instance.
    administrative_history = AdministrativeHistory(config, load_geometries=True)

    
"""

class AdministrativeHistory():
    def __init__(self, config, load_geometries=True, populate_fallback = True):
        # Input files' paths
        self.changes_list_path = config["changes_list_path"]
        self.initial_adm_state_path = config["initial_adm_state_path"]
        self.initial_region_list_path = config["initial_region_list_path"]
        self.initial_dist_list_path = config["initial_dist_list_path"]
        self.territories_path = config["territories_path"]
        self.cities_path = config["cities_path"]

        self.load_geometries = load_geometries

        # Create attributes holding information about state of territory (territory info) loading.
        self.territories_info_loaded = False
        self.territories_loaded = False
        self.territories_info_deduced = False
        self.territories_deduced = False
        self.fallback_territories_info_created = False
        self.fallback_territories_created = False

        # Output files' paths
        self.adm_states_output_path = config["adm_states_output_path"]
        self.adm_states_maps_output_path = config["adm_states_maps_output_path"]

        # Define the administrative history timespan
        self.timespan = TimeSpan(start = config["global_timespan"]["start"], end = config["global_timespan"]["end"])

        # Create lists to store Change objects and Administrative State objects
        self.changes_list = []
        self.states_list = []
        
        # Create empty attribute to store district and region registries
        self.dist_registry = None
        self.region_registry = None

        # Create changes list
        self._load_changes_from_json()

        # Create AdministrativeState object for the initial state
        self._load_state_from_json()

        # Load district and region registries
        self._load_dist_registry()
        self._load_region_registry()

        # Create chronological changes dict {[date]: List[Change]}
        self._create_changes_dates_list()
        self._create_changes_chronology()

        # Create states for the whole timespan
        self._create_history()

        # Initiate list with all states for which territory is loaded from GeoJSON
        self.states_with_loaded_territory = []
        self._load_territories()

        # Deduce information about district territories where possible
        self._deduce_territories(verbose = False)

        # Populate missing territories with fallback values
        if populate_fallback:
            self._populate_territories_fallback()

        self._load_cities()

    def _load_dist_registry(self):
        """
        Load the initial list of district from a JSON file and validate according to a Pydantic
        data model defined in data_models module.

        Args:
            file_path (str): Path to the JSON file containing the list of changes.
        """
        print("Loading initial district registry...")
        start_time = time.time()
        with open(self.initial_dist_list_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        if not isinstance(data, list):
            raise ValueError("Expected a list of District dicts in the JSON file")

        # Use pydantic to parse and validate the list
        try:
            self.dist_registry = parse_obj_as(DistrictRegistry, {"unit_list": data})
            # Set initial timespans
            for dist in self.dist_registry.unit_list:
                dist.states[0].timespan = TimeSpan(start = self.timespan.start, end = self.timespan.end)
            # Set CRS
            n_districts = len(self.dist_registry.unit_list)
            end_time = time.time()
            execution_time = end_time - start_time
            print(f"✅ Loaded {n_districts} validated districts in {execution_time:.2f} seconds. Set their initial state timespans to {TimeSpan(start = self.timespan.start, end = self.timespan.end)}.")
        except ValidationError as e:
            print(e.json(indent=2))

    def _load_region_registry(self):
        """
        Load the initial list of district from a JSON file and validate according to a Pydantic
        data model defined in data_models module.

        Args:
            file_path (str): Path to the JSON file containing the list of changes.
        """
        print("Loading initial region registry...")
        start_time = time.time()

        with open(self.initial_region_list_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        if not isinstance(data, list):
            raise ValueError("Expected a list of Region dicts in the JSON file")

        # Use pydantic to parse and validate the list
        try:
            self.region_registry = parse_obj_as(RegionRegistry, {"unit_list": data})
            for region in self.region_registry.unit_list:
                region.states[0].timespan = TimeSpan(start = self.timespan.start, end = self.timespan.end)
            n_regions = len(self.region_registry.unit_list)

            end_time = time.time()
            execution_time = end_time - start_time
            print(f"✅ Loaded {n_regions} validated regions in {execution_time:.2f} seconds. Set their initial state timespans to {TimeSpan(start = self.timespan.start, end = self.timespan.end)}")
        except ValidationError as e:
            print(e.json(indent=2))

    def _load_changes_from_json(self):
        """
        Load a list of changes from a JSON file and validate according to a Pydantic
        data model defined in data_models module.

        Args:
            file_path (str): Path to the JSON file containing the list of changes.
        """
        print("Loading changes list...")
        start_time = time.time()

        with open(self.changes_list_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        if not isinstance(data, list):
            raise ValueError("Expected a list of changes in the JSON file")

        # Check for non-string elements in links before parsing
        for i, change in enumerate(data):
            links = change.get("links", "MISSING")
            #print(f"Change {i} links type: {type(links).__name__}, value: {links}")
            if isinstance(links, list):
                for j, link in enumerate(links):
                    if not isinstance(link, str):
                        print(f"{change.get('date')}: {change.get('sources')} - Non-string link at index {j}: {link} (type: {type(link).__name__})")
            else:
                print(f"{change.get('date')}: {change.get('sources')} - Links is not a list!")

        # Use pydantic to parse and validate the list
        try:
            self.changes_list = parse_obj_as(List[Change], data)
            self.changes_list.sort(key=lambda change: (change.order is None, change.order))  # Moves None order to end
            n_changes = len(self.changes_list)

            end_time = time.time()
            execution_time = end_time - start_time
            print(f"✅ Loaded {n_changes} validated changes in {execution_time:.2f} seconds.")
        except ValidationError as e:
            print(e.json(indent=2))


    def _load_state_from_json(self):
        """
        Load the administrative state from a JSON file and validate according to the AdministrativeState model.
        """
        print("Loading initial state...")
        with open(self.initial_adm_state_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        try:
            initial_adm_state = AdministrativeState(**data)
            initial_adm_state.timespan = self.timespan.model_copy(deep=True)
            self.states_list.append(initial_adm_state)
            print("✅ Loaded initial state.")
        except ValidationError as e:
            print("❌ Validation error:")
            print(e.json(indent=2))

    def _create_changes_dates_list(self):
        """
        Creates the list of all changes' dates.
        """
        self.changes_dates = [change.date for change in self.changes_list]
        self.changes_dates = list(set(self.changes_dates))
        self.changes_dates.sort()

    def _create_changes_chronology(self):
        """
        Creates the dict self.changes_chron_dict of the form {date_t: list_of_changes_occuring_on_date_t}
        """
        self.changes_chron_dict = {}
        for change in self.changes_list:
            if change.date in self.changes_chron_dict.keys():
                self.changes_chron_dict[change.date].append(change)
            else:
                self.changes_chron_dict[change.date] = [change]

        for change_list in self.changes_chron_dict.values():
            # Sort changes for every date according to the order.
            # change.order = None puts the changes at the end of the list.
            change_list.sort(key=lambda change: (change.order is None, change.order))

        # Check if all changes are there
        assert set(self.changes_chron_dict.keys()) == set(self.changes_dates), f"Lists not equal!\nset(self.changes_chron_dict.keys()):\n {set(self.changes_chron_dict.keys())};\nset(self.changes_dates):\n{set(self.changes_dates)}."

        # Uncomment for debugging only
        # for date, change_list in self.changes_chron_dict.items():
        #     for change in change_list:
        #         print(f"{date}: {change.change_type}, order: {change.order}")
        #         change.echo()

    def _create_history(self):
        """
        Creates the data model of administrative history through the sequential application of administrative changes.
        """
        print(f"Creating administrative history (sequentially applying changes)...")
        start_time = time.time()

        # Delete and recreate the entire folder
        if os.path.exists(self.adm_states_output_path):
            shutil.rmtree(self.adm_states_output_path)
        os.makedirs(self.adm_states_output_path)

        current_change_index = 0

        for i, date in enumerate(self.changes_dates):
            changes_list = self.changes_chron_dict[date]
            old_state = self.states_list[-1]
            new_state = old_state.apply_changes(changes_list, self.region_registry, self.dist_registry, start_index=current_change_index, verbose = False)
            current_change_index += len(changes_list)
            self.states_list.append(new_state)

            csv_filename = "/state" + new_state.timespan.start.strftime("%Y-%m-%d")
            new_state.to_csv(self.adm_states_output_path + csv_filename)
        
        # Sort district list in the district registry by name_id
        self.dist_registry.unit_list.sort(key=lambda dist: dist.name_id)
        self.dist_registry.unique_name_variants.sort()
        self.dist_registry.unique_seat_names.sort()
        self.region_registry.unique_name_variants.sort()
        self.region_registry.unique_seat_names.sort()

        end_time = time.time()
        execution_time = end_time - start_time
        print(f"✅ Successfully applied all changes in {execution_time:.2f} seconds. Administrative history database created.")

    def _load_territories(self, verbose = False):
        """
        Loads a territories from an external JSON file to a Geopandas dataframe
         and asigns them to the district states based on the name_id in the 'District'
         column and a date in the district state's timespan defined in the 'ter_date'
         column.
        """
        start_time = time.time()
        if self.load_geometries:
            print("Loading territories...")
        else:
            print(f"Loading territories information (metadata only)...")
            # Import fiona for looking into the geometry files without loading them
            try:
                import fiona
            except ImportError:
                print("The `fiona` package is required for reading shapefile metadata. Please install it locally with `pip install fiona`.")
                return None
        # Initialize list to store individual territories GeoDataFrames
        gdf_list = []

        # Loop through all files in the directory
        for filename in os.listdir(self.territories_path):
            if filename.endswith((".json", ".geojson", ".shp")):
                file_path = os.path.join(self.territories_path, filename)
                try:
                    if self.load_geometries:
                        gdf = gpd.read_file(file_path)
                        print(f"Loaded: {filename} ({len(gdf)} rows)")
                    else:
                        with fiona.open(file_path) as src:
                            records = [feat["properties"] for feat in src]
                            gdf = pd.DataFrame(records)
                        print(f"Loaded: {filename} attribute table ({len(gdf)} rows)")

                    # If geometry is loaded, ensure CRS and projection
                    if self.load_geometries:
                        # Check for CRS
                        if gdf.crs is None:
                            raise ValueError(f"Geometry loaded from '{file_path}' has no defined CRS.")

                        # Reproject if necessary
                        if gdf.crs != "EPSG:4326":
                            original_crs = gdf.crs
                            gdf = gdf.to_crs("EPSG:4326")
                            if verbose:
                                print(f"CRS of the geometry loaded from file '{file_path}' converted. Original: {original_crs}. New: 'EPSG:4326'.")
                            
                    # Standardize district and region names to name_ids in the registries
                    try:
                        unit_suggestions = standardize_df(gdf, self.region_registry, self.dist_registry, columns = ["District"], verbose = False)
                        if unit_suggestions['District'] != {}:
                            print(f"Some names in the 'District' column of shapefile {filename} have more than one suggested name and were skipped.")
                            print(f"The suggestions:")
                            for key, value in unit_suggestions['District'].items():
                                _, dist_name = key
                                print(f"{dist_name}: {value}.")
                    except ValueError as e:
                        print(f"❌ Failed during names standardization of the shapefile {filename}: {e}")
                        raise  # Do NOT assign the error to territories_gdf!

                    gdf_list.append(gdf)

                except Exception as e:
                    print(f"Failed to load {filename}: {e}")
        
        if not gdf_list:
            print("⚠️ No valid territory files found.")
            return

        # Combine all into one DataFrame
        territories_df = pd.concat(gdf_list, ignore_index=True)

        # If geometries are loaded, set the CRS of the concatenated Geopandas dataframe
        if self.load_geometries:
            territories_gdf = gpd.GeoDataFrame(territories_df, crs="EPSG:4326")
        else:
            territories_gdf = territories_df

        # Set the territories of the appropriate states
        for idx, row in territories_gdf.iterrows():
            # Retrieve the district name and territory date
            district_name_id = str(row.get("District", ""))
            ter_date = str(row.get("ter_date", ""))
            ter_date = datetime.strptime(ter_date, "%d.%m.%Y")

            # Find the appropriate unit state in the registry
            unit, unit_state, _ = self.dist_registry.find_unit_state_by_date(district_name_id, ter_date)
            if unit_state is None and unit is not None:
                print(f"No match found for district '{district_name_id}' (standardized name: {unit.name_id}) on {ter_date.date()}")
                continue
            
            if unit is None:
                continue # This happens if there were more than one suggested names.
            
            # Always set the territory info
            unit_state.current_territory_info = unit.name_id+str(ter_date.date())

            # Set the territory of the appropriate unit state ONLY if self.load_geometries is True.
            if self.load_geometries:
                unit_state.current_territory = row.geometry
            
            unit_state.territory_is_fallback = False

            # Store the information that the state has territory loaded
            self.states_with_loaded_territory.append(unit_state)

        # Update information: the territory info (and territories themselves) were loaded.
        self.territories_info_loaded = True
        if self.load_geometries:
            self.territories_loaded = True

        # Print success message
        end_time = time.time()
        execution_time = end_time - start_time
        print(f"✅ Successfully loaded all territories in {execution_time:.2f} seconds.")

    def _deduce_territories(self, verbose = False):
        """
        This function takes the list of unit states with territory geometries
        loaded for GeoJSON and deduces the territory for all other states
        where it is possible.
        """
        print("Deducing all possible dist territories on the basis of the loaded ones.")
        start_time = time.time()

        was_anything_deduced = False

        for unit_state in self.states_with_loaded_territory:
            # Spread territory info for every state.
            # If self.load_geometries is True (and so the geometries were loaded), share geometries and territory info.
            # If self.load_geometries is False, share ONLY territory info.
            was_something_deduced = unit_state.spread_territory_info(compute_geometries=self.load_geometries, verbose = verbose, iteration='initial')
            if was_something_deduced: was_anything_deduced = True

        # If anything was deduced, rerun the territory spreading as long as something at all is being deduced.
        i = 0
        while was_anything_deduced:
            print(f"Iteration {i} of territory deduction.")
            was_anything_deduced = False
            all_states = self.dist_registry.all_unit_states()
            for unit_state in all_states:
                if unit_state.current_territory_info:
                    was_something_deduced = unit_state.spread_territory_info(compute_geometries=self.load_geometries, verbose = verbose, iteration = 'additional' + str(i))
                    if was_something_deduced: was_anything_deduced = True

        # Update information: the territory info (and territories themselves) were loaded.
        self.territories_info_deduced = True
        if self.load_geometries:
            self.territories_deduced = True

        end_time = time.time()
        execution_time = end_time - start_time
        print(f"✅ All possible information on territories deduced {execution_time:.2f} seconds.")
        
    
    def _populate_territories_fallback(self):
        """
        Fills fallback district state territories for all states with missing territory information.
        Uses simply the next later existing state with territory, or the last earlier one if no later one exists.
        """
        print("Defining fallback territories for states with missing state information (where possible).")
        start_time = time.time()
        
        for dist in self.dist_registry.unit_list:
            n_last_state_with_ter = None # Index of the last state with defined territory in the dist.states list.
            current_ter_info = None
            current_ter = None

            # Backward pass: fill with next known territory
            for i in range(len(dist.states)-1, -1, -1): # Loop descending from len(dist.states)-1 to 0
                # If the dist state has a defined territory, save it as the best guess for the previous territories
                if dist.states[i].current_territory_info is not None:
                    current_ter_info = dist.states[i].current_territory_info
                    if self.load_geometries:
                        current_ter = dist.states[i].current_territory
                    if n_last_state_with_ter is None:
                        n_last_state_with_ter = i
                else: # If not, use the currently best guess as the state territory
                    if current_ter_info is not None:
                        dist.states[i].current_territory_info = current_ter_info
                        if self.load_geometries:
                            dist.states[i].current_territory = current_ter
                        dist.states[i].territory_is_fallback = True
            
            # Forward fill for states after the last one with known territory
            if n_last_state_with_ter is not None:
                current_ter_info = dist.states[n_last_state_with_ter].current_territory_info
                if self.load_geometries:
                    current_ter = dist.states[n_last_state_with_ter].current_territory
                for i in range(n_last_state_with_ter+1, len(dist.states)):
                    dist.states[i].current_territory_info = current_ter_info
                    if self.load_geometries:
                        dist.states[i].current_territory = current_ter
                    dist.states[i].territory_is_fallback = True
            else:
                print(f"[Warning] The district '{dist.name_id}' has no defined territory in any state. All district states' territories left as undefined (None).")
        
        # Update information: the territory info (and territories themselves) were loaded.
        self.fallback_territories_info_created = True
        if self.load_geometries:
            self.fallback_territories_created = True

        # Print success message
        end_time = time.time()
        execution_time = end_time - start_time
        print(f"✅ Successfully created fallback territories in {execution_time:.2f} seconds.")

    def _load_cities(self):
        """
        Loads the geojson with cities from path defined in self.cities_path and stores it in the
        self.cities_df attribute.
        """
        if not os.path.exists(self.cities_path):
            print(f"❌ File not found: {self.cities_path}")
            self.cities_df = None
            return

        try:
            self.cities_df = gpd.read_file(self.cities_path)
            print(f"✅ Successfully loaded {len(self.cities_df)} cities from {self.cities_path}")
        except Exception as e:
            print(f"⚠️ Error while loading cities from {self.cities_path}: {e}")
            self.cities_df = None

    def list_change_dates(self, lang = "pol"):
        # Lists all the dates of administrative changes.
        if lang == "pol":
            print("Wszystkie daty zmian granic:")
        elif lang == "eng":
            print("All dates of administrative changes:")
        else:
            raise ValueError("Wrong value for the lang parameter.") 
        for date in self.changes_dates: print(date)

    def summarize_by_date(self, lang = "pol"):
        # Prints all changes ordered by date.
        for change in self.changes_list:
            change.echo(lang)

    def print_all_states(self):
        for state in self.states_list:
            print(state)

    def find_adm_state_by_date(self, date: datetime) -> AdministrativeState:
        """
        Returns an administrative state with date encompassing the passed date or None if such state was not found.
        """
        for adm_state in self.states_list:
            if date in adm_state.timespan:
                return adm_state
        return None

    def identify_state(self, r_d_aim_list):
        """
        Takes sorted list of (region, district) pairs and identifies the HOMELAND administrative state that it represents.
        """
        # Find the closest district list:
        r_lists_distance = []
        d_lists_distance = []
        state_distances = []
        for state in self.states_list:
            r_list_comparison, d_list_comparison, state_comparison = state.compare_to_r_d_list(r_d_aim_list)
            r_list_distance, r_list_differences = r_list_comparison
            d_list_distance, d_list_differences = d_list_comparison
            state_distance, state_differences = state_comparison
            r_lists_distance.append((r_list_distance, r_list_differences, str(state)))
            d_lists_distance.append((d_list_distance, d_list_differences, str(state)))
            state_distances.append((state_distance, state_differences, str(state)))
            if state_distance == 0:
                print(f"The state identified as: {state}")
                return

        r_lists_distance.sort()
        d_lists_distance.sort()
        state_distances.sort()

        print("No state identified.")

        print("The closest states in terms of region lists:")
        for i, (distance, diff, state) in enumerate (r_lists_distance[:3]):
            diff_1, diff_2 = diff
            print(f"{i}. State {state} (distance: {distance}).\n Absent in list to identify: {diff_1}.\n Absent in state: {diff_2}.")
        
        print("The closest states in terms of district lists:")
        for i, (distance, diff, state) in enumerate (d_lists_distance[:3]):
            diff_1, diff_2 = diff
            print(f"{i}. State {state} (distance: {distance}).\n Absent in list to identify: {diff_1}.\n Absent in state: {diff_2}.")
        
        print("The closest states:")
        for i, (distance, diff, state) in enumerate(state_distances[:3]):
            diff_1, diff_2 = diff
            print(f"{i}. State {state} (distance: {distance}).\n Absent in list to identify: {diff_1}.\n Absent in state: {diff_2}.")

    def coords_to_dist_address(self, lat: float, lon: float, date: datetime):
        """
        This method identifies the district that the point of the given coordinates at a given date
        belongs to, and returns its address.
        """
        # Recover the gdf layer and the adm. state for the given date
        gdf_layer = self.dist_registry._plot_layer(date)
        adm_state = self.find_adm_state_by_date(date)

        # Create a point in the same CRS as gdf_layer (assuming EPSG:4326 WGS84)
        point = Point(lon, lat)

        # Spatial join or manual check
        match = gdf_layer[gdf_layer.contains(point)]

        if match.empty:
            return None  # point not inside any district
    
        # Recover the unit name
        dist_name = match.iloc[0]["name_id"]

        address = adm_state.find_address(dist_name, 'District')

        # Return the name_id of the first matching district
        return address