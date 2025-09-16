import pandas as pd
from datetime import datetime
import geopandas as gpd
from shapely.ops import nearest_points
from shapely.geometry import Point
from typing import List

from core.core import AdministrativeHistory
from data_models.adm_unit import DistrictRegistry

def take_from_closest_centroid(
        administrative_history: AdministrativeHistory,
        df: pd.DataFrame,
        adm_state_date: datetime,
        numeric_cols: List[str],
        data_completeness_threshold=0.2
    ) -> pd.DataFrame:
    """
    Imputes missing values in numeric columns using the value for geographically nearest district.

    For each missing value, the method finds the closest district (based on centroid distance) with a known value in the same column
    and uses that value. Only columns with missing data below `data_completeness_threshold` are imputed.

    Parameters:
    - administrative_history (AdministrativeHistory): Provides district geometries.
    - df (pd.DataFrame): DataFrame indexed by 'District', with numeric columns to impute.
    - adm_state_date (datetime): Date specifying the district boundaries to use.
    - numeric_cols (List[str]): Numeric columns to consider for imputation.
    - data_completeness_threshold (float): Max allowed missingness for a column to be imputed.

    Returns:
    - pd.DataFrame: DataFrame with missing values filled where possible.
    """
    # Step 1: Get the GeoDataFrame of districts and compute centroids
    gdf = administrative_history.dist_registry.gdf(adm_state_date).copy()
    gdf["centroid"] = gdf.geometry.centroid
    gdf.set_index("District", inplace=True)

    # Step 2: Join centroids to df (matching on index)
    df_with_centroids = df.copy()
    df_with_centroids = df_with_centroids.join(gdf[["centroid"]], how="left")

    # Step 3: Convert to GeoDataFrame for spatial calculations
    df_with_centroids = gpd.GeoDataFrame(df_with_centroids, geometry="centroid", crs=gdf.crs)

    # Step 4: Select columns to impute (with enough data to allow imputation)
    columns_to_impute = [
        col for col in numeric_cols
        if df[col].isna().mean() < data_completeness_threshold
    ]

    for col in columns_to_impute:
        unknown = df_with_centroids[df_with_centroids[col].isna()]
        known = df_with_centroids[df_with_centroids[col].notna()]

        for idx, row in unknown.iterrows():
            distances = known["centroid"].distance(row["centroid"])
            nearest_idx = distances.idxmin()
            df_with_centroids.at[idx, col] = known.at[nearest_idx, col]

    # Step 5: Clean up and return with original index
    df_with_centroids = df_with_centroids.drop(columns="centroid")
    return pd.DataFrame(df_with_centroids)