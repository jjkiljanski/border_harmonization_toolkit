import pandas as pd
import numpy as np
import json
import os
from datetime import datetime
import matplotlib.pyplot as plt
from matplotlib.image import imread
from io import BytesIO
import base64
import io
import streamlit as st
from typing import Union, Literal

def normalize_spaces(text: str) -> str:
    # Replace non-breaking spaces (U+00A0) with normal spaces and strip
    return text.replace("\u00A0", " ").strip()

def load_and_standardize_csv(file_path, region_registry, district_registry):
    # Read the CSV
    df = pd.read_csv(file_path)

    unit_suggestions = standardize_df(df, region_registry, district_registry)

    return df, unit_suggestions

def extract_date_parts(date_str: str):
    """
    Extracts year, month, and day as strings from a date string.
    
    Accepted formats:
    - 'YYYY'
    - 'MM.YYYY'
    - 'DD.MM.YYYY'

    Parameters:
    - date_str (str): Date string in one of the accepted formats.

    Returns:
    - year (str): Year in 'YYYY' format.
    - month (str or None): Month in 'MM' format or None if not provided.
    - day (str or None): Day in 'DD' format or None if not provided.
    """
    try:
        parts = date_str.strip().split(".")
        if len(parts) == 1 and len(parts[0]) == 4:
            year = parts[0]
            return int(year), None, None
        elif len(parts) == 2 and len(parts[0]) == 2 and len(parts[1]) == 4:
            month, year = parts
            return int(year), int(month), None
        elif len(parts) == 3 and len(parts[0]) == 2 and len(parts[1]) == 2 and len(parts[2]) == 4:
            day, month, year = parts
            return int(year), int(month), int(day)
        else:
            raise ValueError(f"Date must be in 'YYYY', 'MM.YYYY', or 'DD.MM.YYYY' format. Passed: {date_str}")
    except Exception as e:
        raise ValueError(f"Invalid date format '{date_str}': {e}")


def standardize_df(df, region_registry, district_registry, columns = ["Region", "District"], raise_errors = True, verbose = False):
    """
    Standardizes the 'Region' and 'District' names in a DataFrame using the provided unit registries.

    This function looks up each name in the 'Region' and 'District' columns against the corresponding
    registry. If a name uniquely identifies a unit, it is replaced with that unit's `name_id`.
    A dictionary (`unit_suggestions`) of name-to-matching-region-ID(s) (for regions)
    or (region_name, dist_name)-to-matching-dist-ID(s) is built along the way to record ambiguous
    or alternative names.

    Parameters:
        df (pd.DataFrame): DataFrame containing 'Region' and 'District' columns to be standardized.
        region_registry (UnitRegistry): Registry containing region units.
        district_registry (UnitRegistry): Registry containing district units.
        columns (List): List of columns to standardize. This version supports only: ["Region", "District"]
        raise_errors (bool): If True, raises a ValueError when an unrecognized name is encountered.

    Returns:
            dict: A dictionary mapping each original region name or (standardized region name, original dist name)
                to a list of matching unit `name_id`s.
    """
    if not set(columns).issubset({'Region', 'District'}):
        raise ValueError(f"Parameter 'columns' passed to the function must be a sublist of ['Region', 'District'] list, but argument columns={columns} was passed.")
    
    if set(columns).issubset(df.columns):
        for column_name in columns:
            df[column_name] = df[column_name].str.strip().str.upper()
    else:
        raise ValueError(f"Attempted to standardize {columns} columns, but the dataframe passed as argument doesn't contain {set(columns)-set(df.columns)}.")

    # Dict with 'Region' and 'District' keys (if the values are passed in 'columns' parameter)
    # with lists of names missing in the registry.
    not_in_registry = {column_name: [] for column_name in columns}

    # suggestions dict collects (unit_name_aim : list of units that have the name variant) key:value pairs
    # (case where a name variant is used by many units)
    unit_suggestions = {column_name: {} for column_name in columns}

    if df.empty:
        print("The dafaframe passed to standardization is empty.")
        return unit_suggestions
    else:
        for unit_type in columns:
            for idx, unit_name_aim in df[unit_type].items():
                if unit_type == 'Region':
                    found_units = region_registry.find_unit(unit_name_aim, allow_non_unique = True)
                else:
                    found_units = district_registry.find_unit(unit_name_aim, allow_non_unique = True)


                if verbose:
                    if isinstance(found_units, list):
                        print(f"Standardizing {unit_type} name {unit_name_aim}. Found: {list(set([unit.name_id for unit in found_units]))}.")
                    elif found_units is None or found_units == []:
                        print(f"Standardizing {unit_type} name {unit_name_aim}. Found: None.")
                    else:
                        print(f"Standardizing {unit_type} name {unit_name_aim}. Found: {found_units.name_id}.")
                

                if found_units is None:
                    unit = None
                    if unit_name_aim not in not_in_registry[unit_type]:
                        not_in_registry[unit_type].append(unit_name_aim)

                elif isinstance(found_units, list):
                    unit = None
                    if unit_type == 'Region':
                        if unit_name_aim not in unit_suggestions['Region']:
                            unit_suggestions['Region'][unit_name_aim] = list(set([unit.name_id for unit in found_units]))
                    elif unit_type == 'District':
                        if 'Region' in columns:
                            region_name = df.at[idx,'Region']
                        else:
                            region_name = None
                        if (region_name, unit_name_aim) not in [r_d_pair for r_d_pair in unit_suggestions['District']]:
                            unit_suggestions['District'][(region_name,unit_name_aim)] = list(set([unit.name_id for unit in found_units]))
                else:
                    unit = found_units
                    if unit.name_id != unit_name_aim and verbose:
                        print(f"Warning: name {unit_name_aim} is an alternative {unit_type.lower()} name. Processing further as {unit.name_id}")


                if unit is None:
                    df.at[idx, unit_type] = None
                else:
                    df.at[idx, unit_type] = unit.name_id

        for unit_type in columns:
            if not_in_registry[unit_type] and raise_errors:
                raise ValueError(f"{unit_type} names {not_in_registry[unit_type]} do not exist in the {unit_type.lower()} registry.")
        
        if verbose:
            print("Successfully standardized the given dataframe.")
            print(f"unit_suggestions: {unit_suggestions}")
        return unit_suggestions

def load_uploaded_csv(uploaded_file):
    # Step 1: Read a sample to guess encoding and check delimiter
    try:
        sample_bytes = uploaded_file.read(2048)
        uploaded_file.seek(0)  # reset for actual reading
        try:
            sample_str = sample_bytes.decode('utf-8')
            encoding = 'utf-8'
        except UnicodeDecodeError:
            sample_str = sample_bytes.decode('windows-1250')
            encoding = 'windows-1250'
    except Exception as e:
        st.error(f"Could not read file preview: {e}")
        return None

    # Step 2: Read using pandas
    try:
        df = pd.read_csv(uploaded_file, encoding=encoding, sep=';', engine='python')
        return df
    except Exception as e:
        st.error(f"Could not parse CSV file. Encoding: {encoding}. Error: {e}")
        return None

def load_adm_history_config(config_path):
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration file {config_path} not found.")
    
    with open(config_path, "r") as config_file:
        config_data = json.load(config_file)
    
    # Convert global_timespan start and end dates to datetime objects
    global_timespan = config_data.get("global_timespan", {})
    if "start" in global_timespan:
        global_timespan["start"] = datetime.strptime(global_timespan["start"], "%d-%m-%Y")
    if "end" in global_timespan:
        global_timespan["end"] = datetime.strptime(global_timespan["end"], "%d-%m-%Y")
    
    return config_data

def load_processing_config(config_path="input/processing_config.json"):
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration file {config_path} not found.")
    
    with open(config_path, "r") as config_file:
        config_data = json.load(config_file)
    
    return config_data

def build_plot_from_layers(*layers):
    fig, ax = plt.subplots(figsize=(10, 10))
    for layer in layers:
        # For debugging, uncomment:
        # print(layer.to_string())

        # Group and plot by shared plotting attributes to decrease computation time
        group_cols = ["color", "edgecolor", "linewidth"]
        grouped = layer.groupby(group_cols)
        for (color, edgecolor, linewidth), group in grouped:
            group.plot(
                ax=ax,
                color=color,
                edgecolor=edgecolor,
                linewidth=linewidth
            )

        # If shownames is enabled, plot the names
        if "shownames" in layer.columns and layer["shownames"].any():
            name_col = "name_id" if "name_id" in layer.columns else "name"

            for idx, row in layer.iterrows():
                if pd.notnull(row.get(name_col)) and pd.notnull(row.geometry):
                    x, y = row.geometry.centroid.coords[0]
                    ax.text(x, y, str(row[name_col]), ha="center", va="center", fontsize=20, color="black")

    ax.set_aspect('equal', adjustable='datalim')  # Ensure square aspect ratio
    ax.set_axis_off()
    return fig

def combine_figures(fig1, fig2):
    # Save both figures to image buffers
    buf1 = BytesIO()
    buf2 = BytesIO()
    fig1.savefig(buf1, format='png', bbox_inches='tight')
    fig2.savefig(buf2, format='png', bbox_inches='tight')
    buf1.seek(0)
    buf2.seek(0)

    # Read them back as images
    img1 = imread(buf1)
    img2 = imread(buf2)

    # Create a new figure with two subplots
    fig, axes = plt.subplots(1, 2, figsize=(20, 10))
    axes[0].imshow(img1)
    axes[1].imshow(img2)

    # Hide axes
    for ax in axes:
        ax.axis('off')

    plt.tight_layout()
    return fig

def save_plot_to_html(fig, html_path, title, description, append=False):
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", bbox_inches="tight")
    buffer.seek(0)
    img_base64 = base64.b64encode(buffer.read()).decode("utf-8")
    plt.close(fig)

    html_content = f"""
    <div style="text-align:center; font-family:sans-serif; margin-top:2em;">
        <h2>{title}</h2>
        <p>{description}</p>
        <img src="data:image/png;base64,{img_base64}" />
    </div>
    """

    write_mode = "a" if append and os.path.exists(html_path) else "w"
    with open(html_path, write_mode, encoding="utf-8") as f:
        f.write(html_content)

    print(f"Plot {'appended to' if append else 'saved to'} {html_path}")

def read_economic_csv_input(adm_level: Union[Literal['District'], Literal['Region']], input_csv_path: str, verbose = False, sep=";"):
    """
    Reads in and standardizes csv file with economic data for data harmonization from path passed in input_csv_path.
    """
    if adm_level not in ['District', 'Region', 'City']:
        raise ValueError(f"Argument adm_level must be 'District', 'Region' or 'City'. Passsed: {adm_level}.")
    if verbose:
        print(f"Attempting to read: {input_csv_path}")
    
    if not os.path.exists(input_csv_path):
        print(f"File does not exist: {input_csv_path}")
        raise ValueError(f"File {input_csv_path} not found.")

    encodings_to_try = ['utf-8', 'cp1250', 'latin1']
    encoding = None
    df = None

    for enc in encodings_to_try:
        try:
            df = pd.read_csv(
                input_csv_path,
                sep=sep,
                encoding=enc,
                dtype=str,
                on_bad_lines='warn'
            )

            # Strip whitespace and replace "X" and "-" with NaN
            df = df.applymap(lambda x: x.strip() if isinstance(x, str) else x)
            df.replace(to_replace=["X", "-"], value=np.nan, inplace=True)
            encoding = enc
            break  # success
        except UnicodeDecodeError:
            if verbose:
                print(...)
            continue
        except pd.errors.ParserError as e:
            if verbose:
                print(...)
            continue
        except Exception as e:
            if verbose:
                print(...)
            continue


    if df is None:
        raise ValueError(f"Failed to read CSV with tried encodings: {encodings_to_try}")
    
    if verbose:
        print(f"Successfully read CSV using encoding: {encoding}")

    # Check for parse failure: all content lumped into one column
    if len(df.columns) == 1 and ';' in df.columns[0]:
        raise ValueError(f"CSV appears not to be parsed correctly. First column: {df.columns[0]}")
       
    # Try to identify the district column
    if adm_level not in df.columns:
        raise ValueError(
            f"The input file '{input_csv_path}' must contain a {adm_level} column. "
            f"Columns found: {df.columns.tolist()}"
        )

    # Define the 'District' column as index
    df.set_index(adm_level, inplace=True)

    # Check for non-unique indices and raise error if found
    if not df.index.is_unique:
        duplicated_indices = df.index[df.index.duplicated(keep=False)].unique()
        raise ValueError(
            f"Input data contains non-unique district indices: {list(duplicated_indices)}. "
            "Please ensure all districts are uniquely named in the input CSV."
            )
    
    if df is None:
            return

    # Standardize the columns format for conversion ---
    for col in df.columns:
        # Remove spaces and non-breaking spaces (e.g., '15 500' → '15500')
        df[col] = df[col].astype(str).str.replace('\xa0', '', regex=False)  # non-breaking space
        df[col] = df[col].astype(str).str.replace(' ', '', regex=False)     # regular space
        df[col] = df[col].astype(str).str.replace(',', '.', regex=False)    # optional: comma to dot
        try:
            df[col] = df[col].astype(float)
        except ValueError:
            continue  # If still not convertible, skip

    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    if not numeric_cols:
        raise ValueError(f"No numeric columns found to harmonize in file '{input_csv_path}'.")
    else:
        df_numeric = df[numeric_cols]
    
    return df_numeric

