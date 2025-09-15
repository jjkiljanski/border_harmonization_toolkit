from datetime import datetime
import pandas as pd
import plotly.express as px
import time

from core.core import AdministrativeHistory
from data_models.adm_timespan import *
from data_models.adm_unit import *
from data_models.adm_state import *
from data_models.adm_change import *
from data_models.econ_data_metadata import *
from data_models.processing_config import *

"""
This component holds built-in function summarizing administrative history
in plots.
It is constructed using AdministrativeHistoryProcessor object.

Example usage:
    # Load the configuration.
    config = load_config("config.json")

    # Create an AdministrativeHistory instance.
    adm_history = AdministrativeHistory(config, load_geometries=True)
    adm_history_plotter = AdministartiveHistoryPlotter(adm_history)

    # Generate plots of all adm states.
    adm_history_plotter.generate_adm_state_plots(output_folder_path='output/adm_states_maps/')
"""

class AdministartiveHistoryPlotter():
    def __init__(self, administrative_history: AdministrativeHistory):
        # Add administrative history as attribute
        self.administrative_history = administrative_history

    def plot_dist_changes_by_year(self, homeland_only = True, black_and_white=False):
        """
        Counts the number of districts that were ever changed in administrative history.
        Plots the number of districts with borders changed by year and returns the plot.

        If homeland_only is True, counts only districts that were ever in 'HOMELAND'
        during self.administrative_history.timespan.

        If black_and_white is True, plots in black and white.
        """
        n_dist_changed = 0 # Total number of districts that were changed
        n_districts = 0

        # List of (datetime(year,1,1), datetime(year+1,1,1)) pairs
        year_timespans = [TimeSpan(start = datetime(year, 1, 1), end = datetime(year + 1, 1, 1)) for year in range(self.administrative_history.timespan.start.year, self.administrative_history.timespan.end.year+1)]
        # List to store change type, number of changes and districts affected per year.
        change_records = []
        # Convert each timespan to a label like "1921–1922" (for plotting)
        timespan_labels = [str(year_timespan.start.year) for year_timespan in year_timespans]

        for district in self.administrative_history.dist_registry.unit_list:
            # Check if district was ever homeland:
            was_homeland = False
            for year_timespan in year_timespans:
                current_dist_address = self.administrative_history.find_adm_state_by_date(year_timespan.middle).find_address(district.name_id, 'District')
                if current_dist_address:
                    if current_dist_address[0] == 'HOMELAND':
                        was_homeland = True
            # Count districts if homeland_only is False or the district ever was in 'HOMELAND'
            if not homeland_only or was_homeland:
                n_districts += 1
                print(f"District {district.name_id} belonged to homeland. Num changes: {len(district.changes)}")
                # Count changes per year. We use the 'district.changes', not the 'self.administrative_history.changes_list' list, because we want to count only districts that were ever in 'homeland'.
                # Start with assuring that district changes are sorted. Every element in the district.changes is a pair (change_type, change). We sort first by 'date', then by 'order' attribute.
                district.changes.sort(key=lambda change_pair: (change_pair[1].date, change_pair[1].order is None, change_pair[1].order))
                for i, year_timespan in enumerate(year_timespans):
                    for j, (change_type, change) in enumerate(district.changes):
                        if max(year_timespan.start, self.administrative_history.timespan.start)<change.date<year_timespan.end:
                            # Omit changes if another change followed on the same day (this is simply an artefact of how we describe changes in the toolkit)
                            if j<len(district.changes)-1:
                                if change.date!=district.changes[j+1]:
                                    print(f"Change of type {change_type} was applied to district {district.name_id} on {change.date}.")
                                    change_records.append({
                                        'Year': year_timespan.start.year,
                                        'District': district.name_id,
                                        'Change Type': change_type
                                    })
                            else:
                                print(f"Change of type {change_type} was applied to district {district.name_id} on {change.date}.")
                                change_records.append({
                                        'Year': year_timespan.start.year,
                                        'District': district.name_id,
                                        'Change Type': change_type
                                })
                # Count the district, it it was ever changed or created
                if len(district.changes)>0:
                    n_dist_changed += 1

        print(f"{n_dist_changed}/{n_districts} ({round(n_dist_changed/n_districts*100, 2)}%) of districts{' in homeland' if homeland_only else ''} had their borders changed, were created, abolished, or moved between regions in the given period.")
        
        # Convert the list of change records into a DataFrame
        df_changes = pd.DataFrame(change_records)

        # Group by Year and Change Type to get:
        # - Count of changes
        # - List of district names
        grouped = df_changes.groupby(['Year', 'Change Type']).agg(
            Change_Count=('District', 'count'),
            Districts_List = (
                'District',
                # Truncate the list if it's too long
                lambda districts: (
                    '<br>'.join(sorted(set(districts))[:10]) + 
                    (f"<br>... (+{len(set(districts)) - 10} more)" if len(set(districts)) > 10 else '')
                )

            )
        ).reset_index()

        color_sequence = ['black'] if black_and_white else px.colors.qualitative.Set2 # or any other color scale

        # Create the stacked bar chart with custom hover text
        fig = px.bar(
            grouped,
            x='Year',
            y='Change_Count',
            color='Change Type',
            hover_data={'Districts_List': True, 'Year': False, 'Change_Count': True},
            title='District Changes by Year and Type',
            labels={'Change_Count': 'Number of Districts Affected'},
            color_discrete_sequence=color_sequence,
            barmode='stack'  # <- Use stacked mode
        )

        fig.update_layout(
            xaxis_title='Year',
            yaxis_title='Number of Districts Affected',
            bargap=0.1
        )


        # Customize hover template to display just the districts
        fig.update_traces(
            hovertemplate='<b>%{x}</b><br>%{customdata[0]}<extra></extra>'
        )

        return fig
    
    def generate_adm_state_plots(self, output_folder_path: str):
        """
        Creates and saves plots of all the administrative states in the administrative history.
        """
        import matplotlib.pyplot as plt

        start_time = time.time()
        print("Computing the unary union of all district territories in the registry ('whole_map' geometry).")

        # Create a territory representing the unary union of all territories (the "whole map" shape)
        self.administrative_history.whole_map = unary_union([state.current_territory for state in self.administrative_history.states_with_loaded_territory])

        end_time = time.time()
        execution_time = end_time - start_time
        print(f"✅ Successfully computed 'whole_map' in {execution_time:.2f} seconds.")
        
        print("Creating map plots for every administrative state...")
        start_time = time.time()
        for adm_state in self.administrative_history.states_list:
            region_registry = self.administrative_history.region_registry
            dist_registry = self.administrative_history.dist_registry
            fig = adm_state.plot(region_registry, dist_registry, self.administrative_history.whole_map, adm_state.timespan.middle)
            fig.savefig(output_folder_path+adm_state.to_label() + ".png", bbox_inches=None)
            plt.close(fig)  # prevent memory buildup
            print(f"Saved adm_state_{adm_state.timespan.start.date()}.png.")


        end_time = time.time()
        execution_time = end_time - start_time
        print(f"✅ Successfully generated all administrative state plots in {execution_time:.2f} seconds and saved to 'output' folder.")

    def plot_dataset(self,
                    df: pd.DataFrame,
                    col_name: str,
                    adm_level: Union[Literal['Region'], Literal['District']],
                    adm_state_date: datetime,
                    save_to_path: str = None,
                    title: str = None,
                    legend_min: float = None,
                    legend_max: float = None,
                    cmap='OrRd',
                    custom_grouping: Dict[str, str] = None):
        """
        Generates a choropleth map of the specified data table column.

        If custom_grouping is passed, it is assumed that df was already grouped
            (i.e. it has the index equal to custom_grouping.values()).

        Parameters:
        - df (pd.DataFrame): DataFrame with index as District or Region names.
        - col_name (str): Column name to visualize.
        - adm_level (str): 'District' (currently only this is supported).
        - adm_state_date (datetime): Reference date for administrative boundaries.
        - custom_grouping (dict, optional): Mapping of unit names to custom groups.

        Returns:
        - fig (matplotlib.figure.Figure): A matplotlib Figure object representing the choropleth map.
        """
        import matplotlib.pyplot as plt

        ##################################### Check proper input df form #######################################

        if adm_level == 'Region':
            adm_state_units = self.administrative_history.find_adm_state_by_date(adm_state_date).all_region_names(homeland_only=True)
        elif adm_level == 'District':
            adm_state_units = self.administrative_history.find_adm_state_by_date(adm_state_date).all_district_names(homeland_only=True)
        else:
            raise ValueError(f"adm_level must be 'Region' or 'District', but '{adm_level}' was passed.")

        if df.index.name != adm_level:
            raise ValueError(f"Method 'AdministrativeHistory.plot_dataset' used with adm_level='{adm_level}' argument, but the passed df doesn't have '{adm_level}' as index.")
            
        if custom_grouping:
            grouped_units = set(custom_grouping.values())
            if grouped_units != set(df.index):
                absent_in_df = grouped_units - set(df.index)
                absent_in_custom_grouping = set(df.index) - grouped_units
                raise ValueError(f"Index in the df to plot doesn't correspond to the custom_grouping values. \nAbsent in set(df.index): {absent_in_df}.\nAbsent in custom_grouping values: {absent_in_custom_grouping}.")
        else:
            if set(df.index) != set(adm_state_units):
                absent_in_df = set(adm_state_units) - set(df.index)
                absent_in_adm_state = set(df.index) - set(adm_state_units)
                raise ValueError (f"Method 'AdministrativeHistory.plot_dataset' used with adm_level='{adm_level}' argument, but the values in the df '{adm_level}' index don't fit the existing {adm_level.lower()} names.\nAbsent in set(df.index): {absent_in_df}.\nAbsent in adm_state: {absent_in_adm_state}.")
            
        #####################################             Plot           #######################################      
        
        if adm_level == 'Region':
            raise ValueError(f"Method 'AdministrativeHistory.plot_dataset' for adm_level='Region' not implemented yet.")
        else:
            dist_plot_layer = self.administrative_history.dist_registry._plot_layer(adm_state_date)
            dist_plot_layer.rename(columns={'name_id': 'District'}, inplace = True)
            dist_plot_layer.set_index('District', inplace = True)

            # --------------------------- Merge ---------------------------
            if custom_grouping:
                dist_plot_layer = dist_plot_layer.copy()
                dist_plot_layer['__group__'] = dist_plot_layer.index.map(custom_grouping)
                dist_plot_layer = dist_plot_layer.dissolve(by='__group__')

                dist_plot_layer = dist_plot_layer.merge(df, left_index=True, right_index=True, how='left')
            else:
                dist_plot_layer = dist_plot_layer.merge(df, left_index=True, right_index=True, how='left')

            # --------------------------- Plot ----------------------------
            
            fig, ax = plt.subplots(figsize=(10, 8))

            if legend_min is not None and legend_max is not None:
                dist_plot_layer.plot(
                    ax=ax,
                    column=col_name,
                    cmap=cmap,
                    legend=True,
                    edgecolor='black',
                    linewidth=1,
                    vmin = legend_min,
                    vmax = legend_max
                )
            else:
                dist_plot_layer.plot(
                    ax=ax,
                    column=col_name,
                    cmap=cmap,
                    legend=True,
                    edgecolor='black',
                    linewidth=1
                )
            ax.axis('off')
            if title is not None:
                ax.set_title(title)
            else:
                ax.set_title(f"{col_name} by District")
            plt.tight_layout()

            if save_to_path:
                fig.savefig(save_to_path, dpi=300, bbox_inches='tight')

        return fig
        
