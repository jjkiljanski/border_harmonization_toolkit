import pandas as pd
import os
from collections import defaultdict

from administrative_history.core.processor import AdministrativeHistoryProcessor
from administrative_history.data_models.processing_config import CombineDataTablesArgs, CreateDistAreaDatasetArgs
from administrative_history.data_models.econ_data_metadata import DataTableMetadata, ColumnMetadata

from collections import defaultdict
from typing import List

def collapse_metadata_dicts(
    adm_history_processor: AdministrativeHistoryProcessor,
    metadata_list: List[DataTableMetadata],
    new_data_table_id: str
) -> DataTableMetadata:
    """
    Collapse multiple DataTableMetadata objects into one, aligning source/link/table/page/pdf_page
    into lists if any of them are not unique, otherwise collapsing to a single value.
    """

    def collapse_field(values):
        unique = set(values)
        return unique.pop() if len(unique) == 1 else "VARIES"
    
    def unique_or_none(values):
        unique = set(values)
        return unique.pop() if len(unique) == 1 else None
    
    def unique_or_error(values):
        unique = set(values)
        if len(unique) == 1:
            return unique.pop()
        else:
            raise ValueError(
                f"Attempted to sum up datasets {[md.data_table_id for md in metadata_list]} "
                f"with incompatible metadata entries: {unique}."
            )
    
    def concatenate(attr_name):
        if len({getattr(md, attr_name) for md in metadata_list}) <= 1:
            return getattr(metadata_list[0], attr_name)
        else:
            values_to_concatenate = [
                f"{md.data_table_id}: {getattr(md, attr_name)}" for md in metadata_list
            ]
            return ", ".join(values_to_concatenate)

    def collapse_columns(metadata_list):
        """
        Collapse (merge) the `columns` sections from multiple `DataTableMetadata` objects
        into a single, harmonized dictionary of `ColumnMetadata`.

        This function:
        • Groups columns across all metadata objects by their English `category` value.
        • Ensures that the corresponding Polish (`pol`) categories for each group are identical.
        • Verifies that `unit` and `data_type` are consistent within each category group.
        • Aggregates completeness statistics across datasets (before and after imputation).
        • Builds a new unified `ColumnMetadata` entry per unique category, 
            where both `eng` and `pol` values are retained in a dictionary.

        The result is a dict mapping representative column names to merged `ColumnMetadata` objects.

        Raises:
            ValueError:
                - If any column `category` is not a dict or missing 'eng'/'pol' keys.
                - If multiple Polish categories correspond to the same English one.
                - If `unit` or `data_type` differ across merged columns.
        """

        grouped_columns = defaultdict(list)

        # --- 1. Group columns across metadata by their English category ---
        for md in metadata_list:
            for col_name, col_meta in md.columns.items():
                if not isinstance(col_meta.category, dict):
                    raise ValueError(
                        f"Column '{col_name}' in '{md.data_table_id}' has non-dict category: {col_meta.category!r}"
                    )
                if "eng" not in col_meta.category or "pol" not in col_meta.category:
                    raise ValueError(
                        f"Column '{col_name}' in '{md.data_table_id}' category must have both 'eng' and 'pol' keys."
                    )

                eng_key = col_meta.category["eng"]
                grouped_columns[eng_key].append((col_name, col_meta))

        merged_columns = {}

        # --- 2. Process each category group ---
        for eng_category, col_entries in grouped_columns.items():
            # Ensure Polish categories are consistent for the same English key
            pol_values = {cm.category["pol"] for _, cm in col_entries}
            if len(pol_values) != 1:
                details = {
                    md_id: cm.category["pol"]
                    for (md_id, (cn, cm)) in zip(
                        [md.data_table_id for md in metadata_list], col_entries
                    )
                }
                raise ValueError(
                    "Inconsistent 'pol' category values for the same 'eng' category "
                    f"'{eng_category}': {pol_values}. Details per dataset: {details}"
                )
            pol_category = pol_values.pop()

            # Ensure unit and data_type consistency
            units = {cm.unit for _, cm in col_entries}
            if len(units) != 1:
                raise ValueError(
                    f"Inconsistent 'unit' values for category '{eng_category}': {units}"
                )

            data_types = {cm.data_type for _, cm in col_entries}
            if len(data_types) != 1:
                raise ValueError(
                    f"Inconsistent 'data_type' values for category '{eng_category}': {data_types}"
                )

            # --- 3. Compute completeness stats ---
            go_to_adm_state = adm_history_processor.adm_history.find_adm_state_by_date(
                adm_history_processor.harmonize_to_date
            )
            total_all = len(go_to_adm_state.all_district_names(homeland_only=True))

            # Before imputation
            n_of_none = sum(1 for _, cm in col_entries if cm.n_not_na is None)
            if n_of_none > 0:
                total_not_na = total_na = completeness = None
            else:
                total_not_na = sum(cm.n_not_na or 0 for _, cm in col_entries)
                total_na = total_all - total_not_na
                completeness = total_not_na / total_all

            # After imputation
            n_of_none_after_imputation = sum(
                1 for _, cm in col_entries if cm.n_not_na_after_imputation is None
            )
            if n_of_none_after_imputation > 0:
                total_not_na_after_imputation = total_na_after_imputation = completeness_after_imputation = None
            else:
                total_not_na_after_imputation = sum(
                    cm.n_not_na_after_imputation or 0 for _, cm in col_entries
                )
                total_na_after_imputation = total_all - total_not_na_after_imputation
                completeness_after_imputation = total_not_na_after_imputation / total_all

            # --- 4. Build merged ColumnMetadata entry ---
            representative_name = col_entries[0][0]  # Use first encountered name
            merged_columns[representative_name] = ColumnMetadata(
                unit=next(iter(units)),
                category={"eng": eng_category, "pol": pol_category},
                data_type=next(iter(data_types)),
                n_na=total_na,
                n_not_na=total_not_na,
                completeness=completeness,
                completeness_after_imputation=completeness_after_imputation,
                n_na_after_imputation=total_na_after_imputation,
                n_not_na_after_imputation=total_not_na_after_imputation,
            )

        return merged_columns

    # --- New joint collapsing logic for sources/links/tables/pages/pdf_pages ---
    sources = [md.source for md in metadata_list]
    links = [md.link for md in metadata_list]
    tables = [getattr(md, "table", None) for md in metadata_list]
    pages = [getattr(md, "page", None) for md in metadata_list]
    pdf_pages = [getattr(md, "pdf_page", None) for md in metadata_list]

    def all_equal(values):
        return all(v == values[0] for v in values)

    def flatten(values):
        """Flatten nested lists like [['a'], ['b']] -> ['a', 'b']"""
        flat = []
        for v in values:
            if isinstance(v, list):
                flat.extend(v)   # unwrap inner list
            else:
                flat.append(v)   # keep scalar as-is
        return flat

    if all_equal(sources) and all_equal(links) and all_equal(tables) and all_equal(pages) and all_equal(pdf_pages):
        # Everything is unique → keep scalars
        source_out = sources[0]
        link_out = links[0]
        table_out = tables[0]
        page_out = pages[0]
        pdf_page_out = pdf_pages[0]
    else:
        # Not unique → return aligned, flattened lists
        source_out = flatten(sources)
        link_out = flatten(links)
        table_out = flatten(tables)
        page_out = flatten(pages)
        pdf_page_out = flatten(pdf_pages)

    # --- Build collapsed metadata ---
    return DataTableMetadata(
        data_table_id=new_data_table_id,
        adm_level=unique_or_error([md.adm_level for md in metadata_list]),
        source=source_out,
        link=link_out,
        table=table_out,
        page=page_out,
        pdf_page=pdf_page_out,
        description={
            "pol": ", ".join(
                f"{md.data_table_id}: {md.description.get('pol', '')}"
                for md in metadata_list
            ),
            "eng": ", ".join(
                f"{md.data_table_id}: {md.description.get('eng', '')}"
                for md in metadata_list
            ),
        },
        date=collapse_field([md.date for md in metadata_list]),
        orig_adm_state_date=unique_or_none(
            [md.adm_state_date for md in metadata_list]
        ),  # Use adm_state_date as "original"
        adm_state_date=unique_or_error([md.adm_state_date for md in metadata_list]),
        standardization_comments=(
            "Summed up from the datasets: "
            + ", ".join(
                f"{md.data_table_id} (orig_adm_state_date: {md.orig_adm_state_date})"
                for md in metadata_list
            )
            + "\n"
            + concatenate("standardization_comments")
        ),
        harmonization_method=concatenate("harmonization_method"),
        imputation_method=concatenate("imputation_method"),
        columns=collapse_columns(metadata_list=metadata_list),
    )

def load_and_validate_data_tables_for_summing(folder, arguments):
    """
    Load CSV data tables and validate that:
    - Each table has exactly one of the allowed columns.
    - All tables consistently use the same allowed column.
    """

    # Define the allowed columns (expandable later)
    allowed_columns = ["District", "City"]

    dfs = []
    index_column = None  # The column that all dfs must use

    for data_table_name in arguments.data_tables_list:
        path = os.path.join(folder, f"{data_table_name}.parquet")
        df = pd.read_parquet(path)

        # Which allowed columns are present in this df?
        present_allowed = [col for col in allowed_columns if col in df.columns]

        if len(present_allowed) == 0:
            raise ValueError(
                f"Data table \"{data_table_name}\" must contain one of {allowed_columns}, "
                f"but none found. Columns present: {list(df.columns)}"
            )
        if len(present_allowed) > 1:
            raise ValueError(
                f"Data table \"{data_table_name}\" contains multiple allowed columns "
                f"{present_allowed}, which is not permitted."
            )

        # Decide or check consistency of the chosen allowed column
        if index_column is None:
            index_column = present_allowed[0]
        elif present_allowed[0] != index_column:
            raise ValueError(
                f"Inconsistent column usage: Data table \"{data_table_name}\" uses "
                f"'{present_allowed[0]}', while previous tables use '{index_column}'."
            )

        dfs.append(df)

    return dfs, index_column


def combine_data_tables(adm_history_processor: AdministrativeHistoryProcessor, arguments: CombineDataTablesArgs) -> None:
    """
    This method loads multiple tables from CSV files, sums them up to a new data table,
    saves it, and deletes the old data tables.
    The metadata of both the datasets are collapsed to one.

    This method should be applied only to already processed datasets!
    """
    folder = adm_history_processor.processed_data_parquet_root
    print(f"🟡 Starting combine_data_tables with '{arguments.method}' method: {arguments.data_tables_list} -> {arguments.new_data_table_name}.parquet")

    dfs = []

    # --- Load all data tables and ensure that all have either "District" or "City" column.
    dfs, index_column = load_and_validate_data_tables_for_summing(folder, arguments)

    # ------------------------------
    # Additional checks according to method
    # ------------------------------
    if arguments.method == "sum":
        # Ensure all have the same values in the index_column (and in same order)
        base_indices = dfs[0][index_column].tolist()
        for i, df in enumerate(dfs[1:], start=1):
            if df[index_column].tolist() != base_indices:
                raise ValueError(
                    f"'{index_column}' values or order mismatch in data table: {arguments.data_tables_list[i]}"
                )

        # Sum up data tables (excluding the index column)
        result_df = dfs[0].copy()
        numeric_cols = [col for col in result_df.columns if col != index_column]
        for df in dfs[1:]:
            result_df[numeric_cols] += df[numeric_cols]

    elif arguments.method == "concatenate":
        # Ensure no index value repeats across dfs
        all_indices = pd.concat([df[index_column] for df in dfs], ignore_index=True)
        duplicated = all_indices[all_indices.duplicated()]

        if not duplicated.empty:
            raise ValueError(
                f"Duplicate '{index_column}' values found across tables: {duplicated.unique().tolist()}"
            )

        # Concatenate all dataframes
        result_df = pd.concat(dfs, ignore_index=True)

    else:
        raise ValueError(
            f"The method name {arguments.method} passed as argument "
            f"to the combine_data_tables method is not supported."
        )

    # Write result
    output_path = os.path.join(folder, f"{arguments.new_data_table_name}.parquet")
    result_df.to_parquet(output_path, index=False)

    # Find metadata dicts of the datasets
    metadata_dicts = [metadata_dict for metadata_dict in adm_history_processor.processed_data_metadata if metadata_dict.data_table_id in arguments.data_tables_list]

    # Collapse metadata and update the processed_data_metadata list
    collapsed_metadata = collapse_metadata_dicts(adm_history_processor, metadata_dicts, arguments.new_data_table_name)
    adm_history_processor.processed_data_metadata = [
        md for md in adm_history_processor.processed_data_metadata
        if md.data_table_id not in arguments.data_tables_list
    ] + [collapsed_metadata]

    print(f"✅ Finished combine_data_tables: Output written to {output_path}")

def create_dist_area_dataset(adm_history_processor: AdministrativeHistoryProcessor, arguments: CreateDistAreaDatasetArgs):
    """
    This method creates a data table with district areas for the adm_history_processor.harmonize_to_date.
    Table metadata is created on the basis of the info passed in arguments.
    
    Returns:
    - df (pd.DataFrame): DataFrame with 'District' and 'Area' columns. Area is in hectares.
    """
    print(f"🟡 Starting create_dist_area_dataset (adm. state for {adm_history_processor.harmonize_to_date.date()})")
    data_table_metadata = arguments.data_table_metadata
    output_path = adm_history_processor.processed_data_parquet_root + data_table_metadata.data_table_id + ".parquet"
    # Get the GeoDataFrame of districts
    dist_gdf = adm_history_processor.adm_history.dist_registry._plot_layer(adm_history_processor.harmonize_to_date)

    # Select only homeland values
    homeland_dist_names = adm_history_processor.adm_history.find_adm_state_by_date(adm_history_processor.harmonize_to_date).all_district_names(homeland_only=True)
    dist_gdf = dist_gdf[dist_gdf["name_id"].isin(homeland_dist_names)]

    # Project to a metric CRS (e.g., EPSG:3857 or any equal-area projection)
    dist_gdf_proj = dist_gdf.to_crs(epsg=3857)

    # Calculate area in square meters, then convert to hectares
    dist_gdf_proj["Area"] = dist_gdf_proj["geometry"].area / 10_000  # m² → ha

    # Create DataFrame with 'District' and 'Area'
    df = dist_gdf_proj[["name_id", "Area"]].rename(columns={"name_id": "District"})

    # Write the DataFrame to csv
    df.to_parquet(output_path, index = False)

    # Update processed_data_metadata
    data_table_metadata.date = adm_history_processor.harmonize_to_date.strftime("%d.%m.%Y")
    data_table_metadata.adm_state_date = adm_history_processor.harmonize_to_date
    adm_history_processor.processed_data_metadata.append(data_table_metadata)

    print(f"✅ Finished create_dist_area_dataset: Metadata and output added to the database.")