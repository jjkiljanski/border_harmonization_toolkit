import streamlit as st
import pandas as pd

from administrative_history.core.core import AdministrativeHistory
from utils.helper_functions import standardize_df, load_uploaded_csv
import os

def standardize_dist_region_data_view(administrative_history: AdministrativeHistory):
    ################# Create containers #################
    upload_container = st.container()
    slider_container = st.container()
    comparison_container = st.container()
    editor_container = st.container()
    display_ready_container = st.container()

    ################# Define basic container content #################
    with upload_container:
        st.markdown("### Upload CSV to Compare Against Administrative State")
        upload_column, comparison_type_column, treat_duplicates_as_same_col = st.columns(3)
    with comparison_type_column:
        st.markdown("")
        comparison = st.radio(label = "Compare against:", options = ["Region vs District table", "Region list", "District list", "City name"])
        if comparison == "Region vs District table":
            comparison_cols = ["Region", "District"]
        elif comparison == "Region list":
            comparison_cols = ["Region"]
        elif comparison == "District list":
            comparison_cols = ["District"]
    with treat_duplicates_as_same_col:
        st.markdown("")
        st.markdown("Settings:")
        treat_duplicates_as_same = st.toggle(label = "Treat multiple name instances as one name.", value=False)
        show_other_edited_columns = st.toggle(label = "Show other columns of the standardized dataframe.", value = False)
    with comparison_container:
        state_df_col, uploaded_df_col = st.columns(2)
    with editor_container:
        edit_dataframe_container = st.container()
        suggestions_container = st.container()
        download_edited_csv_container = st.container()

    with slider_container:
        # Generate middle dates for timeline slider
        adm_state_middles = [adm_state.timespan.middle for adm_state in administrative_history.states_list]

        selected_date = st.slider(
            "Select Date",
            min_value=adm_state_middles[0],
            max_value=adm_state_middles[-1],
            value=adm_state_middles[len(adm_state_middles)//2],
            format="YYYY-MM-DD"
        )

    if len(comparison_cols)==2:
        ################ Prepare the administrative state df ###################

        # Get administrative state for selected date
        adm_state = administrative_history.find_adm_state_by_date(selected_date)

        if not adm_state or "HOMELAND" not in adm_state.unit_hierarchy:
            st.warning("No administrative data available for selected date.")
        else:
            homeland_hierarchy = adm_state.unit_hierarchy["HOMELAND"]
            region_district_map = {
                region_key: list(region_value.keys())
                for region_key, region_value in homeland_hierarchy.items()
            }

            # Create a DataFrame where each column is a region, and rows are district keys
            max_rows = max(len(districts) for districts in region_district_map.values())
            df_data = {
                region: districts + [""] * (max_rows - len(districts))
                for region, districts in region_district_map.items()
            }

            adm_state_df = pd.DataFrame(df_data)
    else:
        ################ Prepare the administrative state District or Region list ###################
        unit_type = comparison_cols[0]

        # Get administrative state for selected date
        adm_state = administrative_history.find_adm_state_by_date(selected_date)

        if not adm_state or "HOMELAND" not in adm_state.unit_hierarchy:
            st.warning("No administrative data available for selected date.")
        else:
            homeland_hierarchy = adm_state.unit_hierarchy["HOMELAND"]
            if unit_type == "Region":
                adm_state_unit_list = list(homeland_hierarchy.keys())
                print(f"adm_state_unit_list: {adm_state_unit_list}")
            else:
                adm_state_unit_list = [
                    district_name
                    for region_value in homeland_hierarchy.values()
                    for district_name in list(region_value.keys())
                ]

            # Create a DataFrame with one 'District' column
            df_data = {
                unit_type: adm_state_unit_list
            }

            adm_state_df = pd.DataFrame(df_data)

    with upload_column:
        uploaded_file = st.file_uploader("Upload a CSV with columns 'Region' and/or 'District'", type=["csv"])

    if uploaded_file:
        try:
            ################################# Verify the CSV standard is correct ####################################
            uploaded_df = load_uploaded_csv(uploaded_file)
            if uploaded_df is None:
                st.stop()
            if not set(comparison_cols).issubset(set(uploaded_df.columns)):
                    st.error(f"The chosen comparison type {comparison} requires the columns {comparison_cols} to be present in the uploaded dataset.")
            else:
                ############################# Sort the uploaded df and create df with names to edit ###########################
                if len(comparison_cols)==2:
                    # Sort uploaded_df by region, then by district (case insensitive)
                    uploaded_df = uploaded_df.sort_values(
                        by=["Region", "District"],
                        key=lambda col: col.str.lower() if col.dtype == "object" else col
                    )
                    if show_other_edited_columns:
                        edit_names_df = uploaded_df.copy()
                    else:
                        edit_names_df = uploaded_df.copy()[['Region', 'District']]
                    if treat_duplicates_as_same:
                        edit_names_df = edit_names_df.drop_duplicates(subset=["Region", "District"])
                else:
                    print(f"comparison_cols: {comparison_cols}")
                    unit_type = comparison_cols[0]
                    uploaded_df = uploaded_df.sort_values(
                        by=[unit_type],
                        key=lambda col: col.str.lower() if col.dtype == "object" else col
                    )
                    if show_other_edited_columns:
                        edit_names_df = uploaded_df.copy()
                    else:
                        edit_names_df = uploaded_df.copy()[[unit_type]]
                    if treat_duplicates_as_same:
                        edit_names_df = edit_names_df.drop_duplicates(subset=[unit_type])

                try:
                    ############################# Add columns with standardized names and sort #################################
                    # Use a copy to preserve original for highlighting if needed
                    standard_df = uploaded_df.copy()
                    edit_names_df_standard = edit_names_df.copy()
                    print("Attempting standardization")
                    unit_suggestions = standardize_df(
                        edit_names_df_standard,
                        region_registry=administrative_history.region_registry,
                        district_registry=administrative_history.dist_registry,
                        columns = comparison_cols,
                        raise_errors=False
                    )
                    print("Standardization was successful.")
                    print(f"unit_suggestions: {unit_suggestions}")

                    # Add standardized name versions
                    for unit_type in comparison_cols:
                        edit_names_df[f'Standardized {unit_type} Name'] = edit_names_df_standard[unit_type]

                    ##################################### Create the suggestions column ##########################################
                    suggestions_column = []
                    if len(comparison_cols)==2:
                        for std_region, orig_region, district in zip(
                                edit_names_df['Standardized Region Name'],
                                edit_names_df['Region'],
                                edit_names_df['District']):

                            # Prefer standardized region name if available
                            region = std_region if pd.notna(std_region) and std_region.strip() else orig_region
                            region = region.upper().strip()
                            district = district.upper().strip()

                            suggestions = unit_suggestions['District'].get((region, district), [])
                            suggestions_column.append(suggestions)

                        edit_names_df['District Name Suggestions'] = suggestions_column
                    else:
                        unit_type = comparison_cols[0]
                        for unit in edit_names_df[unit_type]:
                            unit = unit.upper().strip()
                            if unit_type == 'Region':
                                suggestions_column.append(unit_suggestions['Region'].get(unit, []))
                            if unit_type == 'District':
                                suggestions_column.append(unit_suggestions['District'].get((None, unit), []))

                        edit_names_df[f'{unit_type} Name Suggestions'] = suggestions_column
                    
                    ############################ Reorder edit_names_df columns if they are to be shown ############################
                    if show_other_edited_columns:
                        # Define the first columns with the unit names
                        first_columns = comparison_cols + [f'Standardized {unit_type} Name' for unit_type in comparison_cols]
                        if len(comparison_cols)==2:
                            first_columns.append("District Name Suggestions")
                        else:
                            first_columns.append(f"{comparison_cols[0]} Name Suggestions")
                        # Get the rest of the columns, excluding those already in first_columns
                        remaining_columns = [col for col in edit_names_df.columns if col not in first_columns]
                        # Reorder the DataFrame
                        edit_names_df = edit_names_df[first_columns + remaining_columns]
                except Exception as e:
                    st.error(f"An error occurred during standardization: {str(e)}")
                            
                ###################### Create editable dataframe #######################
                with edit_dataframe_container:
                    st.markdown("#### Edit Dataframe - define missing standardized district names")
                    
                    # Let the user edit the dataframe, but don't overwrite session state yet
                    edited_df = st.data_editor(edit_names_df, hide_index=True, key="editable_df")

                ###################### Display the ready dataframe ############################
                # edited_df has unique Region/District combos + standardized names
                # Rename columns in edited_df to avoid confusion
                standardized_cols = []
                for unit_type in comparison_cols:
                    standardized_cols.append(unit_type)
                    standardized_cols.append(f'Standardized {unit_type} Name')

                # Merge on original Region and District to attach standardized columns
                display_df = uploaded_df.copy()
                display_df = display_df.merge(
                    edited_df[standardized_cols],
                    on=comparison_cols,
                    how='left'  # keep all rows in display_df
                )
                
                # Replace original columns with standardized ones, filling missing values if any
                for column_name in comparison_cols:
                    display_df[column_name] = display_df[f'Standardized {column_name} Name'].fillna(display_df[column_name])

                # Drop the standardized columns since they're now copied over
                display_df = display_df.drop(columns=[f'Standardized {unit_type} Name' for unit_type in comparison_cols])
                display_df[unit_type] = display_df[unit_type].str.strip()
                with display_ready_container:
                    st.dataframe(display_df)

                ############################ Prepare for download #############################
                csv_edited_data = display_df.to_csv(index=False, sep = ";")

                # Append "_edited" to the file name before the extension
                name, ext = os.path.splitext(uploaded_file.name)
                edited_file_name = f"{name}_edited{ext}"

                ################ Prepare lists of unit names in both dataframes ###############

                if len(comparison_cols) == 2:

                    ###################### Prepare (Region,District) lists ########################
                    # Extract all (region, district) pairs set from adm_state
                    adm_state_r_d_set = {
                        (region, district)
                        for region in adm_state_df.columns
                        for district in adm_state_df[region].dropna()
                    }

                    # Extract all (region, district) pairs set from the edited dataframe download_df
                    edited_df_r_d_list = list(zip(list(display_df["Region"]), list(display_df["District"])))
                    edited_df_r_d_set = set(edited_df_r_d_list)

                    # Find all missing pairs
                    missing_units = adm_state_r_d_set-edited_df_r_d_set
                    missing_units = {pair for pair in missing_units if pair[1] != ''}
                
                else:
                    ###################### Prepare unit names lists ########################
                    # Extract unit names set from adm_state
                    unit_type = comparison_cols[0]
                    adm_state_unit_set = set(adm_state_df[unit_type])

                    # Extract all (region, district) pairs set from the edited dataframe download_df
                    edited_df_unit_set = set(list(display_df[unit_type]))

                    # Find all missing pairs
                    missing_units = adm_state_unit_set-edited_df_unit_set

                ###################### Prepare download ready CSV data ########################
                # Create a DataFrame for the missing pairs
                missing_df = pd.DataFrame(missing_units, columns = comparison_cols)

                # Append missing pairs to download_df (with other columns as NaN if not specified)
                ready_df = pd.concat([display_df, missing_df], ignore_index=True)
                ready_df = ready_df.sort_values(by=comparison_cols)

                # Convert to CSV
                csv_ready_data = ready_df.to_csv(index=False, sep = ";")

                # Append "_ready" to the file name before the extension
                name, ext = os.path.splitext(uploaded_file.name)
                ready_file_name = f"{name}_ready{ext}"

                ########################## Create download CSV buttons ########################

                with download_edited_csv_container:
                    # Download edited button
                    st.caption("Download edited dataframe as a CSV with standardized names where available.")
                    st.download_button(
                        label="Download Edited CSV",
                        data=csv_edited_data,
                        file_name=edited_file_name,
                        mime="text/csv",
                        key="download_edited_csv"  # Add a unique key
                    )

                    # Download ready button
                    st.caption("Download ready dataframe as a CSV with standardized names where available, and slots for missing data for the chosen administrative state.")
                    st.download_button(
                        label="Download Ready CSV",
                        data=csv_ready_data,
                        file_name=ready_file_name,
                        mime="text/csv",
                        key="download_ready_csv"  # Add a unique key
                    )

                ################## Apply conditional formatting to the dataframes #####################

                # Function to paint the DataFrame
                def style_cells(val, ref_list, color_if_found, color_if_not_found):
                    if val in ref_list:
                        return f"background-color: {color_if_found}"
                    elif val[0] == "":
                        return "" # Don't color if the cell is empty
                    else: 
                        return f"background-color: {color_if_not_found}"

                # Format first DataFrame (adm_state) - light green for matches and light blue for others
                def highlight_adm_state_dataframe(row):
                    return [
                        style_cells((col, row[col]), edited_df_r_d_set, "#90EE90", "#ADD8E6")
                        for col in row.index
                    ]

                # Format second DataFrame (uploaded_df) - light green for matches and light red for others
                def highlight_uploaded_dataframe(row):
                    return [
                        style_cells((col, row[col]), adm_state_r_d_set, "#90EE90", "#FFB6C1")
                        for col in row.index
                    ]
                
                def highlight_adm_state_unit_column(val):
                    if val in edited_df_unit_set:
                        return "background-color: #90EE90"  # Light green
                    else:
                        return "background-color: #ADD8E6"  # Light blue
                
                def highlight_uploaded_unit_column(val):
                    if val in adm_state_unit_set:
                        return "background-color: #90EE90"  # Light green
                    else:
                        return "background-color: #FFB6C1"  # Light red

                if len(comparison_cols)==2:
                    print(f"display_df: {display_df}")
                    # Use standardized names where possible and non-standardized names where they were not recognized.
                    new_r_d_list = [
                        (row["Region"], row["District"])
                        for _, row in display_df.iterrows()
                    ]
                    # Drop dupplicates
                    if treat_duplicates_as_same:
                        new_r_d_list = list(set(new_r_d_list))

                    # Create a map region: districts for the edited dataframe
                    loaded_region_district_map = {}
                    for region_name, dist_name in new_r_d_list:
                        if region_name not in loaded_region_district_map:
                            loaded_region_district_map[region_name] = []
                        if dist_name:
                            loaded_region_district_map[region_name].append(dist_name)

                    # Create a DataFrame where each column is a region, and rows are district keys
                    max_rows = max(len(districts) for districts in loaded_region_district_map.values())
                    df_data = {
                        region: districts + [""] * (max_rows - len(districts))
                        for region, districts in loaded_region_district_map.items()
                    }

                    edited_df_display = pd.DataFrame(df_data)
                else:
                    unit_type = comparison_cols[0]
                    units_list = list(display_df[unit_type])
                    if treat_duplicates_as_same:
                        units_list = list(set(units_list))
                    df_data = {unit_type: units_list}
                    edited_df_display = pd.DataFrame(df_data)

                # Now use edited_df to create styled_uploaded_df
                if len(comparison_cols)==2:
                    styled_uploaded_df = edited_df_display.style.apply(highlight_uploaded_dataframe, axis = 1)
                else:
                    styled_uploaded_df = edited_df_display.style.applymap(
                        highlight_uploaded_unit_column,
                        subset=[unit_type]  # Only apply to the target column
                    )

                with uploaded_df_col:
                    st.markdown(f"#### Names Recognized in the Uploaded File")
                    # Show the second dataframe, now reflecting edits
                    st.dataframe(styled_uploaded_df, hide_index=True)

                with state_df_col:
                    # Generate CSV string in-memory using the new version of to_csv
                    csv_data = adm_state.to_csv(csv_filepath=None, only_homeland=True)

                    # Show the first dataframe with styles
                    if len(comparison_cols) == 2:
                        styled_df_first = adm_state_df.style.apply(highlight_adm_state_dataframe, axis = 1)
                    else:
                        styled_df_first = adm_state_df.style.applymap(
                            highlight_adm_state_unit_column,
                            subset=[unit_type]  # Only apply to the target column
                        )
                    st.markdown(f"#### Administrative State {adm_state.timespan}")
                    st.dataframe(styled_df_first, hide_index=True)

                    st.caption(f"Download CSV template for administrative state {adm_state.timespan} of (Region, District) pairs.")

                    st.download_button(
                        label="Download State Template",
                        data=csv_data,
                        file_name=f"{adm_state.timespan.middle.date()}-region_district_template.csv",
                        mime="text/csv"
                    )

        except Exception as e:
            st.error(f"Could not process uploaded file: {str(e)}")
    else:
        # If file not uploaded, create adm_state_df without styling.
        with state_df_col:
            # Generate CSV string in-memory using the new version of to_csv
            csv_data = adm_state.to_csv(csv_filepath=None, only_homeland=True)

            # Show the adm state dataframe with styles
            st.markdown(f"#### Administrative State {adm_state.timespan}")
            st.dataframe(adm_state_df, hide_index=True)

            st.caption(f"Download CSV template for administrative state {adm_state.timespan} of (Region, District) pairs.")

            st.download_button(
                label="Download State Template",
                data=csv_data,
                file_name="region_district_template.csv",
                mime="text/csv"
            )