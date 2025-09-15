import json
from pathlib import Path
from datetime import datetime
from pydantic import parse_obj_as, ValidationError
from typing import List
import shutil
from shapely.geometry import Point
import geopandas as gpd
import pandas as pd
import numpy as np
import os
import sys
from collections import defaultdict
import plotly.express as px
import time
import traceback

from core.processor import AdministrativeHistoryProcessor
from data_models.adm_timespan import *
from data_models.adm_unit import *
from data_models.adm_state import *
from data_models.adm_change import *
from data_models.econ_data_metadata import *
from data_models.processing_config import *

from utils.helper_functions import read_economic_csv_input
from utils.exceptions import TerritoryNotLoadedError

"""
This is the core component of the toolkit.

When an instance of AdministrativeHistory is created, the object reads in the input data
and creates the data model of the administrative history.

The method 'process_raw_data' automatically creates all necessary harmonization matrices
and harmonizes all the input data.

Example usage:
    # Load the configuration.
    config = load_config("config.json")

    # Create an AdministrativeHistory instance.
    administrative_history = AdministrativeHistory(config, load_geometries=True)

    # Harmonize input data stored in the folder defined in the config.
    administrative_history.process_raw_data()
"""

class AdministrativeHistoryAPI():
    def __init__(self, adm_history_processor: AdministrativeHistoryProcessor):
        self.adm_history_processor = adm_history_processor
        self.adm_history = self.adm_history_processor.adm_history

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
        - custom_grouping (dict): Optional mapping from index to custom group name. Implemented only for 'District' or 'Region'.
        - custom_grouping_method (str): 'sum' or 'average' for how to aggregate grouped data.
        
        Returns:
        - df (pd.DataFrame): The processed data table.
        - data_table_metadata: Metadata object.
        - adm_state_date: Reference date of administrative state.
        """
        if version == 'harmonized':
            data_table_metadata_list = [data_table for data_table in self.processed_data_metadata if data_table.data_table_id == data_table_id]
            if len(data_table_metadata_list) == 0:
                raise ValueError(f"No data table with the given id exists.")
            data_table_metadata = data_table_metadata_list[0]
            adm_state_date = self.harmonize_to_date
            folder = self.processed_data_output_folder
            path = os.path.join(folder, f"{data_table_id}.csv")
            df = pd.read_csv(path)

            adm_level = data_table_metadata.adm_level

            if adm_level not in df.columns:
                raise ValueError(f"'{adm_level}' column missing in data table: {data_table_id}")
            
            df.set_index(adm_level, inplace=True)
        else:
            data_table_metadata_list = [data_table for data_table in self.processed_data_metadata if data_table.data_table_id == data_table_id]
            if len(data_table_metadata_list) == 0:
                raise ValueError(f"No data table with the given id exists.")
            data_table_metadata = data_table_metadata_list[0]
            adm_level = data_table_metadata.adm_level
            adm_state_date = data_table_metadata.orig_adm_state_date
            folder = self.adm_units_raw_data_folder
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
        elif adm_level == 'Region':
            all_unit_names = adm_state.all_region_names(homeland_only=True)

        if adm_level in ['District', 'Region']:
            # Check if data is defined for all adm units existent at a given date. This restriction is not enforced for cities.
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