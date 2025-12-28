import pandas as pd
import numpy as np
from collections import defaultdict
import itertools

################################# Theil-index computation utils ################################

# === Helper: Theil index function ===
def theil_index(series: pd.Series, weights: pd.Series = None) -> float:
    series = series[series > 0]  # Avoid log(0) and div-by-zero
    if weights is not None:
        weights = weights.loc[series.index]
        weights = weights / weights.sum()
        mean = np.average(series, weights=weights)
        theil = np.sum(weights * (series / mean) * np.log(series / mean))
    else:
        mean = series.mean()
        theil = np.mean((series / mean) * np.log(series / mean))
    return theil

# === 1. Regional decomposition of Theil index ===
def decompose_theil_regionally(
    df: pd.DataFrame,
    col_name: str,
    d_to_r: dict,
    population_col='Population',
    pop_df: pd.DataFrame = None
):
    """
    Decomposes the Theil index into within- and between-region components.

    Parameters:
    - df: DataFrame with values and district index
    - col_name: Column name with the variable of interest
    - d_to_r: Dict mapping districts to regions
    - population_col: Name of population column (default: 'Population')
    - pop_df: Optional DataFrame with population values

    Returns:
    Dict with 'Total_Theil', 'Between_Region', and 'Within_Region' inequality.
    """
    df = df.copy()
    df['Region'] = df.index.map(d_to_r)

    # Use df if pop_df not provided
    if pop_df is None:
        pop_df = df
    else:
        pop_df = pop_df.copy()
    
    # Make sure both dataframes have aligned indices
    df = df.join(pop_df[[population_col]], how='left', rsuffix='_pop')

    # Total Theil (district-level)
    total = theil_index(df[col_name], weights=df[population_col])

    # Step 1: Compute average VA per capita by region (weighted by population)
    region_means = df.groupby('Region').apply(
        lambda g: np.average(g[col_name], weights=g[population_col]),
        include_groups=False
    )

    region_pops = df.groupby('Region')[population_col].sum()
    overall_mean = np.average(df[col_name], weights=df[population_col])

    # Between-region inequality
    between = np.sum((region_pops / region_pops.sum()) * 
                     (region_means / overall_mean) * 
                     np.log(region_means / overall_mean))

    # Within-region inequality
    within = 0
    for region, group in df.groupby('Region'):
        t = theil_index(group[col_name], weights=group[population_col])
        weight = group[population_col].sum() / df[population_col].sum()
        within += weight * t

    return {
        'Total_Theil': total,
        'Between_Region': between,
        'Within_Region': within
    }

# === 2. Sectoral decomposition of Theil index ===
def compute_shapley_contributions(df, population_col='Population'):
    """Computes Shapley value decomposition of inequality across sectors."""
    sector_cols = [
        'Agriculture_VA_constant_prices_per_capita',
        'Industry_VA_constant_prices_per_capita',
        'Private_Services_VA_constant_prices_per_capita',
        'Public_Services_VA_constant_prices_per_capita'
    ]
    n = len(sector_cols)
    shapley_values = {sector: 0.0 for sector in sector_cols}
    perms = list(itertools.permutations(sector_cols))

    for perm in perms:
        included = []
        previous_va = np.zeros(len(df))

        for i, sector in enumerate(perm):
            included.append(sector)
            current_va = previous_va + df[sector]
            
            theil_prev = theil_index(previous_va, df[population_col]) if i > 0 else 0.0
            theil_curr = theil_index(current_va, df[population_col])
            
            marginal_contribution = theil_curr - theil_prev
            shapley_values[sector] += marginal_contribution

            previous_va = current_va

    num_perms = len(perms)
    for sector in shapley_values:
        shapley_values[sector] /= num_perms

    return shapley_values

# === Main Analysis per Year ===
def analyze_all_years_theil(production_by_year, d_to_r, sum_up_regions):
    results = defaultdict(dict)

    for year, df in production_by_year.items():
        df = df.copy()
        
        # Dummy: If no population column exists, simulate equal population
        if 'Population' not in df.columns:
            df['Population'] = 1  # equal weighting as fallback
        
        # 1. Region vs District decomposition of VA (total VA and for each sector)
        for prefix in ['', 'Agriculture_', 'Industry_', 'Private_Services_', 'Public_Services_']:
            region_result = decompose_theil_regionally(df=df, col_name=f'{prefix}VA_constant_prices_per_capita', d_to_r=d_to_r)
            results[year][f'Regional_Decomposition_{prefix}VA'] = region_result
        
        # 2. Sector decomposition - district level
        sector_result_district = compute_shapley_contributions(df)
        results[year]['Sectoral_Decomposition_District'] = sector_result_district
        
        # 3. Sector decomposition - region level
        region_df = sum_up_regions(df, d_to_r)
        sector_result_region = compute_shapley_contributions(region_df)
        results[year]['Sectoral_Decomposition_Region'] = sector_result_region

    return results


############################## Spatial econometrics ####################################
from shapely.geometry import Point

from pyproj import Geod

def create_distance_matrix(dist_geoms):
    """
    Computes a geodesic (ellipsoidal) distance matrix in meters.
    """
    # Ensure coordinates are in geographic CRS (degrees)
    if not dist_geoms.crs.is_geographic:
        dist_geoms = dist_geoms.to_crs(4326)
    
    geod = Geod(ellps="WGS84")  # standard Earth ellipsoid
    centroids = dist_geoms.geometry.centroid
    coords = {i: (pt.x, pt.y) for i, pt in zip(dist_geoms.index, centroids)}
    districts = dist_geoms.index

    D = pd.DataFrame(index=districts, columns=districts, dtype=float)

    for i in districts:
        lon1, lat1 = coords[i]
        for j in districts:
            if pd.isna(D.at[i, j]):
                lon2, lat2 = coords[j]
                # returns (fwd_azimuth, back_azimuth, distance_meters)
                _, _, dist_m = geod.inv(lon1, lat1, lon2, lat2)
                D.at[i, j] = D.at[j, i] = dist_m
    return D

from libpysal.weights import W

def distance_matrix_to_weights(distance_matrix, threshold, binary=True):
    """
    Converts a distance matrix to a PySAL weights object (W) using a distance threshold.
    """
    neighbors = {}
    weights = {}

    for i in distance_matrix.index:
        # Find all neighbors within threshold (excluding self)
        valid = distance_matrix.loc[i][(distance_matrix.loc[i] > 0) & (distance_matrix.loc[i] <= threshold)]
        neighbors[i] = list(valid.index)
        if binary:
            weights[i] = [1.0] * len(valid)
        else:
            weights[i] = list(1 / valid)  # inverse distance
    
    return W(neighbors, weights)

############################## Functions to measure spatial correlation ###########################

from libpysal.weights import DistanceBand
from esda.moran import Moran, Moran_Local
from esda.geary import Geary

def compute_morans_I(df, col_name, weights):
    """
    Computes global Moran's I.
    """
    y = df[col_name].values
    mi = Moran(y, weights)
    return {
        "Moran's I": mi.I,
        "Expected I": mi.EI,
        "p-value": mi.p_norm,
        "z-score": mi.z_norm
    }

def compute_gearys_C(df, col_name, weights):
    """
    Computes global Geary's C.
    """
    y = df[col_name].values
    gc = Geary(y, weights)
    return {
        "Geary's C": gc.C,
        "Expected C": gc.EC,
        "p-value": gc.p_norm,
        "z-score": gc.z_norm
    }

def compute_lisa(df, col_name, weights):
    """
    Computes LISA (Local Moran's I).
    Returns original values, local Moran's I, and cluster labels.
    """
    y = df[col_name].values
    lisa = Moran_Local(y, weights)

    result = df.copy()
    result["Local I"] = lisa.Is
    result["p-value"] = lisa.p_sim

    # Cluster labels:
    # HH: High-high, LL: Low-low, HL: High-low, LH: Low-high, NS: Not significant
    cluster = []
    for i in range(len(y)):
        if lisa.p_sim[i] < 0.05:
            if lisa.q[i] == 1:
                cluster.append("HH")
            elif lisa.q[i] == 2:
                cluster.append("LH")
            elif lisa.q[i] == 3:
                cluster.append("LL")
            elif lisa.q[i] == 4:
                cluster.append("HL")
        else:
            cluster.append("NS")
    
    result["LISA Cluster"] = cluster
    return result

######################################### Variance decomposition ##############################################
def variance_decomposition(production_by_year, d_to_r, variable):
    """
    This function decomposes the variance to between-regional, and within-regional variance
    """
    results = []

    for year, df in production_by_year.items():
        # Copy df to avoid modifying original
        df = df.copy()

        # Add 'Region' column based on district mapping
        df['Region'] = df.index.map(d_to_r)

        # Drop rows with missing region or variable values
        df = df.dropna(subset=['Region', variable])

        if df.empty:
            # Skip if no data
            continue

        # Calculate total variance (district-level)
        total_var = df[variable].var(ddof=1)

        # Calculate region means
        region_means = df.groupby('Region')[variable].mean()

        # Calculate weights: proportion of districts in each region
        region_sizes = df.groupby('Region').size()
        weights = region_sizes / region_sizes.sum()

        # Between-region variance (weighted variance of region means)
        between_var = np.sum(weights * (region_means - region_means.mean())**2)

        # Within-region variance
        within_var = total_var - between_var

        # Handle edge cases
        if total_var == 0:
            prop_between = np.nan
            prop_within = np.nan
        else:
            prop_between = between_var / total_var
            prop_within = within_var / total_var

        results.append({
            'Year': year,
            'Total_Variance': total_var,
            'Between_Region_Variance': between_var,
            'Within_Region_Variance': within_var,
            'Proportion_Between': prop_between,
            'Proportion_Within': prop_within
        })

    return pd.DataFrame(results).sort_values('Year')


def compute_within_region_variance(production_by_year, d_to_r, pop_weighted=True):
    """
    Computes the within-region coeffiients of variation (potentially weighted by population if pop_weighted passed)"""
    results = []

    for year, df in production_by_year.items():
        # Assign region to each district
        df = df.copy()
        df['region'] = df.index.map(d_to_r)

        # Group by region and compute stats
        grouped = df.groupby('region')

        # Mean and variance per region
        region_stats = grouped['VA_constant_prices_per_capita'].agg(['mean', 'var']).rename(
            columns={'mean': 'mean_va', 'var': 'var_va'}
        ).reset_index()

        # Compute CV^2 = var / mean^2
        region_stats['cv_squared'] = region_stats['var_va'] / region_stats['mean_va']**2

        if pop_weighted:
            # Sum population per region
            region_pops = grouped['Population'].sum().reset_index(name='region_pop')
            region_stats = region_stats.merge(region_pops, on='region')

            # Weighted average of CV^2
            weighted_cv2 = (region_stats['cv_squared'] * region_stats['region_pop']).sum() / region_stats['region_pop'].sum()
        else:
            # Count of districts per region
            region_stats['district_count'] = grouped.size().values

            # Unweighted (by pop), but weighted by district count
            weighted_cv2 = (region_stats['cv_squared'] * region_stats['district_count']).sum() / region_stats['district_count'].sum()

        results.append({'year': year, 'weighted_cv_squared': weighted_cv2})

    return pd.DataFrame(results).sort_values('year')

#################################### 2-level beta-convergence model ######################################
from statsmodels.regression.mixed_linear_model import MixedLM

def estimate_multilevel_convergence(production_by_year, district_to_region):
    """
    Estimate 2-level beta-convergence model for districts nested within regions.
    
    Parameters:
    - production_by_year: dict of {year: pd.DataFrame} with district as index and columns including
      'VA_constant_prices_per_capita' (district-level total VA per capita)
    - district_to_region: pd.Series or dict mapping district -> region
    
    Returns:
    - fitted MixedLMResults object
    """

    # Sort years
    years = sorted(production_by_year.keys())
    y0, yT = years[0], years[-1]

    # Extract initial data with total VA and Population
    df_0 = production_by_year[y0][['VA_constant_prices', 'Population']].copy()

    # Extract final VA per capita (for growth rate)
    df_T = production_by_year[yT][['VA_constant_prices_per_capita']].copy()

    # Merge initial and final data on district (index)
    df = df_0.join(df_T, how='inner')
    df = df.dropna(subset=['VA_constant_prices', 'Population', 'VA_constant_prices_per_capita'])

    # Add region info
    if isinstance(district_to_region, dict):
        df['region'] = df.index.map(district_to_region)
    else:
        df['region'] = district_to_region.reindex(df.index)

    df = df.dropna(subset=['region'])

    # Compute district-level initial VA per capita explicitly (could be safer)
    df['VA_per_capita_0'] = df['VA_constant_prices'] / df['Population']

    # Compute average annual growth rate (log difference) of VA per capita
    T = yT - y0
    df['growth'] = (np.log(df['VA_constant_prices_per_capita']) - np.log(df['VA_per_capita_0'])) / T

    # Compute region total VA and population (initial year)
    region_sum_va = df.groupby('region')['VA_constant_prices'].transform('sum')
    region_sum_pop = df.groupby('region')['Population'].transform('sum')

    # Calculate regional average VA per capita (initial year)
    df['region_avg_va_per_capita_0'] = region_sum_va / region_sum_pop

    # Log-transform district and region initial values
    df['log_init_district'] = np.log(df['VA_per_capita_0'])
    df['log_init_region'] = np.log(df['region_avg_va_per_capita_0'])

    # Within-region deviation
    df['within_init'] = df['log_init_district'] - df['log_init_region']

    # Between-region (region means)
    df['between_init'] = df['log_init_region']

    # Prepare model data
    endog = df['growth']
    exog = pd.DataFrame({
        'Intercept': 1,
        'between_init': df['between_init'],
        'within_init': df['within_init']
    })
    groups = df['region']

    # Fit multilevel model with random intercept for region
    model = MixedLM(endog, exog, groups=groups)
    result = model.fit()

    print(result.summary())
    return result
