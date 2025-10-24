from __future__ import annotations

from pathlib import Path
from datetime import datetime
from typing import Iterable, Any, Optional
import duckdb
import pandas as pd
import json
import os

"""
This module handles the creation of DuckDB and parquet files.
It is used by core.processor.AdministrativeHistoryProcessor when
it method process_raw_csv_file is called.
"""

def _json_or_text(x: Any) -> str:
    if isinstance(x, (list, dict)):
        return json.dumps(x, ensure_ascii=False)
    return "" if x is None else str(x)


class DuckParquetStorage:
    """
    Responsibilities:
      - During processing: append observations, replace metadata, export to Parquet
      - At startup: ensure DuckDB is present, or rebuild it from Parquet (if available)
      - For duckdb-wasm: generate SQL to expose Parquet via CREATE VIEW
    """

    def __init__(self, duckdb_path: str | Path, parquet_dir: str | Path):
        self.duckdb_path = str(duckdb_path)
        self.parquet_dir = Path(parquet_dir)
        Path(self.duckdb_path).parent.mkdir(parents=True, exist_ok=True)
        self.parquet_dir.mkdir(parents=True, exist_ok=True)

        # Connect (creates file if not present; we may populate from Parquet)
        self.con = duckdb.connect(self.duckdb_path)
        self._ensure_observations_table()

    # ---------- stable table (DDL once) ----------
    def _ensure_observations_table(self):
        self.con.execute("""
        CREATE TABLE IF NOT EXISTS observations (
            adm_unit_id TEXT,
            adm_level TEXT,
            data_table_id TEXT,
            variable_name TEXT,
            value DOUBLE,
            harmonize_to_date TIMESTAMP,
            orig_adm_state_date TIMESTAMP,
            adm_state_date TIMESTAMP,
            date_text TEXT
        );
        """)

    # ---------- metadata from Pydantic models ----------
    @staticmethod
    def _datatables_df_from_models(models: Iterable[Any]) -> pd.DataFrame:
        rows = []
        for m in models:
            rows.append({
                "data_table_id": m.data_table_id,
                "adm_level": m.adm_level,
                "source": _json_or_text(m.source),
                "link": _json_or_text(m.link),
                "table_ref": _json_or_text(m.table),
                "page": _json_or_text(m.page),
                "pdf_page": _json_or_text(m.pdf_page),
                "description_pol": m.description.get("pol"),
                "description_eng": m.description.get("eng"),
                "date_text": m.date,
                "orig_adm_state_date": m.orig_adm_state_date,
                "adm_state_date": m.adm_state_date,
                "standardization_comments": m.standardization_comments,
                "harmonization_method": m.harmonization_method,
                "imputation_method": m.imputation_method,
            })
        return pd.DataFrame(rows)

    @staticmethod
    def _datasets_df_from_models(models: Iterable[Any]) -> pd.DataFrame:
        rows = []
        for m in models:
            for var_name, meta in m.columns.items():
                rows.append({
                    "data_table_id": m.data_table_id,
                    "variable_name": var_name,
                    "unit": meta.unit,
                    "category_pol": meta.category.get("pol"),
                    "category_eng": meta.category.get("eng"),
                    "data_type": meta.data_type,
                    "completeness": meta.completeness,
                    "n_na": meta.n_na,
                    "n_not_na": meta.n_not_na,
                    "completeness_after_imputation": meta.completeness_after_imputation,
                    "n_na_after_imputation": meta.n_na_after_imputation,
                    "n_not_na_after_imputation": meta.n_not_na_after_imputation,
                })
        return pd.DataFrame(rows)

    def replace_metadata_tables(self, models: Iterable[Any]) -> None:
        dt_df = self._datatables_df_from_models(models)
        ds_df = self._datasets_df_from_models(models)

        self.con.register("dt_df", dt_df)
        self.con.execute("CREATE OR REPLACE TABLE datatables_metadata AS SELECT * FROM dt_df;")
        self.con.unregister("dt_df")

        self.con.register("ds_df", ds_df)
        self.con.execute("CREATE OR REPLACE TABLE datasets_metadata AS SELECT * FROM ds_df;")
        self.con.unregister("ds_df")

    # ---------- ingest processed DataFrame (from your pipeline) ----------
    def ingest_processed_df(
        self,
        df_output: pd.DataFrame,
        m,                                # DataTableMetadata instance
        harmonize_to_date: Optional[datetime],
        id_column: str,                   # "District" / "Region" / "City"
    ):
        value_cols = [c for c in df_output.columns if c != id_column]
        if not value_cols:
            return

        obs_df = df_output.melt(
            id_vars=[id_column],
            value_vars=value_cols,
            var_name="variable_name",
            value_name="value",
            ignore_index=True,
        ).rename(columns={id_column: "adm_unit_id"}).copy()

        obs_df["adm_level"] = m.adm_level
        obs_df["data_table_id"] = m.data_table_id
        obs_df["harmonize_to_date"] = harmonize_to_date
        obs_df["orig_adm_state_date"] = m.orig_adm_state_date
        obs_df["adm_state_date"] = m.adm_state_date
        obs_df["date_text"] = m.date

        obs_df["value"] = pd.to_numeric(obs_df["value"], errors="coerce")

        self.con.register("obs_df", obs_df)
        self.con.execute("""
            INSERT INTO observations
            SELECT
                CAST(adm_unit_id AS TEXT),
                CAST(adm_level AS TEXT),
                CAST(data_table_id AS TEXT),
                CAST(variable_name AS TEXT),
                CAST(value AS DOUBLE),
                harmonize_to_date::TIMESTAMP,
                orig_adm_state_date::TIMESTAMP,
                adm_state_date::TIMESTAMP,
                CAST(date_text AS TEXT)
            FROM obs_df;
        """)
        self.con.unregister("obs_df")

    # ---------- export to Parquet (single files) ----------
    def export_all_to_parquet(self):
        out = self.parquet_dir
        for name in ("datatables_metadata", "datasets_metadata", "observations"):
            p = out / f"{name}.parquet"
            if p.exists():
                p.unlink()

        self.con.execute(f"COPY (SELECT * FROM datatables_metadata) TO '{out}/datatables_metadata.parquet' (FORMAT PARQUET, COMPRESSION 'ZSTD');")
        self.con.execute(f"COPY (SELECT * FROM datasets_metadata)  TO '{out}/datasets_metadata.parquet'  (FORMAT PARQUET, COMPRESSION 'ZSTD');")
        self.con.execute(f"COPY (SELECT * FROM observations)       TO '{out}/observations.parquet'       (FORMAT PARQUET, COMPRESSION 'ZSTD');")

    # ---------- rebuild DB from Parquet if DB is empty/missing ----------
    def parquet_files_exist(self) -> bool:
        return all((self.parquet_dir / f"{n}.parquet").exists()
                   for n in ("datatables_metadata", "datasets_metadata", "observations"))

    def rebuild_duckdb_from_parquet(self, overwrite: bool = True):
        """
        Creates (or replaces) DB tables from the three Parquet files.
        """
        if not self.parquet_files_exist():
            raise FileNotFoundError(f"Parquet not found in {self.parquet_dir}")

        # Optionally drop to ensure clean state
        if overwrite:
            self.con.execute("DROP TABLE IF EXISTS datatables_metadata;")
            self.con.execute("DROP TABLE IF EXISTS datasets_metadata;")
            self.con.execute("DROP TABLE IF EXISTS observations;")

        # Recreate tables from Parquet
        self.con.execute(f"""
            CREATE TABLE datatables_metadata AS
            SELECT * FROM read_parquet('{(self.parquet_dir / "datatables_metadata.parquet").as_posix()}');
        """)
        self.con.execute(f"""
            CREATE TABLE datasets_metadata AS
            SELECT * FROM read_parquet('{(self.parquet_dir / "datasets_metadata.parquet").as_posix()}');
        """)
        self._ensure_observations_table()
        self.con.execute(f"""
            INSERT INTO observations
            SELECT * FROM read_parquet('{(self.parquet_dir / "observations.parquet").as_posix()}');
        """)

    # ---------- duckdb-wasm bootstrap (browser) ----------
    def wasm_bootstrap_sql(self, base_url: str) -> str:
        """
        Returns SQL to create views over Parquet (for duckdb-wasm).
        base_url should point to the folder where the three Parquet files are hosted.
        Example: 'https://yourcdn.example.com/parquet'
        """
        if base_url.endswith("/"):
            base_url = base_url[:-1]
        dt = f"{base_url}/datatables_metadata.parquet"
        ds = f"{base_url}/datasets_metadata.parquet"
        ob = f"{base_url}/observations.parquet"
        return f"""
-- duckdb-wasm bootstrap
CREATE VIEW datatables_metadata AS SELECT * FROM read_parquet('{dt}');
CREATE VIEW datasets_metadata  AS SELECT * FROM read_parquet('{ds}');
CREATE VIEW observations       AS SELECT * FROM read_parquet('{ob}');
-- (optional) a couple of convenience indexes in wasm are no-ops,
-- but you can still optimize queries via projections/predicates.
"""

    def close(self):
        if self.con:
            self.con.close()
            self.con = None