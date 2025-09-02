import json
from pathlib import Path
from datetime import datetime
from pydantic import parse_obj_as, ValidationError
from typing import List
import shutil
import geopandas as gpd
import pandas as pd
import numpy as np
import os
import sys
from collections import defaultdict
import plotly.express as px
import time

from data_models.adm_timespan import *
from data_models.adm_unit import *
from data_models.adm_state import *
from data_models.adm_change import *
from data_models.econ_data_metadata import *
from data_models.harmonization_config import *

from utils.helper_functions import load_config, standardize_df, read_economic_csv_input
from utils.exceptions import TerritoryNotLoadedError

"""
This is the core component of the toolkit.

When an instance of AdministrativeHistory is created, the object reads in the input data
and creates the data model of the administrative history.

The method 'harmonize_data' automatically creates all necessary harmonization matrices
and harmonizes all the input data.

Example usage:
    # Load the configuration.
    config = load_config("config.json")

    # Create an AdministrativeHistory instance.
    administrative_history = AdministrativeHistory(config, load_geometries=True)

    # Harmonize input data stored in the folder defined in the config.
    administrative_history.harmonize_data()
"""

class AdministrativeHistory():
    def __init__(self, config, load_geometries=True, populate_fallback = True):
        # Load the configuration
        config = load_config("config.json")
        
        # Input files' paths
        self.changes_list_path = config["changes_list_path"]
        self.initial_adm_state_path = config["initial_adm_state_path"]
        self.initial_region_list_path = config["initial_region_list_path"]
        self.initial_dist_list_path = config["initial_dist_list_path"]
        self.territories_path = config["territories_path"]
        self.data_to_harmonize_metadata_path = config["data_to_harmonize_metadata_path"]
        self.harmonization_config_path = config["harmonization_config_path"]
        self.harmonize_to_date = datetime.strptime(config["harmonize_to_date"], "%d.%m.%Y")
        self.data_harmonization_input_folder = config["data_harmonization_input_folder"]
        self.data_harmonization_output_folder = config["data_harmonization_output_folder"]
        self.harmonization_errors_output_path = config["harmonization_errors_output_path"]
        self.post_processing_errors_output_path = config["post_processing_errors_output_path"]
        self.harmonization_metadata_output_path = config["harmonization_metadata_output_path"]

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

        self._load_harmonization_metadata()

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
            print(f"✅ Loaded {n_districts} validated districts in {execution_time:.2f} seconds. Set their initial state timespands to {TimeSpan(start = self.timespan.start, end = self.timespan.end)}.")
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
            print(f"✅ Loaded {n_regions} validated regions in {execution_time:.2f} seconds. Set their initial state timespands to {TimeSpan(start = self.timespan.start, end = self.timespan.end)}")
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

        for i, date in enumerate(self.changes_dates):
            changes_list = self.changes_chron_dict[date]
            old_state = self.states_list[-1]
            new_state = old_state.apply_changes(changes_list, self.region_registry, self.dist_registry, verbose = False)
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

        # Standardize district and region names to name_ids in the registries
        try:
            unit_suggestions = standardize_df(territories_gdf, self.region_registry, self.dist_registry, columns = ["District"], verbose = False)
        except ValueError as e:
            print("❌ Failed during names standardization of the loaded geometry dataframes:", e)
            raise  # Do NOT assign the error to territories_gdf!

        # Set the territories of the appropriate states
        for idx, row in territories_gdf.iterrows():
            # Retrieve the district name and territory date
            district_name_id = str(row.get("District", ""))
            ter_date = str(row.get("ter_date", ""))
            ter_date = datetime.strptime(ter_date, "%d.%m.%Y")

            # Find the appropriate unit state in the registry
            unit, unit_state, _ = self.dist_registry.find_unit_state_by_date(district_name_id, ter_date)
            if unit_state is None:
                print(f"No match found for district '{district_name_id}' on {ter_date.date()}")
                continue
            
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
        for unit_state in self.states_with_loaded_territory:
            # Spread territory info for every state.
            # If self.load_geometries is True (and so the geometries were loaded), share geometries and territory info.
            # If self.load_geometries is False, share ONLY territory info.
            unit_state.spread_territory_info(compute_geometries=self.load_geometries, verbose = verbose)

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
    
    def _load_harmonization_metadata(self):
        """
        Loads data_tables metadata, harmonization config, and the metadata of previously harmonized data from JSONs stored in relevant paths.
        If the 'harmonize_data' method is called, self.harmonized_data_metadata is overwritten.
        """
        ################## Load data tables metadata ###################
        start_time = time.time()
        print(f"Loading metadata of the data tables that will be harmonized...")
        # Load harmonization metadata from JSON:
        with open(self.data_to_harmonize_metadata_path, 'r', encoding='utf-8') as f:
            harmonization_metadata_raw = json.load(f)
        # Convert each dict to a DataTableMetadata instance
        self.harmonization_metadata: List[DataTableMetadata] = [
            DataTableMetadata(**metadata_dict) for metadata_dict in harmonization_metadata_raw
        ]
        # Sort by orig_adm_state_date
        self.harmonization_metadata.sort(key=lambda metadata: metadata.orig_adm_state_date)

        # Print success message
        end_time = time.time()
        execution_time = end_time - start_time
        print(f"✅ Successfully loaded harmonization data tables metadata in {execution_time:.2f} seconds.")

        ################# Load harmonization config ##################
        start_time = time.time()
        print(f"Loading harmonization config...")
        # Load harmonization config from JSON:
        with open(self.harmonization_config_path, 'r', encoding='utf-8') as f:
            harmonization_config_raw = json.load(f)
        # Convert each dict to a DataTableMetadata instance
        self.harmonization_config = HarmonizationConfig(**harmonization_config_raw)

        # Print success message
        end_time = time.time()
        execution_time = end_time - start_time
        print(f"✅ Successfully loaded harmonization config in {execution_time:.2f} seconds.")

        ################# Load harmonized data metadata ##################
        start_time = time.time()
        print(f"Loading harmonized data metadata...")
        try:
            # Load harmonized data metadata from JSON:
            with open(self.harmonization_metadata_output_path, 'r', encoding='utf-8') as f:
                harmonized_data_metadata_raw = json.load(f)
            # Convert each dict to a DataTableMetadata instance
            self.harmonized_data_metadata: List[DataTableMetadata] = [
                DataTableMetadata(**metadata_dict) for metadata_dict in harmonized_data_metadata_raw
            ]
            # Sort by orig_adm_state_date
            self.harmonized_data_metadata.sort(key=lambda metadata: metadata.orig_adm_state_date)
        except Exception as e:
            print(f"⚠️ Failed to load harmonized data metadata: {e}")
            self.harmonized_data_metadata = []

        # Print success message
        end_time = time.time()
        execution_time = end_time - start_time
        print(f"✅ Successfully loaded harmonized data metadata in {execution_time:.2f} seconds.")

    def _construct_conversion_dict(self, date_from: datetime, date_to: datetime, verbose: bool = False):
        """
        Constructs a dictionary that maps each district (by name_id) existing on `date_from`
        in the dist_registry and in 'HOMELAND' for the date date_from to a dict. of districts
        existing on `date_to` and in 'HOMELAND' on that date, with each entry indicating
        the proportion of the territory that overlaps between the two.

        If no territory is defined for one of the districts that are related between the changes,
        fallback computations are used.

        This mapping is intended to support the harmonization of spatial datasets between
        administrative states valid at different times. Specifically, it provides the proportion
        of each `date_from` district’s territory that should be reassigned to corresponding
        `date_to` districts during a temporal boundary adjustment or data transformation process.

        Returns:
            dict[str, dict[str, float]]: A nested dictionary in the form:
                {
                    "district_id_on_date_from": {
                        "district_id_on_date_to": proportion_of_overlap,
                        ...
                    },
                    ...
                }
        """
        if not self.territories_loaded:
            raise TerritoryNotLoadedError(f"Attempted to construct conversion dict, but territories were not loaded.")
        if not self.territories_deduced:
            raise TerritoryNotLoadedError(f"Attempted to construct conversion dict, but the territories were not deduced yet.")
        if not self.fallback_territories_created:
            raise TerritoryNotLoadedError(f"Attempted to construct conversion dict, but the fallback territories were not created yet.")
        
        start_time = time.time()

        if verbose:
            print(f"Constructing conversion dict between adm. states valid for dates {date_from.date()} and {date_to.date()}")

        conversion_dict = {}

        state_from = self.find_adm_state_by_date(date_from)
        from_dist_names = state_from.all_district_names(homeland_only=True)

        state_to = self.find_adm_state_by_date(date_to)
        to_dist_names = state_to.all_district_names(homeland_only=True)

        # If date_from.date() == date_to.date(), return mapping of every district to itself.
        if date_from.date()==date_to.date():
            return {dist_name: {dist_name: 1.0} for dist_name in from_dist_names}

        for from_dist in self.dist_registry.unit_list:
            if from_dist.name_id in from_dist_names:
                from_state = from_dist.find_state_by_date(date_from)
                if from_state is not None:
                    from_state_dict = {}
                    if from_state.current_territory is None:
                        # If neither deduced or fallback teritory is defined for a dist at date 'date_from',
                        # pass all its values to itself if the dist still exists at date_to
                        if from_dist.exists(date_to):
                            from_state_dict = {from_dist.name_id: 1.0}
                            if verbose:
                                print(f"Territory of the district {from_dist.name_id} is not defined for {date_from.date()}. Ascribed the whole proportion of its territory to itself on date {date_to.date()}.")
                        else:
                            # if not, distribute the dist values evenly across the districts:
                            #   - the dist was dissolved to if date_to>date_from
                            #   - the dist was created from if date_to<date_from
                            if date_to>date_from:
                                # Find the last state of the dist that existed before date_to
                                last_state_from_dist = from_state
                                next_state_to_consider = last_state_from_dist.next
                                while next_state_to_consider is not None:
                                    if next_state_to_consider.timespan.end > date_to:
                                        raise ValueError(f"The district {from_dist.name_id} on the date {date_to.date()} didn't exist according to the method 'District.exists' but it has a state with timespan {str(from_dist.timespan)}.")
                                    else:
                                        last_state_from_dist = next_state_to_consider
                                        next_state_to_consider = last_state_from_dist.next
                                # Find districts the dist was dissolved to and that still exist at date_to
                                dists_after_abolishment = [dist.name_id for dist, dist_state in last_state_from_dist.next_change.dist_ter_to if dist.exists(date_to)]
                                # Ascribe same proportion to every district in dists_after_abolishment
                                if len(dists_after_abolishment) == 0:
                                    print(f"No districts that the dist {from_dist.name_id} was dissolved to exist on the date {date_to.date()}. Its data will not be ascribed to any district.")
                                    from_state_dict = {}
                                else:
                                    from_state_dict = {dist_name: 1.0/len(dists_after_abolishment) for dist_name in dists_after_abolishment}
                            else:
                                # Find the first state of the dist that existed after date_to
                                first_state_from_dist = from_state
                                previous_state_to_consider = first_state_from_dist.previous
                                while previous_state_to_consider is not None:
                                    if previous_state_to_consider.timespan.start < date_to:
                                        raise ValueError(f"The district {from_dist.name_id} on the date {date_from.date()} didn't exist according to the method 'District.exists', but it has a state with timespan {str(from_dist.timespan)}.")
                                    else:
                                        first_state_from_dist = previous_state_to_consider
                                        previous_state_to_consider = first_state_from_dist.previous
                                # Find districts the dist was dissolved to and that existed at date_from
                                dists_created_from = [dist.name_id for dist, dist_state in first_state_from_dist.previous_change.dist_ter_from if dist.exists(date_from)]
                                # Ascribe same proportion to every district in dists_after_abolishment
                                if len(dists_created_from) == 0:
                                    print(f"No districts that the dist {from_dist.name_id} was created from exist on the date {date_to.date()}. Its data will not be ascribed to any district.")
                                    from_state_dict = {}
                                else:
                                    from_state_dict = {dist_name: 1.0/len(dists_created_from) for dist_name in dists_created_from}

                            if verbose:
                                print(f"Territory of the district {from_dist.name_id} is not defined for {date_from.date()}. Distributed its territory evenly.")
                    else:
                        dists_no_ter_defined = []
                        if verbose:
                            print(f"Searching districts related by territory to the district {from_dist.name_id}.")
                        ter_related_dict = from_state.get_states_related_by_ter(from_dist.name_id, date_to, verbose = verbose)
                        # Compute the intersection of every district in ter_related_dict with the from_dist if it has a territory defined.
                        # If not, add it to the dists_no_ter_defined list.
                        for to_dist_name_id, to_state in ter_related_dict.items():
                            if to_dist_name_id in to_dist_names:
                                if to_state.current_territory is None:
                                    dists_no_ter_defined.append(to_dist_name_id)
                                else:
                                    intersection_with_dist_area = from_state.current_territory.intersection(to_state.current_territory).area
                                    from_state_area = from_state.current_territory.area
                                    from_state_dict[to_dist_name_id] = intersection_with_dist_area / from_state_area if from_state_area else 0
                        # Now take the proportion left after all other proportions are subtracted from 1.0
                        # and distribute it evenly across the districts in ter_related_dict that have no territory defined.
                        proportions_sum = sum(from_state_dict.values())
                        # Compute proportion left. If it's negative (e.g. because some territories are fallback and so inaccurate), set it to 0.
                        proportion_left = max(0, 1.0-proportions_sum)
                        # Distribute the proportion left evenly across the dists with no territory information.
                        if len(dists_no_ter_defined)>0:
                            for to_dist_name_id in dists_no_ter_defined:
                                from_state_dict[to_dist_name_id] = proportion_left/len(dists_no_ter_defined)
                        
                        # Standardize the proportions to 1.0:
                        all_proportions_sum = sum(from_state_dict.values())
                        if all_proportions_sum>0:
                            from_state_dict = {dist_name: proportion/all_proportions_sum for dist_name, proportion in from_state_dict.items()}
                        else:
                            if verbose:
                                print(f"Cannot standardize values in the dict {from_state_dict}.")

                        # Print message if verbose is True
                        if verbose:
                            if len(dists_no_ter_defined)>0:
                                dists_no_ter_defined_dict = {dist_name: from_state_dict[dist_name] for dist_name in dists_no_ter_defined}
                                print(f"Territory of district {from_dist.name_id} on the date {date_from.date()} is defined, but between {date_from.date()} and {date_to.date()} it shared territories with districts with no territory information on {date_to.date()}. Ascribed the following proportions to the districts: {dists_no_ter_defined_dict}.")
                
                conversion_dict[from_dist.name_id] = from_state_dict
                if verbose:
                    print(f"Conversion dict for district {from_dist.name_id} constructed: {from_state_dict}")

        end_time = time.time()
        execution_time = end_time - start_time
        print(f"✅ Successfully constructed conversion dict in {execution_time:.2f} seconds.")
        return conversion_dict
    
    def construct_conversion_matrix(self, adm_level: Union[Literal['Region'], Literal['District']], date_from: datetime, date_to: datetime, verbose: bool = False):
        """
        Constructs a pandas DataFrame representing a conversion matrix between administrative
        state valid for date 'date_from and administrative state valid for date 'date_to'.

        If adm_level == 'District':
            The rows of the matrix correspond to districts existing on `date_from` in 'HOMELAND',
            and the columns correspond to districts existing on `date_to` in 'HOMELAND'.
        If adm_level == 'Region':
            The rows of the matrix correspond to districts existing on `date_from` in 'HOMELAND',
            and the columns correspond to districts existing on `date_to` in 'HOMELAND'.
            In the current version of the tookit the data on the region level are NOT harmonized
            - i.e. the function returns an identity matrix.

        Returns:
            pd.DataFrame: A DataFrame with shape (len(dists_from), len(dists_to)),
                        where each cell [i, j] represents the proportion of the
                        territory of district/region i (at date_from) that maps to
                        district/region j (at date_to).
        """
        if not self.territories_loaded:
            raise TerritoryNotLoadedError(f"Attempted to construct conversion matrix, but territories were not loaded.")
        if not self.territories_deduced:
            raise TerritoryNotLoadedError(f"Attempted to construct conversion matrix, but the territories were not deduced yet.")
        if not self.fallback_territories_created:
            raise TerritoryNotLoadedError(f"Attempted to construct conversion matrix, but the fallback territories were not created yet.")

        start_time = time.time()
        print(f"Constructing conversion matrix between two administrative states:\nAdministrative State from: {self.find_adm_state_by_date(date_from)}\nAdministrative State to: {self.find_adm_state_by_date(date_to)}")
        
        # Get district name_ids for both dates
        if adm_level == 'District':
            units_from_list = self.find_adm_state_by_date(date_from).all_district_names(homeland_only=True)
            units_to_list = self.find_adm_state_by_date(date_to).all_district_names(homeland_only=True)
        elif adm_level == 'Region':
            units_from_list = self.find_adm_state_by_date(date_from).all_region_names(homeland_only=True)
            units_to_list = self.find_adm_state_by_date(date_to).all_region_names(homeland_only=True)
        else:
            raise ValueError(f"Method AdministrativeHistory.construct_conversion_matrix takes only 'Region' or 'District' as adm_level argument. Passed: {adm_level}.")

        if adm_level == 'District':
            # Initialize empty DataFrame with 0s
            conversion_matrix = pd.DataFrame(
                0.0,
                index=units_from_list,
                columns=units_to_list
            )

            # Get the conversion dictionary with proportions
            conversion_dict = self._construct_conversion_dict(date_from, date_to, verbose = verbose)

            print("Constructing conversion matrix based on the dict.")
            # Fill the matrix
            for from_dist, to_dists_dict in conversion_dict.items():
                for to_dist, proportion in to_dists_dict.items():
                    if from_dist in conversion_matrix.index and to_dist in conversion_matrix.columns:
                        conversion_matrix.at[from_dist, to_dist] = proportion

            end_time = time.time()
            execution_time = end_time - start_time
            print(f"✅ Successfully constructed conversion matrix in {execution_time:.2f} seconds.")
        else:
            # This is a mock function written only for the current version of the toolkit.
            # Check if the list of from- and to-regions is the same. If not, raise error.
            if set(units_from_list) != set(units_to_list):
                missing_adm_state_from = set(units_to_list) - set(units_from_list)
                missing_adm_state_to = set(units_from_list) - set(units_to_list)
                raise ValueError(f"In the current version of the toolkit regions are not harmonized, but there are {len(units_from_list)} regions in the adm. state the data comes from and {len(units_to_list)} regions in the adm. state the data in the whole database is harmonized to.\nMissing in adm_state_from: {missing_adm_state_from}.\nMissing in adm_state_to: {missing_adm_state_to}.")
            else:
                conversion_matrix = pd.DataFrame(
                    0.0,
                    index=units_from_list,
                    columns=units_to_list
                )
                # Fill identity (1.0 where index == column)
                for unit in set(units_from_list) & set(units_to_list):
                    conversion_matrix.loc[unit, unit] = 1.0
        
        return conversion_matrix
    
    def harmonize_data(self):
        """
        Load all data from the self.data_harmonization_input_folder folder, impute the missing data
        according to the methods defined in the metadata json, and harmonize all data
        to the borders for administrative date valid for the self.harmonize_to_date date.
        """
        if not self.territories_loaded:
            raise TerritoryNotLoadedError(f"Attempted to harmonize data in the '{self.data_harmonization_input_folder}' folder, but territories were not loaded.")
        if not self.territories_deduced:
            raise TerritoryNotLoadedError(f"Attempted to harmonize data in the '{self.data_harmonization_input_folder}' folder, but the territories were not deduced yet.")
        if not self.fallback_territories_created:
            raise TerritoryNotLoadedError(f"Attempted to harmonize data in the '{self.data_harmonization_input_folder}' folder, but the fallback territories were not created yet.")

        start_time = time.time()
        print(f"Harmonizing example data in the '{self.data_harmonization_input_folder}' folder.")

        harmonize_from_dict = {}
        conv_matrix = None

        self.harmonized_data_metadata = []
        failed_files = []

        ################################################    Harmonize district data    #####################################################

        district_metadata_dicts = [metadata_dict for metadata_dict in self.harmonization_metadata if metadata_dict.adm_level == 'District']

        for data_table_metadata_dict in district_metadata_dicts:
            try:
                currently_considered_adm_state = self.find_adm_state_by_date(data_table_metadata_dict.orig_adm_state_date)
                if str(currently_considered_adm_state) not in harmonize_from_dict:
                    harmonize_from_dict[str(currently_considered_adm_state)] = []
                    conv_matrix = self.construct_conversion_matrix(
                        adm_level='District',
                        date_from=currently_considered_adm_state.timespan.middle,
                        date_to=self.harmonize_to_date,
                        verbose=False
                    )
                harmonize_from_dict[str(currently_considered_adm_state)].append(data_table_metadata_dict.data_table_id)

                input_csv_path = self.data_harmonization_input_folder + data_table_metadata_dict.data_table_id + ".csv"
                output_csv_path = self.data_harmonization_output_folder + data_table_metadata_dict.data_table_id + ".csv"

                harmonized_data_table_dict = self.harmonize_csv_file(
                    input_csv_path=input_csv_path,
                    output_csv_path=output_csv_path,
                    data_table_metadata_dict=data_table_metadata_dict,
                    date_to=self.harmonize_to_date,
                    conv_matrix=conv_matrix
                )

                self.harmonized_data_metadata.append(harmonized_data_table_dict)

            except Exception as e:
                error_msg = f"❌ {data_table_metadata_dict.data_table_id}: {e}"
                print(error_msg)
                failed_files.append(error_msg)

        ################################################     Harmonize region data     #####################################################

        region_metadata_dicts = [metadata_dict for metadata_dict in self.harmonization_metadata if metadata_dict.adm_level == 'Region']

        for data_table_metadata_dict in region_metadata_dicts:
            try:
                input_csv_path = self.data_harmonization_input_folder + data_table_metadata_dict.data_table_id + ".csv"
                output_csv_path = self.data_harmonization_output_folder + data_table_metadata_dict.data_table_id + ".csv"

                conv_matrix = self.construct_conversion_matrix(
                    adm_level='Region',
                    date_from=currently_considered_adm_state.timespan.middle,
                    date_to=self.harmonize_to_date,
                    verbose=False
                )
                
                harmonized_data_table_dict = self.harmonize_csv_file(
                    input_csv_path=input_csv_path,
                    output_csv_path=output_csv_path,
                    data_table_metadata_dict=data_table_metadata_dict,
                    date_to=self.harmonize_to_date,
                    conv_matrix=conv_matrix
                )

                self.harmonized_data_metadata.append(harmonized_data_table_dict)

            except Exception as e:
                error_msg = f"❌ {data_table_metadata_dict.data_table_id}: {e}"
                print(error_msg)
                failed_files.append(error_msg)

        end_time = time.time()
        execution_time = end_time - start_time

        print(f"✅ Finished harmonization in {execution_time:.2f} seconds.")

        # Save self.harmonized_data_metadata to JSON file
        # Write the dictionary to JSON
        # Dump using Pydantic's JSON serialization (handles datetime etc. properly)
        with open(self.harmonization_metadata_output_path, 'w', encoding='utf-8') as f:
            json_str = json.dumps([model.model_dump(mode="json") for model in self.harmonized_data_metadata], ensure_ascii=False, indent=4)
            f.write(json_str)

        # Create log file with harmonization errors
        with open(self.harmonization_errors_output_path, 'w', encoding='utf-8') as f:
            f.write("Harmonization Errors:\n\n")
            for error in failed_files:
                f.write(error + '\n')
        # Write errors to file if any
        if failed_files:
            print(f"\n⚠️ The following data tables failed to harmonize. See log at: {self.harmonization_errors_output_path}")
        else:
            print("🎉 All data tables harmonized successfully.")

    def harmonize_csv_file(self, input_csv_path: str, output_csv_path: str, data_table_metadata_dict: DataTableMetadata, date_to: Optional[datetime] = None, conv_matrix: Optional[pd.DataFrame] = None):
        """
        Harmonizes district-level numerical data from an input CSV file to match the administrative
        division defined by a target date. The result is saved to the specified output CSV path.

        Args:
            input_csv_path (str): Path to the input CSV. Must contain a 'District' column (or similar).
            output_csv_path (str): Path to save the harmonized output CSV.
            date_to (Optional[datetime]): Target administrative state date. Defaults to `self.harmonize_to_date`.
            data_table_metadata_dict (DataTableMetadata): A DataTableMetadata instance holding metadata about the data table.
            conv_matrix (Optional[pd.DataFrame]): Optional precomputed conversion matrix.
                If not provided, one is constructed automatically.

        Returns:
            data_table_metadata_dict (DataTableMetadata): The updated DataTableMetadata instance with the data table's metadata dict.

        Notes:
            - Automatically detects CSV delimiter and handles missing values (e.g., 'X').
            - Only numeric columns are harmonized. Text columns are ignored.
        """
        if not self.territories_loaded:
            raise TerritoryNotLoadedError(f"Attempted to harmonize the '{input_csv_path}' file, but territories were not loaded.")
        if not self.territories_deduced:
            raise TerritoryNotLoadedError(f"Attempted to harmonize the '{input_csv_path}' file, but the territories were not deduced yet.")
        if not self.fallback_territories_created:
            raise TerritoryNotLoadedError(f"Attempted to harmonize the '{input_csv_path}' file, but the fallback territories were not created yet.")
        
        start_time = time.time()
        if date_to is None:
            date_to = self.harmonize_to_date
        adm_state_date_from=data_table_metadata_dict.orig_adm_state_date
        adm_level = data_table_metadata_dict.adm_level
        print(f"Harmonizing csv with {adm_level} data file '{input_csv_path}' from {adm_state_date_from.date()} to {date_to.date()}.\nOriginal borders: {str(self.find_adm_state_by_date(adm_state_date_from))}.\nTarget borders: {str(self.find_adm_state_by_date(date_to))}.")
        
        # --- Step 1: Load and clean the input data file ---
        df_input_numeric = read_economic_csv_input(adm_level = adm_level, input_csv_path=input_csv_path)
        numeric_cols = list(set(df_input_numeric.columns)-{adm_level})

        # --- Step 2: Get or build the conversion matrix ---
        if conv_matrix is None:
            print(f"⏳ Building conversion matrix from {adm_state_date_from.date()} to {self.harmonize_to_date.date()}...")
            date_from = data_table_metadata_dict.orig_adm_state_date
            conv_matrix = self.construct_conversion_matrix(adm_level=adm_level, date_from=date_from, date_to=date_to, verbose=True)

        # --- Step 3: Diagnostics ---
        input_districts = set(df_input_numeric.index)
        matrix_districts = set(conv_matrix.index)

        missing_in_input = matrix_districts - input_districts
        missing_in_matrix = input_districts - matrix_districts

        if missing_in_input:
            message_lines = [f"⚠️ {adm_level}s in conversion matrix but NOT in input data:"]
            for dist in sorted(missing_in_input):
                message_lines.append(f"  - {dist}")
            raise ValueError("\n".join(message_lines))

        if missing_in_matrix:
            print(f"⚠️ {adm_level}s in input data but NOT in conversion matrix:")
            for dist in sorted(missing_in_matrix):
                print(f"  - {dist}")

        # Filter matrix and input to only overlapping districts
        common_districts = list(input_districts & matrix_districts)
        conv_matrix_filtered = conv_matrix.loc[common_districts]
        df_input_filtered = df_input_numeric.loc[common_districts]

        print(f"df_input_filtered.shape before sorting: {df_input_filtered.shape}")

        if conv_matrix_filtered.empty:
            raise ValueError("No matching districts found between input data and conversion matrix.")
        
        # --- Step 4: Compute data completeness ---
        # Count of non-NaN values used in each aggregation

        # Align both by index intersection and ensure consistent order
        df_input_filtered = df_input_filtered.sort_index()
        conv_matrix_filtered = conv_matrix_filtered.sort_index()

        """ Uncomment for debugging purposes.
        print(f"df_input.shape: {df_input.shape}")
        print(f"conv_matrix.shape: {conv_matrix.shape}")
        print(f"conv_matrix_filtered.shape: {conv_matrix_filtered.shape}")
        print(f"df_input.shape: {df_input.shape}")
        print(f"df_input_filtered.shape after sorting: {df_input_filtered.shape}.")
        print(f"len(numeric_cols) = {len(numeric_cols)}.")
        print(f"df_input_filtered.shape = {df_input_filtered.shape}.")
        print(f"df_input_filtered.notna().shape = {df_input_filtered.notna().shape}")
        print(f"df_input_filtered.notna().astype(float).shape = {df_input_filtered.notna().astype(float).shape}.")
        """

        # Now compute the data mask
        data_mask = df_input_filtered.notna().astype(float)

        print("Matrix shapes:")
        print(" - conv_matrix_filtered.T:", conv_matrix_filtered.T.shape)
        print(" - data_mask:", data_mask.shape)
        print(" - common index alignment:", df_input_filtered.index.equals(conv_matrix_filtered.index))

        # Compute the completeness
        column_completeness = df_input_filtered.notna().mean()
        column_n_not_na = df_input_filtered.notna().sum()
        column_n_na = df_input_filtered.isna().sum()
        print("📊 Data completeness of all numeric columns found:")
        for col, completeness in column_completeness.items():
            print(f"  - {col}: {completeness:.2%}")

        # --- Step 5: Imputation ---
        imputation_method = data_table_metadata_dict.imputation_method
        if imputation_method is not None:
            df_input_filtered = self.impute_data(df=df_input_filtered, adm_state_date=adm_state_date_from, numeric_cols=numeric_cols, method = imputation_method)

            # Compute the completeness after imputation
            column_completeness_after_imputation = df_input_filtered.notna().mean()
            column_n_not_na_after_imputation = df_input_filtered.notna().sum()
            column_n_na_after_imputation = df_input_filtered.isna().sum()
            print("📊 Data completeness of all numeric columns after imputation:")
            for col, completeness in column_completeness_after_imputation.items():
                print(f"  - {col}: {completeness:.2%}")

        print("Matrix shapes after imputation:")
        print(" - conv_matrix_filtered.T:", conv_matrix_filtered.T.shape)
        print(" - df_input_filtered:", df_input_filtered.shape)
        print(" - common index alignment:", df_input_filtered.index.equals(conv_matrix_filtered.index))

        # --- Step 6: Harmonization ---
        print("🔄 Applying harmonization...")
        # Fill NaNs with 0s to avoid NaN propagation in dot product
        df_input_filled = df_input_filtered.fillna(0)
        df_harmonized = conv_matrix_filtered.T @ df_input_filled
        df_harmonized = df_harmonized.reset_index().rename(columns={'index': adm_level})

        # --- Step 7: Save to CSV ---
        df_harmonized.to_csv(output_csv_path, index=False)
        end_time = time.time()
        execution_time = end_time - start_time

        # --- Step 8: Update harmonization data table metadata dict
        # numpy.float64 and numpy.int64 are cast to native python float and int types to allow for pydantic serialization.
        for col in numeric_cols:
            if col in data_table_metadata_dict.columns.keys():
                data_table_metadata_dict.columns[col].completeness = float(column_completeness[col])
                data_table_metadata_dict.columns[col].n_na = int(column_n_na[col])
                data_table_metadata_dict.columns[col].n_not_na = int(column_n_not_na[col])

                if imputation_method is not None:
                    data_table_metadata_dict.columns[col].completeness_after_imputation = float(column_completeness_after_imputation[col])
                    data_table_metadata_dict.columns[col].n_na_after_imputation = int(column_n_na_after_imputation[col])
                    data_table_metadata_dict.columns[col].n_not_na_after_imputation = int(column_n_not_na_after_imputation[col])
            else:
                raise ValueError(f"Column '{col}' found in the data table '{input_csv_path}', but it doesn't exist in the data tables harmonization metadata.")
            
        data_table_metadata_dict.adm_state_date = self.harmonize_to_date
        print(f"Set data_table_metadata_dict.adm_state_date to {self.harmonize_to_date.date()}.\data_table_metadata_dict: {data_table_metadata_dict}.")
        print(f"✅ Successfully harmonized '{input_csv_path}' and saved to '{output_csv_path}' in {execution_time:.2f} seconds")       

        return data_table_metadata_dict

    def impute_data(self, df: pd.DataFrame, adm_state_date: datetime, numeric_cols: List[str], method: str) -> pd.DataFrame:
        """
        Imputes missing data in a DataFrame using the specified method.

        Parameters:
        - df (pd.DataFrame): The input DataFrame with missing values.
        - method (str): The imputation method ('mean', 'median', 'mode', etc.).

        Returns:
        - pd.DataFrame: The imputed DataFrame.
        """
        # Example implementation:
        if method == "mean":
            return df.fillna(df.mean())
        elif method == "median":
            return df.fillna(df.median())
        elif method == "mode":
            return df.fillna(df.mode().iloc[0])
        elif method == "take_from_closest_centroid":
            from data_processing.imputation import take_from_closest_centroid
            return take_from_closest_centroid(administrative_history=self, df=df, numeric_cols=numeric_cols, adm_state_date=adm_state_date)
        else:
            raise ValueError(f"Unknown imputation method: {method}")
        
    def post_organization_reorganize_data_tables(self):
        """
        Reorganizes data tables (e.g. sums them up to one) after the harmonization of all data.
        Takes arguments defined in self.harmonization_config and reorganized generated data, as well as metadata.

        Parameters:

        Returns:

        """
        failed_methods = []

        print(f"Beginning post-processing. Total number of methods to apply: {len(self.harmonization_config.post_harmonization_reorganize_data_tables)}")

        for i, method_dict in enumerate(self.harmonization_config.post_harmonization_reorganize_data_tables):
            try:
                if method_dict.method_name == "sum_up_data_tables":
                    print("Calling sum_up_data_tables method...")
                    from data_processing.post_processing import sum_up_data_tables
                    sum_up_data_tables(self, method_dict.arguments)
                elif method_dict.method_name == "create_dist_area_dataset":
                    print("Calling create_dist_area_dataset method...")
                    from data_processing.post_processing import create_dist_area_dataset
                    create_dist_area_dataset(self, method_dict.arguments)
                else:
                    raise ValueError(f"The method {method_dict.method_name} is not supported.")
            except Exception as e:
                error_msg = f"❌ {i}. method in the post_processing sequence ({method_dict.method_name}): {e}"
                print(error_msg)
                failed_methods.append(error_msg)
        
        # Dump harmonization_metadata (overwriting the previous instance)
        with open(self.harmonization_metadata_output_path, 'w', encoding='utf-8') as f:
            json_str = json.dumps([model.model_dump(mode="json") for model in self.harmonized_data_metadata], ensure_ascii=False, indent=4)
            f.write(json_str)

        # Create log file with harmonization errors
        with open(self.post_processing_errors_output_path, 'w', encoding='utf-8') as f:
            f.write("Post-Processing Errors:\n\n")
            for error in failed_methods:
                f.write(error + '\n')
        # Write errors to file if any
        if failed_methods:
            print(f"\n⚠️ The following post-processing methods failed. See log at: {self.post_processing_errors_output_path}")
        else:
            print("🎉 All post-processing methods applied successfully.")
    
    def load_data_table(
                        self,
                        data_table_id: str,
                        version: Union[Literal['original'], Literal['harmonized']],
                        custom_grouping: Dict[str, str] = None,
                        custom_grouping_method: Union[Literal['sum'], Literal['average']] = 'average'
                    ):
        """
        This function is the basic API accesspoint to the economic database.
        It imports the given data_table in the original form or its harmonized version.
        
        Parameters:
        - data_table_id (str): ID of the data table.
        - version (str): 'original' or 'harmonized'.
        - custom_grouping (dict): Optional mapping from index to custom group name.
        - custom_grouping_method (str): 'sum' or 'average' for how to aggregate grouped data.
        
        Returns:
        - df (pd.DataFrame): The processed data table.
        - data_table_metadata: Metadata object.
        - adm_state_date: Reference date of administrative state.
        """
        if version == 'harmonized':
            data_table_metadata_list = [data_table for data_table in self.harmonized_data_metadata if data_table.data_table_id == data_table_id]
            if len(data_table_metadata_list) == 0:
                raise ValueError(f"No data table with the given id exists.")
            data_table_metadata = data_table_metadata_list[0]
            adm_state_date = self.harmonize_to_date
            folder = self.data_harmonization_output_folder
            path = os.path.join(folder, f"{data_table_id}.csv")
            df = pd.read_csv(path)

            adm_level = data_table_metadata.adm_level

            if adm_level not in df.columns:
                raise ValueError(f"'{adm_level}' column missing in data table: {data_table_id}")
            
            df.set_index(adm_level, inplace=True)
        else:
            data_table_metadata_list = [data_table for data_table in self.harmonization_metadata if data_table.data_table_id == data_table_id]
            if len(data_table_metadata_list) == 0:
                raise ValueError(f"No data table with the given id exists.")
            data_table_metadata = data_table_metadata_list[0]
            adm_level = data_table_metadata.adm_level
            adm_state_date = data_table_metadata.adm_state_date
            folder = self.data_harmonization_input_folder
            path = os.path.join(folder, f"{data_table_id}.csv")
            df = read_economic_csv_input(adm_level=adm_level, input_csv_path=path)
            
        col_rename_dict = {
            col_name: f"{data_table_metadata.columns[col_name].subcategory}: {data_table_metadata.columns[col_name].subsubcategory}"
            for col_name in df.columns
            if col_name in data_table_metadata.columns
        }
        df.rename(columns=col_rename_dict, inplace = True)

        # Check that the loaded dataframe contains all districts/regions:        
        adm_state = self.find_adm_state_by_date(adm_state_date)

        if adm_level == 'District':
            all_unit_names = adm_state.all_district_names(homeland_only=True)
        else:
            all_unit_names = adm_state.all_region_names(homeland_only=True)

        if set(all_unit_names)!=set(df.index):
            missing_in_df = set(all_unit_names)-set(df.index)
            missing_in_adm_state = set(df.index)-set(all_unit_names)
            raise RuntimeError(f"{adm_level} set for the loaded dataframe doesn't agree with the {adm_level.lower()} set for its adm. state!\nMissing in df: {missing_in_df}\nMissing in adm. state: {missing_in_adm_state}.")
        
        # Apply custom grouping if provided
        if custom_grouping:
            df = df.copy()
            df['__group__'] = df.index.map(custom_grouping)

            if df['__group__'].isnull().any():
                missing_keys = df.index[df['__group__'].isnull()].tolist()
                raise ValueError(f"Missing entries in custom_grouping for: {missing_keys}")

            grouped = df.groupby('__group__')

            if custom_grouping_method == 'sum':
                df = grouped.sum()
            elif custom_grouping_method == 'average':
                df = grouped.mean()
            else:
                raise ValueError("custom_grouping_method must be either 'sum' or 'average'.")

            df.index.name = adm_level  # restore the expected index name
        
        return df, data_table_metadata, adm_state_date

        
    def standardize_address(self):
        """
        To implement later. Every address should be standardized before any use."""
        pass

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

    def plot_dist_changes_by_year(self, homeland_only = True, black_and_white=False):
        """
        Counts the number of districts that were ever changed in administrative history.
        Plots the number of districts with borders changed by year and returns the plot.

        If homeland_only is True, counts only districts that were ever in 'HOMELAND'
        during self.timespan.

        If black_and_white is True, plots in black and white.
        """
        n_dist_changed = 0 # Total number of districts that were changed
        n_districts = 0

        # List of (datetime(year,1,1), datetime(year+1,1,1)) pairs
        year_timespans = [TimeSpan(start = datetime(year, 1, 1), end = datetime(year + 1, 1, 1)) for year in range(self.timespan.start.year, self.timespan.end.year+1)]
        # List to store change type, number of changes and districts affected per year.
        change_records = []
        # Convert each timespan to a label like "1921–1922" (for plotting)
        timespan_labels = [str(year_timespan.start.year) for year_timespan in year_timespans]

        for district in self.dist_registry.unit_list:
            # Check if district was ever homeland:
            was_homeland = False
            for year_timespan in year_timespans:
                current_dist_address = self.find_adm_state_by_date(year_timespan.middle).find_address(district.name_id, 'District')
                if current_dist_address:
                    if current_dist_address[0] == 'HOMELAND':
                        was_homeland = True
            # Count districts if homeland_only is False or the district ever was in 'HOMELAND'
            if not homeland_only or was_homeland:
                n_districts += 1
                print(f"District {district.name_id} belonged to homeland. Num changes: {len(district.changes)}")
                # Count changes per year. We use the 'district.changes', not the 'self.changes_list' list, because we want to count only districts that were ever in 'homeland'.
                # Start with assuring that district changes are sorted. Every element in the district.changes is a pair (change_type, change). We sort first by 'date', then by 'order' attribute.
                district.changes.sort(key=lambda change_pair: (change_pair[1].date, change_pair[1].order is None, change_pair[1].order))
                for i, year_timespan in enumerate(year_timespans):
                    for j, (change_type, change) in enumerate(district.changes):
                        if max(year_timespan.start, self.timespan.start)<change.date<year_timespan.end:
                            # Omit changes if another change followed on the same day (this is simply an artefact of how we describe changes in the toolkit)
                            if j<len(district.changes)-1:
                                if change.date!=district.changes[j+1]:
                                    print(f"Change of type {change_type} was applied to district {district.name_id} on {change.date}.")
                                    change_records.append({
                                        'Year': year_timespan.start.year,
                                        'District': district.name_id,
                                        'Change Type': change_type
                                    })
                            else:
                                print(f"Change of type {change_type} was applied to district {district.name_id} on {change.date}.")
                                change_records.append({
                                        'Year': year_timespan.start.year,
                                        'District': district.name_id,
                                        'Change Type': change_type
                                })
                # Count the district, it it was ever changed or created
                if len(district.changes)>0:
                    n_dist_changed += 1

        print(f"{n_dist_changed}/{n_districts} ({round(n_dist_changed/n_districts*100, 2)}%) of districts{' in homeland' if homeland_only else ''} had their borders changed, were created, abolished, or moved between regions in the given period.")
        
        # Convert the list of change records into a DataFrame
        df_changes = pd.DataFrame(change_records)

        # Group by Year and Change Type to get:
        # - Count of changes
        # - List of district names
        grouped = df_changes.groupby(['Year', 'Change Type']).agg(
            Change_Count=('District', 'count'),
            Districts_List = (
                'District',
                # Truncate the list if it's too long
                lambda districts: (
                    '<br>'.join(sorted(set(districts))[:10]) + 
                    (f"<br>... (+{len(set(districts)) - 10} more)" if len(set(districts)) > 10 else '')
                )

            )
        ).reset_index()

        color_sequence = ['black'] if black_and_white else px.colors.qualitative.Set2 # or any other color scale

        # Create the stacked bar chart with custom hover text
        fig = px.bar(
            grouped,
            x='Year',
            y='Change_Count',
            color='Change Type',
            hover_data={'Districts_List': True, 'Year': False, 'Change_Count': True},
            title='District Changes by Year and Type',
            labels={'Change_Count': 'Number of Districts Affected'},
            color_discrete_sequence=color_sequence,
            barmode='stack'  # <- Use stacked mode
        )

        fig.update_layout(
            xaxis_title='Year',
            yaxis_title='Number of Districts Affected',
            bargap=0.1
        )


        # Customize hover template to display just the districts
        fig.update_traces(
            hovertemplate='<b>%{x}</b><br>%{customdata[0]}<extra></extra>'
        )

        return fig
    
    def generate_adm_state_plots(self):
        """
        Creates and saves plots of all the administrative states in the administrative history.
        """
        import matplotlib.pyplot as plt

        start_time = time.time()
        print("Computing the unary union of all district territories in the registry ('whole_map' geometry).")

        # Create a territory representing the unary union of all territories (the "whole map" shape)
        self.whole_map = unary_union([state.current_territory for state in self.states_with_loaded_territory])

        end_time = time.time()
        execution_time = end_time - start_time
        print(f"✅ Successfully computed 'whole_map' in {execution_time:.2f} seconds.")
        
        print("Creating map plots for every administrative state...")
        start_time = time.time()
        for adm_state in self.states_list:
            region_registry = self.region_registry
            dist_registry = self.dist_registry
            fig = adm_state.plot(region_registry, dist_registry, self.whole_map, adm_state.timespan.middle)
            fig.savefig(f"output/adm_states_maps/"+adm_state.to_label() + ".png", bbox_inches=None)
            plt.close(fig)  # prevent memory buildup
            print(f"Saved adm_state_{adm_state.timespan.start.date()}.png.")


        end_time = time.time()
        execution_time = end_time - start_time
        print(f"✅ Successfully generated all administrative state plots in {execution_time:.2f} seconds and saved to 'output' folder.")

    def plot_dataset(self,
                    df: pd.DataFrame,
                    col_name: str,
                    adm_level: Union[Literal['Region'], Literal['District']],
                    adm_state_date: datetime,
                    save_to_path: str = None,
                    title: str = None,
                    legend_min: float = None,
                    legend_max: float = None,
                    cmap='OrRd',
                    custom_grouping: Dict[str, str] = None):
        """
        Generates a choropleth map of the specified data table column.

        If custom_grouping is passed, it is assumed that df was already grouped
            (i.e. it has the index equal to custom_grouping.values()).

        Parameters:
        - df (pd.DataFrame): DataFrame with index as District or Region names.
        - col_name (str): Column name to visualize.
        - adm_level (str): 'District' (currently only this is supported).
        - adm_state_date (datetime): Reference date for administrative boundaries.
        - custom_grouping (dict, optional): Mapping of unit names to custom groups.

        Returns:
        - fig (matplotlib.figure.Figure): A matplotlib Figure object representing the choropleth map.
        """
        import matplotlib.pyplot as plt

        ##################################### Check proper input df form #######################################

        if adm_level == 'Region':
            adm_state_units = self.find_adm_state_by_date(adm_state_date).all_region_names(homeland_only=True)
        elif adm_level == 'District':
            adm_state_units = self.find_adm_state_by_date(adm_state_date).all_district_names(homeland_only=True)
        else:
            raise ValueError(f"adm_level must be 'Region' or 'District', but '{adm_level}' was passed.")

        if df.index.name != adm_level:
            raise ValueError(f"Method 'AdministrativeHistory.plot_dataset' used with adm_level='{adm_level}' argument, but the passed df doesn't have '{adm_level}' as index.")
            
        if custom_grouping:
            grouped_units = set(custom_grouping.values())
            if grouped_units != set(df.index):
                absent_in_df = grouped_units - set(df.index)
                absent_in_custom_grouping = set(df.index) - grouped_units
                raise ValueError(f"Index in the df to plot doesn't correspond to the custom_grouping values. \nAbsent in set(df.index): {absent_in_df}.\nAbsent in custom_grouping values: {absent_in_custom_grouping}.")
        else:
            if set(df.index) != set(adm_state_units):
                absent_in_df = set(adm_state_units) - set(df.index)
                absent_in_adm_state = set(df.index) - set(adm_state_units)
                raise ValueError (f"Method 'AdministrativeHistory.plot_dataset' used with adm_level='{adm_level}' argument, but the values in the df '{adm_level}' index don't fit the existing {adm_level.lower()} names.\nAbsent in set(df.index): {absent_in_df}.\nAbsent in adm_state: {absent_in_adm_state}.")
            
        #####################################             Plot           #######################################      
        
        if adm_level == 'Region':
            raise ValueError(f"Method 'AdministrativeHistory.plot_dataset' for adm_level='Region' not implemented yet.")
        else:
            dist_plot_layer = self.dist_registry._plot_layer(adm_state_date)
            dist_plot_layer.rename(columns={'name_id': 'District'}, inplace = True)
            dist_plot_layer.set_index('District', inplace = True)

            # --------------------------- Merge ---------------------------
            if custom_grouping:
                dist_plot_layer = dist_plot_layer.copy()
                dist_plot_layer['__group__'] = dist_plot_layer.index.map(custom_grouping)
                dist_plot_layer = dist_plot_layer.dissolve(by='__group__')

                dist_plot_layer = dist_plot_layer.merge(df, left_index=True, right_index=True, how='left')
            else:
                dist_plot_layer = dist_plot_layer.merge(df, left_index=True, right_index=True, how='left')

            # --------------------------- Plot ----------------------------
            
            fig, ax = plt.subplots(figsize=(10, 8))

            if legend_min is not None and legend_max is not None:
                dist_plot_layer.plot(
                    ax=ax,
                    column=col_name,
                    cmap=cmap,
                    legend=True,
                    edgecolor='black',
                    linewidth=1,
                    vmin = legend_min,
                    vmax = legend_max
                )
            else:
                dist_plot_layer.plot(
                    ax=ax,
                    column=col_name,
                    cmap=cmap,
                    legend=True,
                    edgecolor='black',
                    linewidth=1
                )
            ax.axis('off')
            if title is not None:
                ax.set_title(title)
            else:
                ax.set_title(f"{col_name} by District")
            plt.tight_layout()

            if save_to_path:
                fig.savefig(save_to_path, dpi=300, bbox_inches='tight')

        return fig
        
