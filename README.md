# border_harmonization_toolkit
## Aims
This toolkit has three main aims:
1. The reconstruction of a data model of the district-level administrative history;
2. The standardization of statistic district-level datasets (unification of district and region/voivodeship names and the dataset's aligment with one of the chosen administrative states in the data model of the administrative history);
3. Automatic generation of concordance matrices and harmonization of input datasets to a chosen administrative state.

## Inputs

This toolkit takes different inputs at each of the levels above. They are described by appropriate pydantic data models (PDM) for input data validation purposes:

1. Administrative history data model reconstruction - inputs:

    a. `initial_dist_state_list.json` file (list of districts existent in the beginning of the administrative history). The data model of a district dict is defined in the `data_models.adm_unit.District` PDM.  
    b. `initial_region_state_list.json` file (list of regions existent in the beginning of the administrative history). The data model of a region dict is defined in the `data_models.adm_unit.Region` PDM.  
    c. `initial_adm_state.json` file (administrative hierarchy: country -> region -> district). The data model of an administrative state is defined in the `data_models.adm_state.AdministrativeState` PDM.  
    d. `changes_list.json` file (list of administrative changes). Each change is a part of legal act coded into a machine-readable format and quotes its legal source. The data models of administrative changes are defined in the `data_models.adm_change` file.  
    e. Maps representing administrative divisions on the district level in ESRI shapefile or GeoJSON format (stored in the folder with a path defined in the config JSON `"territories_path"` entry — in the present version of the toolkit it is the `input/territories` folder). Every district map should contain columns `"District"` with district names, `"ter_date"` (in format DD.MM.YY) with the date for which the district's territory is valid, and `geometry` with the geometry of the district.

    On the basis of these inputs, the toolkit is able to reconstruct the full administrative history of a country (or group of countries) on the Country → Region → District level and generate maps for every administrative state. It can generate the concordance matrices to harmonize data between any two chosen administrative states. If the inputs are too scarce (e.g. many administrative changes occurred and only 3 maps were loaded) and the toolkit is unable to deduce shapes of some districts, it uses fallback territories of the districts from other timepoints or other fallback methods to generate the harmonization matrices.

2. Standardization of district-level datasets - inputs:

    a. CSV with the columns `"District"` and/or `"Region"` with economic/social data. The Streamlit app provides a GUI for the easy standardization of data to align the District and/or Region naming conventions and choose the administrative state that the dataset fits. A standardized dataset can be directly used as an input for the harmonization step.

3. Harmonization of datasets - inputs:

    a. `data_tables_metadata.json` (list of metadata dicts — one dict for each CSV to harmonize). The data model of a datadict is defined in the `data_models.econ_data_metadata.DataTableMetadata`.  
    b. `harmonization_config.json` (in the current version, holding only a list of post-processing methods to apply). The PDMs for the harmonization config and each post-processing method dict are defined in the `data_models.harmonization_config` module.
   
## Data Model of Administrative History
The administrative history of each country can be analyzed through looking at the:
1. administrative units and their existence through time;
2. administrative hierarchy and its changes through time.
This is why in the toolkit the basic element of analysis is the UnitState PDM (and its children DistrictState and RegionState PDMs). Unit PDM (District or Region PDM) represents an administrative unit and contains a list of UnitState instances (District instance contains a list of DistrictState instances, Region instance contains a list of RegionState instances). AdministrativeState PDM contains a "country_name->region_name->district_name" hierarchy of Unit names.

AdministrativeHistory class defined in the core.core module is the core component holding the whole information on the administrative history. An instance of the class is created with an initial administrative state (i.e. initial country -> region -> district hierarchy) (loaded from initial_adm_state.json), initial district registry (from initial_dist_state_list.json), and initial region registry (from initial_region_state_list.json). Then, all the administrative changes (from changes_list.json) are sequentially applied, changing the district and region registries and adding new administrative states to the list, until the whole administrative history is created.

There are four types of administrative changes PDMs defined in the data_models.adm_change module:
1. UnitReform: creates a new UnitState with some UnitState attributes different than the previous one.
2. OneToMany: transfers some territory from one District to at least one District. It creates a new AdministrativeState (even if the hierarchy between regions and districts doesn't change). It can abolish the District from which the territory is taken (i.e. end the timespan of the DistrictState of the district) or create a new district to which the territory is transfered (i.e. add a new District to the DistrictRegistry with a new DistrictState, and add the district to the AdministrativeState). OneToMany change attributes do not "define" the exact way in which the territory is transfered - the only effect on the knowledge about the territories is that during the stage of reconstruction of maps for each administrative state the AdministrativeHistory object "knows" that a transfer between the territories occured and that the exact form of the transfered has to be deduced from the maps.
3. ManyToOne: transfers some territory from at least one District to one District. It can create or delete districts and has an effect on DistrictRegistry and creates a new AdministrativeState instance as OneToMany change.
4. ChangeAdmState: Changes the "address" of one unit in the unit hierarchy, i.e. moves one region from one country to another or one district from one region to another.

After the whole administrative history was created, the AdministrativeHistory instance can be used to define the territory for each DistrictState through the application of AdministrativeHistory._deduce_territories() method and add fallback territories where territories are not deducible through the AdministrativeHistory._populate_territories_fallback() method.

