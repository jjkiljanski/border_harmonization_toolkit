import streamlit as st
import pandas as pd
import os
from PIL import Image

from collections import defaultdict

from core.core import AdministrativeHistory
from visualization.adm_unit_plots import (
    plot_dist_history,
    plot_dist_ter_info_history,
    plot_district_map
)

def display_district_registry(administrative_history: AdministrativeHistory):

    dist_changes_container = st.container()
    history_plot_container = st.container()

    dist_registry = administrative_history.dist_registry

    # Collect district change data
    district_change_rows = []
    for dist in dist_registry.unit_list:
        change_entries = []
        for change_type, change in dist.changes:
            dists_from = "(" + ", ".join([dist.name_id for dist, _ in change.dist_ter_from]) + ")"
            dists_to = "(" + ", ".join([dist.name_id for dist, _ in change.dist_ter_to]) + ")"
            change_entries.append("DATE: " + change.date.strftime("%Y-%m-%d") + ", CHANGE TYPE: " + change_type + ", TER. FLOW: " + dists_from + "->" + dists_to)
        change_entries.sort()
        district_change_rows.append({
            "District": dist.name_id,
            "Changes": change_entries
        })

    # Create DataFrame
    district_changes_df = pd.DataFrame(district_change_rows)

    # Display table in container
    with dist_changes_container:
        st.subheader("District Changes Overview")
        st.dataframe(
            district_changes_df,
            use_container_width=True,
            column_config={
                "Changes": st.column_config.ListColumn(
                    label="Changes (Type, Date)",
                    help="List of (change_type, date) for each change affecting the district"
                )
            }
        )

    start_date = administrative_history.timespan.start
    end_date = administrative_history.timespan.end
    fig = plot_dist_history(dist_registry, start_date, end_date)
    with history_plot_container:
        st.plotly_chart(fig, use_container_width=True)

def display_territorial_state_info(administrative_history: AdministrativeHistory):
    dist_registry = administrative_history.dist_registry

    start_date = administrative_history.timespan.start
    end_date = administrative_history.timespan.end
    fig = plot_dist_ter_info_history(dist_registry, start_date, end_date)
    st.plotly_chart(fig, use_container_width=True)

def display_adm_state_maps(administrative_history: AdministrativeHistory):
    st.subheader("Administrative State Maps")

    # Load all PNGs and map them to labels (without file extension)
    map_folder = "output/adm_states_maps"
    available_map_files = {
        filename[:-4]: os.path.join(map_folder, filename)
        for filename in os.listdir(map_folder)
        if filename.endswith(".png")
    }

    # Initialize session state for index tracking
    if "admin_state_index" not in st.session_state:
        st.session_state.admin_state_index = 0

    # Total number of states
    total_states = len(administrative_history.states_list)

    # Navigation buttons
    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("Previous State"):
            if st.session_state.admin_state_index > 0:
                st.session_state.admin_state_index -= 1
    with col2:
        if st.button("Next State"):
            if st.session_state.admin_state_index < total_states - 1:
                st.session_state.admin_state_index += 1

    # Get current administrative state
    current_state = administrative_history.states_list[st.session_state.admin_state_index]
    current_label = current_state.to_label()

    # Display info
    st.markdown(f"**Administrative State {current_state.timespan}: {st.session_state.admin_state_index + 1} of {total_states}**")

    # Try to display the corresponding map
    image_path = available_map_files.get(current_label)
    if image_path and os.path.exists(image_path):
        image = Image.open(image_path)
        st.image(image, caption=current_label, width=800)
    else:
        st.warning(f"No map image found for: {current_label}")

def display_changes_history(administrative_history: AdministrativeHistory):
    st.subheader("Administrative Change History")

    change_plot_container = st.container()
    change_list_container = st.container()
    source_list_container = st.container()

    with change_plot_container:
        # Plot changes by year
        dist_changes_hist_plot = administrative_history.plot_dist_changes_by_year(black_and_white=False)
        st.plotly_chart(dist_changes_hist_plot, use_container_width=True)

    change_data = []
    for change in administrative_history.changes_list:
        date = change.date
        change_type = getattr(change.matter, "change_type", "Unknown")

        source_1_name = change.sources[0]
        source_1_link = change.links[0]

        source_2_name = change.sources[1]
        source_2_link = change.links[1]

        districts_before = change.units_affected_ids["District"].get("before", [])
        districts_after = change.units_affected_ids["District"].get("after", [])
        districts_affected = set(districts_before + districts_after)

        change_data.append({
            "date": date.date(),
            "Change Type": change_type,
            "districts affected": ", ".join(sorted(districts_affected)),
            "Source 1 Name": source_1_name,
            "Source 1 Link": source_1_link if source_1_link else "",
            "Source 2 Name": source_2_name,
            "Source 2 Link": source_2_link if source_2_link else "",
        })

    change_df = pd.DataFrame(change_data).sort_values("date")

    with change_list_container:
        st.markdown("### Summary of all single changes")
        st.dataframe(
            change_df,
            use_container_width=True,
            column_config={
                "Source 1 Link": st.column_config.LinkColumn(
                    label="Source 1 Link",
                    validate="^https?://.+$"
                ),
                "Source 2 Link": st.column_config.LinkColumn(
                    label="Source 2 Link",
                    validate="^https?://.+$"
                ),
            }
        )

    # Temporary dictionary keyed by (date, legal_act_name, legal_act_link)
    grouped_changes = defaultdict(set)

    for change in administrative_history.changes_list:
        change_date = change.date
        legal_act_name = change.sources[0] if change.sources else "Unknown"
        legal_act_link = change.links[0] if (change.links and change.links[0] and change.links[0] != "X") else ""

        districts_before = change.units_affected_ids["District"].get("before", [])
        districts_after = change.units_affected_ids["District"].get("after", [])
        affected_districts_set = set(districts_before + districts_after)

        key = (change_date, legal_act_name, legal_act_link)
        grouped_changes[key].update(affected_districts_set)

    # Build rows from grouped data
    aggregated_rows = []
    for (date, act_name, act_link), districts_set in grouped_changes.items():
        aggregated_rows.append({
            "Date": date.date(),
            "Legal Act": act_name,
            "Link": act_link,
            "Affected Districts": ", ".join(sorted(districts_set))
        })

    df_aggregated_changes = pd.DataFrame(aggregated_rows).sort_values(["Date", "Legal Act"])

    with source_list_container:
        st.markdown("### Summary of all changes by source")
        st.dataframe(
            df_aggregated_changes,
            use_container_width=True,
            column_config={
                "Link": st.column_config.LinkColumn(
                    label="Legal Act Link",
                    validate="^https?://.+$"
                )
            }
        ) 
