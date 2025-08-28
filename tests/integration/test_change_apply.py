import pytest
from datetime import datetime
import copy

from ...data_models.adm_change import *

############################################################################
#                       UnitReform.apply method tests                      #
############################################################################

@pytest.mark.parametrize(
    "unit_type, current_name, to_reform_seat_name, should_raise",
    [
        ("Region", "region_a", "seat_region_a", False),            # Valid
        ("Region","wrong_region", "seat_region_a", True),         # Wrong region name
        ("Region","region_a", "wrong_seat", True),                # Wrong seat name
        ("Region","wrong_region", "wrong_seat", True),            # Both wrong
        ("District", "district_a", "seat_a", False),            # Valid
        ("District","wrong_district", "seat_a", True),         # Wrong region name
        ("District","district_a", "wrong_seat", True),                # Wrong seat name
        ("District","wrong_district", "wrong_seat", True),            # Both wrong
    ]
)
def test_parametrized_region_change_application(
    unit_type, current_name, to_reform_seat_name, should_raise,
    parametrized_region_change,
    change_test_setup
):
    change = parametrized_region_change(unit_type, current_name, to_reform_seat_name)
    adm_state = change_test_setup["administrative_state"]
    region_registry = change_test_setup["region_registry"]
    dist_registry = change_test_setup["dist_registry"]

    if should_raise:
        with pytest.raises(ConsistencyError):
            change.apply(adm_state, region_registry, dist_registry)
    else:
        change.apply(adm_state, region_registry, dist_registry)

def test_apply_one_to_many(change_test_setup, one_to_many_matter_fixture):
    # This change should refer to existing attributes and be valid.

    # Arrange
    adm_state = change_test_setup["administrative_state"]
    region_registry = change_test_setup["region_registry"]
    dist_registry = change_test_setup["dist_registry"]
    
    change = Change(
        date=datetime(1923, 1, 2),
        sources=["Test Source"],
        description="Legal Act X",
        order=1,
        matter=one_to_many_matter_fixture,
        units_affected = {"Region": [], "District": []}
    )
    
    # Act
    change.apply(adm_state, region_registry, dist_registry)

    # Assert
    # Check that district_a was abolished
    district_a = dist_registry.find_unit("district_a")
    assert district_a.find_state_by_date(datetime(1923, 1, 1)).timespan.end == datetime(1923, 1, 2)
    assert ("abolished", change) in district_a.changes
    assert ("abolished", district_a) in change.units_affected["District"]

    # Check that district_b received a new state and has territory change
    district_b = dist_registry.find_unit("district_b")
    assert len(district_b.states) > 1
    assert district_b.changes[-1] == ("territory", change)
    assert ("territory", district_b) in change.units_affected["District"]

    # Check that district_x was created with proper state
    district_x = dist_registry.find_unit("district_x")
    assert district_x is not None
    assert district_x.states[0].timespan.start == datetime(1923, 1, 2)
    assert ("created", change) in district_x.changes
    assert ("created", district_x) in change.units_affected["District"]

def test_apply_many_to_one(change_test_setup, create_many_to_one_matter_fixture):
    # This change should refer to existing attributes and be valid.

    # Arrange
    adm_state = change_test_setup["administrative_state"]
    region_registry = change_test_setup["region_registry"]
    dist_registry = change_test_setup["dist_registry"]
    
    change = Change(
        date=datetime(1924, 1, 2),
        sources=["Test Source"],
        description="Legal Act X",
        order=1,
        matter=create_many_to_one_matter_fixture,
        units_affected={"Region": [], "District": []}
    )
    
    # Act
    change.apply(adm_state, region_registry, dist_registry)

    # Assert
    # Check that district_a was abolished
    district_a = dist_registry.find_unit("district_a")
    assert district_a.exists(datetime(1924, 1, 1)) and not district_a.exists(datetime(1924, 1, 3))
    assert ("abolished", change) in district_a.changes
    assert ("abolished", district_a) in change.units_affected["District"]

    # Check that district_b's state is updated, but it is not deleted
    district_b = dist_registry.find_unit("district_b")
    assert len(district_b.states) > 1
    assert district_b.changes[-1] == ("territory", change)
    assert ("territory", district_b) in change.units_affected["District"]

    # Check that district_x was created with the correct state and timespan
    district_x = dist_registry.find_unit("district_x")
    assert district_x is not None
    assert not district_x.exists(datetime(1924, 1, 1)) and district_x.exists(datetime(1924, 1, 3))
    assert ("created", change) in district_x.changes
    assert ("created", district_x) in change.units_affected["District"]

def test_apply_change_adm_state(change_test_setup, region_change_adm_state_matter_fixture):
    # This change should refer to existing attributes and be valid.

    # Arrange
    adm_state = change_test_setup["administrative_state"]
    region_registry = change_test_setup["region_registry"]
    dist_registry = change_test_setup["dist_registry"]
    
    change = Change(
        date=datetime(1924, 1, 2),
        sources=["Test Source"],
        description="Legal Act X",
        order=1,
        matter=region_change_adm_state_matter_fixture,
        units_affected={"Region": [], "District": []}
    )
    
    # Act
    change.apply(adm_state, region_registry, dist_registry)

    # Assert that the address was moved in the administrative state
    assert adm_state.get_address(("HOMELAND", "region_c")) is True
    assert adm_state.get_address(("ABROAD", "region_c")) is False

    # Assert that the region unit was affected
    region_unit = region_registry.find_unit("region_c")
    assert ("adm_affiliation", change) in region_unit.changes
    assert ("adm_affiliation", region_unit) in change.units_affected["Region"]


############################################################################
#             AdministrativeState.apply_changes method tests               #
############################################################################

def test_administrative_state_apply(request, change_test_setup):

    # Deepcopy to reset state for each fixture
    region_registry = copy.deepcopy(change_test_setup["region_registry"])
    dist_registry = copy.deepcopy(change_test_setup["dist_registry"])
    administrative_state = copy.deepcopy(change_test_setup["administrative_state"])
    
    changes_list = []
    
    # 2. Add the plots for every fixture
    for i, fixture_name in enumerate(["district_change_adm_state_matter_fixture", "region_reform_matter_fixture",
                         "reuse_many_to_one_matter_fixture"]):
        
        matter = request.getfixturevalue(fixture_name)
        change = Change(
            date=datetime(1930, 5, 1),
            sources=["Legal Act XYZ"],
            description="Test change",
            order=3-i,
            matter=matter
        )

        changes_list.append(change)

    _, all_units_affected = administrative_state.apply_changes(changes_list, region_registry, dist_registry)
    
    district_a = dist_registry.find_unit('district_a')
    assert [change_type for (change_type, _) in district_a.changes] == ['adm_affiliation']
    district_b = dist_registry.find_unit('district_b')
    assert [change_type for (change_type, _) in district_b.changes] == []
    district_c = dist_registry.find_unit('district_c')
    assert [change_type for (change_type, _) in district_c.changes] == ['territory']
    district_d = dist_registry.find_unit('district_d')
    assert [change_type for (change_type, _) in district_d.changes] == ['abolished']
    district_e = dist_registry.find_unit('district_e')
    assert [change_type for (change_type, _) in district_e.changes] == ['territory']
    region_a = region_registry.find_unit('region_a')
    assert [change_type for (change_type, _) in region_a.changes] == ['reform', 'adm_affiliation']  
    region_b = region_registry.find_unit('region_b')
    assert [change_type for (change_type, _) in region_b.changes] == ['adm_affiliation']  