from __future__ import annotations
from pydantic import BaseModel, model_validator
from typing import Optional, Literal, List, Tuple, Any, Union, TYPE_CHECKING

from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import pandas as pd
import geopandas as gpd
from shapely.ops import unary_union
from shapely.geometry.base import BaseGeometry

from collections import Counter


from administrative_history.data_models.adm_timespan import TimeSpan

if TYPE_CHECKING: # Using TYPE_CHECKING to postpone Change import and avoid circular imports
    from data_models.adm_change import Change
    
#####################################################################################
#                   Data models for states of administrative units                  #
#####################################################################################

#############################################################################################
# Hierarchy of models to store information about administrative units:
#       UnitState ∈ Unit (stores chronological sequence of its states) ∈ UnitRegistry

class UnitState(BaseModel):
    """
    Represents the state of an administrative unit (e.g., district, region) at a specific time.
    """
    current_name: str
    current_seat_name: str
    timespan: Optional[TimeSpan] = None

    # Self-references
    next: Optional[UnitState] = None
    previous: Optional[UnitState] = None

    # Forward references to Change
    next_change: Optional[Any] = None
    previous_change: Optional[Any] = None

    # Custon __repr__ magic method to avoid infinite recursion loop between Change and UnitState that hold each other as parameters.
    def __repr__(self):
        return (
            f"UnitState(current_name={self.current_name!r}, "
            f"current_seat_name={self.current_seat_name!r}, "
            f"timespan={self.timespan!r}, "
            f"next=..., "
            f"previous=..., "
            f"next_change=..., previous_change=...)"
        )



# This replaces `update_forward_refs()` in Pydantic v2
UnitState.model_rebuild()

class Unit(BaseModel):
    """
    Represents one administrative unit (district or region for the current version).
    The class's attributes describe unit attributes that don't change through time (e.g. name_variants).
    Attributes that do change through time (e.g. current_name should be handled as UnitState attributes)"""
    name_id: str
    name_variants: List[str]
    seat_name_variants: Optional[List[str]] = [] # Optional
    states: List[UnitState]
    changes: Optional[List] = []

    @model_validator(mode="after")
    def check_unit_name_in_variants(self) -> "Unit":
        """
        Ensures that name_id in the name_variants list.
        """
        if self.name_id not in self.name_variants:
            raise ValueError(f"name_id '{self.name_id}' must be in name_variants {self.name_variants}")
        return self
    
    def find_state_by_date(self, date: datetime) -> Optional[UnitState]:
        """Returns the state for the unit at a specific date, or None if no match is found."""
        for unit_state in self.states:
            if unit_state.timespan and date in unit_state.timespan:
                return unit_state
        return None  # Return None if no match is found
    
    def find_state_by_timespan(self, timespan: TimeSpan) -> Optional[UnitState]:
        """Returns the state for the unit within a specific timespan, or None if no match is found."""
        for unit_state in self.states:
            if unit_state.timespan:
                # Compare start and end dates directly
                if unit_state.timespan.start == timespan.start and unit_state.timespan.end == timespan.end:
                    return unit_state
        return None  # Return None if no matching timespan is found
    
    def create_next_state(self, date):
        """
        Creates a new state starting at the given date, ending the previous state, 
        and sorting the states list. The date must fall within an existing state's timespan.

        This method assumes that the state that is ended is THE LAST STATE in the 'self.states' list.
        """
        last_state = self.states[-1] # States should be stored according to the timely order.
        if date not in last_state.timespan:
            raise ValueError(f"Invalid date: {date.date()}. The last unit state doesn't cover this date. The last state ends at {last_state.timespan.end.date()}.")
        
        # Copy the last state, but avoid infinite referencing loop.
        data = last_state.model_dump(
            exclude={"next", "previous", "next_change", "previous_change"},
            round_trip=True  # Ensures correct types
        )
        new_state = last_state.__class__.model_validate({
            **data,
            'next': None,
            'previous': None,
            'next_change': None,
            'previous_change': None
        })

        last_state.timespan.end = date
        last_state.timespan.update_middle()
        new_state.timespan.start = date
        new_state.timespan.update_middle()
        self.states.append(new_state)
        self.states.sort(key=lambda state: state.timespan.start)

        return last_state, new_state
    
    def abolish(self, date):
        """Sets the end of the timespan covering the given date to the passed date, marking the unit's abolition."""
        last_state = self.find_state_by_date(date)
        last_state.timespan.end = date
        last_state.timespan.update_middle()
        return last_state

    def exists(self, date):
        """Returns True if the state exists for a given date or False if it doesn't."""
        searched_state = self.find_state_by_date(date)
        if searched_state is None:
            return False
        else:
            return True


class UnitRegistry(BaseModel):
    """
    A registry to manage a list of one type of units (districts/regions) and handle unit state transitions.
    """
    unit_list: List[Unit]
    unit_name_ids: Optional[List[str]] = None # Atttribute defined in the model validator
    all_name_variants: Optional[List[str]] = None
    all_seat_name_variants: Optional[List[str]] = None
    unique_name_variants: Optional[List[str]] = None # Atttribute defined in the model validator
    unique_seat_names: Optional[List[str]] = None # Atttribute defined in the model validator

    @model_validator(mode="after")
    def compute_name_variants(self) -> "UnitRegistry":
        # Define the self.unit_name_ids attribute
        unit_name_ids = [unit.name_id for unit in self.unit_list]
        dupplicate_name_ids = [name_id for name_id, count in Counter(unit_name_ids).items() if count > 1]
        if dupplicate_name_ids:
            raise ValueError(f"Some unit name_id parameters in the registry are not unique: {dupplicate_name_ids}")
        
        self.unit_name_ids = unit_name_ids
        
        # Check that no unit has name_variants or seat_name_variants values that are other unit's name_id
        for unit in self.unit_list:
            other_ids = [name_id for name_id in self.unit_name_ids if name_id != unit.name_id]
            for name in unit.name_variants:
                if name in other_ids:
                    raise ValueError(f"Unit {unit.name_id} has a name variant that is used as other unit's name_id. Please delete the name variant or change the name_id of the unit {unit.name_id} to a name_id that uniquely describes the unit.")
            for name in unit.seat_name_variants:
                if name in other_ids:
                    raise ValueError(f"Unit {unit.name_id} has a name variant that is used as other unit's name_id. Please delete the name variant or change the name_id of the unit {unit.name_id} to a name_id that uniquely describes the unit.")
        
        # Flatten and count all name_variants
        name_counts = Counter(
            name for unit in self.unit_list for name in set(unit.name_variants+unit.seat_name_variants) # Use set(...) to count only once the names that are BOTH a seat name and a name of THE SAME unit.
        )

        self.all_name_variants = [name for unit in self.unit_list for name in unit.name_variants]
        self.all_seat_name_variants = [name for unit in self.unit_list for name in unit.seat_name_variants]

        # Only keep variants that occur exactly once
        self.unique_name_variants = [name for name in self.all_name_variants if name_counts[name] == 1]
        self.unique_seat_names = [seat_name for seat_name in self.all_seat_name_variants if name_counts[seat_name] == 1]

        return self

    def find_unit(self, unit_name: str, use_seat_names = True, allow_non_unique = False) -> Optional[Unit]:
        """
        Finds a unit by its name or variant.

        If use_unique_seat_names is True, checks also seat names that are in the in the 

        Args:
            unit_name: The name to search for.

        Returns:
            Optional[Unit]: The unit if found, or None.
        """
        if allow_non_unique:
            unit_list = []
        for unit in self.unit_list:
            if unit_name == unit.name_id:
                return unit # name_id is always unique - the unit is returned immediately.
            if unit_name in unit.name_variants:
                if unit_name in self.unique_name_variants:
                    return unit # is name variant is unique, return the name immediately
                elif allow_non_unique:
                    unit_list.append(unit)
            if use_seat_names:
                if unit_name in unit.seat_name_variants:
                    if unit_name in self.unique_seat_names:
                        return unit
                    elif allow_non_unique:
                        unit_list.append(unit)
        if allow_non_unique:
            if unit_list:
                unit_list.sort(key=lambda unit: unit.name_id)
                return unit_list
            else:
                return None
        else:
            return None
    
    def find_unit_state_by_date(self, unit_name: str, date: datetime) -> Tuple[Unit, UnitState, TimeSpan]:
        """
        Finds the unit, its state, and timespan for a given date.

        Args:
            unit_name: The unit's name.
            date: The date for the state.

        Returns:
            Tuple: Unit, UnitState, and its TimeSpan.
        """
        unit = self.find_unit(unit_name)
        if unit is None:
            return None, None, None
        else:
            unit_state = unit.find_state_by_date(date)
            if unit_state is None:
                return unit, None, None
            else:
                timespan = unit_state.timespan
                return unit, unit_state, timespan
    
    def create_next_unit_state(self, unit_name: str, date: datetime) -> UnitState:
        """
        Creates the next state for a unit at a given date.

        Args:
            unit_name: The unit's name.
            date: The date for the next state.

        Returns:
            UnitState: The newly created unit state.
        """
        unit, unit_state, timespan = self.find_unit_state_by_date(unit_name, date)
        if unit is None:
            raise ValueError(f"Invalid unit_name: {unit_name}. This unit is not in the registry.")
        elif unit_state is None:
            raise ValueError(f"Invalid date: {date.date()}. No state covers this date.")
        else:
            return unit.create_next_state(date)
        
    def all_unit_states_by_date(self, date):
        all_existent = []
        for unit in self.unit_list:
            if unit.exists(date):
                all_existent.append((unit, unit.find_state_by_date(date)))
        return all_existent
    
    def all_unit_states(self):
        all_existent = []
        for unit in self.unit_list:
            all_existent += unit.states
        return all_existent
    
    def assure_consistency_and_append_new_unit(self,new_unit: Unit, verbose = False):
        """
        This method verifies:
            1) that the name_id if the new_unit passed is not used as a name variant of seat name variant
                of any other unit;
            2) that any name variant or seat name variant of the new_unit passed is not used as a name_id
                of any other unit.
        
        This method edits the self.unique_name_variants and self.unique_seat_name_variants attributes
        of the registry by checking if they do not repeat with the new unit's attributes.
        """
        for unit in self.unit_list:
            if new_unit.name_id in unit.name_variants:
                raise ValueError(f"The name_id '{new_unit.name_id}' of the new unit is used as another unit's name variant.")
            if new_unit.name_id in unit.seat_name_variants:
                raise ValueError(f"The name_id '{new_unit.name_id}' of the new unit is used as another unit's seat name variant.")

        # Append the unit
        self.unit_list.append(new_unit)

        # Verify that none of its name variants collides with existing name_ids
        for name_variant in new_unit.name_variants:
            if name_variant in self.unit_name_ids:
                raise ValueError(f"The name variant {name_variant} of the new unit is used as another unit's name_id.")
        
        for seat_name_variant in new_unit.seat_name_variants:
            if seat_name_variant in self.unit_name_ids:
                raise ValueError(f"The seat name variant {seat_name_variant} of the appended new unit is used as another unit's name_id.")
            
        # Correct the registries of unique unit name variants
        all_unit_name_variants = set(new_unit.name_variants + new_unit.seat_name_variants)
        for name_variant in all_unit_name_variants:
            if verbose:
                print(f"Checking the name variant {name_variant}.")
            #print(f"Current self.unique_name_variants: {self.unique_name_variants}")
            #print(f"Current self.unique_seat_names: {self.unique_seat_names}")
            if name_variant in self.all_name_variants or name_variant in self.all_seat_name_variants:
                if name_variant not in self.all_name_variants:
                    self.all_name_variants.append(name_variant)
                if name_variant not in self.all_seat_name_variants:
                    self.all_name_variants.append(name_variant)
                if name_variant in self.unique_name_variants:
                    self.unique_name_variants.remove(name_variant)
                    if verbose:
                        print(f"Removed name variant '{name_variant}' from unique_name_variants.")
                if name_variant in self.unique_seat_names:
                    self.unique_seat_names.remove(name_variant)
                    if verbose:
                        print(f"Removed name variant '{name_variant}' from unique_seat_names.")
            else:
                if name_variant in new_unit.name_variants:
                    self.unique_name_variants.append(name_variant)
                    self.all_name_variants.append(name_variant)
                else:
                    self.unique_seat_names.append(name_variant)
                    self.all_seat_name_variants.append(name_variant)

    
#############################################################################################
# Hierarchy of models to store districts states: DistrictState ∈ District ∈ DistrictRegistry

class DistState(UnitState):
    current_dist_type: Literal["w", "m"]
    current_territory: Optional[Any] = None
    current_territory_info: Optional[str] = None
    territory_is_fallback: Optional[bool] = None
    territory_is_deduced: Optional[bool] = False

    def _ter_union(self, ter_list: Union[List[BaseGeometry],List[str]], is_geometry = False):
        """
        Returns the unary union of geometries if compute_territory is true and a sum written in the form of a string if compute_territory is false.
        Used in self.spread_territory_info method.
        """
        if is_geometry:
            for ter in ter_list:
                if not (isinstance(ter, BaseGeometry) or ter is None):
                    raise ValueError(f"DistState._ter_union method expects a list of BaseGeometry type objects if is_geometry passed as True, but an element of type {type(ter)} was found in the list.")
            return unary_union(ter_list)
        else:
            if ter_list == []:
                return "(no_info)"
            for ter in ter_list:
                if not (isinstance(ter, str) or ter is None):
                    raise ValueError(f"DistState._ter_union method expects a list of str type objects if is_geometry passed as False, but an element of type {type(ter)} was found in the list.")
            ter_list = [ter if isinstance(ter, str) else "(no_info)" for ter in ter_list]
            return "("+" + ".join(ter_list)+")"
    
    def _ter_difference(self, ter_1: Union[BaseGeometry, str], ter_2: Union[BaseGeometry, str], is_geometry = False):
        """
        Returns the difference of geometries if compute_territory is true and the difference written in the form of a string if compute_territory is false.
        Used in self.spread_territory_info method.
        """
        if (isinstance(ter_1, BaseGeometry) or ter_1 is None) and (isinstance(ter_2, BaseGeometry) or ter_2 is None):
            return ter_1.difference(ter_2)
        elif (isinstance(ter_1, str) or ter_1 is None) and (isinstance(ter_2, str) or ter_2 is None):
            if ter_1 is None: ter_1 = "(no_info)"
            if ter_2 is None: ter_2 = "(no_info)"
            return "("+ter_1+" - "+ter_2+")"
        else:
            raise ValueError(f"DistState._ter_difference method expects a pair of BaseGeometry or str type elements. The elements passed are of type ({type(ter_1)}, {type(ter_2)}).")

    def spread_territory_info(self, compute_geometries=True, verbose = False, iteration = 'not defined'):
        """
        This method searches recursively through the graph of all links between district states
        and fills all district territories that can be deduced on the basis of type of district
        changes linking the consecutive states and the territories of the consecutive states.

        The logic of the method:
        The method tries to get the territory of the state before and after itself.
        1. If the state was created by a district attribute reform, the territory is same as of the state before.
        2. If the state was created by the change of unit address, the territory is the same as of the state before.
        3. If the state was created by a OneToMany or ManyToOne change involving n districts (including itself), then
            the state's territory can be deduced if the territories of the n-1 others are known.
        
        The method reaches to the states before and afterwards (in case of OneToMany and ManyToOne it reaches also to the
        states of other units involved in the change), and:
        1. Either retreives their territory,
        2. Or 
            a. Verifies that they haven't been checked yet - if yes, it returns None,
            b. if no, it calls the 'get_territory' method
        """
        if verbose:
            print(f"Iteration \'{iteration}\' Spreading territory info for district {self.current_name} {self.timespan} state.")

        was_something_deduced = False
        
        # This function should be called only for states that have the current_territory attribute defined
        if self.next_change:
            if verbose:
                print (f"The next change is {self.next_change}.")
            if len(self.next_change.next_states) == 1 and len(self.next_change.previous_states)==1:
                next_state = self.next_change.next_states[0]
                if next_state.current_territory_info is None:
                    next_state.current_territory_info = self.current_territory_info
                    next_state.territory_is_deduced = True
                    if compute_geometries:
                        next_state.current_territory = self.current_territory
                    next_state.territory_is_fallback = False
                    was_something_deduced = True
                    next_state.spread_territory_info(compute_geometries=compute_geometries, verbose=verbose, iteration=iteration)
            else:
                num_ter_unknown = 0
                state_with_ter_unknown = None # Holder for state with an unknown territory
                ter_unknown_after_or_before = None # If the state with an unknown territory exists after or before the change
                territory_before_info = []
                for unit_state in self.next_change.previous_states:
                    territory_before_info.append((unit_state.current_name, unit_state.current_territory_info))
                    if unit_state.current_territory_info is None:
                        num_ter_unknown += 1
                        state_with_ter_unknown = unit_state
                        ter_unknown_after_or_before = 'before'
                territory_after_info = []
                for unit_state in self.next_change.next_states:
                    territory_after_info.append((unit_state.current_name, unit_state.current_territory_info))
                    if unit_state.current_territory_info is None:
                        state_with_ter_unknown = unit_state
                        ter_unknown_after_or_before = 'after'
                        num_ter_unknown += 1
                if verbose:
                    dists_from = "(" + ", ".join([dist.name_id for dist, _ in self.next_change.dist_ter_from]) + ")"
                    dists_to = "(" + ", ".join([dist.name_id for dist, _ in self.next_change.dist_ter_to]) + ")"
                    change_str = "DATE: " + self.next_change.date.strftime("%Y-%m-%d") + ", CHANGE TYPE: " + self.next_change.matter.change_type + ", TER. FLOW: " + dists_from + "->" + dists_to
                    if not (num_ter_unknown == 1):
                        print(f"Unable to share territory farther. Change {self.next_change.index}:")
                    else:
                        print(f"Sharing territory farther. Change {self.next_change.index}:")
                    print(f"{change_str}\nKnown territories before:\n{territory_before_info}\nKnown territories after:\n{territory_after_info}")
                if num_ter_unknown == 1:
                    ############## Deduction of the n-th territory on the basis of n-1 territories involved in the change. ######################
                    # Create lists with all territory INFO immediately after and before the next administrative change
                    all_territory_info_before = [unit_state.current_territory_info for unit_state in self.next_change.previous_states if unit_state.current_territory_info is not None]
                    all_territory_info_after = [unit_state.current_territory_info for unit_state in self.next_change.next_states if unit_state.current_territory_info is not None]
                    # Create lists with all territory GEOMETRIES immediately after and before the next administrative change
                    if compute_geometries:
                        territories_before = [unit_state.current_territory for unit_state in self.next_change.previous_states if unit_state.current_territory is not None]
                        territories_after = [unit_state.current_territory for unit_state in self.next_change.next_states if unit_state.current_territory is not None]
                    # Merge territories before and after (respectively) into unified geometries
                    merged_territory_info_before = self._ter_union(all_territory_info_before, is_geometry=False)
                    merged_territory_info_after = self._ter_union(all_territory_info_after, is_geometry=False)
                    if compute_geometries:
                        merged_territory_before = self._ter_union(territories_before, is_geometry=True)
                        merged_territory_after = self._ter_union(territories_after, is_geometry=True)
                    # Deduce the territory:
                    if ter_unknown_after_or_before == 'before':
                        # The unknown territory can be deduced as the union of the known ones AFTER the change minus
                        #   the union of the known ones BEFORE the change
                        unknown_before_territory_info = self._ter_difference(merged_territory_info_after, merged_territory_info_before, is_geometry=False)
                        state_with_ter_unknown.current_territory_info = unknown_before_territory_info
                        if compute_geometries:
                            unknown_before_territory = self._ter_difference(merged_territory_after, merged_territory_before, is_geometry=True)
                            state_with_ter_unknown.current_territory = unknown_before_territory
                        state_with_ter_unknown.territory_is_deduced = True
                        state_with_ter_unknown.territory_is_fallback = False
                    else:
                        # The unknown territory can be deduced as the union of the known ones BEFORE the change minus
                        #   the union of the known ones AFTER the change
                        unknown_after_territory_info = self._ter_difference(merged_territory_info_before,merged_territory_info_after, is_geometry=False)
                        state_with_ter_unknown.current_territory_info = unknown_after_territory_info
                        if compute_geometries:
                            unknown_after_territory = self._ter_difference(merged_territory_before,merged_territory_after, is_geometry=True)
                            state_with_ter_unknown.current_territory = unknown_after_territory
                            state_with_ter_unknown.territory_is_deduced = True
                        state_with_ter_unknown.territory_is_fallback = False
                    if verbose:
                        print(f"Deduced territory: {state_with_ter_unknown.current_name}: {state_with_ter_unknown.current_territory_info}.")
                    # Run the spread_territory for the state for which territory was deduced
                    was_something_deduced = True
                    state_with_ter_unknown.spread_territory_info(compute_geometries=compute_geometries, verbose=verbose, iteration=iteration)
        else:
            if verbose:
                print (f"No next change defined.")
        # The logic for backward info share mirrors the forward info share logic.
        if self.previous_change:
            if verbose:
                print (f"The previous change is {self.previous_change}.")
                print("DEBUG: type=", type(self.previous_change))

            if len(self.previous_change.previous_states) == 1 and len(self.previous_change.next_states) == 1:
                previous_state = self.previous_change.previous_states[0]
                if previous_state.current_territory_info is None:
                    previous_state.current_territory_info = self.current_territory_info
                    if compute_geometries:
                        previous_state.current_territory = self.current_territory
                    previous_state.territory_is_deduced = True
                    previous_state.territory_is_fallback = False
                    was_something_deduced = True
                    previous_state.spread_territory_info(compute_geometries=compute_geometries, verbose=verbose, iteration = iteration)
            else:
                num_ter_unknown = 0
                state_with_ter_unknown = None # Holder for state with an unknown territory
                ter_unknown_after_or_before = None # If the state with an unknown territory exists after or before the change

                territory_before_info = []
                for unit_state in self.previous_change.previous_states:
                    territory_before_info.append((unit_state.current_name, unit_state.current_territory_info))
                    if unit_state.current_territory_info is None:
                        num_ter_unknown += 1
                        state_with_ter_unknown = unit_state
                        ter_unknown_after_or_before = 'before'

                territory_after_info = []
                for unit_state in self.previous_change.next_states:
                    territory_after_info.append((unit_state.current_name, unit_state.current_territory_info))
                    if unit_state.current_territory_info is None:
                        state_with_ter_unknown = unit_state
                        ter_unknown_after_or_before = 'after'
                        num_ter_unknown += 1
                
                if verbose:
                    dists_from = "(" + ", ".join([dist.name_id for dist, _ in self.previous_change.dist_ter_from]) + ")"
                    dists_to = "(" + ", ".join([dist.name_id for dist, _ in self.previous_change.dist_ter_to]) + ")"
                    change_str = "DATE: " + self.previous_change.date.strftime("%Y-%m-%d") + ", CHANGE TYPE: " + self.previous_change.matter.change_type + ", TER. FLOW: " + dists_from + "->" + dists_to
                    if not (num_ter_unknown == 1):
                        print(f"Unable to share territory farther. Change {self.previous_change.index}:")
                    else:
                        print(f"Sharing territory farther. Change {self.previous_change.index}:")
                    print(f"{change_str}\nKnown territories before:\n{territory_before_info}\nKnown territories after:\n{territory_after_info}")

                if num_ter_unknown == 1:
                    ################## Deduction of the n-th territory on the basis of n-1 territories involved in the change. #####################
                    all_territory_info_before = [unit_state.current_territory_info for unit_state in self.previous_change.previous_states if unit_state.current_territory_info is not None]
                    all_territory_info_after = [unit_state.current_territory_info for unit_state in self.previous_change.next_states if unit_state.current_territory_info is not None]
                    if compute_geometries:
                        territories_before = [unit_state.current_territory for unit_state in self.previous_change.previous_states if unit_state.current_territory is not None]
                        territories_after = [unit_state.current_territory for unit_state in self.previous_change.next_states if unit_state.current_territory is not None]
                    # Merge territories before and after (respectively) into unified geometries
                    merged_territory_info_before = self._ter_union(all_territory_info_before, is_geometry=False)
                    merged_territory_info_after = self._ter_union(all_territory_info_after, is_geometry=False)
                    if compute_geometries:
                        merged_territory_before = self._ter_union(territories_before, is_geometry=True)
                        merged_territory_after = self._ter_union(territories_after, is_geometry=True)
                    # Deduce the territory:
                    if ter_unknown_after_or_before == 'before':
                        # The unknown territory can be deduced as the union of the known ones AFTER the change minus
                        #   the union of the known ones BEFORE the change
                        unknown_before_territory_info = self._ter_difference(merged_territory_info_after,merged_territory_info_before, is_geometry=False)
                        state_with_ter_unknown.current_territory_info = unknown_before_territory_info
                        if compute_geometries:
                            unknown_before_territory = self._ter_difference(merged_territory_after,merged_territory_before, is_geometry=True)
                            state_with_ter_unknown.current_territory = unknown_before_territory
                        state_with_ter_unknown.territory_is_deduced = True
                        state_with_ter_unknown.territory_is_fallback = False
                    else:
                        # The unknown territory can be deduced as the union of the known ones BEFORE the change minus
                        #   the union of the known ones AFTER the change
                        unknown_after_territory_info = self._ter_difference(merged_territory_info_before,merged_territory_info_after, is_geometry=False)
                        state_with_ter_unknown.current_territory_info = unknown_after_territory_info
                        if compute_geometries:
                            unknown_after_territory = self._ter_difference(merged_territory_before,merged_territory_after, is_geometry=True)
                            state_with_ter_unknown.current_territory = unknown_after_territory
                        state_with_ter_unknown.territory_is_deduced = True
                        state_with_ter_unknown.territory_is_fallback = False

                    if verbose:
                        print(f"Deduced territory: {state_with_ter_unknown.current_name}: {state_with_ter_unknown.current_territory_info}.")

                    # Run the spread_territory for the state for which territory was deduced
                    was_something_deduced = True
                    state_with_ter_unknown.spread_territory_info(compute_geometries=compute_geometries, verbose=verbose, iteration=iteration)
        else:
            if verbose:
                print (f"No previous change defined.")

        return was_something_deduced

    def get_states_related_by_ter(self, parent_name, search_date, verbose = True):
        """
        Returns all DistrictState instances that existed on the given search_date and whose territories
        can overlap with the territory of this DistrictState as a result of administrative territory exchange sequence.

        Parameters:
            parent_name      (str): The name_id of the district that the state refers to.
            search_date (datetime): The date on which to search for existing district states.

        Returns:
            List[DistrictState]: A list of DistrictState instances that share part of their territory
                                with this instance and were active on the specified date.
        """
        if search_date in self.timespan:
            if verbose:
                print(f"Adding district '{parent_name}' state {str(self.timespan)} to related territories for search_date {search_date.date()}.")
            return {parent_name: self}
        elif search_date>=self.timespan.end:
            all_related_states = {}
            if self in [state for dist, state in self.next_change.dist_ter_from]:
                if verbose:
                    directly_related_territories = [dist.name_id for dist, state in self.next_change.dist_ter_to]+[parent_name]
                    if self.next is not None:
                        directly_related_territories.append(parent_name)
                    print(f"Searching through territories {directly_related_territories} related by the change on the date {self.next_change.date.date()}.")
                for dist, state in self.next_change.dist_ter_to:
                    all_related_states.update(state.get_states_related_by_ter(dist.name_id, search_date, verbose = verbose))
                if self.next is not None:
                    all_related_states.update(self.next.get_states_related_by_ter(parent_name, search_date, verbose = verbose))
                return all_related_states
            else:
                return self.next.get_states_related_by_ter(parent_name, search_date, verbose = verbose)
        elif search_date<self.timespan.start:
            all_related_states = {}
            if self in [state for dist, state in self.previous_change.dist_ter_to]:
                if verbose:
                    directly_related_territories = [dist.name_id for dist, state in self.previous_change.dist_ter_from]
                    if self.previous is not None:
                        directly_related_territories.append(parent_name)
                    print(f"Searching through territories {directly_related_territories} related by the change on the date {self.previous_change.date.date()}.")

                for dist, state in self.previous_change.dist_ter_from:
                    all_related_states.update(state.get_states_related_by_ter(dist.name_id, search_date, verbose = verbose))
                if self.previous is not None:
                    all_related_states.update(self.previous.get_states_related_by_ter(parent_name, search_date, verbose = verbose))
                return all_related_states
            else:
                return self.previous.get_states_related_by_ter(parent_name, search_date, verbose = verbose)

class District(Unit):
    """
    Represents one district. The attributes of this class describe district attributes that don't change through time (e.g. dist_name_variants).
    Attributes that do change through time (e.g. current_dist_name should be handled as DistStateDict attributes)
    """
    states: List[DistState]
            

class DistrictRegistry(UnitRegistry):
    """
    Registry of districts.
    """
    unit_list: List[District]

    def add_unit(self, district_data):
        if isinstance(district_data, District):
            district = district_data
        elif isinstance(district_data, dict):
            district = District(**district_data)
        else:
            raise TypeError("add_unit expects a District instance or a dictionary of District parameters.")
        
        self.assure_consistency_and_append_new_unit(district)
        return district
    
    def gdf(self, date: datetime):
        states_and_names = [(district.find_state_by_date(date), district.name_id) for district in self.unit_list if district.exists(date)]
        # Extract geometries and district names
        geometries = [state.current_territory for state, _ in states_and_names if state.current_territory is not None]
        dist_name_id = [name for state, name in states_and_names if state.current_territory is not None]
        return gpd.GeoDataFrame({'District': dist_name_id, 'geometry': geometries}, crs = "EPSG:4326")
    
    def _plot_layer(self, date: datetime):
    # Collect district states and names for districts that exist on the given date
        states_and_names = [(district.find_state_by_date(date), district.name_id) for district in self.unit_list if district.exists(date)]
        # Extract geometries and district names
        geometries = [state.current_territory for state, _ in states_and_names if state.current_territory is not None]
        dist_name_id = [name for state, name in states_and_names if state.current_territory is not None]  # Extract names for each district
        colors = [
            "green" if not state.territory_is_fallback and not state.territory_is_deduced
            else "lightgreen" if not state.territory_is_fallback and state.territory_is_deduced
            else "orange"
            for state, _ in states_and_names
            if state.current_territory is not None
        ]
        # Return a GeoDataFrame with district names and corresponding geometries
        return gpd.GeoDataFrame({'name_id': dist_name_id, 'geometry': geometries, 'color': colors}, crs = "EPSG:4326")

    
    def plot(self, adm_state_date: datetime, shownames: bool = True, df: pd.DataFrame = None):
        from utils.helper_functions import build_plot_from_layers

        layer = self._plot_layer(adm_state_date)
        
        if df is not None:
            if df.index.name != 'District' or df.shape[1] != 1:
                raise ValueError("DataFrame must have 'District' as index and exactly one data column.")

            # Reset index to turn 'District' into a column
            df_reset = df.reset_index()

            # Identify the single data column (other than 'District')
            data_col = df_reset.columns.difference(['District'])[0]

            # Rename for merge compatibility
            df_reset = df_reset.rename(columns={'District': 'name_id'})
            layer = layer.merge(df_reset, on='name_id', how='left')

            # Assign the data column to 'color', using a fallback for missing data
            layer["color"] = layer[data_col].fillna("lightgray")
        else:
            layer["color"] = "none"

        layer["edgecolor"] = "black"
        layer["linewidth"] = 1
        layer["shownames"] = shownames
    
        fig = build_plot_from_layers(layer)
        return fig
                

#############################################################################################
# Hierarchy of models to store Region states: RegionState ∈ Region ∈ RegionRegistry

class RegionState(UnitState):
    """
    State of a region.
    """

class Region(Unit):
    is_homeland: bool
    states: List[RegionState]

class RegionRegistry(UnitRegistry):
    unit_list: List[Region]

    def add_unit(self, region_data):
        if isinstance(region_data, Region):
            region = region_data
        elif isinstance(region_data, dict):
            region = Region(**region_data)
        else:
            raise TypeError("add_unit expects a Region instance or a dictionary of Region parameters.")

        self.unit_list.append(region)
        for name_variant in region.name_variants:
            if name_variant in self.unique_name_variants:
                self.unique_name_variants.pop(name_variant)
            else:
                self.unique_name_variants.append(name_variant)
        for seat_name_variant in region.seat_name_variants:
            if seat_name_variant in self.unique_seat_names:
                self.unique_seat_names.pop(seat_name_variant)
            else:
                self.unique_seat_names.append(seat_name_variant)
        return region

################################## DistrictEventLog model ##################################

class DistrictEvent(BaseModel):
    """ Represents the log of a change from the perspective of a district """
    district_name: str
    date: datetime
    event_type: str  # e.g. "created", "abolished", "moved", etc.
    change_ref: Optional['Change'] = None  # optional reference to the actual change

class DistrictEventLog(BaseModel):
    log: List[DistrictEvent]