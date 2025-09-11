import streamlit as st
import pandas as pd
import geopandas as gpd
from fuzzywuzzy import process

def standardize_city_data_view(administrative_history):
    reference_names = administrative_history.cities_df["City"].tolist()
    reference_dict = dict(zip(administrative_history.cities_df["City"], administrative_history.cities_df["Wiki_link"]))

    # --- Streamlit app ---
    st.title("City Name Standardization Tool")

    # Upload CSV
    uploaded_file = st.file_uploader("Upload a CSV with a 'City' column", type=["csv"])

    if uploaded_file:
        df = pd.read_csv(uploaded_file, encoding="utf-8")

        if "City" not in df.columns:
            st.error("The uploaded CSV must have a 'City' column.")
            st.stop()

        # Prepare editable dataframe
        standardized_data = []
        for city in df["City"]:
            if pd.isna(city) or city.strip() == "":
                standardized_data.append({
                    "City": city,
                    "Standardized_City_Name": "",
                    "City_Name_Suggestion_1": "",
                    "Link_1": "",
                    "City_Name_Suggestion_2": "",
                    "Link_2": "",
                    "City_Name_Suggestion_3": "",
                    "Link_3": "",
                })
                continue

            # Exact match
            if city in reference_dict:
                standardized_data.append({
                    "City": city,
                    "Standardized_City_Name": city,
                    "City_Name_Suggestion_1": "",
                    "Link_1": "",
                    "City_Name_Suggestion_2": "",
                    "Link_2": "",
                    "City_Name_Suggestion_3": "",
                    "Link_3": "",
                })
            else:
                # Fuzzy match top 3
                matches = process.extract(city, reference_names, limit=3)
                suggestions = []
                for match_name, score in matches:
                    suggestions.append((match_name, reference_dict.get(match_name, "")))

                # Pad to 3 suggestions
                while len(suggestions) < 3:
                    suggestions.append(("", ""))

                standardized_data.append({
                    "City": city,
                    "Standardized_City_Name": "",
                    "City_Name_Suggestion_1": suggestions[0][0],
                    "Link_1": suggestions[0][1],
                    "City_Name_Suggestion_2": suggestions[1][0],
                    "Link_2": suggestions[1][1],
                    "City_Name_Suggestion_3": suggestions[2][0],
                    "Link_3": suggestions[2][1],
                })

        edit_df = pd.DataFrame(standardized_data)

        # Editable table
        st.markdown("### Edit Standardized City Names")
        edited_df = st.data_editor(edit_df, hide_index=True, num_rows="dynamic")

        # Download button
        st.download_button(
            "Download Edited CSV",
            edited_df.to_csv(index=False, encoding="utf-8"),
            file_name="standardized_cities.csv",
            mime="text/csv"
        )