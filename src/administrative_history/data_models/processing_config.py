"""
This module defines the Pydantic data models for the harmonization configuration JSON.

The harmonization config JSON is loaded from the path specified in 
`config.harmonization_config_path`.  

It contains a list of post-harmonization reorganization method descriptions.  
Each method is represented by a discriminated union (`ReorganizeMethod`) of 
specific method models. These models describe how different data reorganization 
operations (e.g., summing data tables, creating datasets) should be configured.
"""

from typing import Union, List, Annotated, Literal
from pydantic import BaseModel, Field
from typing_extensions import Annotated  # redundant import kept for compatibility

from administrative_history.data_models.econ_data_metadata import DataTableMetadata


# ======================================================================
# Data Models for Specific Reorganizing Methods
# ======================================================================

# ----------------------------------------------------------------------
# CombineDataTables Method
# ----------------------------------------------------------------------
class CombineDataTablesArgs(BaseModel):
    """
    Arguments for the `data_processing.post_processing.sum_up_data_tables` function.
    
    Attributes:
        data_tables_list: List of names of the input data tables to sum up.
        new_data_table_name: Name of the newly created summed data table.
    """
    method: Literal["sum", "concatenate"]
    data_tables_list: List[str]
    new_data_table_name: str


class CombineDataTables(BaseModel):
    """
    Model for the `sum_up_data_tables` method configuration.
    
    Attributes:
        method_name: Discriminator literal, must be `"sum_up_data_tables"`.
        arguments: Arguments required by the method.
    """
    method_name: Literal["combine_data_tables"]
    arguments: CombineDataTablesArgs


# ----------------------------------------------------------------------
# CreateDistAreaDataset Method
# ----------------------------------------------------------------------
class CreateDistAreaDatasetArgs(BaseModel):
    """
    Arguments for the `data_processing.post_processing.create_dist_area_dataset` function.
    
    Attributes:
        data_table_metadata: Metadata describing the new distribution-area dataset.
    """
    data_table_metadata: DataTableMetadata


class CreateDistAreaDataset(BaseModel):
    """
    Model for the `create_dist_area_dataset` method configuration.
    
    Attributes:
        method_name: Discriminator literal, must be `"create_dist_area_dataset"`.
        arguments: Arguments required by the method.
    """
    method_name: Literal["create_dist_area_dataset"]
    arguments: CreateDistAreaDatasetArgs


# ======================================================================
# Discriminated Union of All Reorganization Methods
# ======================================================================
ReorganizeMethod = Annotated[
    Union[
        CombineDataTables,
        CreateDistAreaDataset,
        # Future methods can be added here
    ],
    Field(discriminator="method_name"),
]


# ======================================================================
# Top-Level Harmonization Config
# ======================================================================
class ProcessingConfig(BaseModel):
    """
    Top-level model for the harmonization configuration JSON.
    
    Attributes:
        post_processing_reorganize_data_tables: A list of reorganizing methods
        to apply after harmonization, represented as `ReorganizeMethod` objects.
    """
    adm_units_raw_data_metadata_path: str
    cities_raw_data_metadata_path: str
    adm_units_raw_data_folder: str
    cities_raw_data_folder: str
    processed_data_output_folder: str
    harmonization_errors_output_path: str
    post_processing_errors_output_path: str
    processed_data_metadata_output_path: str
    database_tree_output_path: str
    harmonize_to_date: str
    post_processing_config: List[ReorganizeMethod]