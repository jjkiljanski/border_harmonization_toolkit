import pandas as pd
import os
from __future__ import annotations
from pathlib import Path
from core.db_injector import DuckParquetStorage
from typing import Union, Literal, Dict, Optional

from administrative_history.core.processor import AdministrativeHistoryProcessor
from administrative_history.utils.helper_functions import read_economic_csv_input

"""
This component serves as the user api for the access to the data stored in the database.
It is constructed using AdministrativeHistoryProcessor object.

Example usage:
    # Load the configuration.
    config = load_adm_history_config("config.json")
    processing_config = load_processing_config("input/initial_region_state_list.json")

    # Create an AdministrativeHistory instance.
    adm_history = AdministrativeHistory(config, load_geometries=True)
    adm_history_processor = AdministrativeHistoryProcessor(processing_config, adm_history)
    adm_history_api = AdministativeHistoryApi(adm_history_processor)

    # Load the needed data table.
    population_1931, population_1931_data_table_metadata, population_1931_adm_state_date = adm_history_api.load_data_table(data_table_id = '1931-total_population', version='harmonized')
"""
class AdministrativeHistoryAPI:
    def __init__(self, adm_history_processor):
        """
        Behavior:
          - If a DuckDB file exists at adm_history_processor.duckdb_path, open it.
          - Else, if Parquet exists at adm_history_processor.parquet_root, create DB from Parquet.
          - Else, raise a descriptive error.
        """
        self.adm_history_processor = adm_history_processor
        self.adm_history = self.adm_history_processor.adm_history

        duckdb_path: Path = Path(self.adm_history_processor.duckdb_path)
        parquet_root: Path = Path(self.adm_history_processor.parquet_root)

        self.storage = DuckParquetStorage(duckdb_path, parquet_root)

        db_exists = duckdb_path.exists() and duckdb_path.stat().st_size > 0

        if db_exists:
            # DB already connected by storage.__init__
            pass
        elif self.storage.parquet_files_exist():
            # Rebuild DB from Parquet and reuse it
            print(f"ℹ️ DuckDB not found at {duckdb_path}. Rebuilding from Parquet in {parquet_root}...")
            self.storage.rebuild_duckdb_from_parquet(overwrite=True)
            print("✅ DuckDB rebuilt from Parquet.")
        else:
            self.storage.close()
            raise FileNotFoundError(
                f"No DuckDB at '{duckdb_path}' and no Parquet files in '{parquet_root}'. "
                f"Run your processing pipeline first to create them."
            )

        # Optional: expose a convenient connection for local queries
        self.con = self.storage.con

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
            col_name: data_table_metadata.columns[col_name].category.eng
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