import json
from datetime import datetime
from typing import List
from shapely.geometry import Point
import geopandas as gpd
import pandas as pd
import time
import traceback
import os
import csv
from collections import defaultdict

from administrative_history.core.core import AdministrativeHistory
from administrative_history.data_models.adm_timespan import *
from administrative_history.data_models.adm_unit import *
from administrative_history.data_models.adm_state import *
from administrative_history.data_models.adm_change import *
from administrative_history.data_models.econ_data_metadata import *
from administrative_history.data_models.processing_config import *

from administrative_history.utils.helper_functions import read_economic_csv_input
from administrative_history.utils.exceptions import TerritoryNotLoadedError

"""
This component can be viewed as the 'injection layer' of the economic database.
Its task is to prepare the raw input data through cleaning, standardization, and
harmonziation for the usage of economic analysis. I uses the underlying model
of administrative history stored in an AdministrativeHistory instance.

The method 'process_raw_data' automatically creates all necessary harmonization matrices
and harmonizes all the input data.

Example usage:
    # Load the configuration.
    config = load_adm_history_config("config.json")
    processing_config = load_processing_config("input/initial_region_state_list.json")

    # Create an AdministrativeHistory instance.
    adm_history = AdministrativeHistory(config, load_geometries=True)
    adm_history_processor = AdministrativeHistoryProcessor(processing_config, adm_history)

    # Harmonize all input data stored in the folder defined in the config.
    adm_history_processor.process_raw_data()
"""

class AdministrativeHistoryProcessor():
    def __init__(self, processing_config, adm_history: AdministrativeHistory):
        # Add administrative history as attribute
        self.adm_history = adm_history
        
        # Verify the structure of the processing config
        self.processing_config = ProcessingConfig(**processing_config)
        self.post_processing_config = self.processing_config.post_processing_config

        self.adm_units_raw_data_metadata_path = self.processing_config.adm_units_raw_data_metadata_path
        self.cities_raw_data_metadata_path = self.processing_config.cities_raw_data_metadata_path
        self.harmonize_to_date = datetime.strptime(self.processing_config.harmonize_to_date, "%d.%m.%Y")
        self.adm_units_raw_data_folder = self.processing_config.adm_units_raw_data_folder
        self.cities_raw_data_folder = self.processing_config.cities_raw_data_folder
        self.processed_data_output_folder = self.processing_config.processed_data_output_folder
        self.harmonization_errors_output_path = self.processing_config.harmonization_errors_output_path
        self.post_processing_errors_output_path = self.processing_config.post_processing_errors_output_path
        self.processed_data_metadata_output_path = self.processing_config.processed_data_metadata_output_path
        self.database_tree_output_path = self.processing_config.database_tree_output_path

        self._load_processed_data_metadata()
    
    def _load_processed_data_metadata(self):
        """
        Loads raw data_tables metadata, processing config, and the metadata of previously harmonized data from JSONs stored in relevant paths.
        If the 'process_raw_data' method is called, self.processed_data_metadata is overwritten.
        """
        ################## Load data tables metadata ###################
        start_time = time.time()
        print(f"Loading metadata of the data tables that will be harmonized...")

        ### Load adm units metadata ###
        # Load raw data metadata from JSON:
        with open(self.adm_units_raw_data_metadata_path, 'r', encoding='utf-8') as f:
            adm_units_raw_data_metadata_raw = json.load(f)
        # Convert each dict to a DataTableMetadata instance
        adm_units_raw_data_metadata: List[DataTableMetadata] = [
            DataTableMetadata(**metadata_dict) for metadata_dict in adm_units_raw_data_metadata_raw
        ]
        # Sort by orig_adm_state_date
        adm_units_raw_data_metadata.sort(key=lambda metadata: metadata.orig_adm_state_date)

        ### Load cities data metadata
        # Load raw data metadata from JSON:
        with open(self.cities_raw_data_metadata_path, 'r', encoding='utf-8') as f:
            cities_raw_data_metadata_raw = json.load(f)
        # Convert each dict to a DataTableMetadata instance
        cities_raw_data_metadata: List[DataTableMetadata] = [
            DataTableMetadata(**metadata_dict) for metadata_dict in cities_raw_data_metadata_raw
        ]
        # Sort by orig_adm_state_date
        cities_raw_data_metadata.sort(key=lambda metadata: metadata.orig_adm_state_date)

        self.raw_data_metadata = adm_units_raw_data_metadata + cities_raw_data_metadata

        # Print success message
        end_time = time.time()
        execution_time = end_time - start_time
        print(f"✅ Successfully loaded metadata of raw data tables in {execution_time:.2f} seconds.")

        ################# Load harmonized data metadata ##################
        start_time = time.time()
        print(f"Loading processed data metadata...")
        try:
            # Load processed data metadata from JSON:
            with open(self.processed_data_metadata_output_path, 'r', encoding='utf-8') as f:
                processed_data_metadata_raw = json.load(f)
            # Convert each dict to a DataTableMetadata instance
            self.processed_data_metadata: List[DataTableMetadata] = [
                DataTableMetadata(**metadata_dict) for metadata_dict in processed_data_metadata_raw
            ]
            # Sort by orig_adm_state_date
            self.processed_data_metadata.sort(key=lambda metadata: metadata.orig_adm_state_date)
        except Exception as e:
            print(f"⚠️ Failed to load harmonized data metadata: {e}")
            self.processed_data_metadata = []

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
        if not self.adm_history.territories_loaded:
            raise TerritoryNotLoadedError(f"Attempted to construct conversion dict, but territories were not loaded to the administrative history.")
        if not self.adm_history.territories_deduced:
            raise TerritoryNotLoadedError(f"Attempted to construct conversion dict, but the territories were not deduced yet in the administrative history.")
        if not self.adm_history.fallback_territories_created:
            raise TerritoryNotLoadedError(f"Attempted to construct conversion dict, but the fallback territories were not created yet in the administrative history.")
        
        start_time = time.time()

        if verbose:
            print(f"Constructing conversion dict between adm. states valid for dates {date_from.date()} and {date_to.date()}")

        conversion_dict = {}

        state_from = self.adm_history.find_adm_state_by_date(date_from)
        from_dist_names = state_from.all_district_names(homeland_only=True)

        state_to = self.adm_history.find_adm_state_by_date(date_to)
        to_dist_names = state_to.all_district_names(homeland_only=True)

        # If date_from.date() == date_to.date(), return mapping of every district to itself.
        if date_from.date()==date_to.date():
            return {dist_name: {dist_name: 1.0} for dist_name in from_dist_names}

        for from_dist in self.adm_history.dist_registry.unit_list:
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
        if not self.adm_history.territories_loaded:
            raise TerritoryNotLoadedError(f"Attempted to construct conversion matrix, but territories were not loaded to the administrative history.")
        if not self.adm_history.territories_deduced:
            raise TerritoryNotLoadedError(f"Attempted to construct conversion matrix, but the territories were not deduced yet in the administrative history.")
        if not self.adm_history.fallback_territories_created:
            raise TerritoryNotLoadedError(f"Attempted to construct conversion matrix, but the fallback territories were not created yet in the administrative history.")

        start_time = time.time()
        print(f"Constructing conversion matrix between two administrative states:\nAdministrative State from: {self.adm_history.find_adm_state_by_date(date_from)}\nAdministrative State to: {self.adm_history.find_adm_state_by_date(date_to)}")
        
        # Get district name_ids for both dates
        if adm_level == 'District':
            units_from_list = self.adm_history.find_adm_state_by_date(date_from).all_district_names(homeland_only=True)
            units_to_list = self.adm_history.find_adm_state_by_date(date_to).all_district_names(homeland_only=True)
        elif adm_level == 'Region':
            units_from_list = self.adm_history.find_adm_state_by_date(date_from).all_region_names(homeland_only=True)
            units_to_list = self.adm_history.find_adm_state_by_date(date_to).all_region_names(homeland_only=True)
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
    
    def process_raw_data(self):
        """
        Load all data from the self.adm_units_raw_data_folder folder, impute the missing data
        according to the methods defined in the metadata json, and harmonize all data
        to the borders for administrative date valid for the self.harmonize_to_date date.
        """
        if not self.adm_history.territories_loaded:
            raise TerritoryNotLoadedError(f"Attempted to harmonize data in the '{self.adm_units_raw_data_folder}' folder, but territories were not loaded to the administrative history.")
        if not self.adm_history.territories_deduced:
            raise TerritoryNotLoadedError(f"Attempted to harmonize data in the '{self.adm_units_raw_data_folder}' folder, but the territories were not deduced yet in the administrative history.")
        if not self.adm_history.fallback_territories_created:
            raise TerritoryNotLoadedError(f"Attempted to harmonize data in the '{self.adm_units_raw_data_folder}' folder, but the fallback territories were not created yet in the administrative history.")

        start_time = time.time()
        print(f"Harmonizing data in the '{self.adm_units_raw_data_folder}' folder.")

        harmonize_from_dict = {} # Dict mapping adm. states to the list of data table ids
        conv_matrix = None

        self.processed_data_metadata = []
        failed_files = []

        ################################################    Harmonize district data    #####################################################

        dist_metadata = [metadata_dict for metadata_dict in self.raw_data_metadata if metadata_dict.adm_level == "District"]
        region_metadata = [metadata_dict for metadata_dict in self.raw_data_metadata if metadata_dict.adm_level == "Region"]
        city_metadata = [metadata_dict for metadata_dict in self.raw_data_metadata if metadata_dict.adm_level == "City"]

        all_metadata = dist_metadata + region_metadata + city_metadata

        for data_table_metadata_dict in all_metadata:
            adm_level = data_table_metadata_dict.adm_level
            try:
                if adm_level in ["Region", "District"]:
                    input_csv_path = self.adm_units_raw_data_folder + data_table_metadata_dict.data_table_id + ".csv"

                    currently_considered_adm_state = self.adm_history.find_adm_state_by_date(data_table_metadata_dict.orig_adm_state_date)
                    
                    if adm_level == 'Region' or (adm_level == "District" and str(currently_considered_adm_state) not in harmonize_from_dict):
                        harmonize_from_dict[str(currently_considered_adm_state)] = []
                        conv_matrix = self.construct_conversion_matrix(
                            adm_level=data_table_metadata_dict.adm_level,
                            date_from=currently_considered_adm_state.timespan.middle,
                            date_to=self.harmonize_to_date,
                            verbose=False
                        )
                    harmonize_from_dict[str(currently_considered_adm_state)].append(data_table_metadata_dict.data_table_id)
                else:
                    input_csv_path = self.cities_raw_data_folder + data_table_metadata_dict.data_table_id + ".csv"

                output_csv_path = self.processed_data_output_folder + data_table_metadata_dict.data_table_id + ".csv"

                processed_data_table_dict = self.process_raw_csv_file(
                    input_csv_path=input_csv_path,
                    output_csv_path=output_csv_path,
                    data_table_metadata_dict=data_table_metadata_dict,
                    date_to=self.harmonize_to_date,
                    conv_matrix=conv_matrix     # For cities it doesn't matter which date_to and conv_matrix are passed.
                )

                self.processed_data_metadata.append(processed_data_table_dict)

            except Exception as e:
                error_msg = (
                    f"❌ {data_table_metadata_dict.data_table_id} failed.\n"
                    f"Exception: {e}\n"
                    f"Traceback:\n{traceback.format_exc()}"
                )
                print(error_msg)
                failed_files.append(error_msg)

        end_time = time.time()
        execution_time = end_time - start_time

        print(f"✅ Finished harmonization in {execution_time:.2f} seconds.")

        # Save self.processed_data_metadata to JSON file
        # Write the dictionary to JSON
        # Dump using Pydantic's JSON serialization (handles datetime etc. properly)
        with open(self.processed_data_metadata_output_path, 'w', encoding='utf-8') as f:
            json_str = json.dumps([model.model_dump(mode="json") for model in self.processed_data_metadata], ensure_ascii=False, indent=4)
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

    def process_raw_csv_file(
        self,
        input_csv_path: str,
        output_csv_path: str,
        data_table_metadata_dict: DataTableMetadata,
        date_to: Optional[datetime] = None,
        conv_matrix: Optional[pd.DataFrame] = None,
    ):
        """
        Process a raw CSV file containing either District- or City-level data.  

        The workflow is divided into four clearly separated steps:

        1. Validation & Loading  
        - Load the CSV into a DataFrame.  
        - Verify structural correctness and validate identifiers 
            (Districts vs conversion matrix; Cities vs reference list).  
        - Compute initial completeness statistics.  

        2. Imputation  
        - Apply imputation according to the metadata instructions.  
        - Recompute completeness after imputation.  

        3. Harmonization  
        - For District-level data only: apply conversion matrix to harmonize 
            input data to the target administrative state.  
        - For City-level data: this step is skipped.  

        4. Saving & Metadata Update  
        - Save the processed DataFrame to CSV.  
        - Update metadata (completeness, imputation, harmonization date, etc.).  
        """

        if not self.adm_history.territories_loaded:
            raise TerritoryNotLoadedError("Territories not loaded to the administrative history.")
        if not self.adm_history.territories_deduced:
            raise TerritoryNotLoadedError("Territories not deduced yet in the administrative history.")
        if not self.adm_history.fallback_territories_created:
            raise TerritoryNotLoadedError("Fallback territories not created yet in the administrative history.")

        start_time = time.time()
        adm_level = data_table_metadata_dict.adm_level
        print(f"Processing '{input_csv_path}' with {adm_level}-level raw data.")

        # ============================================================
        # 1. VALIDATION & LOADING
        # ============================================================
        df_input = read_economic_csv_input(adm_level=adm_level, input_csv_path=input_csv_path)
        numeric_cols = list(set(df_input.columns) - {adm_level})

        if adm_level == "City":
            # ✅ Validate city names against reference list (when "City" is the index)
            valid_city_names = set(self.adm_history.cities_df["City"])
            print(f"Index name: {df_input.index.name}")

            # Keep only valid cities
            df_valid = df_input[df_input.index.isin(valid_city_names)].copy()

            # Track dropped cities
            df_dropped = df_input[~df_input.index.isin(valid_city_names)]
            if not df_dropped.empty:
                dropped_list = df_dropped.index.unique().tolist()
                print(f"⚠️ Dropped {len(dropped_list)} cities due to name mismatch: {dropped_list}")

            df_input_filtered = df_valid

        elif adm_level == "District" or "Region":
            # Build conversion matrix if not provided
            if date_to is None:
                date_to = self.harmonize_to_date
            date_from = data_table_metadata_dict.orig_adm_state_date
            if conv_matrix is None:
                conv_matrix = self.construct_conversion_matrix(
                    adm_level="District", date_from=date_from, date_to=date_to, verbose=True
                )

            # Validate overlap between input and matrix
            input_districts = set(df_input.index)
            matrix_districts = set(conv_matrix.index)
            missing_in_input = matrix_districts - input_districts
            missing_in_matrix = input_districts - matrix_districts

            if missing_in_input:
                raise ValueError(f"Districts in conversion matrix but not in input: {missing_in_input}")
            if missing_in_matrix:
                print(f"⚠️ Districts in input but not in conversion matrix: {missing_in_matrix}")

            common_districts = list(input_districts & matrix_districts)
            df_input_filtered = df_input.loc[common_districts]
            conv_matrix_filtered = conv_matrix.loc[common_districts]

        else:
            raise ValueError(f"Unsupported adm_level: {adm_level}")

        # Compute completeness BEFORE imputation
        column_completeness = df_input_filtered.notna().mean()
        column_n_not_na = df_input_filtered.notna().sum()
        column_n_na = df_input_filtered.isna().sum()

        print("📊 Completeness before imputation:")
        for col, val in column_completeness.items():
            print(f"  - {col}: {val:.2%}")

        # ============================================================
        # 2. IMPUTATION
        # ============================================================
        imputation_method = data_table_metadata_dict.imputation_method
        if imputation_method is not None:
            df_input_filtered = self.impute_data(
                df=df_input_filtered,
                adm_state_date=data_table_metadata_dict.orig_adm_state_date,
                numeric_cols=numeric_cols,
                method=imputation_method,
            )

            # Compute completeness AFTER imputation
            column_completeness_after_imputation = df_input_filtered.notna().mean()
            column_n_not_na_after_imputation = df_input_filtered.notna().sum()
            column_n_na_after_imputation = df_input_filtered.isna().sum()

            print("📊 Completeness after imputation:")
            for col, val in column_completeness_after_imputation.items():
                print(f"  - {col}: {val:.2%}")

        # ============================================================
        # 3. HARMONIZATION
        # ============================================================
        if adm_level in ["District", "Region"]:
            print("🔄 Applying harmonization...")
            df_input_filled = df_input_filtered.fillna(0)
            df_harmonized = conv_matrix_filtered.T @ df_input_filled
            df_output = df_harmonized.reset_index().rename(columns={"index": adm_level})
        else:
            # City-level: skip harmonization
            df_output = df_input_filtered.reset_index().rename(columns={"index": adm_level})

        # ============================================================
        # 4. SAVING & METADATA UPDATE
        # ============================================================
        df_output.to_csv(output_csv_path, index=False)
        end_time = time.time()
        print(f"✅ Finished processing in {end_time - start_time:.2f} seconds. Output: {output_csv_path}")

        # Update metadata
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
                raise ValueError(f"Column '{col}' found in the data table '{input_csv_path}', but it doesn't exist in the raw data table metadata.\nColumns present in metadata: {data_table_metadata_dict.columns.keys()}.")
            
        data_table_metadata_dict.adm_state_date = self.harmonize_to_date
        print(f"Set data_table_metadata_dict.adm_state_date to {self.harmonize_to_date.date()}.\data_table_metadata_dict: {data_table_metadata_dict}.")

        end_time = time.time()
        execution_time = end_time-start_time
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
            from administrative_history.data_processing.imputation import take_from_closest_centroid
            return take_from_closest_centroid(administrative_history=self.adm_history, df=df, numeric_cols=numeric_cols, adm_state_date=adm_state_date)
        else:
            raise ValueError(f"Unknown imputation method: {method}")
        
    def post_processing_reorganize_data_tables(self):
        """
        Reorganizes data tables (e.g. sums them up to one) after the harmonization of all data.
        Takes arguments defined in self.post_processing_config and reorganized generated data, as well as metadata.

        Parameters:

        Returns:

        """
        failed_methods = []

        print(f"Beginning post-processing. Total number of methods to apply: {len(self.processing_config.post_processing_config)}")

        for i, method_dict in enumerate(self.post_processing_config):
            try:
                if method_dict.method_name == "combine_data_tables":
                    print("Calling combine_data_tables method...")
                    from administrative_history.data_processing.post_processing import combine_data_tables
                    combine_data_tables(self, method_dict.arguments)
                elif method_dict.method_name == "create_dist_area_dataset":
                    print("Calling create_dist_area_dataset method...")
                    from administrative_history.data_processing.post_processing import create_dist_area_dataset
                    create_dist_area_dataset(self, method_dict.arguments)
                else:
                    raise ValueError(f"The method {method_dict.method_name} is not supported.")
            except Exception as e:
                error_msg = f"❌ {i}. method in the post_processing sequence ({method_dict.method_name}): {e}"
                print(error_msg)
                failed_methods.append(error_msg)
        
        # Dump processed_data_metadata (overwriting the previous instance)
        with open(self.processed_data_metadata_output_path, 'w', encoding='utf-8') as f:
            json_str = json.dumps([model.model_dump(mode="json") for model in self.processed_data_metadata], ensure_ascii=False, indent=4)
            f.write(json_str)

        # Create log file with post-processing errors
        with open(self.post_processing_errors_output_path, 'w', encoding='utf-8') as f:
            f.write("Post-Processing Errors:\n\n")
            for error in failed_methods:
                f.write(error + '\n')
        # Write errors to file if any
        if failed_methods:
            print(f"\n⚠️ The following post-processing methods failed. See log at: {self.post_processing_errors_output_path}")
        else:
            print("🎉 All post-processing methods applied successfully.")

    def map_city_data_to_dists(self, df: pd.DataFrame, date, geojson_path: str = None, custom_grouping: Dict[str, str] = None,
                        custom_grouping_method: Union[Literal['sum'], Literal['average']] = 'average'):
        """
        Maps a city-indexed dataframe to districts and regions.

        Parameters
        ----------
        df : pd.DataFrame
            Input dataframe where the index contains city names.
        date : any
            Date parameter passed to coords_to_dist_address().
        geojson_path : str, optional
            If provided, writes a GeoJSON file with point geometries of all recognized
            cities and their mapped attributes to this path.

        Returns
        -------
        pd.DataFrame
            Aggregated dataframe with columns ['Region', 'District', 'Cities in district'] 
            and numeric columns summed per district.
        """

        if self.adm_history.cities_df is None:
            raise ValueError("self.adm_history.cities_df is not loaded. Please run self.adm_history.load_cities() first.")

        # ✅ Step 1: Drop unrecognized cities
        valid_city_names = set(self.adm_history.cities_df["City"])
        df_valid = df[df.index.isin(valid_city_names)].copy()
        df_dropped = df[~df.index.isin(valid_city_names)]

        if not df_dropped.empty:
            dropped_list = df_dropped.index.unique().tolist()
            print(f"⚠️ Dropped {len(dropped_list)} cities due to name mismatch: {dropped_list}")

        # ✅ Step 2: Drop rows with NaNs
        df_nans = df_valid[df_valid.isna().any(axis=1)]
        if not df_nans.empty:
            dropped_nans_list = df_nans.index.tolist()
            print(f"⚠️ Dropped {len(dropped_nans_list)} rows due to NaN values: {dropped_nans_list}")
            df_valid = df_valid.dropna()

        if df_valid.empty:
            print("❌ No valid cities remain after filtering. Returning empty DataFrame.")
            return pd.DataFrame(columns=["Region", "District", "Cities in district"])

        # ✅ Step 3: Map each city to a district
        district_records = []
        geo_records = []
        for city_name, row in df_valid.iterrows():
            city_geom = self.adm_history.cities_df.loc[self.adm_history.cities_df["City"] == city_name, "geometry"].iloc[0]
            lat, lon = city_geom.y, city_geom.x  # Point(y=lat, x=lon)

            try:
                country, region, district = self.adm_history.coords_to_dist_address(lat, lon, date)
                record = {
                    "Region": region,
                    "District": district,
                    "City": city_name,
                    **row.to_dict()
                }
                district_records.append(record)

                # For optional GeoJSON export
                geo_records.append({
                    **record,
                    "geometry": Point(lon, lat)  # GeoJSON expects (lon, lat)
                })

            except Exception as e:
                print(f"⚠️ Could not map city '{city_name}' to district: {e}")

        if not district_records:
            print("❌ No cities could be mapped to districts.")
            return pd.DataFrame(columns=["Region", "District", "Cities in district"])

        mapped_df = pd.DataFrame(district_records)

        # ✅ Step 4: Aggregate by Region + District
        agg_dict = {col: "sum" for col in mapped_df.columns if col not in ["Region", "District", "City"]}
        grouped = mapped_df.groupby(["Region", "District"]).agg(agg_dict).reset_index()

        # ✅ Step 5: Collect city names
        city_groups = mapped_df.groupby(["Region", "District"])["City"].apply(list).reset_index()
        grouped = grouped.merge(city_groups, on=["Region", "District"], how="left")
        
        grouped = grouped.set_index("District")
        grouped = grouped.rename(columns={"City": "Cities in district"})

        # ✅ Step 6: Optionally export GeoJSON
        if geojson_path is not None:
            gdf = gpd.GeoDataFrame(geo_records, geometry="geometry", crs="EPSG:4326")
            gdf.to_file(geojson_path, driver="GeoJSON")
            print(f"📂 GeoJSON with {len(gdf)} city points written to: {geojson_path}")

        # ✅ Step 7: Apply custom grouping if provided
            if custom_grouping:
                grouped = grouped.copy()
                grouped['__group__'] = grouped.index.map(custom_grouping)

                if grouped['__group__'].isnull().any():
                    missing_keys = grouped.index[grouped['__group__'].isnull()].tolist()
                    raise ValueError(f"Missing entries in custom_grouping for: {missing_keys}")

                grouped = grouped.groupby('__group__')

                if custom_grouping_method == 'sum':
                    grouped = grouped.sum()
                elif custom_grouping_method == 'average':
                    grouped = grouped.mean()
                else:
                    raise ValueError("custom_grouping_method must be either 'sum' or 'average'.")

                grouped.index.name = "City"  # restore the expected index name

        return grouped

    def build_database_tree(self, filename, format: str = "ascii", lang: str = "eng"):
        """
        Build a tree from all `columns[*]["category"]` values and write it out.

        Args:
            filename: str (if no extension passed, it is added based on format).
            format: one of {"ascii", "markdown", "csv"}.
                    - "ascii": Unicode box-drawing tree (best for readability).
                    - "markdown": nested bullet list (portable in docs/READMEs).
                    - "csv": tabular, easy to filter/sort in spreadsheets.
            lang: one of {"eng", "pol"}.

        Output path:
            Uses self.database_tree_output_path.
        """

        metadata = self.processed_data_metadata
        # Ensure the base output directory exists
        base_dir = getattr(self, "database_tree_output_path", None)
        if not isinstance(base_dir, str) or not base_dir:
            raise ValueError("self.database_tree_output_path must be a non-empty string (a directory path).")
        os.makedirs(base_dir, exist_ok=True)

        # Determine extension and construct full output path
        base_name, ext = os.path.splitext(filename)
        if not ext:  # add extension if missing
            if format == "ascii":
                ext = ".txt"
            elif format == "markdown":
                ext = ".md"
            elif format == "csv":
                ext = ".csv"
            else:
                raise ValueError('format must be one of: "ascii", "markdown", "csv"')

        out_path = os.path.join(base_dir, base_name + ext)

        # --- 1) Collect category paths
        leaf_paths = set()
        for item in metadata:
            cols = item.columns
            for col_info in cols.values():
                if lang=="eng":
                    cat = col_info.category["eng"]
                elif lang=="pol":
                    cat = col_info.category["pol"]
                else:
                    raise ValueError(f"Only 'eng' and 'pol' values of the 'lang' attribute supported. Passed: {lang}.")
                if not isinstance(cat, str) or not cat.strip():
                    continue
                parts = [p.strip() for p in cat.split("/") if p.strip()]
                if parts:
                    leaf_paths.add("/".join(parts))

        # --- 2) Build a nested tree structure: dict[node] -> children dict
        def tree():
            return defaultdict(tree)

        root = tree()
        for full in leaf_paths:
            parts = full.split("/")
            cursor = root
            for part in parts:
                cursor = cursor[part]

        # Helper to list children in sorted order
        def _sorted_items(node_dict):
            return sorted(node_dict.items(), key=lambda kv: kv[0].lower())

        # --- 3) Writers for each format
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

        if format == "ascii":
            # Unicode box drawing (├──, └──, │)
            lines = []

            def dfs(node_dict, prefix=""):
                items = _sorted_items(node_dict)
                for i, (name, child) in enumerate(items):
                    connector = "└── " if i == len(items) - 1 else "├── "
                    lines.append(prefix + connector + name)
                    next_prefix = prefix + ("    " if i == len(items) - 1 else "│   ")
                    dfs(child, next_prefix)

            dfs(root)
            # If there are multiple top-level roots, there will be multiple first-level lines.
            with open(out_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))

        elif format == "markdown":
            # Nested bullet list
            lines = []

            def dfs_md(node_dict, depth=0):
                for name, child in _sorted_items(node_dict):
                    lines.append(("  " * depth) + f"- {name}")
                    dfs_md(child, depth + 1)

            dfs_md(root)
            with open(out_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))

        elif format == "csv":
            # Flat table with hierarchy columns
            nodes = {}  # path -> (level, name, parent)
            for full in leaf_paths:
                parts = full.split("/")
                for i in range(1, len(parts) + 1):
                    path = "/".join(parts[:i])
                    parent = "/".join(parts[:i-1]) if i > 1 else ""
                    if path not in nodes:
                        nodes[path] = (i, parts[i-1], parent)

            # Sort parents -> children, alpha by name
            sorted_rows = sorted(
                ({"level": lvl, "name": name, "path": p, "parent": parent, "is_leaf": p in leaf_paths}
                for p, (lvl, name, parent) in nodes.items()),
                key=lambda r: (r["level"], r["parent"], r["name"].lower())
            )

            with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(["level", "name", "path", "parent", "is_leaf"])
                for r in sorted_rows:
                    w.writerow([r["level"], r["name"], r["path"], r["parent"], str(r["is_leaf"])])
        else:
            raise ValueError('format must be one of: "ascii", "markdown", "csv"')
