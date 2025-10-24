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
    DuckDB-based loader for either the harmonized (from observations) or original (via DuckDB read_csv_auto) table.

    Returns:
    - df (pd.DataFrame): rows = adm units, columns = variables (renamed to English categories if available)
    - data_table_metadata: Pydantic metadata object
    - adm_state_date: datetime for the administrative state used (harmonize_to_date for harmonized; orig for original)
    """
    
    # --- get metadata for this table ---
    matches = [dt for dt in self.processed_data_metadata if dt.data_table_id == data_table_id]
    if not matches:
        raise ValueError(f"No data table with id '{data_table_id}' exists in processed_data_metadata.")
    data_table_metadata = matches[0]
    adm_level = data_table_metadata.adm_level

    # --- DuckDB connection (created in your AdministrativeHistoryAPI.__init__) ---
    if not hasattr(self, "con") or self.con is None:
        raise RuntimeError("DuckDB connection 'self.con' is not initialized on AdministrativeHistoryAPI.")

    # ========== HARMONIZED: from DuckDB observations ==========
    if version == 'harmonized':
        # We’ll build a tidy frame from observations + datasets_metadata, then pivot to wide.
        # Get the admin state date from the metadata table (it should equal the harmonize_to_date used in processing).
        # We use datatables_metadata.adm_state_date to return alongside the df.
        adm_state_date_df = self.con.execute(
            "SELECT adm_state_date FROM datatables_metadata WHERE data_table_id = ? LIMIT 1;",
            [data_table_id]
        ).df()
        if adm_state_date_df.empty or pd.isna(adm_state_date_df.loc[0, "adm_state_date"]):
            # Fallback to processor’s harmonize_to_date if metadata is missing
            adm_state_date = getattr(self, "harmonize_to_date", None)
        else:
            adm_state_date = adm_state_date_df.loc[0, "adm_state_date"]

        # Pull observations joined with datasets_metadata to get English labels
        obs = self.con.execute(
            """
            SELECT
              o.adm_unit_id,
              o.variable_name,
              o.value,
              ds.category_eng
            FROM observations o
            LEFT JOIN datasets_metadata ds
              ON ds.data_table_id = o.data_table_id
             AND ds.variable_name = o.variable_name
            WHERE o.data_table_id = ?
              AND o.adm_level = (
                    SELECT adm_level FROM datatables_metadata WHERE data_table_id = ? LIMIT 1
                  )
            ;
            """,
            [data_table_id, data_table_id]
        ).df()

        if obs.empty:
            raise ValueError(f"No observations found in DuckDB for data_table_id='{data_table_id}' (harmonized).")

        # Choose column labels: prefer English category, else fall back to variable_name
        col_labels = obs["category_eng"].where(obs["category_eng"].notna(), obs["variable_name"])
        obs = obs.assign(_col_label=col_labels)

        # Pivot to wide
        df = obs.pivot_table(index="adm_unit_id", columns="_col_label", values="value", aggfunc="first")
        df.index.name = adm_level  # expose the adm level in the index name

    # ========== ORIGINAL: via DuckDB read_csv_auto (no pandas CSV I/O) ==========
    elif version == 'original':
        # original path mirrors your previous behavior, but uses DuckDB to read CSV
        adm_state_date = data_table_metadata.orig_adm_state_date
        folder = self.adm_units_raw_data_folder
        path = os.path.join(folder, f"{data_table_id}.csv")
        if not os.path.exists(path):
            raise FileNotFoundError(f"Raw CSV for '{data_table_id}' not found at: {path}")

        # Load with DuckDB (lets DuckDB handle types), then to pandas for the rest of your logic
        df = self.con.execute(
            "SELECT * FROM read_csv_auto(?, HEADER TRUE);",
            [path]
        ).df()

        if adm_level not in df.columns:
            raise ValueError(f"'{adm_level}' column missing in data table: {data_table_id}")

        df = df.set_index(adm_level)

    else:
        raise ValueError("version must be 'original' or 'harmonized'.")

    # --- rename columns to English category names when present in metadata ---
    # This matches your previous logic.
    col_rename_dict = {
        col_name: data_table_metadata.columns[col_name].category.eng
        for col_name in df.columns
        if col_name in data_table_metadata.columns
    }
    if col_rename_dict:
        df = df.rename(columns=col_rename_dict)

    # --- admin state checks and optional grouping ---
    adm_state = self.find_adm_state_by_date(adm_state_date)

    if adm_level == 'District':
        all_unit_names = adm_state.all_district_names(homeland_only=True)
    elif adm_level == 'Region':
        all_unit_names = adm_state.all_region_names(homeland_only=True)
    else:
        all_unit_names = None  # City-level: skip completeness enforcement below

    if adm_level in ['District', 'Region']:
        # Ensure index name is exactly the adm level; useful for error messages
        df.index.name = adm_level

        # Verify coverage against the administrative state units
        df_index_set = set(df.index.astype(str))
        all_unit_set = set(map(str, all_unit_names))
        if df_index_set != all_unit_set:
            missing_in_df = all_unit_set - df_index_set
            missing_in_adm_state = df_index_set - all_unit_set
            raise RuntimeError(
                f"{adm_level} set for the loaded dataframe doesn't agree with the {adm_level.lower()} set for its adm. state!\n"
                f"Missing in df: {missing_in_df}\nMissing in adm. state: {missing_in_adm_state}."
            )

        # Apply custom grouping if provided
        if custom_grouping:
            # Map index to group; ensure all keys provided
            mapped = pd.Series(df.index, index=df.index).map(custom_grouping)
            if mapped.isnull().any():
                missing_keys = mapped[mapped.isnull()].index.tolist()
                raise ValueError(f"Missing entries in custom_grouping for: {missing_keys}")

            df = df.copy()
            df["__group__"] = mapped.values
            grouped = df.groupby("__group__")
            if custom_grouping_method == 'sum':
                df = grouped.sum(numeric_only=True)
            elif custom_grouping_method == 'average':
                df = grouped.mean(numeric_only=True)
            else:
                raise ValueError("custom_grouping_method must be either 'sum' or 'average'.")
            df.index.name = adm_level  # keep expected name

    return df, data_table_metadata, adm_state_date