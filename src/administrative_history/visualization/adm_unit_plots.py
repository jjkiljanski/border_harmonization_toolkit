import pandas as pd
import plotly.express as px
import json
from datetime import datetime
import geopandas as gpd
from shapely.geometry import MultiPolygon, Polygon

from data_models.adm_unit import DistrictRegistry

def plot_dist_history(dist_registry, start_date, end_date):

    districts = dist_registry.unit_list
    districts.sort(key=lambda d: d.name_id)

    # Flatten states into a dataframe, assigning a unique task name for each state
    timeline_data = []
    for district in districts:
        state_i = 0
        if district.states:
            state_date = district.states[0].timespan.start
        for i, state in enumerate(district.states):
            if state.timespan.start>state_date:
                state_i += 1 # Increment state_i for coloring only if the date changes
            timeline_data.append({
                "StateInfo": f"{district.name_id} {str(state.timespan)}",
                "Start": state.timespan.start,
                "Finish": state.timespan.end,
                "District": district.name_id,
                "Color": str(state_i%2)
            })
            state_date = state.timespan.start
    
    df = pd.DataFrame(timeline_data)

    # Create thick horizontal bars using px.timeline
    fig = px.timeline(
        df,
        x_start="Start",
        x_end="Finish",
        y="District",       # This maps to 'Resource' in your example
        color="Color",   # Optional: use to color by district
        color_discrete_map={
            "1": "#5989cb",  # darker blue
            "0": "#3865a2",  # medium-dark royal blue
        },
        title="Districts Existence Over Time",
        hover_name="StateInfo"
    )

    # Add horizontal (vertical in time axis) lines for each year
    for year in range(start_date.year, end_date.year + 1):
        # Add vertical dotted line at the start of each year
        fig.add_shape(
            type="line",
            xref="x", yref="paper",
            x0=datetime(year, 1, 1), x1=datetime(year, 1, 1),
            y0=0, y1=1,
            line=dict(color="black", width=1, dash="dot")
        )

        # Add year label just above the line
        fig.add_annotation(
            x=datetime(year, 1, 1),
            y=1.02,
            xref="x", yref="paper",
            text=str(year),
            showarrow=False,
            font=dict(size=10, color="black"),
            align="center",
            yanchor="middle",
        )

    # Set appearance
    fig.update_layout(
        height=max(500, 45 * len(df['District'].unique())),
        xaxis_range=[start_date, end_date],
        showlegend=False,
    )

    fig.for_each_trace(lambda t: t.update(showlegend=False))  # <- This hides legend for all traces

    fig.update_yaxes(autorange="reversed")

    fig.update_traces(width= 0.6)

    return fig
    
def plot_dist_ter_info_history(dist_registry, start_date, end_date):
    districts = dist_registry.unit_list
    districts.sort(key=lambda d: d.name_id)

    # Flatten states into a dataframe
    timeline_data = []
    for district in districts:
        for state in district.states:
            if state.current_territory_info is not None:
                if state.territory_is_fallback:
                    color = "#FFA500"  # orange
                elif state.territory_is_deduced:
                    color = "#90EE90"
                else:
                    color = "#008000"  # green
            else:
                color = "#a9a9a9"  # grey

            timeline_data.append({
                "StateInfo": f"{district.name_id} {str(state.timespan)}",
                "Start": state.timespan.start,
                "Finish": state.timespan.end,
                "District": district.name_id,
                "Color": color,
                "TerritoryInfo": state.current_territory_info
            })

    df = pd.DataFrame(timeline_data)

    # Create timeline plot with green/grey bars based on Territory presence
    fig = px.timeline(
        df,
        x_start="Start",
        x_end="Finish",
        y="District",
        color_discrete_sequence=["#a9a9a9"],  # Default grey, will override per trace
        hover_name="StateInfo",
        hover_data=["TerritoryInfo"],
        title="Territorial State Information"
    )

    # Apply per-bar color from the "Color" column
    fig.update_traces(marker=dict(color=df["Color"]))

    # Add vertical dotted lines and year labels
    for year in range(start_date.year, end_date.year + 1):
        fig.add_shape(
            type="line",
            xref="x", yref="paper",
            x0=datetime(year, 1, 1), x1=datetime(year, 1, 1),
            y0=0, y1=1,
            line=dict(color="black", width=1, dash="dot")
        )
        fig.add_annotation(
            x=datetime(year, 1, 1),
            y=1.02,
            xref="x", yref="paper",
            text=str(year),
            showarrow=False,
            font=dict(size=10, color="black"),
            align="center",
            yanchor="middle",
        )

    fig.update_layout(
        height=max(500, 45 * len(df['District'].unique())),
        xaxis_range=[start_date, end_date],
        showlegend=False,
    )

    fig.update_yaxes(autorange="reversed")
    fig.update_traces(width=0.6)

    return fig

def plot_district_map(registry, date: datetime, opacity: float = 0.6):
    """
    Plots the district geometries at a given date using Plotly (no Mapbox).

    Args:
        registry (DistrictRegistry): The registry containing district data.
        date (datetime): The date at which the district states are to be plotted.
    
    Returns:
        plotly.graph_objs.Figure: A Plotly figure object.
    """
    # Get GeoDataFrame of district states existing on the given date
    gdf = registry._plot_layer(date)

    # Ensure geometries are in WGS84 (EPSG:4326)
    if gdf.crs is not None and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)

    # Convert GeoDataFrame to GeoJSON
    geojson_data = json.loads(gdf.to_json())

    # Use district names as unique identifiers
    district_ids = gdf["name_id"].tolist()

    # Create dummy DataFrame for mapping
    df = pd.DataFrame({
        "District": district_ids,
        "value": [1] * len(district_ids),  # Dummy uniform value
        "hover": [f"{district}<br>state for: {date.date}" for district in district_ids]
    })

    # Generate the choropleth map
    fig = px.choropleth_mapbox(
        df,
        geojson=geojson_data,
        locations="District",
        featureidkey="properties.name_id",
        color="value",
        custom_data=["hover"],
        color_continuous_scale=["gray", "gray"],  # All districts same color
        mapbox_style="carto-positron",
        zoom=5,
        center={"lat": 52.0, "lon": 19.0},  # Adjust to your region
        opacity=opacity
    )

    # Layout cleanup
    fig.update_layout(
        margin={"r": 0, "t": 0, "l": 0, "b": 0},
        coloraxis_showscale=False
    )

    return fig