import pandas as pd
from typing import Dict, List, Optional

def distribute_r_values_to_d(region_df, region_value_col, dist_df, dist_value_col, new_col_name, d_to_r):
    """
    This function takes the regional values in the column region_df[region_value_col]
    and distributes every region value according to the proportion of dist_df[dist_value_col]
    for every district to the proportion of the dist_df[dist_value_col] sum for the whole region.

    Parameters:
    - region_df (pd.DataFrame): DataFrame indexed by region names.
    - region_value_col (str): Column name in region_df containing values to be distributed.
    - dist_df (pd.DataFrame): DataFrame indexed by district names.
    - dist_value_col (str): Column name in dist_df used as basis for distribution.
    - new_col_name (str): Name of the new column to store distributed values.
    - d_to_r (dict): Dictionary mapping district names to region names.

    Returns:
    - pd.DataFrame: Copy of dist_df with a new column `new_col_name` with distributed values.
    """

    # Validate index names
    if dist_df.index.name != "District":
        raise ValueError(f"dist_df must have index name 'District', got '{dist_df.index.name}'")
    if region_df.index.name != "Region":
        raise ValueError(f"region_df must have index name 'Region', got '{region_df.index.name}'")

    # Verify all districts are in d_to_r
    missing_districts = set(dist_df.index) - set(d_to_r)
    if missing_districts:
        raise ValueError(f"Missing region mapping for districts: {missing_districts}")

    # Add region information to dist_df
    dist_df = dist_df.copy()
    dist_df["Region"] = dist_df.index.map(d_to_r)

    # Group by region and compute totals for distribution
    dist_grouped = dist_df.groupby("Region")[dist_value_col].transform("sum")

    # Compute share of each district in its region
    dist_df["share"] = dist_df[dist_value_col] / dist_grouped

    # Map regional values from region_df
    dist_df["regional_value"] = dist_df["Region"].map(region_df[region_value_col])

    # Final distributed value
    dist_df[new_col_name] = dist_df["share"] * dist_df["regional_value"]

    # Drop temporary columns
    return dist_df.drop(columns=["Region", "share", "regional_value"])
    
def interpolate_missing_years(year_to_df: Dict[int, pd.DataFrame], col_name: str,
                               all_years: List[int],
                               empty_dist_df: pd.DataFrame,
                               extrapolate_trends: bool = True) -> Dict[int, pd.DataFrame]:
    """
    Fills in values for the missing years through LINEAR interpolation between
    existing datasets and extrapolation (or duplication) for marginal years.

    Parameters:
    - year_to_df (Dict[int,pd.DataFrame]): A dictionary mapping years to dfs with data.
    - col_name (str): Name of the column in year_to_df dataframes to be linearly interpolated.
    - all_years (list): List of all years for which to interpolate
    - empty_dist_df (pd.DataFrame): An empty dataframe with 'District' index.
    - extrapolate_trends (bool): If True, extrapolate internal trends at margins;
                                 if False, copy nearest existing year's data.

    Returns:
    - year_to_df (Dict[int,pd.DataFrame]): The updated year_to_df dictionary.
    """
    # Ensure all_years list is sorted
    all_years = sorted(all_years)

    # --- Determine available and missing years ---
    years_present = sorted([year for year, df in year_to_df.items() if col_name in df.columns])
    
    if not years_present:
        raise ValueError(f"No data found with column '{col_name}' in any year.")

    # --- Interpolate between known years ---
    for year_index in range(len(years_present) - 1):
        year_1, year_2 = years_present[year_index], years_present[year_index + 1]
        df1, df2 = year_to_df[year_1], year_to_df[year_2]
        for year in range(year_1 + 1, year_2):
            weight = (year - year_1) / (year_2 - year_1)
            interpolated_values = (1 - weight) * df1[col_name] + weight * df2[col_name]
            new_df = year_to_df.get(year, empty_dist_df.copy())
            new_df[col_name] = interpolated_values
            year_to_df[year] = new_df

    # --- Extrapolate or copy before the first year ---
    min_year = years_present[0]
    if all_years[0] < min_year:
        if extrapolate_trends and len(years_present) >= 2:
            second_year = years_present[1]
            delta = (year_to_df[second_year][col_name] - year_to_df[min_year][col_name]) / (second_year - min_year)
            for year in range(all_years[0], min_year):
                years_back = min_year - year
                extrapolated_values = year_to_df[min_year][col_name] - years_back * delta
                new_df = year_to_df.get(year, empty_dist_df.copy())
                new_df[col_name] = extrapolated_values
                year_to_df[year] = new_df
        else:
            for year in range(all_years[0], min_year):
                new_df = year_to_df.get(year, empty_dist_df.copy())
                new_df[col_name] = year_to_df[min_year][col_name]
                year_to_df[year] = new_df

    # --- Extrapolate or copy after the last year ---
    max_year = years_present[-1]
    if all_years[-1] > max_year:
        if extrapolate_trends and len(years_present) >= 2:
            prev_year = years_present[-2]
            delta = (year_to_df[max_year][col_name] - year_to_df[prev_year][col_name]) / (max_year - prev_year)
            for year in range(max_year + 1, all_years[-1] + 1):
                years_forward = year - max_year
                extrapolated_values = year_to_df[max_year][col_name] + years_forward * delta
                new_df = year_to_df.get(year, empty_dist_df.copy())
                new_df[col_name] = extrapolated_values
                year_to_df[year] = new_df
        else:
            for year in range(max_year + 1, all_years[-1] + 1):
                new_df = year_to_df.get(year, empty_dist_df.copy())
                new_df[col_name] = year_to_df[max_year][col_name]
                year_to_df[year] = new_df

    # --- Final step: sort indices alphabetically for consistency ---
    for year in year_to_df:
        year_to_df[year] = year_to_df[year].sort_index()

    return year_to_df


def fill_zero_values_by_proportional_scaling(
    year_to_df: Dict[int, pd.DataFrame],
    col_name: str,
    only_fill_indices: Optional[List[str]] = None
) -> Dict[int, pd.DataFrame]:
    """
    Fills zero values (treated as missing) in a specified column of a {year: df} dictionary.

    For each zero in year x, finds the closest year y where the value is nonzero for that row,
    and scales it by the ratio of total sums between x and y using only shared non-zero indices.

    Parameters:
    - year_to_df (dict): Dictionary mapping years to DataFrames with a common index.
    - col_name (str): Column name in which to fill missing (zero) values.
    - only_fill_indices (list, optional): List of indices for which values should be imputed.
      If None, all indices with zero values will be considered.

    Returns:
    - new_dict (dict): A new dictionary with updated DataFrames.
    """
    from copy import deepcopy

    filled_dict = deepcopy(year_to_df)
    years = sorted(year_to_df.keys())

    for year in years:
        df = filled_dict[year]
        zero_mask = df[col_name] == 0

        # Restrict to specific indices if provided
        if only_fill_indices is not None:
            zero_mask &= df.index.isin(only_fill_indices)

        if zero_mask.sum() == 0:
            continue  # No zeros to fill

        for idx in df.index[zero_mask]:
            # Try to find the closest year with a non-zero value for this index
            closest_year = None
            for offset in range(1, len(years)):
                for direction in [-1, 1]:  # check earlier and later
                    try_year = year + offset * direction
                    if try_year in year_to_df and idx in year_to_df[try_year].index:
                        val = year_to_df[try_year].loc[idx, col_name]
                        if val != 0:
                            closest_year = try_year
                            break
                if closest_year is not None:
                    break

            if closest_year is not None:
                df_x = year_to_df[year]
                df_y = year_to_df[closest_year]

                # Filter to common non-zero entries
                common_index = df_x.index.intersection(df_y.index)
                valid_index = [
                    i for i in common_index
                    if df_x.at[i, col_name] != 0 and df_y.at[i, col_name] != 0
                ]

                if valid_index:
                    sum_x = df_x.loc[valid_index, col_name].sum()
                    sum_y = df_y.loc[valid_index, col_name].sum()
                    scale = sum_x / sum_y if sum_y != 0 else 1
                    estimated_val = df_y.at[idx, col_name] * scale
                    df.at[idx, col_name] = estimated_val
                    print(f"Filled missing value for '{idx}' in {year} using {closest_year} with scaling factor {scale:.3f}")
                else:
                    print(f"No valid common indices to estimate for '{idx}' in {year}. Skipped.")
            else:
                print(f"No data found to estimate missing value for '{idx}' in {year}. Skipped.")

    return filled_dict

def sum_up_regions(df: pd.DataFrame, d_to_r: Dict[str, str]) -> pd.DataFrame:
    """
    Aggregates a DataFrame from district-level to region-level using a global 'd_to_r' mapping.
    Per capita columns are recalculated as (aggregated value) / (aggregated population).

    Parameters:
    - df (pd.DataFrame): DataFrame with 'District' as index.

    Returns:
    - pd.DataFrame: Region-aggregated DataFrame.
    """
    if df.index.name != 'District':
        raise ValueError("Input DataFrame must have 'District' as its index.")

    df_copy = df.copy()

    if 'Region' in df_copy.columns:
        raise ValueError("'Region' column already exists in the DataFrame. Please remove or rename it before proceeding.")

    # Map Districts to Regions
    df_copy['Region'] = df_copy.index.map(d_to_r)

    if df_copy['Region'].isnull().any():
        missing = df_copy[df_copy['Region'].isnull()].index.tolist()
        raise ValueError(f"Some districts are not in the d_to_r mapping: {missing}")

    # Separate per capita and normal columns
    per_capita_cols = [col for col in df_copy.columns if col.endswith('_per_capita') or col.endswith(' Per Capita')]
    normal_cols = [col for col in df_copy.select_dtypes(include='number').columns if col not in per_capita_cols and col != 'Population']

    # Group base columns
    grouped = df_copy.groupby('Region')[normal_cols + ['Population']].sum(numeric_only=True)

    # Recalculate per capita columns
    for col in per_capita_cols:
        # Try to find corresponding original column
        base_col = (
            col.removesuffix('_per_capita') if col.endswith('_per_capita')
            else col.removesuffix(' Per Capita') if col.endswith(' Per Capita')
            else None
        )
        if base_col and base_col in df_copy.columns:
            grouped[col] = (
                df_copy.groupby('Region')[base_col].sum()
                / df_copy.groupby('Region')['Population'].sum()
            )
        else:
            raise ValueError(f"Could not find matching base column for per capita column: {col}")

    return grouped

def fill_zeros_with_column(df, target_col, source_col):
    """
    Replace 0s in `target_col` of `df` with corresponding values from `source_col`.

    Parameters:
        df (pd.DataFrame): Input DataFrame with same indices for both columns.
        target_col (str): Name of the column to fill.
        source_col (str): Name of the column to pull values from.
    
    Returns:
        pd.DataFrame: A new DataFrame with the target column updated.
    """
    df = df.copy()
    zero_mask = df[target_col] == 0
    df.loc[zero_mask, target_col] = df.loc[zero_mask, source_col]
    return df

def collect_variable_over_years(production_by_year: dict, variable: str, d_to_r: Dict[str, str], years: list = None) -> pd.DataFrame:
    """
    Collects a single variable (e.g., 'Agriculture VA') from regionally aggregated DataFrames
    over multiple years.

    Parameters:
    - production_by_year (dict): Dictionary of year → district-level DataFrame
    - variable (str): The column name to extract after regional aggregation
    - years (list, optional): List of years to include. If None, all years in production_by_year are used.

    Returns:
    - pd.DataFrame: Region x Year DataFrame with values of the selected variable.
    """
    if years is None:
        years = sorted(production_by_year.keys())

    aggr_dict = {}

    for year in years:
        if year not in production_by_year:
            raise KeyError(f"Year {year} not found in production_by_year.")

        regional_df = sum_up_regions(production_by_year[year], d_to_r=d_to_r)
        if variable not in regional_df.columns:
            raise KeyError(f"Column '{variable}' not found in aggregated DataFrame for year {year}.")

        aggr_dict[year] = regional_df[variable]

    result_df = pd.DataFrame(aggr_dict)
    return result_df[sorted(result_df.columns)]
