from pydantic import BaseModel
from typing import Union, Optional, Literal, Dict, Any, Tuple
from datetime import datetime
import sys


from administrative_history.data_models.adm_timespan import TimeSpan
from administrative_history.data_models.adm_unit import *
from administrative_history.utils.exceptions import ConsistencyError

import matplotlib
import matplotlib.patches as mpatches
matplotlib.use("Agg")
import geopandas as gpd
from shapely.ops import unary_union
from shapely.geometry import Polygon
import io
import pandas as pd

#############################################################################################

"""
An instance adm_state of the AdministrativeState model describes all the relations of administrative
appartenance in the form:    "country -> region -> district."

Every two consecutive administrative changes at times t_1 and t_2 define a timespan of existence
of a distinct administrative state.
In other words, no Region or District should have a state timespan that ends or begins between t_1 and t_2.

Every Region and District that exist at the timepoint t (t_1 <= t < t_2) must be present somewhere
in the hierarchy of the administrative state with the timespan [t_1, t_2).

"""

RegionAddress = Tuple[Literal["HOMELAND", "ABROAD"], str]              # For regions"
DistAddress = Tuple[Literal["HOMELAND", "ABROAD"], str, str]         # For districts
Address = Union[DistAddress, RegionAddress]

class AdministrativeState(BaseModel):
    timespan: Optional[TimeSpan] = None
    unit_hierarchy: Dict[Literal["HOMELAND", "ABROAD"], Dict[str, Dict[str, Any]]]

    def to_label(self) -> str:
        """
        Generates a short, filesystem-safe string label representing the administrative state
        based on its timespan.

        Returns:
            str: A string like 'adm_state_1922-07-26_to_1923-01-01'
        """
        # Ensure dates are in YYYY-MM-DD format
        start_str = self.timespan.start.strftime("%Y-%m-%d") if self.timespan.start else "unknown_start"
        end_str = self.timespan.end.strftime("%Y-%m-%d") if self.timespan.end else "unknown_end"

        # Compose the label
        label = f"adm_state_{start_str}_to_{end_str}"

        return label

    def create_new(self, date):
        """
        Creates a new administrative state that is a copy of itself, the date passed as argument
        as self.timespan.end and new_state.timespan.start.
        """
        # Create a deep copy of itself
        new_state = self.model_copy(deep=True)
        # Define the end and origin of states
        self.timespan.end = date
        new_state.timespan.start = date

        # Correct the timespan 'middle' attribute:
        self.timespan.update_middle()
        new_state.timespan.update_middle()
        return new_state
    
    def all_region_names(self, homeland_only = False):
        """
        Returns all region names. If homeland_only is True, returns only regions in HOMELAND.
        """
        if homeland_only:
            country_dict = self.unit_hierarchy['HOMELAND']
            all_region_names = [
                region
                for region in country_dict.keys()
            ]
        else:
            all_region_names = [
                region
                for _, country_dict in self.unit_hierarchy.items()
                for region in country_dict.keys()
            ]
        return all_region_names
    
    def all_district_names(self, homeland_only: bool = False):
        """
        Returns all district names for the current state. If homeland_only is True,
        returns only districts in HOMELAND.

        Parameters:
        - homeland_only (bool): If True, return only district names in homeland.
        
        Returns:
        - all_district_names (List[str]): List of district names existent in the adm. state.
        """
        if homeland_only:
            country_dict = self.unit_hierarchy['HOMELAND']
            all_district_names = [
                district
                for _, region_dict in country_dict.items()
                for district in region_dict.keys()
            ]
        else:
            all_district_names = [
                district
                for _, country_dict in self.unit_hierarchy.items()
                for _, region_dict in country_dict.items()
                for district in region_dict.keys()
            ]
        return all_district_names
    
    def pop_address(self, address):
        """
        Pops adm_state[address[0]][address[1]]...[address[n]].
        """
        current = self.unit_hierarchy
        current_parent = None
        for i, attr in enumerate(address):
            current_parent = current
            if attr not in current.keys():
                raise ValueError(f"Unit '{attr}' does not belong to {address[:i]}")
            current = current[attr]
        
        return current_parent.pop(address[-1])
        
    def add_address(self, address, content):
        """
        Adds address[n]:content (a key:value pair) at the address adm_state[address[0]][address[1]]...[address[n-1]].
        """
        current = self.unit_hierarchy
        for i, attr in enumerate(address[:-1]):
            if attr not in current.keys():
                raise ValueError(f"Unit '{attr}' does not belong to {address[:i]}")
            current = current[attr]
        current[address[-1]] = content
        return
    
    def get_address(self, address):
        """
        Returns True if the address exists or False otherwise.
        """
        current = self.unit_hierarchy
        for i, attr in enumerate(address):
            if attr not in current.keys():
                return False
            current = current[attr]
        return True
    
    def find_address(self, unit_name_id, unit_type):
        """
        Returns the address of a unit, given its name (unit_name_id) and type ('District' or 'Region') 
        """
        if unit_type not in ['District', 'Region']:
            raise ValueError(f"Argument 'unit_type' of method 'AdministrativeState.find_address' must be 'District' or 'Region'. Passed: {unit_type}.")
        for country_name, country_dict in self.unit_hierarchy.items():
            for region_name, region_dict in country_dict.items():
                if unit_type=='Region':
                    if unit_name_id==region_name:
                        return (country_name, region_name)
                else:
                    for district_name, district_dict in region_dict.items():
                        if unit_type == 'District':
                            if unit_name_id == district_name:
                                return (country_name, region_name, district_name)
        return None
    
    def find_and_pop(self, unit_name_id, unit_type):
        """
        Pops a unit, given its name (unit_name_id) and type ('District' or 'Region').
        """
        address = self.find_address(unit_name_id, unit_type)
        if address is None:
            raise ValueError(f"{unit_type} {unit_name_id} doesn't exist in the AdministrativeState.unit_hierarchy.")
        return self.pop_address(address)
    
    def verify_and_standardize_address(self, address, region_registry, dist_registry, check_date = None):
        """
        1. Checks that all units in the address exist in their registry,
        2. Substitutes current unit names in the address to unit name_ids,
        3. Verifies that such standardized address exists.

        If check_date passed, uses check_date for checks. If not, uses check_date = self.timespan.middle.

        Returns:
            - the standardized address (tuple).
        """
        if check_date is None:
            check_date = self.timespan.middle # Set check_date if not passed
        
        # Verify and standardize region address
        region_current_name = address[1]
        region, region_state, _ = region_registry.find_unit_state_by_date(region_current_name, check_date)
        if region is None:
            raise ConsistencyError(
                f"Change {str(self)} applied to {address} address, but no region with name variant '{region_current_name}' exists in the region registry."
            )
        if region_state is None:
            raise ConsistencyError(
                f"Change {str(self)} applied to {address} address, but no region state for region '{region_current_name}' exists in the region registry."
            )

        if len(address) == 2:
            address = (address[0], region.name_id)
        else:
            address = (address[0], region.name_id, address[2])

        # Verify and standardize district if exists in address
        if len(address) == 3:  # If district
            dist_current_name = address[2]
            dist, dist_state, _ = dist_registry.find_unit_state_by_date(dist_current_name, check_date)
            if dist is None:
                raise ConsistencyError(
                    f"Change {str(self)} applied to {address} address, but no district with name variant '{dist_current_name}' exists in the district registry."
                )
            if dist_state is None:
                raise ConsistencyError(
                    f"Change {str(self)} applied to {address} address, but no district state for district '{dist_current_name}' exists in the district registry."
                )

            address = (address[0], address[1], dist.name_id)  # Modify district name_id

        # Check if the address exists:
        if not self.get_address(address):
            raise ConsistencyError(f"Address {address} doesn't exist in the administrative state {str(self)}.")
        return address

    def verify_consistency(self, region_registry, dist_registry, check_date = None, timespan_registry = None):
        """
        Verifies the consistency of the current administrative state.

        Parameters:
            region_registry (RegionRegistry)
            dist_registry (DistrictRegistry)
            check_date (Optional[datetime]): Optional
            timespan_registry (Optional[TimeSpanRegistry]): Optional

        Raises:
            ValueError: If:
                1) any region or district listed in self.hierarchy doesn't exist in the registry,
                2) a region or districts exists in the hierarchy, but doesn't have a state defined at the self.timespan.middle timepoint,
                3) the timespan of any of a the state existant doesn't contain the self.timespan wholly.

        If check_date is passed as argument, check_date instead of self.timespan.middle is used as date for verification.
        """
        if check_date:
            if check_date not in self.timespan:
                raise ValueError(f"Wrong 'checkdate' argument: {check_date.date()}, 'checkdate' must be contained in self.timespan: {self.timespan}.")
        else:
            check_date = self.timespan.middle
                
        for country_name, region_dict in self.unit_hierarchy.items():
            for region_name_id, district_dict in region_dict.items():
                # Check if Region registry correctly passed and contains info coherent with the info in adm. state.
                region, region_state, region_timespan = region_registry.find_unit_state_by_date(region_name_id, check_date)
                if region is None:
                    raise ConsistencyError(f" Region {region_name_id} exists in the administrative state, but doesn't exist in the RegionRegistry.")
                if region_state is None:
                    raise ConsistencyError(f"Region {region_name_id} exists in the administrative state with timespan {str(self.timespan)}, but the the region's state for the date {check_date.date()} doesn't exist in the region registry.")
                if self.timespan not in region_timespan:
                    raise ConsistencyError(f"Region {region_name_id} exists in the administrative state, but the administrative state's timespan ({self.timespan}) is not contained in its timespan ({region_timespan}).")
                for district_name_id in district_dict.keys():
                    # Check if District registry correctly passed and contains info coherent with the info in adm. state.
                    district, district_state, district_timespan = dist_registry.find_unit_state_by_date(district_name_id, check_date)
                    if district is None:
                        raise ConsistencyError(f"District {district_name_id} exists in the administrative state, but doesn't exist in the DistrictRegistry.")
                    if district_state is None:
                        raise ConsistencyError(f"District {district_name_id} exists in the administrative state with timespan {str(self.timespan)}, but the the district's state for the date {check_date.date()} doesn't exist in the district registry. District states: {district.states}")
                    if self.timespan not in district_timespan:
                        raise ConsistencyError(f"District {district_name_id} exists in the administrative state, but the administrative state's timespan ({self.timespan}) is not contained in its timespan ({district_timespan}).")
                    
        for region, region_state in region_registry.all_unit_states_by_date(check_date):
            if region.name_id not in self.all_region_names():
                raise ConsistencyError(f"Region {region.name_id} exists on {check_date.date()}, but doesn't belong to the current administrative state hierarchy.")
        for district, district_state in dist_registry.all_unit_states_by_date(check_date):
            if district.name_id not in self.all_district_names():
                raise ConsistencyError(f"District {district.name_id} exists on {check_date.date()}, but doesn't belong to the current administrative state hierarchy.")
    
    def to_address_list(self, only_homeland = False, with_variants = False, current_not_id = False, region_registry = None, dist_registry = None):
        """
        Returns a list of (country, region, district) tuples, sorted alphabetically.
        If only_homeland is true, the method returns only pairs of regions in homeland.
        If with_variants is True, the method returns the list with all region and district name variants.
        If current_not_id is True, the method returns the list with region and district current names and not id names.
        If with_variants or current_not_id is True, region_registry and dist_registry must be passed
        
        """
        if with_variants or current_not_id:
            if not (isinstance(region_registry, RegionRegistry) and isinstance(dist_registry, DistrictRegistry)):
                raise ValueError(
                    f"'with_variants=True' requires region_registry and dist_registry to be RegionRegistry and DistrictRegistry. "
                    f"Got types: region_registry={type(region_registry).__name__}, "
                    f"dist_registry={type(dist_registry).__name__}."
                )
            self.verify_consistency(region_registry=region_registry, dist_registry=dist_registry)

        address_list = []
        for country_name, country_dict in self.unit_hierarchy.items():
            if only_homeland:
                if country_name!='HOMELAND':
                    continue # Skip if not interested in addresses from abroad.
            for region_name_id, region_dict in country_dict.items():
                # Reset lists for the current region
                region_names_to_store = [] # All region name variants
                dist_names_to_store = [] # All district name variants for districts in the region

                # Create a list with all wanted name variants for the current region.
                if with_variants or current_not_id:
                    region, region_state, _ = region_registry.find_unit_state_by_date(region_name_id, self.timespan.middle)
                    if with_variants:
                        region_names_to_store = region.name_variants
                    else:
                        region_names_to_store = [region_state.current_name]
                else:
                    region_names_to_store = [region_name_id]
                # Iterate through the whole region_names_to_store list and add districts:
                for dist_name_id in region_dict.keys():
                    # Create a list with all wanted name variants for the current district.
                    if with_variants or current_not_id:
                        district, dist_state, _ = dist_registry.find_unit_state_by_date(dist_name_id, self.timespan.middle)
                        if with_variants:
                            dist_names_to_store += district.name_variants
                        else:
                            dist_names_to_store += [dist_state.current_name]
                    else:
                        dist_names_to_store += [dist_name_id]
                # For every region, append all combinations of (region_name, district_name) stored in the created lists.
                for region_name in region_names_to_store:
                    for dist_name in dist_names_to_store:
                        if only_homeland:
                            address_list.append((region_name, dist_name))
                        else:
                            address_list.append((country_name, region_name, dist_name))                    
        address_list.sort()
        return address_list

    def to_csv(self, csv_filepath: Optional[Union[str, io.StringIO]] = None, only_homeland=True) -> Optional[str]:
        """
        Export the administrative state to a CSV file or return it as a string.

        This method is designed to support both:
        - File-based export for scripting and data storage (when `csv_filepath` is a path)
        - In-memory string export for GUI usage (e.g., download via Streamlit) when `csv_filepath=None`.

        Args:
            csv_filepath (str or StringIO, optional): File path or buffer to write CSV to. If None, returns CSV as string.
            only_homeland (bool): Whether to include only homeland addresses.

        Returns:
            Optional[str]: CSV content as string if `csv_filepath` is None, otherwise None.
        """
        address_list = self.to_address_list(only_homeland=only_homeland)

        if not address_list:
            raise ValueError("Address list is empty; nothing to write.")

        df = pd.DataFrame(address_list, columns=["Region", "District"])

        if csv_filepath is None:
            return df.to_csv(index=False)
        else:
            df.to_csv(csv_filepath, index=False)
            return None

    def compare_to_r_d_list(self, r_d_list, verbose = False):
        """
        Takes a list of (region_name_id, dist_name_id) HOMELAND address pairs, estimates its own
        distance to the address list and returns distance measures.
        """
        # Comparison of the dist lists
        r_d_adm_state_list = self.to_address_list(only_homeland=True)
        d_adm_state_list = [district for region, district in r_d_adm_state_list]
        d_adm_state_set = set(d_adm_state_list)
        d_aim_list = [district for region, district in r_d_list]
        d_aim_set = set(d_aim_list)
        d_list_difference_1 = list(d_adm_state_set - d_aim_set)
        d_list_difference_1.sort()
        d_list_difference_2 = list(d_aim_set - d_adm_state_set)
        d_list_difference_2.sort()
        d_list_differences = (d_list_difference_1, d_list_difference_2)
        d_list_distance = len(d_list_difference_1) + len(d_list_difference_2)
        d_list_comparison = d_list_distance, d_list_differences

        # Comparison of the region lists
        r_d_adm_state_list = self.to_address_list(only_homeland=True)
        r_adm_state_list = [region for region, district in r_d_adm_state_list]
        r_adm_state_set = set(r_adm_state_list)
        r_aim_list = [region for region, district in r_d_list]
        r_aim_set = set(r_aim_list)
        r_list_difference_1 = list(r_adm_state_set - r_aim_set)
        r_list_difference_1.sort()
        r_list_difference_2 = list(r_aim_set - r_adm_state_set)
        r_list_difference_2.sort()
        r_list_differences = (r_list_difference_1, r_list_difference_2)
        r_list_distance = len(r_list_difference_1) + len(r_list_difference_2)
        r_list_comparison = r_list_distance, r_list_differences

        # Comparison of the region-district state
        r_d_adm_state_list = self.to_address_list(only_homeland=True)
        r_d_adm_state_set = set(r_d_adm_state_list)
        r_d_aim_set = set(r_d_list)
        state_difference_1 = list(r_d_adm_state_set - r_d_aim_set)
        state_difference_1.sort()
        state_difference_2 = list(r_d_aim_set - r_d_adm_state_set)
        state_difference_2.sort()
        state_differences = (state_difference_1, state_difference_2)
        state_distance = len(state_difference_1) + len(state_difference_2)
        state_comparison = state_distance, state_differences

        if verbose == True:
            print(f"State {self}:")
            print("Region list comparison:")
            print(f"\tDistance from the r_list: {r_list_distance}")
            print(f"\tAbsent in r_list to identify: {r_list_difference_1}.\n Absent in state: {r_list_difference_2}.")
            print("District list comparison:")
            print(f"\tDistance from the d_list: {d_list_distance}")
            print(f"\tAbsent in d_list to identify: {d_list_difference_1}.\n Absent in state: {d_list_difference_2}.")
            print("(Region,district) pairs comparison:")
            print(f"\tDistance from the r_d_list: {state_distance}")
            print(f"\tAbsent in r_d_list to identify: {state_difference_1}.\n Absent in state: {state_difference_2}.")

        return r_list_comparison, d_list_comparison, state_comparison
    
    def _district_plot_layer(self, dist_registry: DistrictRegistry, date: datetime, test=False):
        """
        Returns a districts GeoDataFrame for downstream plotting task (gdf columns definie the plotting styles).
        """
        gdf = dist_registry._plot_layer(date)

        if test:
            shownames = True
            gdf["color"] = "none"
        else:
            shownames = False
            # Keep the color returned by the dist_registry._plot_layer() method

        gdf["edgecolor"] = "black"
        gdf["linewidth"] = 1
        gdf["shownames"] = shownames
        return gdf
    
    def _region_plot_layer(self, region_registry, dist_registry: DistrictRegistry, date: datetime, test=False):
        """
        Returns a regions GeoDataFrame for downstream plotting task (gdf columns definie the plotting styles).
        Each Region geometry is created through the union of districts that belong to the region.
        """
        records = []
        for area_type, regions in self.unit_hierarchy.items():
            for region_name, districts in regions.items():
                region_name_id = region_registry.find_unit(region_name).name_id
                district_geoms = []
                for district_name in districts:
                    d, d_state, _ = dist_registry.find_unit_state_by_date(district_name, date)
                    if(d.exists(date)):
                        if d_state.current_territory is not None:
                            district_geoms.append(d_state.current_territory)
                # Set values for testing and examples:
                if test:
                    linewidth = 10
                    shownames = True
                else:
                    linewidth = 2
                    shownames = False
                if district_geoms:  # Only proceed if there is at least one valid geometry
                    region_shape = unary_union(district_geoms)
                    records.append({
                        "name_id": region_name_id,
                        "geometry": region_shape,
                        "color": "none",
                        "edgecolor": "black",
                        "linewidth": linewidth,
                        "shownames": shownames
                    })
        return gpd.GeoDataFrame(
            records,
            columns=["name_id", "geometry", "color", "edgecolor", "linewidth", "shownames"]
        )
    
    def _country_plot_layer(self, dist_registry: DistrictRegistry, date: datetime, test = False, plot_abroad = False):
        """
        Returns a country GeoDataFrame for downstream plotting task (gdf columns definie the plotting styles).
        Each country geometry is created through the union of districts that belong to ithe country
        """
        country_geoms = {}
        for country_name in self.unit_hierarchy.keys():
            country_geoms[country_name] = []
            for region_name, districts in self.unit_hierarchy[country_name].items():
                for district_name in districts:
                    district, dist_state, _ = dist_registry.find_unit_state_by_date(district_name, date)
                    if district.exists(date):
                        if dist_state.current_territory:
                            country_geoms[country_name].append(dist_state.current_territory)
        records = []
        # Set values for testing and examples:
        if test:
            homeland_color = "green"
        else:
            homeland_color = "white"

        if country_geoms.get("HOMELAND", None):
            records.append({
                "name_id": "HOMELAND",
                "geometry": unary_union(country_geoms["HOMELAND"]),
                "color": homeland_color,
                "edgecolor": "black",
                "linewidth": 0.5,
                "shownames": False
            })
        if plot_abroad:
            if country_geoms.get("ABROAD", None):
                records.append({
                    "name_id": "HOMELAND",
                    "geometry": unary_union(country_geoms["ABROAD"]),
                    "color": "blue",
                    "edgecolor": "black",
                    "linewidth": 0.5,
                    "shownames": False
                })
        return gpd.GeoDataFrame(
            records,
            columns=["name_id", "geometry", "color", "edgecolor", "linewidth", "shownames"]
        )
    
    def _whole_map_plot_layer(self, whole_map):
        """
        Takes a geometry with the shape of the whole map and adds styles for downstream plotting tasks.
        """
        whole_map_gpd = gpd.GeoDataFrame({
            "name_id": ["WHOLE_MAP"],
            "geometry": [whole_map],
            "color": ["gray"],
            "edgecolor": ["black"],
            "linewidth": [0.5],
            "shownames": [False]
        })

        return whole_map_gpd
    
    def plot(self, region_registry, dist_registry, whole_map, date, plot_abroad = False):
        """
        Creates a plot of the administrative state and returns the figure with the plot.
        """
        from utils.helper_functions import build_plot_from_layers

        start_time = time.time()

        # Prepare the layers
        if plot_abroad:
            country_layer = self._country_plot_layer(dist_registry, date)
        whole_map_layer = self._whole_map_plot_layer(whole_map)
        region_layer = self._region_plot_layer(region_registry, dist_registry, date)
        district_layer = self._district_plot_layer(dist_registry, date)

        # Build the figure
        if plot_abroad:
            fig = build_plot_from_layers(whole_map_layer, country_layer, district_layer, region_layer)
        else:
            fig = build_plot_from_layers(whole_map_layer, district_layer, region_layer)

        # 🎨 Add custom legend
        ax = fig.axes[0]  # Get the primary axis
        legend_patches = [
            mpatches.Patch(color="gray", label="No territory info"),
            mpatches.Patch(color="orange", label="Fallback territory"),
            mpatches.Patch(color="lightgreen", label="Deduced territory"),
            mpatches.Patch(color="green", label="Loaded territory"),
            mpatches.Patch(color="lightblue", label="Abroad"),
        ]
        ax.legend(handles=legend_patches, loc="lower left", fontsize="medium", frameon=True)

        end_time = time.time()
        execution_time = end_time-start_time
        print(f"Successfully created plot for administrative state {str(self)} in {execution_time:.2f} seconds.")
        return fig
    
    def apply_changes(self, changes_list, region_registry, dist_registry, start_index, verbose = True):
        """
        Creates a copy of itself, applies all changes to the copy and returns it as a new state.

        Arguments:
            - changes_list (list): A list of data_models.adm_change.Change instances.
                All changes are assumed to occur on the same date ending the timespan of the adm_state.
            - region_registry (adm_unit.RegionRegistry): Region registry.
            - dist_registry (adm_unit.DistrictRegistry): District registry.

        Returns:
            - new_state (AdministrativeState): New state - the outcome of the application of all changes.
        """

        if self.timespan is None:
            raise ValueError(f"Method 'apply_changes' applied to the state {str(self)} which has no defined timespan.")

        current_change_index = start_index

        # Take the date of the change and ensure that all changes have the same date.
        change_date = changes_list[0].date
        for change in changes_list:
            if change.date != change_date:
                raise ValueError(f"Changes applied to the state {self} have different dates!")
            
        changes_list.sort(key=lambda change: (change.order is None, change.order))

        # Create a new state such that change_date marks the transition between the old and the new one.
        new_state = self.create_new(change_date)
            
        for change in changes_list:
            try:
                # Ascribe an index to the change
                change.index = current_change_index
                current_change_index += 1
                
                # Apply change and store information on the affected districts
                change.apply(new_state, region_registry, dist_registry, adm_history_end_date = new_state.timespan.end, plot_change = False, verbose = verbose)
            except Exception as e:
                raise RuntimeError(f"Error during the application of change {str(change)}: {str(e)}") from e
        
        new_state.verify_consistency(region_registry, dist_registry)
        
        return new_state
    
    def __str__(self):
        regions_len = len(self.all_region_names())
        districts_len = len(self.all_district_names())
        return f"<AdministrativeState timespan={self.timespan}, regions={regions_len}, districts={districts_len}>"