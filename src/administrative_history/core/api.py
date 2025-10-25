from __future__ import annotations

import os
from pathlib import Path
from typing import Union, Literal, Dict
import duckdb

from administrative_history.utils.helper_functions import read_economic_csv_input

"""
This component serves as the user API for accessing data stored in the DuckDB database.
It is constructed using an AdministrativeHistoryProcessor object and a DuckDB file path.

Example usage:
    # Load the configuration.
    config = load_adm_history_config("config.json")
    processing_config = load_processing_config("input/initial_region_state_list.json")

    # Create an AdministrativeHistory instance.
    adm_history = AdministrativeHistory(config, load_geometries=True)
    adm_history_processor = AdministrativeHistoryProcessor(processing_config, adm_history)
    duckdb_path = "output/adm_history.duckdb"

    # Initialize API (create DB if not exists or overwrite if requested)
    adm_history_api = AdministrativeHistoryAPI(adm_history_processor, duckdb_path, overwrite_duckdb=False)

    # Load the needed data table.
    population_1931, population_1931_metadata, population_1931_date = adm_history_api.load_data_table(
        data_table_id='1931-total_population',
        version='harmonized'
    )
"""

class AdministrativeHistoryAPI:
    def __init__(self, adm_history_processor, duckdb_path: Union[str, Path], overwrite_duckdb: bool = False):
        """
        Initializes the AdministrativeHistoryAPI.

        Parameters
        ----------
        adm_history_processor : AdministrativeHistoryProcessor
            Processor instance that provides administrative history and paths to processed data.
        duckdb_path : str | Path
            Path to the DuckDB database file. If it exists, it will be opened.
            If overwrite_duckdb=True, it will be deleted and rebuilt from Parquet.
        overwrite_duckdb : bool, default=False
            - If True: recreate the DuckDB database from Parquet (delete any existing file).
            - If False: use the existing DuckDB if present, or create it from Parquet if missing.

        Behavior
        --------
        - If overwrite_duckdb=True, delete any existing DuckDB file and recreate it from Parquet.
        - Else, if the DuckDB file exists, open it.
        - Else, if Parquet files exist under
          `adm_history_processor.processed_data_metadata_output_folder`, create the database from them.
        - Else, raise a descriptive FileNotFoundError.
        """

        self.adm_history_processor = adm_history_processor
        self.adm_history = self.adm_history_processor.adm_history

        duckdb_path = Path(duckdb_path)
        parquet_root = Path(self.adm_history_processor.processed_data_metadata_output_folder)

        # --- handle overwrite logic
        if overwrite_duckdb and duckdb_path.exists():
            print(f"[INFO] Overwriting existing DuckDB file at {duckdb_path}")
            duckdb_path.unlink()

        # --- main logic
        if duckdb_path.exists():
            # Use existing DB
            self.con = duckdb.connect(str(duckdb_path))
        elif parquet_root.exists():
            # Build a fresh DB
            self.con = duckdb.connect(str(duckdb_path))
            self._build_db_from_parquet(parquet_root)
        else:
            raise FileNotFoundError(
                f"No data sources found.\n"
                f"Expected DuckDB at: {duckdb_path}\n"
                f"Or Parquet folder at: {parquet_root}"
            )

    def _build_db_from_parquet(self, root: Path):
        """Read Parquet files and populate DuckDB (overwrites existing tables)."""
        mapping = {
            "city_datasets": root / "City_datasets.parquet",
            "district_datasets": root / "District_datasets.parquet",
            "region_datasets": root / "Region_datasets.parquet",
            "data_tables_metadata": root / "data_tables_metadata.parquet",
            "columns_metadata": root / "columns_metadata.parquet",
        }

        self.con.execute("CREATE SCHEMA IF NOT EXISTS adm;")

        for table_name, parquet_spec in mapping.items():

            print(f"[INFO] Loading {table_name} from {parquet_spec}")
            self.con.execute(
                f"""
                CREATE OR REPLACE TABLE adm.{table_name} AS
                SELECT * FROM read_parquet(?, union_by_name=true);
                """,
                [os.fspath(parquet_spec)],
            )

        print(f"[INFO] DuckDB created successfully at: {root}")

    def load_data_table(
                        self,
                        data_table_id: str,
                        version: Union[Literal['original'], Literal['harmonized']],
                        custom_grouping: Dict[str, str] = None,
                        custom_grouping_method: Union[Literal['sum'], Literal['average']] = 'average'
                    ):
        """
        Basic API access point to the economic database.
        Loads the given data_table in either original or harmonized form.

        Returns:
        - df (pd.DataFrame)
        - data_table_metadata
        - adm_state_date
        """

        # ---- fetch metadata (unchanged) ----
        data_table_metadata_list = [
            data_table for data_table in self.adm_history_processor.processed_data_metadata.items
            if data_table.data_table_id == data_table_id
        ]
        if len(data_table_metadata_list) == 0:
            raise ValueError("No data table with the given id exists.")
        data_table_metadata = data_table_metadata_list[0]
        adm_level = data_table_metadata.adm_level

        if version == 'harmonized':
            # --- Load from DuckDB (built from your parquet files) ---
            adm_state_date = self.adm_history_processor.harmonize_to_date

            # connect if not already connected
            con = getattr(self, "con", None)
            if con is None:
                duckdb_path = getattr(self.adm_history_processor, "duckdb_path", None)
                if not duckdb_path:
                    raise RuntimeError("DuckDB path is not configured on adm_history_processor.")
                con = duckdb.connect(duckdb_path)
                self.con = con

            # select the correct fact table based on adm_level
            table_map = {
                'District': 'district_datasets',
                'Region': 'region_datasets',
                'City': 'city_datasets',
            }
            if adm_level not in table_map:
                raise ValueError(f"Unsupported adm_level in metadata: {adm_level}")

            # prefer schema 'adm', fall back to bare table if needed
            base_table = table_map[adm_level]
            qualified_candidates = [f"adm.{base_table}", base_table]

            df_long = None
            last_err = None
            for tbl in qualified_candidates:
                try:
                    df_long = con.execute(
                        f"""
                        SELECT
                            {adm_level} AS unit,
                            variable_name,
                            value
                        FROM {tbl}
                        WHERE data_table_id = ?
                        """,
                        [data_table_id]
                    ).df()
                    break
                except Exception as e:
                    last_err = e
                    continue

            if df_long is None:
                raise RuntimeError(
                    f"Failed to read harmonized data from DuckDB tables "
                    f"({qualified_candidates}). Last error: {last_err}"
                )

            if df_long.empty:
                raise ValueError(
                    f"No rows found in {base_table} for data_table_id='{data_table_id}'."
                )

            # pivot: rows = unit, columns = variable_name, values = value
            df = (
                df_long
                .pivot(index='unit', columns='variable_name', values='value')
                .sort_index()
            )
            df.index.name = adm_level

        else:
            # --- Original path: keep your existing CSV-based loader ---
            adm_state_date = data_table_metadata.orig_adm_state_date
            folder = self.adm_units_raw_data_folder
            path = os.path.join(folder, f"{data_table_id}.csv")
            df = read_economic_csv_input(adm_level=adm_level, input_csv_path=path)

            if adm_level not in df.columns:
                raise ValueError(f"'{adm_level}' column missing in data table: {data_table_id}")
            df.set_index(adm_level, inplace=True)

        # ---- rename columns according to metadata (same logic as before) ----
        col_rename_dict = {
            col_name: data_table_metadata.columns[col_name].category["eng"]
            for col_name in df.columns
            if col_name in data_table_metadata.columns
        }
        if col_rename_dict:
            df.rename(columns=col_rename_dict, inplace=True)

        # ---- completeness check against administrative state ----
        adm_state = self.adm_history.find_adm_state_by_date(adm_state_date)

        if adm_level == 'District':
            all_unit_names = adm_state.all_district_names(homeland_only=True)
        elif adm_level == 'Region':
            all_unit_names = adm_state.all_region_names(homeland_only=True)
        else:
            all_unit_names = None  # No completeness check for City in your original code

        if adm_level in ['District', 'Region']:
            if set(all_unit_names) != set(df.index):
                missing_in_df = set(all_unit_names) - set(df.index)
                missing_in_adm_state = set(df.index) - set(all_unit_names)
                raise RuntimeError(
                    f"{adm_level} set for the loaded dataframe doesn't agree with the "
                    f"{adm_level.lower()} set for its adm. state!\n"
                    f"Missing in df: {missing_in_df}\n"
                    f"Missing in adm. state: {missing_in_adm_state}."
                )

            # ---- optional custom grouping ----
            if custom_grouping:
                df = df.copy()
                df['__group__'] = df.index.map(custom_grouping)

                if df['__group__'].isnull().any():
                    missing_keys = df.index[df['__group__'].isnull()].tolist()
                    raise ValueError(f"Missing entries in custom_grouping for: {missing_keys}")

                grouped = df.groupby('__group__')

                if custom_grouping_method == 'sum':
                    df = grouped.sum(numeric_only=True)
                elif custom_grouping_method == 'average':
                    df = grouped.mean(numeric_only=True)
                else:
                    raise ValueError("custom_grouping_method must be either 'sum' or 'average'.")

                df.index.name = adm_level  # restore the expected index name

        return df, data_table_metadata, adm_state_date