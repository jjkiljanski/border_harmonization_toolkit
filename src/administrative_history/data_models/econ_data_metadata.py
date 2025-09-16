from pydantic import BaseModel, model_validator
from typing import Union, Optional, Literal, List, Dict, Any
from datetime import datetime

class ColumnMetadata(BaseModel):
    unit: str
    subcategory: str
    subsubcategory: Optional[str] = "Together"
    data_type: str
    completeness: Optional[float] = None
    n_na: Optional[int] = None
    n_not_na: Optional[int] = None
    completeness_after_imputation: Optional[float] = None
    n_na_after_imputation: Optional[int] = None
    n_not_na_after_imputation: Optional[int] = None
class DataTableMetadata(BaseModel):
    """
    Metadata model for describing a data table, including source and reference 
    information, administrative levels, description in multiple languages, 
    date validity, and methods for harmonization/imputation.
    """

    data_table_id: str
    adm_level: Union[Literal['District'], Literal['Region'], Literal['City']]
    category: str

    # Source and link can be single strings or lists of strings
    source: Optional[Union[str, List[str]]] = ""
    link: Optional[Union[str, List[str]]] = ""

    # If source/link are lists, these may also be lists of the same length
    table: Optional[Union[str, List[Optional[str]]]] = ""
    page: Optional[Union[int, str, List[Optional[Union[int, str]]]]] = None
    pdf_page: Optional[Union[int, List[Optional[int]]]] = None

    description: Dict[Union[Literal["pol"], Literal["eng"]], str]
    date: str

    orig_adm_state_date: Optional[datetime] = None  # parsed from multiple formats
    adm_state_date: Optional[datetime]

    standardization_comments: Optional[str] = ""
    harmonization_method: Optional[Literal["proportional_to_territory"]] = None
    imputation_method: Optional[Literal["take_from_closest_centroid"]] = None
    columns: Dict[str, "ColumnMetadata"] = {}

    @model_validator(mode="before")
    @classmethod
    def parse_flexible_date(cls, data: Any) -> Any:
        if isinstance(data, dict):
            adm_date = data.get("orig_adm_state_date")
            if isinstance(adm_date, str):
                for fmt in ("%d.%m.%Y", "%Y-%m-%dT%H:%M:%S"):
                    try:
                        data["orig_adm_state_date"] = datetime.strptime(adm_date, fmt)
                        if data.get("adm_state_date", None) is None:
                            data["adm_state_date"] = data["orig_adm_state_date"]
                        break
                    except ValueError:
                        continue
                else:
                    raise ValueError(
                        f"Date format must be DD.MM.YYYY or ISO 8601, got: {adm_date}"
                    )
        return data

    @model_validator(mode="after")
    def validate_sources_and_links(self) -> "DataTableMetadata":
        """
        Validate that 'source' and 'link' are either both strings or both lists of equal length. 
        If lists are used, enforce that 'table', 'page', and 'pdf_page' (if lists) also match this length.
        """
        is_source_list = isinstance(self.source, list)
        is_link_list = isinstance(self.link, list)

        # Enforce both to be lists or both to be strings
        if is_source_list != is_link_list:
            raise ValueError("Both 'source' and 'link' must be either lists or single strings.")

        if is_source_list and is_link_list:
            if len(self.source) != len(self.link):
                raise ValueError("'source' and 'link' lists must be of the same length.")

            # If table/page/pdf_page are lists, they must match length
            for field_name in ["table", "page", "pdf_page"]:
                field_value = getattr(self, field_name)
                if isinstance(field_value, list):
                    if len(field_value) != len(self.source):
                        raise ValueError(
                            f"'{field_name}' list must have the same length as 'source'/'link'."
                        )

        return self