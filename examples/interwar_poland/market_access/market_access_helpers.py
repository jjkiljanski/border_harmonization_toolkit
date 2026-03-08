from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def normalize_text(value: str) -> str:
    if value is None:
        return ""
    txt = str(value).strip().lower()
    txt = unicodedata.normalize("NFKD", txt)
    txt = "".join(ch for ch in txt if not unicodedata.combining(ch))
    txt = txt.replace("ł", "l")
    txt = re.sub(r"[^a-z0-9]+", "", txt)
    return txt


def parse_decimal_series(series: pd.Series) -> pd.Series:
    s = series.astype(str).str.replace(" ", "", regex=False).str.replace(",", ".", regex=False)
    return pd.to_numeric(s, errors="coerce")


def parse_polish_bool(series: pd.Series) -> pd.Series:
    mapper = {
        "PRAWDA": True,
        "FAŁSZ": False,
        "FALSZ": False,
        "TRUE": True,
        "FALSE": False,
    }
    return series.astype(str).str.upper().map(mapper).fillna(False)


def list_available_years(dist_dir: Path, scenario: str, years_target: list[int]) -> list[int]:
    years = []
    if scenario == "fixed14":
        pat = re.compile(r"distance_matrix_long_(\d{4})_fixed14\.csv$")
        for p in dist_dir.glob("distance_matrix_long_*_fixed14.csv"):
            m = pat.match(p.name)
            if m:
                years.append(int(m.group(1)))
    elif scenario == "baseline":
        pat_h = re.compile(r"distance_matrix_horse_km_long_(\d{4})_baseline\.csv$")
        pat_r = re.compile(r"distance_matrix_rail_km_long_(\d{4})_baseline\.csv$")
        horse_years = set()
        rail_years = set()
        for p in dist_dir.glob("distance_matrix_horse_km_long_*_baseline.csv"):
            m = pat_h.match(p.name)
            if m:
                horse_years.add(int(m.group(1)))
        for p in dist_dir.glob("distance_matrix_rail_km_long_*_baseline.csv"):
            m = pat_r.match(p.name)
            if m:
                rail_years.add(int(m.group(1)))
        years = sorted(horse_years & rail_years)
    else:
        raise ValueError(f"Unknown scenario: {scenario}")
    return sorted(y for y in years if y in years_target)


def load_distance_matrix_for_scenario(
    dist_dir: Path, year: int, scenario: str, compute_in_miles: bool = False
) -> pd.DataFrame:
    if scenario == "fixed14":
        path = dist_dir / f"distance_matrix_long_{year}_fixed14.csv"
        dm = pd.read_csv(path)
        needed = {"origin_id", "dest_id", "time_min"}
        missing = needed - set(dm.columns)
        if missing:
            raise RuntimeError(f"{path} missing columns: {sorted(missing)}")
        out = dm[["origin_id", "dest_id", "time_min"]].copy()
        out = out.rename(columns={"time_min": "distance_value"})
        out["distance_value"] = pd.to_numeric(out["distance_value"], errors="coerce")
        return out

    if scenario == "baseline":
        horse_path = dist_dir / f"distance_matrix_horse_km_long_{year}_baseline.csv"
        rail_path = dist_dir / f"distance_matrix_rail_km_long_{year}_baseline.csv"
        horse = pd.read_csv(horse_path)
        rail = pd.read_csv(rail_path)
        h_need = {"origin_id", "dest_id", "horse_km"}
        r_need = {"origin_id", "dest_id", "rail_km"}
        if h_need - set(horse.columns):
            raise RuntimeError(f"{horse_path} missing columns: {sorted(h_need - set(horse.columns))}")
        if r_need - set(rail.columns):
            raise RuntimeError(f"{rail_path} missing columns: {sorted(r_need - set(rail.columns))}")
        keys = ["origin_id", "dest_id"]
        merged = horse[keys + ["horse_km"]].merge(rail[keys + ["rail_km"]], on=keys, how="inner")
        merged["horse_km"] = pd.to_numeric(merged["horse_km"], errors="coerce")
        merged["rail_km"] = pd.to_numeric(merged["rail_km"], errors="coerce")
        merged["distance_value"] = merged["horse_km"] + merged["rail_km"]
        if compute_in_miles:
            merged["distance_value"] = merged["distance_value"] * 0.621371
        return merged[["origin_id", "dest_id", "distance_value"]].copy()

    raise ValueError(f"Unknown scenario: {scenario}")


def load_partition_coefficients(path: Path) -> dict[int, float]:
    df = pd.read_csv(path, sep=";")
    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    df["value"] = parse_decimal_series(df["value"])
    df = df.dropna(subset=["year", "value"]).copy()
    return {int(row.year): float(row.value) for row in df.itertuples(index=False)}


def load_partition_dummies(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, sep=";")
    needed = {
        "District",
        "former_german_partition",
        "former_russian_partition",
        "former_ah_partition",
    }
    missing = needed - set(df.columns)
    if missing:
        raise RuntimeError(f"partition_dummies missing columns: {sorted(missing)}")
    df = df.copy()
    df["former_german_partition"] = parse_polish_bool(df["former_german_partition"])
    df["former_russian_partition"] = parse_polish_bool(df["former_russian_partition"])
    df["former_ah_partition"] = parse_polish_bool(df["former_ah_partition"])

    def label_partition(row: pd.Series) -> str:
        if row["former_german_partition"]:
            return "GERMAN"
        if row["former_russian_partition"]:
            return "RUSSIAN"
        if row["former_ah_partition"]:
            return "AH"
        return "UNKNOWN"

    df["partition_label"] = df.apply(label_partition, axis=1)
    return df[["District", "partition_label"]].copy()


def build_population_inputs(
    districts_geojson: Path,
    city_coords_geojson: Path,
    city_pop_csv: Path,
    rural_pop_csv: Path,
    years_target: list[int],
) -> tuple[gpd.GeoDataFrame, list[str], pd.DataFrame, pd.DataFrame]:
    districts = gpd.read_file(districts_geojson)
    if "District" not in districts.columns:
        raise RuntimeError("District geojson must have 'District' column")
    districts = districts[["District", "geometry"]].copy()

    city_coords = gpd.read_file(city_coords_geojson)
    if "City" not in city_coords.columns:
        raise RuntimeError("City coords geojson must have 'City' column")

    city_sjoin = gpd.sjoin(
        city_coords[["City", "geometry"]],
        districts[["District", "geometry"]],
        how="inner",
        predicate="within",
    )
    city_to_district = city_sjoin[["City", "District"]].drop_duplicates().copy()

    city_raw = pd.read_csv(city_pop_csv, sep=";")
    city_raw["City"] = city_raw["City"].astype(str)
    city = city_raw.merge(city_to_district, on="City", how="inner")

    city["1921"] = pd.to_numeric(city["1921"], errors="coerce")
    city["1931"] = pd.to_numeric(city["1931"], errors="coerce")
    city["1939"] = pd.to_numeric(city["1939"], errors="coerce")

    for year in years_target:
        y = str(year)
        if year <= 1931:
            city[y] = city["1921"] + (city["1931"] - city["1921"]) * ((year - 1921) / (1931 - 1921))
        else:
            city[y] = city["1931"] + (city["1939"] - city["1931"]) * ((year - 1931) / (1939 - 1931))
    city_keep = city[["City", "District"] + [str(y) for y in years_target]].copy()

    rural = pd.read_csv(rural_pop_csv, sep=";")
    for year in years_target:
        col = str(year)
        if col not in rural.columns:
            raise RuntimeError(f"rural_population.csv missing year column {col}")
        rural[col] = pd.to_numeric(rural[col], errors="coerce")
    rural_keep = rural[["District"] + [str(y) for y in years_target]].copy()

    district_list = sorted(set(districts["District"]))
    return districts, district_list, city_keep, rural_keep


def build_point_population(
    year: int, city_keep: pd.DataFrame, rural_keep: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    y = str(year)
    d = rural_keep[["District", y]].copy()
    d["point_id"] = "District:" + d["District"].astype(str)
    d["pop"] = pd.to_numeric(d[y], errors="coerce").fillna(0.0)

    c = city_keep[["City", "District", y]].copy()
    c["point_id"] = "City:" + c["City"].astype(str)
    c["pop"] = pd.to_numeric(c[y], errors="coerce").fillna(0.0)

    points = pd.concat(
        [d[["point_id", "District", "pop"]], c[["point_id", "District", "pop"]]],
        ignore_index=True,
    )

    pop_total = d[["District", "pop"]].rename(columns={"pop": "rural_pop"})
    city_by_dist = c.groupby("District", as_index=False)["pop"].sum().rename(columns={"pop": "city_pop_sum"})
    pop_total = pop_total.merge(city_by_dist, on="District", how="left")
    pop_total["city_pop_sum"] = pop_total["city_pop_sum"].fillna(0.0)
    pop_total["mass"] = pop_total["rural_pop"] + pop_total["city_pop_sum"]
    return points, pop_total[["District", "mass"]].copy()


def build_border_connections(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, sep=";")
    needed = {"border_crossing", "where_to", "country_or_province", "length_km"}
    missing = needed - set(df.columns)
    if missing:
        raise RuntimeError(f"border_crossing_IIRP_connections missing columns: {sorted(missing)}")
    df = df.copy()
    df["length_km"] = pd.to_numeric(df["length_km"], errors="coerce")
    df["border_crossing_norm"] = df["border_crossing"].map(normalize_text)
    return df


def build_foreign_gdp_long(path: Path, years_target: list[int]) -> pd.DataFrame:
    g = pd.read_csv(path, sep=";")
    if "Foreign region" not in g.columns:
        raise RuntimeError("foreign_region_gdp.csv missing 'Foreign region' column")
    year_cols = [c for c in g.columns if c.isdigit() and int(c) in years_target]
    if not year_cols:
        raise RuntimeError("foreign_region_gdp.csv has no target year columns")
    gg = g.melt(id_vars=["Foreign region"], value_vars=year_cols, var_name="year", value_name="gdp")
    gg["year"] = pd.to_numeric(gg["year"], errors="coerce").astype("Int64")
    gg["gdp"] = parse_decimal_series(gg["gdp"])
    gg = gg.dropna(subset=["year", "gdp"]).copy()
    gg["year"] = gg["year"].astype(int)
    gg = gg.groupby(["Foreign region", "year"], as_index=False)["gdp"].sum()
    gg["region_norm"] = gg["Foreign region"].map(normalize_text)
    return gg


def build_district_gdp_long(path: Path, years_target: list[int]) -> pd.DataFrame:
    df = pd.read_csv(path, sep=";")
    if "District" not in df.columns:
        raise RuntimeError("district_gdp.csv missing 'District' column")
    year_cols = [c for c in df.columns if c.isdigit() and int(c) in years_target]
    if not year_cols:
        raise RuntimeError("district_gdp.csv has no target year columns")

    out = df.melt(id_vars=["District"], value_vars=year_cols, var_name="year", value_name="district_gdp")
    out["year"] = pd.to_numeric(out["year"], errors="coerce").astype("Int64")
    out["district_gdp"] = parse_decimal_series(out["district_gdp"])
    out = out.dropna(subset=["year", "district_gdp"]).copy()
    out["year"] = out["year"].astype(int)
    return out[["District", "year", "district_gdp"]].copy()


def border_id_norm(border_id: str) -> str:
    return normalize_text(str(border_id).replace("Border_Crossing:", ""))


def match_border_connections_to_matrix_borders(
    district_to_border: pd.DataFrame,
    border_connections: pd.DataFrame,
) -> pd.DataFrame:
    """
    Match rows from border_connections to border IDs available in district_to_border.

    Matching strategy:
    1) exact normalized name match,
    2) containment heuristic (e.g. 'zbaszyn' -> 'zbaszynzbaszynek'),
    3) Gdansk route fallback: map to any of Kozliny/Kolibki/Sulmin if present.
    """
    if district_to_border.empty or border_connections.empty:
        return pd.DataFrame(
            columns=[
                "border_crossing",
                "where_to",
                "country_or_province",
                "length_km",
                "border_crossing_norm",
                "matched_border_norm",
            ]
        )

    avail = (
        district_to_border["dest_id"]
        .dropna()
        .astype(str)
        .loc[lambda s: s.str.startswith("Border_Crossing:")]
        .map(border_id_norm)
        .dropna()
        .unique()
        .tolist()
    )
    avail_set = set(avail)

    conn = border_connections.copy()
    conn["border_crossing_norm"] = conn["border_crossing"].map(normalize_text)
    conn["where_to_norm"] = conn["where_to"].map(normalize_text)

    rows = []
    gdansk_gate = {"kozliny", "kolibki", "sulmin"}

    for r in conn.itertuples(index=False):
        bc_norm = r.border_crossing_norm
        matches: list[str] = []

        # 1) Exact match.
        if bc_norm in avail_set:
            matches = [bc_norm]
        else:
            # 2) Containment heuristic.
            heur = [a for a in avail if (bc_norm and (bc_norm in a or a in bc_norm))]
            if heur:
                # Keep deterministic order.
                matches = sorted(set(heur), key=lambda x: (len(x), x))
            # 3) Gdansk gate fallback.
            elif r.where_to_norm == "gdansk":
                matches = sorted(list(gdansk_gate & avail_set))

        for m in matches:
            rows.append(
                {
                    "border_crossing": r.border_crossing,
                    "where_to": r.where_to,
                    "country_or_province": r.country_or_province,
                    "length_km": r.length_km,
                    "border_crossing_norm": bc_norm,
                    "matched_border_norm": m,
                }
            )

    if not rows:
        return pd.DataFrame(
            columns=[
                "border_crossing",
                "where_to",
                "country_or_province",
                "length_km",
                "border_crossing_norm",
                "matched_border_norm",
            ]
        )
    return pd.DataFrame(rows)


def robust_bounds(values: pd.Series, qmin: float = 0.02, qmax: float = 0.98) -> tuple[float, float]:
    v = pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if len(v) == 0:
        return (0.0, 1.0)
    lo = float(v.quantile(qmin))
    hi = float(v.quantile(qmax))
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        lo = float(v.min())
        hi = float(v.max())
        if hi <= lo:
            hi = lo + 1.0
    return (lo, hi)


def save_tables(df: pd.DataFrame, out_dir: Path, scenario: str) -> None:
    d = df[df["scenario"] == scenario].copy()
    if d.empty:
        print(f"No data for scenario {scenario}, skipping exports.")
        return
    d = d.sort_values(["year", "District"]).copy()
    scenario_dir = out_dir / scenario
    scenario_dir.mkdir(parents=True, exist_ok=True)
    csv_path = scenario_dir / f"market_access_annual_{scenario}.csv"
    d.to_csv(csv_path, index=False)
    print("Wrote:", csv_path)
    xlsx_path = scenario_dir / f"market_access_annual_{scenario}.xlsx"
    try:
        with pd.ExcelWriter(xlsx_path) as writer:
            d.to_excel(writer, index=False, sheet_name="annual_ma")
            d_within = d[["District", "year", "scenario", "ma_domestic"]].rename(
                columns={"ma_domestic": "ma_within_country"}
            )
            d_foreign = d[["District", "year", "scenario", "ma_foreign"]].rename(
                columns={"ma_foreign": "ma_foreign_only"}
            )
            d_within.to_excel(writer, index=False, sheet_name="within_country_only")
            d_foreign.to_excel(writer, index=False, sheet_name="foreign_only")
        print("Wrote:", xlsx_path)
    except Exception as exc:
        print(f"Could not write xlsx for {scenario}: {exc}")


def save_annual_maps(
    df: pd.DataFrame,
    scenario: str,
    value_col: str,
    cmap: str,
    plots_dir: Path,
    adm_history_plotter,
    adm_state_date,
    custom_grouping
) -> None:
    d = df[df["scenario"] == scenario].copy()
    if d.empty:
        return
    scenario_dir = plots_dir / scenario / value_col
    scenario_dir.mkdir(parents=True, exist_ok=True)
    vmin, vmax = robust_bounds(d[value_col])
    for year in sorted(d["year"].unique()):
        cur = d[d["year"] == year][["District", value_col]].copy().set_index("District")
        save_to = scenario_dir / f"{value_col}_{scenario}_{year}.png"
        fig = adm_history_plotter.plot_dataset(
            df=cur,
            col_name=value_col,
            adm_level="District",
            adm_state_date=adm_state_date,
            title=f"{value_col} | {scenario} | {year}",
            save_to_path=str(save_to),
            legend_min=vmin,
            legend_max=vmax,
            cmap=cmap,
            custom_grouping=custom_grouping
        )
        plt.close(fig)


def save_change_map_1938_vs_1924(
    df: pd.DataFrame,
    scenario: str,
    value_col: str,
    cmap: str,
    plots_dir: Path,
    adm_history_plotter,
    adm_state_date,
    custom_grouping
) -> None:
    d = df[df["scenario"] == scenario].copy()
    years = set(d["year"].unique())
    if 1924 not in years or 1938 not in years:
        print(f"Scenario {scenario}: cannot build 1938 vs 1924 for {value_col} (missing year).")
        return
    a = d[d["year"] == 1924][["District", value_col]].rename(columns={value_col: "v1924"})
    b = d[d["year"] == 1938][["District", value_col]].rename(columns={value_col: "v1938"})
    m = a.merge(b, on="District", how="inner")
    m["change_1938_vs_1924"] = m["v1938"] - m["v1924"]
    out_dir = plots_dir / scenario / f"{value_col}_change"
    out_dir.mkdir(parents=True, exist_ok=True)
    vm = pd.to_numeric(m["change_1938_vs_1924"], errors="coerce")
    q = float(np.nanquantile(np.abs(vm), 0.98)) if vm.notna().any() else 1.0
    if not np.isfinite(q) or q <= 0:
        q = 1.0
    fig = adm_history_plotter.plot_dataset(
        df=m[["District", "change_1938_vs_1924"]].set_index("District"),
        col_name="change_1938_vs_1924",
        adm_level="District",
        adm_state_date=adm_state_date,
        title=f"{value_col} change 1938 vs 1924 | {scenario}",
        save_to_path=str(out_dir / f"{value_col}_change_1938_vs_1924_{scenario}.png"),
        legend_min=-q,
        legend_max=q,
        cmap=cmap,
        custom_grouping=custom_grouping
    )
    plt.close(fig)


def collect_target_pair_distances(
    ma_all: pd.DataFrame,
    district_distances_all: pd.DataFrame,
    compute_in_miles: bool,
    target_distance_pairs: list[tuple[str, str]],
) -> pd.DataFrame:
    """
    Compute diagnostic district-to-district distances for selected origin/destination pairs
    from already-computed district distance matrices.

    Notes:
    - No matrix reload / recomputation is performed here.
    - `ma_all` is used to define the scenario-year scope to report.
    """
    if ma_all.empty or district_distances_all.empty:
        return pd.DataFrame(
            columns=[
                "scenario",
                "year",
                "origin_district",
                "dest_district",
                "distance_value",
                "distance_km",
                "distance_miles",
                "distance_minutes",
            ]
        )

    rows = []
    scope = ma_all[["scenario", "year"]].drop_duplicates().sort_values(["scenario", "year"])
    for row in scope.itertuples(index=False):
        scenario = row.scenario
        year = int(row.year)
        dd = district_distances_all[
            (district_distances_all["scenario"] == scenario)
            & (district_distances_all["year"] == year)
        ]
        if dd.empty:
            continue
        for origin_district, dest_district in target_distance_pairs:
            hit = dd[
                (dd["origin_district"] == origin_district)
                & (dd["dest_district"] == dest_district)
            ]
            val = float(hit["distance_value"].iloc[0]) if not hit.empty else np.nan
            if scenario == "fixed14":
                d_km = np.nan
                d_miles = np.nan
                d_minutes = val
            else:
                if np.isnan(val):
                    d_km = np.nan
                    d_miles = np.nan
                elif compute_in_miles:
                    d_miles = val
                    d_km = val / 0.621371
                else:
                    d_km = val
                    d_miles = val * 0.621371
                d_minutes = np.nan
            rows.append(
                {
                    "scenario": scenario,
                    "year": year,
                    "origin_district": origin_district,
                    "dest_district": dest_district,
                    "distance_value": val,
                    "distance_km": d_km,
                    "distance_miles": d_miles,
                    "distance_minutes": d_minutes,
                }
            )

    return pd.DataFrame(rows)


def collect_foreign_city_route_distances(
    ma_all: pd.DataFrame,
    district_to_border_all: pd.DataFrame,
    border_connections: pd.DataFrame,
    origin_district: str,
    foreign_cities: list[str],
    compute_in_miles: bool,
) -> pd.DataFrame:
    """
    Build a diagnostic table for routes:
    origin district -> relevant border crossing -> selected foreign city.

    Uses already-computed district_to_border distances (no recomputation).
    For km/miles output:
    - baseline: district->border is interpreted as km/miles (depending on compute_in_miles)
      and converted to both units.
    - fixed14: district->border is time (minutes), so km/miles are not reported.
    """
    out_cols = [
        "scenario",
        "year",
        "origin_district",
        "foreign_city",
        "border_crossing",
        "district_to_border_km",
        "district_to_border_miles",
        "border_to_city_km",
        "border_to_city_miles",
        "total_km",
        "total_miles",
    ]

    if ma_all.empty or district_to_border_all.empty:
        return pd.DataFrame(columns=out_cols)

    conn = border_connections.copy()
    conn["where_to_norm"] = conn["where_to"].map(normalize_text)
    conn_city = conn[conn["where_to_norm"].isin([normalize_text(c) for c in foreign_cities])].copy()

    if conn_city.empty:
        return pd.DataFrame(columns=out_cols)

    scope = ma_all[["scenario", "year"]].drop_duplicates().sort_values(["scenario", "year"])
    rows = []

    for row in scope.itertuples(index=False):
        scenario = row.scenario
        year = int(row.year)

        dd = district_to_border_all[
            (district_to_border_all["scenario"] == scenario)
            & (district_to_border_all["year"] == year)
            & (district_to_border_all["origin_district"] == origin_district)
        ].copy()
        if dd.empty:
            continue

        dd["border_norm"] = dd["dest_id"].map(border_id_norm)
        conn_match = match_border_connections_to_matrix_borders(dd, conn_city)
        if conn_match.empty:
            continue
        merged = dd.merge(conn_match, left_on="border_norm", right_on="matched_border_norm", how="inner")
        if merged.empty:
            continue

        # Compute comparable route metric for selecting one "relevant" crossing
        # per foreign city (shortest route).
        if scenario == "baseline":
            if compute_in_miles:
                d_border_miles_sel = pd.to_numeric(merged["distance_to_border"], errors="coerce")
                d_border_km_sel = d_border_miles_sel / 0.621371
            else:
                d_border_km_sel = pd.to_numeric(merged["distance_to_border"], errors="coerce")
                d_border_miles_sel = d_border_km_sel * 0.621371
            connector_km_sel = pd.to_numeric(merged["length_km"], errors="coerce")
            merged["route_selector"] = d_border_km_sel + connector_km_sel
        else:
            # fixed14: distance_to_border is minutes, connector is in km.
            # Convert connector to minutes with fixed14 speed so we can pick shortest route.
            d_border_min_sel = pd.to_numeric(merged["distance_to_border"], errors="coerce")
            connector_km_sel = pd.to_numeric(merged["length_km"], errors="coerce")
            merged["route_selector"] = d_border_min_sel + connector_km_sel * (60.0 / 14.0)

        # Keep one relevant crossing (minimum route) per foreign city.
        merged = (
            merged.sort_values(["where_to", "route_selector"])
            .groupby(["where_to"], as_index=False, sort=False)
            .head(1)
            .copy()
        )

        for r in merged.itertuples(index=False):
            if scenario == "baseline":
                if compute_in_miles:
                    d_border_miles = float(r.distance_to_border)
                    d_border_km = d_border_miles / 0.621371
                else:
                    d_border_km = float(r.distance_to_border)
                    d_border_miles = d_border_km * 0.621371

                border_to_city_km = float(r.length_km)
                border_to_city_miles = border_to_city_km * 0.621371
                total_km = d_border_km + border_to_city_km
                total_miles = d_border_miles + border_to_city_miles
            else:
                # fixed14 stores minutes, so km/miles decomposition is not available.
                d_border_km = np.nan
                d_border_miles = np.nan
                border_to_city_km = float(r.length_km)
                border_to_city_miles = border_to_city_km * 0.621371
                total_km = np.nan
                total_miles = np.nan

            rows.append(
                {
                    "scenario": scenario,
                    "year": year,
                    "origin_district": origin_district,
                    "foreign_city": r.where_to,
                    "border_crossing": r.border_crossing,
                    "district_to_border_km": d_border_km,
                    "district_to_border_miles": d_border_miles,
                    "border_to_city_km": border_to_city_km,
                    "border_to_city_miles": border_to_city_miles,
                    "total_km": total_km,
                    "total_miles": total_miles,
                }
            )

    if not rows:
        return pd.DataFrame(columns=out_cols)
    return pd.DataFrame(rows, columns=out_cols)
