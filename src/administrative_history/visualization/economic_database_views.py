import streamlit as st
import plotly.express as px

def display_data_map(geojson, all_data_df, selected_dataset_id, selected_column):

    center = {
        "lat": 52.2297,
        "lon": 21.0122
    }

    chosen_category = f"{selected_dataset_id}:{selected_column}"

    st.dataframe(all_data_df[['District', chosen_category]])

    # Plot
    fig = px.choropleth_mapbox(
        all_data_df,
        geojson=geojson,
        locations='District',
        featureidkey="properties.id",
        color=chosen_category,
        center=center,
        mapbox_style="carto-positron",
        zoom=4,
        opacity=0.7,
        color_continuous_scale="Viridis",
        hover_name='District',
        hover_data={chosen_category: True}
    )

    fig.update_layout(margin={"r":0,"t":0,"l":0,"b":0})
    st.plotly_chart(fig, use_container_width=True)
