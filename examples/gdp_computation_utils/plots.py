import matplotlib.patches as mpatches
from sklearn.linear_model import LinearRegression
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
import os
from typing import Dict
from collections import defaultdict

import geopandas as gpd
import matplotlib.pyplot as plt
from adjustText import adjust_text

def plot_administrative_borders(
    dist_geoms,
    d_to_r_group,
    r_group_to_color,
    default_color='lightgray',
    figsize=(10, 10),
    focus_group=None,
    show_labels=True,
    save_to_path=None
):
    # Make a copy to avoid modifying the original
    geoms = dist_geoms.copy()

    # Ensure 'District' is a column
    if geoms.index.name == 'District':
        geoms = geoms.reset_index()

    # Map group info and default color
    geoms['r_group'] = geoms['District'].map(d_to_r_group)

    if focus_group is not None:
        # Focus mode: paint only selected group in green, rest in gray
        geoms['color'] = geoms['r_group'].apply(
            lambda g: 'lightgreen' if g == focus_group else 'lightgray'
        )
        edgecolor = 'white'
    else:
        # Normal mode: use color map and fallback color
        geoms['color'] = geoms['r_group'].map(r_group_to_color).fillna(default_color)
        edgecolor = 'white'

    # Plot
    fig, ax = plt.subplots(figsize=figsize)
    geoms.plot(ax=ax, color=geoms['color'], edgecolor=edgecolor)

    # Label logic
    if show_labels:
        texts = []
        if focus_group is not None:
            focus_geoms = geoms[geoms['r_group'] == focus_group]
            if not focus_geoms.empty:
                # Zoom to bounds of focus group
                ax.set_xlim(*focus_geoms.total_bounds[[0, 2]])
                ax.set_ylim(*focus_geoms.total_bounds[[1, 3]])

                # Labels for focus group only
                for idx, row in focus_geoms.iterrows():
                    if row['geometry'].is_empty or row['geometry'] is None:
                        continue
                    centroid = row['geometry'].centroid
                    label = ax.text(
                        centroid.x, centroid.y, row['District'],
                        fontsize=8, ha='center', va='center',
                        color='black', weight='bold'
                    )
                    label.set_horizontalalignment('center')
                    label.set_verticalalignment('center')
                    texts.append(label)
            else:
                print(f"⚠️ No districts found for focus_group='{focus_group}'. Skipping zoom/labels.")
        else:
            # Labels for all districts
            for idx, row in geoms.iterrows():
                if row['geometry'].is_empty or row['geometry'] is None:
                    continue
                centroid = row['geometry'].centroid
                label = ax.text(
                    centroid.x, centroid.y, row['District'],
                    fontsize=8, ha='center', va='center',
                    color='black', weight='bold'
                )
                label.set_horizontalalignment('center')
                label.set_verticalalignment('center')
                texts.append(label)

        adjust_text(
            texts,
            ax=ax,
            only_move={'points': 'y', 'text': 'xy'},
            arrowprops=dict(arrowstyle='-', color='gray', lw=0.5)
        )

    ax.set_axis_off()

    # Set background only if not focusing
    if focus_group is None:
        ax.set_facecolor('#d6d6d6')
        fig.patch.set_facecolor('#f2f2f2')

    plt.tight_layout()
    if save_to_path:
        plt.savefig(save_to_path, dpi=300)
        print(f"Plot saved to: {save_to_path}")
    else:
        plt.show()


def plot_convergence(
    year_df_dict,
    values_column,
    adm_level='District',
    color_by_district=False,
    d_to_group=None,
    group_to_color=None,
    plots_output_path=None,
    path_suffix=None,
    verbose = False
):
    """
    Plots values over time from a dictionary of {year: DataFrame}.

    Parameters:
    - year_df_dict (dict): Dictionary with year as keys and DataFrames as values.
    - values_column (str): Name of the column with values to plot.
    - adm_level (str): Name of the column representing districts or data level.
    - color_by_district (bool): Whether to color-code points by region group.
    - d_to_group (dict): Mapping from district to region group.
    - group_to_color (dict): Mapping from region group to color.
    - save_to_path (str): If provided, saves the plot to this path.

    Returns:
    - None
    """

    # Combine all years into a single DataFrame
    all_years_data = []
    for year, df in year_df_dict.items():
        if df.index.name != adm_level:
            raise ValueError(f"The df for year {year} in year_df_dict index name must be '{adm_level}'. Found: {df.index.name}.")
        temp = df.copy()
        temp['Year'] = year
        if values_column in temp.columns:
            all_years_data.append(temp[['Year', values_column]].reset_index())
            if verbose:
                print(f"Added values from {values_column} to plot.")
        else:
            if verbose:
                print(f"The df for year {year} doesn't contain {values_column} column.")

    if not all_years_data:
        raise ValueError("No valid data to plot. Check column names.")

    combined_df = pd.concat(all_years_data, ignore_index=True)

    if color_by_district:
        if d_to_group is None or group_to_color is None:
            raise ValueError("To color by district, both 'd_to_group' and 'group_to_color' must be provided.")

        # Validate all districts are mapped
        unique_districts = combined_df[adm_level].unique()
        unmapped_districts = [d for d in unique_districts if d not in d_to_group]
        if unmapped_districts:
            raise ValueError(f"The following districts are missing in 'd_to_group': {unmapped_districts}")

        # Validate all region groups are mapped
        combined_df['Region Group'] = combined_df[adm_level].map(d_to_group)
        unique_region_groups = combined_df['Region Group'].unique()
        unmapped_region_groups = [r for r in unique_region_groups if r not in group_to_color.keys()]
        if unmapped_region_groups:
            raise ValueError(f"The following region groups are missing in 'group_to_color': {unmapped_region_groups}")

        # Assign colors
        combined_df['Color'] = combined_df['Region Group'].map(group_to_color)

        # Plot
        plt.figure(figsize=(10, 6))
        plt.scatter(
            combined_df['Year'],
            combined_df[values_column],
            c=combined_df['Color'],
            alpha=0.7,
            s=15
        )

        # Custom legend
        legend_handles = [
            mpatches.Patch(color=color, label=region)
            for region, color in group_to_color.items()
        ]
        plt.legend(handles=legend_handles, title="Region Group", bbox_to_anchor=(1.05, 1), loc='upper left')

    else:
        # Default plotting
        plt.figure(figsize=(10, 6))
        plt.scatter(combined_df['Year'], combined_df[values_column], alpha=0.7)

    # Final plot formatting
    plt.title(f'{values_column.replace("_", " ")} by {adm_level} Over Time')
    plt.xlabel('Year')
    plt.ylabel(values_column.replace('_', ' '))
    plt.grid(True)
    plt.tight_layout()
    
    # Save or show the plot
    if path_suffix:
        save_to_path = plots_output_path + path_suffix + "convergence.png"
        plt.savefig(save_to_path, dpi=300, bbox_inches='tight')
        print(f"Plot saved to {save_to_path}")
        plt.close()
    else:
        plt.show()

from core.core import AdministrativeHistory

def plot_year_df_columns(
    administrative_history: AdministrativeHistory,
    custom_dist_grouping: Dict,
    plots_output_path: str,
    path_suffix: str,
    year_df_dict: Dict[int, pd.DataFrame],
    col_name: str,
    title: str,
    export_excel: bool = True,
    legend_min: float = None,
    legend_max: float = None,
    cmap: str = 'OrRd'
):
    """
    Creates maps for each column in each DataFrame in year_df_dict and optionally saves the data to an Excel file.

    Parameters:
    - path_suffix (str): Subfolder path where plots and Excel file will be saved.
    - year_df_dict (Dict[int, pd.DataFrame]): Dictionary mapping years to DataFrames.
    - col_name (str): Base name used in file naming and Excel export.
    - title (str): Base title for plots.
    - export_excel (bool): Whether to export the data to an Excel file.
    - legend_min (float): Minimum value plotted in the legend.
    - legend_max (float): Maximum value plotted in the legend.
    - cmap (str): Color map for map plotting.
    """
    import os

    os.makedirs(os.path.join(plots_output_path, path_suffix), exist_ok=True)

    # Collect all years' data into one DataFrame
    combined_df = pd.DataFrame()

    for year, df in year_df_dict.items():
        if col_name not in df.columns:
            raise ValueError(f"df for year {year} doesn't contain the {col_name} column!")
        plot_path = plots_output_path + path_suffix + f"{year}.png"
        fig = administrative_history.plot_dataset(
            df=df,
            col_name=col_name,
            adm_level='District',
            adm_state_date=administrative_history.harmonize_to_date,
            save_to_path=plot_path,
            title=f'{title} ({year})',
            legend_min = legend_min,
            legend_max = legend_max,
            cmap=cmap,
            custom_grouping = custom_dist_grouping
        )
        # Merge data into combined_df
        combined_df[year] = df[col_name]

    # Save to single-sheet Excel
    if export_excel:
        excel_path = plots_output_path + path_suffix + f"data.xlsx"
        combined_df.to_excel(excel_path, sheet_name="data")

def plot_df_columns_and_export_excel(
    administrative_history: AdministrativeHistory,
    custom_dist_grouping: Dict,
    plots_output_path: str,
    path_suffix: str,
    df: pd.DataFrame,
    col_title_prefix: str,
    cmap: str = 'OrRd',
    export_excel: bool = True,
    columns_subset = None
):
    """
    Creates maps for all columns in the DataFrame and optionally saves them and the data to an Excel file.

    Parameters:
    - path_suffix (str): Subfolder path where plots and Excel file will be saved.
    - df (pd.DataFrame): DataFrame to be visualized and exported. Index should be District or Region.
    - col_title_prefix (str): Prefix added to the title of each plot.
    - adm_state_date (datetime): The administrative state date to use for plotting.
    - cmap (str): Color map for the plots.
    - export_excel (bool): Whether to export the data to an Excel file.
    - columns_subset (list): If passed, plots only the given subset of the columns.
    """
    import os

    os.makedirs(os.path.join(plots_output_path, path_suffix), exist_ok=True)

    combined_df = pd.DataFrame(index=df.index)

    if columns_subset is None:
        columns_subset = df.columns
    else:
        columns_subset = list(set(columns_subset)&set(df.columns))

    for i, column in enumerate(columns_subset):
        plot_path = plots_output_path + path_suffix + f"{column.replace(': ', '_')}.png"
        fig = administrative_history.plot_dataset(
            df=df,
            col_name=column,
            adm_level='District',
            adm_state_date = administrative_history.harmonize_to_date,
            save_to_path=plot_path,
            title=f'{col_title_prefix} ({column})',
            cmap=cmap,
            custom_grouping = custom_dist_grouping
        )
        combined_df[column] = df[column]

    if export_excel:
        excel_path = plots_output_path + path_suffix + f"data.xlsx"
        print(f"Exporting to {excel_path}")
        combined_df.to_excel(excel_path, sheet_name="data")

import statsmodels.api as sm

def plot_va_growth_scatter(
    production_by_year,
    all_years,
    x_col_name='VA_constant_prices_per_capita',
    d_to_r_group=None,
    r_group_to_color=None,
    save_to_path=None,
    title=None,
    x_label=None
):
    start_year = min(all_years)
    end_year = max(all_years)

    # Extract VA values
    va_start = production_by_year[start_year]['VA_constant_prices_per_capita']
    va_end = production_by_year[end_year]['VA_constant_prices_per_capita']
    x_values = production_by_year[start_year][x_col_name]

    # Keep common districts and filter invalid values
    common = va_start.index.intersection(va_end.index).intersection(x_values.index)
    va_start = va_start.loc[common]
    va_end = va_end.loc[common]
    x_values = x_values.loc[common]
    mask = (va_start > 0) & (va_end > 0)
    va_start, va_end, x_values = va_start[mask], va_end[mask], x_values[mask]

    # Compute CAGR
    n_years = end_year - start_year
    growth_rate = ((va_end / va_start) ** (1 / n_years)) - 1

    # Prepare regression with statsmodels
    X = sm.add_constant(x_values.values)  # Adds intercept
    y = growth_rate.values
    model = sm.OLS(y, X).fit()

    # Extract stats
    intercept = model.params[0]
    coef = model.params[1]
    r_squared = model.rsquared
    p_value = model.pvalues[1]

    print("📊 Regression summary:\n")
    print(model.summary())

    # Plot
    plt.figure(figsize=(10, 6))

    if d_to_r_group and r_group_to_color:
        plot_df = pd.DataFrame({
            'x': x_values,
            'y': growth_rate,
            'group': x_values.index.map(d_to_r_group)
        })
        plot_df['color'] = plot_df['group'].map(r_group_to_color)

        for group, group_df in plot_df.groupby('group'):
            plt.scatter(group_df['x'], group_df['y'], label=group,
                        color=r_group_to_color.get(group, 'gray'), alpha=0.7)
        plt.legend(title='Region Group')
    else:
        plt.scatter(x_values, growth_rate, alpha=0.7, label='Districts')

    # Regression line
    x_sorted = np.sort(x_values.values)
    y_pred = intercept + coef * x_sorted
    plt.plot(x_sorted, y_pred, color='black', linewidth=2, label='Regression line')

    # Annotation
    stats_text = (
        f"$y = {coef:.4f}x + {intercept:.4f}$\n"
        f"$R^2 = {r_squared:.3f}$\n"
        f"$p$-value = {p_value:.4f}"
    )
    plt.gca().text(0.05, 0.95, stats_text,
                   transform=plt.gca().transAxes,
                   fontsize=10, verticalalignment='top',
                   bbox=dict(boxstyle="round", facecolor='white', alpha=0.7))

    # Labels
    if title is None:
        title = f'VA Per Capita Growth ({start_year}–{end_year})'
    if x_label is None:
        x_label = f'{x_col_name} ({start_year})'

    plt.xlabel(x_label)
    plt.ylabel(f'Average Annual Growth Rate ({start_year}–{end_year})')
    plt.title(title)
    plt.grid(True)
    plt.tight_layout()

    if save_to_path:
        plt.savefig(save_to_path, dpi=300)
        print(f"Plot saved to: {save_to_path}")
    else:
        plt.show()

####################################### Theil-index ########################################

def plot_theil_decompositions(results, save_path: str, sector_colors: Dict[str, str]):
    """
    Creates Theil decomposition plots and saves them to a specified folder.
    
    Parameters:
    - results: dict output from analyze_all_years()
    - save_path: str, folder where plots will be saved
    """
    os.makedirs(save_path, exist_ok=True)
    years = sorted(results.keys())
    
    # --- 1. Regional decomposition of Theil ---
    for prefix in ['', 'Agriculture_', 'Industry_', 'Private_Services_', 'Public_Services_']:
        if prefix != '':
            sector_name = f"{prefix[:-1]} VA"
        else:
            sector_name = "Total VA"

        reg_total = [results[y][f'Regional_Decomposition_{prefix}VA']['Total_Theil'] for y in years]
        reg_within = [results[y][f'Regional_Decomposition_{prefix}VA']['Within_Region'] for y in years]
        reg_between = [results[y][f'Regional_Decomposition_{prefix}VA']['Between_Region'] for y in years]

        plt.figure(figsize=(10, 5))
        plt.plot(years, reg_total, label='Total Theil')
        plt.plot(years, reg_within, label='Within-Region')
        plt.plot(years, reg_between, label='Between-Region')
        plt.title(f"Regional Decomposition of Theil Index Over Time ({sector_name})")
        plt.xlabel("Year")
        plt.ylabel("Theil Index")
        plt.legend()
        plt.grid(True)
        plt.tight_layout()
        plt.savefig(os.path.join(save_path, f"regional_VA_{prefix}decomposition.png"))
        plt.close()

    # --- 2. Sectoral decomposition via Shapley (District and Region Level) ---
    for level in ['District', 'Region']:
        # Collect Shapley contributions by sector and year
        sector_series = defaultdict(list)

        for year in years:
            shapley_result = results[year].get(f'Sectoral_Decomposition_{level}', {})
            for sector in sector_colors.keys():
                sector_series[sector].append(shapley_result.get(f'{sector}_VA_constant_prices_per_capita', np.nan))

        # Plot
        plt.figure(figsize=(10, 5))
        for sector, values in sector_series.items():
            plt.plot(years, values, label=sector.replace("_", " "), color=sector_colors[sector])
        
        plt.title(f"Sectoral Shapley Contributions to Theil Index ({level} Level)")
        plt.xlabel("Year")
        plt.ylabel("Shapley Contribution (Δ Theil)")
        plt.legend()
        plt.grid(True)
        plt.tight_layout()
        plt.savefig(os.path.join(save_path, f"sectoral_shapley_{level.lower()}.png"))
        plt.close()

import matplotlib.pyplot as plt

def plot_theil_decomposition_sequence(
    production_by_year: dict,
    variable: str,
    d_to_r: dict,
    population_col: str = 'Population',
    pop_by_year: dict = None,
    save_path: str = None,
    var_title: str = None
):
    """
    Plots the Theil index decomposition (Total, Between, Within) over years
    for a given variable across a dictionary of yearly data.

    Parameters:
        production_by_year (dict): {year: DataFrame}, each with 'District' index and the target variable.
        variable (str): Name of the variable to analyze (column in DataFrames).
        d_to_r (dict): Mapping of district names to regions.
        population_col (str): Name of population column. Default is 'Population'.
        pop_by_year (dict): Optional dict {year: DataFrame} with population data per district.
        save_path (str): Optional path to save the plot.
        var_title (str): Optional title for the variable (used in plot title).
    """
    from gdp_computation_utils.estimates import decompose_theil_regionally

    theil_total, theil_between, theil_within = [], [], []
    years = sorted(production_by_year.keys())

    for year in years:
        df = production_by_year[year]
        pop_df = pop_by_year[year] if pop_by_year else None

        result = decompose_theil_regionally(
            df=df,
            col_name=variable,
            d_to_r=d_to_r,
            population_col=population_col,
            pop_df=pop_df
        )

        theil_total.append(result['Total_Theil'])
        theil_between.append(result['Between_Region'])
        theil_within.append(result['Within_Region'])

    # Plotting
    plt.figure(figsize=(10, 6))
    plt.plot(years, theil_total, label='Total Theil', color='black', linewidth=2)
    plt.plot(years, theil_within, label='Within-region', linestyle='--', color='blue')
    plt.plot(years, theil_between, label='Between-region', linestyle='--', color='green')

    plt.xlabel('Year')
    plt.ylabel('Theil Index')
    title = f"Theil Decomposition of {var_title or variable} Over Time"
    plt.title(title)
    plt.legend()
    plt.grid(True)

    if save_path:
        plt.savefig(save_path, bbox_inches='tight')
    else:
        plt.show()

########################################### Spatial ##############################################

from gdp_computation_utils.estimates import distance_matrix_to_weights

def spatial_autocorrelation_over_time(
    year_to_df,
    col_name,
    distance_matrix,
    threshold=120000,
    save_to_path=None,
    var_name_in_title=None,
    measures=["moran", "geary"],
    verbose=False
):
    import matplotlib.pyplot as plt
    import numpy as np
    from esda.moran import Moran, Moran_Local
    from esda.geary import Geary

    morans_I_list = []
    gearys_C_list = []
    lisa_avg_list = []
    years = sorted(year_to_df.keys())
    years = [year for year in years if col_name in year_to_df[year].columns]
    if not years:
        raise ValueError(f"No dfs with {col_name} column to plot.")
    else:
        print(f"Years with '{col_name}': {years}")

    # Build spatial weights object
    weights = distance_matrix_to_weights(distance_matrix, threshold=threshold, binary=False)

    for year in years:
        df = year_to_df[year]
        df = df.loc[weights.id_order]
        y = df[col_name].values.astype(float)

        if verbose:
            print(f"{year} — valid values: {np.isfinite(y).sum()} / {len(y)}, std: {np.std(y)}")

        if "moran" in measures:
            mi = Moran(y, weights)
            morans_I_list.append(mi.I)
        if "geary" in measures:
            gc = Geary(y, weights)
            gearys_C_list.append(gc.C)
        if "lisa" in measures:
            lisa = Moran_Local(y, weights)
            lisa_avg_list.append(lisa.Is.mean())

    # Plotting
    plt.figure(figsize=(10, 6))
    if "moran" in measures:
        plt.plot(years, morans_I_list, label="Moran's I")
    if "geary" in measures:
        plt.plot(years, gearys_C_list, label="Geary's C")
    if "lisa" in measures:
        plt.plot(years, lisa_avg_list, label="Avg. Local Moran's I")

    if var_name_in_title is None:
        var_name_in_title = col_name

    plt.title(f"Spatial Autocorrelation of {var_name_in_title} Over Time")
    plt.xlabel("Year")
    plt.ylabel("Index Value")
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    if save_to_path:
        import os
        os.makedirs(os.path.dirname(save_to_path), exist_ok=True)
        plt.savefig(save_to_path, dpi=300)
        print(f"Plot saved to: {save_to_path}")
    else:
        plt.show()

import matplotlib.pyplot as plt
import numpy as np
import os
from esda.moran import Moran

def plot_morans_I_over_time(
    production_by_year: dict,
    weights,
    variables: list,
    var_titles: dict = None,
    var_colors: dict = None,
    threshold: float = 120000,
    save_path: str = None,
    title: str = ""
):
    """
    Compute and plot Moran's I over time for multiple variables.

    Parameters:
    - production_by_year (dict): Dict of {year: DataFrame}, districts as rows, variables as columns.
    - distance_matrix (np.ndarray or pd.DataFrame): Matrix of distances between districts.
    - variables (list): List of variable names (columns) to compute Moran's I.
    - var_titles (dict, optional): Dict mapping variable names to nicer legend titles.
    - var_colors (dict, optional): Dict mapping variable names to colors for plotting.
    - threshold (float, optional): Distance threshold for spatial weights construction.
    - save_path (str, optional): Path to save the plot.
    - title (str, optional): Additional title info.

    Returns:
    - pd.DataFrame: Long-format DataFrame with columns ['Year', 'Variable', 'Morans_I'].
    """

    records = []
    years = sorted(production_by_year.keys())
    
    # Use the id_order attribute (district order used in weights)
    id_order = weights.id_order

    for year in years:
        df = production_by_year[year]
        # Filter variables missing in this year
        present_vars = [v for v in variables if v in df.columns]
        if not present_vars:
            continue
        
        # Reorder df to match spatial weights order
        df = df.loc[id_order]
        
        for var in present_vars:
            y = df[var].values.astype(float)
            if np.isnan(y).all():
                continue  # skip if all missing
            
            mi = Moran(y, weights)
            records.append({'Year': year, 'Variable': var, 'Morans_I': mi.I})

    moran_df = pd.DataFrame(records)

    # Defaults for titles and colors
    if var_titles is None:
        var_titles = {v: v for v in variables}
    if var_colors is None:
        var_colors = {}

    plt.figure(figsize=(10, 6))
    for var in variables:
        sub_df = moran_df[moran_df['Variable'] == var]
        if sub_df.empty:
            continue
        plt.plot(
            sub_df['Year'],
            sub_df['Morans_I'],
            label=var_titles.get(var, var),
            color=var_colors.get(var),
            marker='o'
        )

    full_title = f"Spatial Autocorrelation (Moran's I) {title}".strip()
    plt.title(full_title)
    plt.xlabel("Year")
    plt.ylabel("Moran's I")
    plt.grid(True)
    plt.legend()
    plt.tight_layout()

    if save_path:
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        plt.savefig(save_path, dpi=300)
        print(f"Plot saved to {save_path}")
    else:
        plt.show()

    return moran_df


######################################### Variance decomposition ##############################################
def plot_cumulative_variance_decomposition(decomp_df, path_to_save, variable_name):
    """
    Plots the variance decomposition into between- and within-region variance
    estimated with the use of gdp_computation_utils.estimates.variance_decomposition function.

    Example call:
    from gdp_computation_utils.estimates import variance_decomposition
    decomp_df = variance_decomposition(production_by_year, d_to_r, 'VA_constant_prices_per_capita')
    plot_cumulative_variance_decomposition(decomp_df=decomp_df, path_to_save = plots_output_path+"/Spatial_Inequality/VA_per_capita/", variable_name = 'VA_constant_prices_per_capita')
    
    """
    os.makedirs(path_to_save, exist_ok=True)
    
    years = decomp_df['Year']
    
    # Prepare cumulative data for raw variances
    # We treat 'Between_Region_Variance' and 'Within_Region_Variance' as parts summing to total variance
    # The total variance line will be on top (cumulative sum of between + within)
    raw_df = decomp_df[['Between_Region_Variance', 'Within_Region_Variance']].copy()
    raw_cum = raw_df.cumsum(axis=1)
    
    plt.figure(figsize=(12, 6))
    plt.fill_between(years, 0, raw_cum['Between_Region_Variance'], label='Between-Region Variance', alpha=0.6)
    plt.fill_between(years, raw_cum['Between_Region_Variance'], raw_cum['Within_Region_Variance'], label='Within-Region Variance', alpha=0.6)
    plt.plot(years, decomp_df['Total_Variance'], color='black', label='Total Variance', linewidth=2)
    
    plt.title(f'Cumulative Variance Decomposition over Time for {variable_name}')
    plt.xlabel('Year')
    plt.ylabel('Variance')
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(path_to_save, f'{variable_name}_cumulative_variance.png'))
    plt.close()
    
    # Prepare cumulative data for proportions (standardized to 100%)
    prop_df = decomp_df[['Proportion_Between', 'Proportion_Within']].copy()
    prop_cum = prop_df.cumsum(axis=1) * 100  # convert to percentages and cumulative
    
    plt.figure(figsize=(12, 6))
    plt.fill_between(years, 0, prop_cum['Proportion_Between'], label='Between-Region (%)', alpha=0.6)
    plt.fill_between(years, prop_cum['Proportion_Between'], prop_cum['Proportion_Within'], label='Within-Region (%)', alpha=0.6)
    
    plt.title(f'Cumulative Relative Variance Contributions over Time for {variable_name}')
    plt.xlabel('Year')
    plt.ylabel('Cumulative Percentage (%)')
    plt.ylim(0, 100)
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(path_to_save, f'{variable_name}_cumulative_proportions.png'))
    plt.close()

##################################### Coefficients of variation #####################################
def plot_cv_over_time(production_by_year: Dict[int,pd.DataFrame], variable: str, save_path: str=None, var_title: str=None):
    """
    Plots the coefficient of variation of column variable in each df in the production_by_year {year:df} dict.
    Parameters:
        production_by_year (dict): year->df dict, each df should contain the variable column and have 'District' index
        variable (str): Name of the column to be plotted.
        save_path (str): Path where the plot is saved. Optional.
        var_title (str): Name of the variable in the plot title. Optional.
    """
    years = []
    cvs = []

    for year, df in sorted(production_by_year.items()):
        values = df[variable].dropna()
        mean_val = values.mean()
        std_val = values.std(ddof=1)

        if mean_val != 0:
            cv = std_val / mean_val
        else:
            cv = np.nan

        years.append(year)
        cvs.append(cv)

    cv_df = pd.DataFrame({'Year': years, 'CV': cvs})

    if not var_title:
        var_title = variable

    plt.figure(figsize=(10, 6))
    plt.plot(cv_df['Year'], cv_df['CV'], linestyle='-', color='black')
    plt.title(f'Coefficient of Variation Over Time for {var_title}')
    plt.xlabel('Year')
    plt.ylabel('Coefficient of Variation (CV)')
    plt.grid(True)
    plt.tight_layout()

    if save_path:
        # Ensure directory exists
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        plt.savefig(save_path)
        print(f"Plot saved to {save_path}")

    plt.show()

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import os
from typing import Dict, List

def plot_many_cvs_over_time(
    production_by_year: dict,
    variables: List[str],
    var_titles: Dict[str, str] = None,
    var_colors: Dict[str, str] = None,
    save_path: str = None,
    title: str = ""
) -> pd.DataFrame:
    """
    Plot coefficients of variation (CV = std/mean) over time for multiple variables.

    Parameters:
    - production_by_year (dict): Dict of {year: DataFrame}, where each DataFrame has districts as rows and variables as columns.
    - variables (list): List of variable names (column names) to plot.
    - var_titles (dict, optional): Dict of variable: variable_title pairs for the legend.
    - var_colors (dict, optional): Dict of variable: color pairs to control line colors.
    - save_path (str, optional): If provided, saves the plot to this path.

    Returns:
    """

    records = []

    for year, df in sorted(production_by_year.items()):
        for variable in variables:
            if variable not in df.columns:
                continue  # Skip missing variable

            values = df[variable].dropna()
            mean_val = values.mean()
            std_val = values.std(ddof=1)

            cv = std_val / mean_val if mean_val != 0 else np.nan
            records.append({'Year': year, 'Variable': variable, 'CV': cv})

    cv_df = pd.DataFrame(records)

    # Defaults
    if not var_titles:
        var_titles = {var: var for var in variables}
    if not var_colors:
        var_colors = {}

    # Plotting
    plt.figure(figsize=(10, 6))
    for variable in variables:
        sub_df = cv_df[cv_df['Variable'] == variable]
        plt.plot(
            sub_df['Year'],
            sub_df['CV'],
            label=var_titles.get(variable, variable),
            color=var_colors.get(variable)
        )

    if title != "":
        title = f"in {title} "

    plt.title(f'Coefficient of Variation {title}Over Time')
    plt.xlabel('Year')
    plt.ylabel('Coefficient of Variation (CV)')
    plt.grid(True)
    plt.legend()
    plt.tight_layout()

    if save_path:
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        plt.savefig(save_path)
        print(f"Plot saved to {save_path}")

    plt.show()