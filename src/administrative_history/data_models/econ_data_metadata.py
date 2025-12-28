from __future__ import annotations

from pydantic import BaseModel, model_validator
from typing import Union, Optional, Literal, List, Dict, Any, Tuple
from pydantic.type_adapter import TypeAdapter
from datetime import datetime
from collections import defaultdict
from pathlib import Path
import json

class ColumnMetadata(BaseModel):
    unit: str
    category: Dict[Union[Literal["pol"], Literal["eng"]], str]
    data_type: str
    completeness: Optional[float] = None
    n_na: Optional[int] = None
    n_not_na: Optional[int] = None
    completeness_after_imputation: Optional[float] = None
    n_na_after_imputation: Optional[int] = None
    n_not_na_after_imputation: Optional[int] = None

    @model_validator(mode="after")
    def validate_category_parts(self) -> "ColumnMetadata":
        """
        Ensure that all values in `category` have the same number of '/'-separated parts.
        """
        if self.category:
            # Count non-empty parts to avoid mismatches from accidental '//' or leading/trailing '/'
            counts = {lang: len([p for p in text.split("/") if p.strip() != ""])
                      for lang, text in self.category.items()}
            if len(set(counts.values())) > 1:
                raise ValueError(
                    f"All `category` values must have the same number of '/' parts; got {counts}"
                )
        return self
class DataTableMetadata(BaseModel):
    """
    Metadata model for describing a data table, including source and reference 
    information, administrative levels, description in multiple languages, 
    date validity, and methods for harmonization/imputation.
    """

    data_table_id: str
    adm_level: Union[Literal['District'], Literal['Region'], Literal['City']]

    # Source and link can be single strings or lists of strings
    source: Optional[Union[str, List[str]]] = ""
    link: Optional[Union[str, List[str]]] = ""

    # If source/link are lists, these may also be lists of the same length
    table: Optional[Union[str, List[Optional[str]]]] = ""
    page: Optional[Union[int, str, List[Optional[Union[int, str]]]]] = None
    pdf_page: Optional[Union[int, List[Optional[int]]]] = None

    description: Dict[Union[Literal["pol"], Literal["eng"]], str]
    date: str

    orig_adm_state_date: Optional[datetime] = None  # parsed from multiple formats
    adm_state_date: Optional[datetime]

    standardization_comments: Optional[str] = ""
    harmonization_method: Optional[Literal["proportional_to_territory"]] = None
    imputation_method: Optional[Literal["take_from_closest_centroid"]] = None
    columns: Dict[str, "ColumnMetadata"] = {}

    @model_validator(mode="before")
    @classmethod
    def parse_flexible_date(cls, data: Any) -> Any:
        if isinstance(data, dict):
            adm_date = data.get("orig_adm_state_date")
            if isinstance(adm_date, str):
                for fmt in ("%d.%m.%Y", "%Y-%m-%dT%H:%M:%S"):
                    try:
                        data["orig_adm_state_date"] = datetime.strptime(adm_date, fmt)
                        if data.get("adm_state_date", None) is None:
                            data["adm_state_date"] = data["orig_adm_state_date"]
                        break
                    except ValueError:
                        continue
                else:
                    raise ValueError(
                        f"Date format must be DD.MM.YYYY or ISO 8601, got: {adm_date}"
                    )
        return data

    @model_validator(mode="after")
    def validate_sources_and_links(self) -> "DataTableMetadata":
        """
        Validate that 'source' and 'link' are either both strings or both lists of equal length. 
        If lists are used, enforce that 'table', 'page', and 'pdf_page' (if lists) also match this length.
        """
        is_source_list = isinstance(self.source, list)
        is_link_list = isinstance(self.link, list)

        # Enforce both to be lists or both to be strings
        if is_source_list != is_link_list:
            raise ValueError("Both 'source' and 'link' must be either lists or single strings.")

        if is_source_list and is_link_list:
            if len(self.source) != len(self.link):
                raise ValueError("'source' and 'link' lists must be of the same length.")

            # If table/page/pdf_page are lists, they must match length
            for field_name in ["table", "page", "pdf_page"]:
                field_value = getattr(self, field_name)
                if isinstance(field_value, list):
                    if len(field_value) != len(self.source):
                        raise ValueError(
                            f"'{field_name}' list must have the same length as 'source'/'link'."
                        )

        return self
    
# Adapter for validating a list of DataTableMetadata
_DATA_TABLE_LIST = TypeAdapter(List[DataTableMetadata])
class MetadataRegistry(BaseModel):
    """
    A registry of data-table metadata entries with a helper to flatten
    into two analytics-friendly pandas DataFrames.

    This model stays I/O-free: it only returns DataFrames; saving is the caller's job.
    """
    items: List[DataTableMetadata] = []

    @model_validator(mode="after")
    def validate_bilingual_categories(self) -> "MetadataRegistry":
        """
        Ensures that:
        - All identical category['pol'] map to the same category['eng'].
        - All identical category['eng'] map to the same category['pol'].

        Enforces a 1-to-1 bilingual mapping across all columns.
        """

        pol_to_eng = defaultdict(set)
        eng_to_pol = defaultdict(set)

        # Gather mappings
        for table in self.items:
            for col_name, col in (table.columns or {}).items():
                cat = col.category or {}
                pol = cat.get("pol")
                eng = cat.get("eng")
                if pol and eng:
                    pol_to_eng[pol].add(eng)
                    eng_to_pol[eng].add(pol)

        errors = []

        # Check: pol → eng must map to one unique eng
        for pol, eng_values in pol_to_eng.items():
            if len(eng_values) > 1:
                errors.append(
                    f"POL '{pol}' maps to multiple ENG categories: {sorted(eng_values)}"
                )

        # Check: eng → pol must map to one unique pol
        for eng, pol_values in eng_to_pol.items():
            if len(pol_values) > 1:
                errors.append(
                    f"ENG '{eng}' maps to multiple POL categories: {sorted(pol_values)}"
                )

        if errors:
            raise ValueError(
                "Inconsistent bilingual category mappings:\n" +
                "\n".join(errors)
            )

        return self
    
    # ------------------------ Loaders -----------------------

    @classmethod
    def from_json_list(cls, data: List[Dict[str, Any]]) -> "MetadataRegistry":
        return cls.model_validate({"items": data}).sort_by_dates_inplace()
    
    @classmethod
    def from_folder(cls, folder: Path) -> "MetadataRegistry":
        """
        Read all *.json files directly in `folder`.
        Each must contain a JSON list of DataTableMetadata dicts.
        Loads all valid files, reports (but does not stop on) file errors.
        Raises if no JSON files are found in the folder.
        """
        if not folder.exists() or not folder.is_dir():
            raise FileNotFoundError(f"{folder} is not a directory")

        json_files = sorted(folder.glob("*.json"))
        if not json_files:
            raise FileNotFoundError(f"No *.json files found in folder: {folder}")

        all_items: List[DataTableMetadata] = []

        for json_path in json_files:
            try:
                with json_path.open("r", encoding="utf-8") as f:
                    payload = json.load(f)

                if not isinstance(payload, list):
                    raise TypeError(
                        f"{json_path} must contain a JSON list, got {type(payload).__name__}"
                    )

                items = _DATA_TABLE_LIST.validate_python(payload)
                all_items.extend(items)

            except Exception as e:
                # Report and continue; the caller can log or handle differently if needed
                print(f"[MetadataRegistry.from_folder] Skipped {json_path}: {e}")

        return cls(items=all_items)
    
    # ------------------------ Sorter ------------------------

    def sort_by_dates_inplace(self) -> "MetadataRegistry":
        self.items.sort(
            key=lambda m: (m.orig_adm_state_date or m.adm_state_date or datetime.min)
        )
        return self

    # ---------- helpers (translator-specific, pure) ----------

    @staticmethod
    def _to_list(x: Optional[Union[str, List[Any]]]) -> List[Any]:
        """Normalize scalars/None to lists. Empty string -> []"""
        if x is None:
            return []
        if isinstance(x, list):
            return x
        if isinstance(x, str) and x.strip() == "":
            return []
        return [x]
    
    @staticmethod
    def _as_str_list(lst: List[Any]) -> List[str]:
        return [None if x is None else str(x) for x in lst]

    @staticmethod
    def _dt(x: Optional[datetime]):
        """Convert datetime/None to pandas Timestamp; import pandas lazily."""
        if x is None:
            return None
        import pandas as pd
        return pd.to_datetime(x)

    @staticmethod
    def _get_lang(d: Optional[Dict[str, str]], key: str) -> Optional[str]:
        if not d:
            return None
        return d.get(key)

    # ---------- public API ----------

    def to_parquet(self, output_folder: str):
        """
        Returns:
          tables_df: one row per DataTableMetadata (description flattened, list fields preserved)
          columns_df: one row per ColumnMetadata with data_table_id + column_name (category flattened)
        """
        import pandas as pd

        table_rows: List[Dict[str, Any]] = []
        column_rows: List[Dict[str, Any]] = []

        for t in self.items:
            # -- table row --
            table_rows.append({
                "data_table_id": t.data_table_id,
                "adm_level": t.adm_level,

                # list-like fields preserved (Arrow will store as list<...>)
                "source": self._to_list(t.source),
                "link": self._to_list(t.link),
                "table": self._to_list(t.table),
                "page": self._to_list(t.page),
                "pdf_page": self._to_list(t.pdf_page),

                # language flatten
                "description_pol": self._get_lang(t.description, "pol"),
                "description_eng": self._get_lang(t.description, "eng"),

                # scalars
                "date": t.date,
                "orig_adm_state_date": self._dt(t.orig_adm_state_date),
                "adm_state_date": self._dt(t.adm_state_date),
                "standardization_comments": t.standardization_comments or None,
                "harmonization_method": t.harmonization_method or None,
                "imputation_method": t.imputation_method or None,
            })

            # -- column rows --
            for col_name, c in (t.columns or {}).items():
                column_rows.append({
                    "data_table_id": t.data_table_id,   # FK to table
                    "column_name": col_name,
                    "unit": c.unit,
                    "data_type": c.data_type,
                    "category_pol": self._get_lang(c.category, "pol"),
                    "category_eng": self._get_lang(c.category, "eng"),
                    "completeness": c.completeness,
                    "n_na": c.n_na,
                    "n_not_na": c.n_not_na,
                    "completeness_after_imputation": c.completeness_after_imputation,
                    "n_na_after_imputation": c.n_na_after_imputation,
                    "n_not_na_after_imputation": c.n_not_na_after_imputation,
                })

        tables_df = pd.DataFrame.from_records(table_rows)
        columns_df = pd.DataFrame.from_records(column_rows)

        # Guarantee list-typed columns are actual lists (important for Arrow)
        for col in ("source", "link", "table", "page", "pdf_page"):
            if col in tables_df.columns:
                tables_df[col] = tables_df[col].apply(
                    lambda v: v if isinstance(v, list) else ([] if v is None else [v])
                )

        # page can be int/str per model -> store as list[str]
        if "page" in tables_df.columns:
            tables_df["page"] = tables_df["page"].apply(self._as_str_list)

        # Coerce datetimes (robust even if all Nones)
        for col in ("orig_adm_state_date", "adm_state_date"):
            if col in tables_df.columns:
                tables_df[col] = pd.to_datetime(tables_df[col], errors="coerce")

        # Optional: use pandas 'string' dtype for nicer null handling downstream
        for col in (
            "data_table_id", "adm_level", "description_pol", "description_eng", "date",
            "standardization_comments", "harmonization_method", "imputation_method",
        ):
            if col in tables_df.columns:
                tables_df[col] = tables_df[col].astype("string")

        for col in ("data_table_id", "column_name", "unit", "data_type", "category_pol", "category_eng"):
            if col in columns_df.columns:
                columns_df[col] = columns_df[col].astype("string")

        tables_df.to_parquet(output_folder + "data_tables_metadata.parquet", engine="pyarrow", index=False)
        columns_df.to_parquet(output_folder + "columns_metadata.parquet", engine="pyarrow", index=False)