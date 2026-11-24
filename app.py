"""
Main entrypoint for the multi-page Streamlit Bulk Geochemical Analysis app.
Handles workbook upload, column remapping, pre-levelling negative/NaN cleaning,
optional seasonal levelling (OFF by default with prominent banner), global filters,
and page navigation.
"""

import os
import pandas as pd
import streamlit as st

from color_standards import get_element_color_map, get_group_color_map
from geochem_core import (
    DEFAULT_SHEET,
    REF_GROUP_ORDER,
    SEASON_FILTER,
    apply_seasonal_levelling,
    classify_reference_samples,
    clean_negatives_and_nans,
    load_excel_sheet,
    remap_geochem_columns,
)

st.set_page_config(
    page_title="Bulk Geochemical Analysis",
    page_icon="🧪",
    layout="wide",
)

with st.sidebar:
    st.header("1. Workbook & Sheet")
    uploaded_file = st.file_uploader(
        "Drag and drop an .xlsx file here",
        type=["xlsx"],
        help="Defaults to sheet 'ms'. Uses local fallback only if no file is uploaded.",
    )
    sheet_choice = st.selectbox(
        "Worksheet name",
        options=["ms", "oes"],
        index=0,  # Default is 'ms'
    )

    st.divider()
    st.header("2. Data Cleaning (Pre-Levelling)")
    nan_strategy = st.selectbox(
        "Missing value (NaN) handling before levelling",
        options=["Keep as NaN", "Fill with column median", "Fill with 0"],
        index=0,
    )

    st.divider()
    st.header("3. Seasonal Levelling")
    # Explicitly OFF by default
    enable_levelling = st.toggle(
        "Enable Seasonal Levelling",
        value=True,
        help="Off by default. Runs after negative/NaN cleaning when enabled.",
    )
    levelling_method = st.selectbox(
        "Levelling method",
        options=["MedianShift", "ZRobust", "ZScore"],
        index=1,
        disabled=not enable_levelling,
    )

# local_fallback_path = os.path.join(DEFAULT_ROOT, DEFAULT_FOLDER, DEFAULT_FILE)
file_bytes = uploaded_file.getvalue() if uploaded_file is not None else None

if file_bytes is None:# and not os.path.exists(local_fallback_path):
    st.title("🧪 Bulk Geochemical Data Explorer")
    st.info(
        "Please drag and drop an `.xlsx` file in the sidebar to begin "

    )
    st.stop()

df_raw = load_excel_sheet(
    file_bytes=file_bytes,
    sheet_name=sheet_choice,
)

df_mapped, col_meta = remap_geochem_columns(df_raw, sheet_choice)
df_mapped = classify_reference_samples(df_mapped)

available_roles = sorted({
    role
    for roles in col_meta["element_unit_map"].values()
    for role in roles.keys()
    if role != "mult_req"
})
default_role = "ppb_2" if col_meta["sheet_key"] == "ms" else "ppm_2"
default_idx = available_roles.index(default_role) if default_role in available_roles else 0

season_options = (
    [s for s in SEASON_FILTER if s in set(df_mapped["Season"].dropna())]
    if "Season" in df_mapped.columns
    else []
)
if not season_options and "Season" in df_mapped.columns:
    season_options = list(df_mapped["Season"].dropna().unique())

with st.sidebar:
    selected_role = st.selectbox(
        "Unit column role for element analysis",
        options=available_roles,
        index=default_idx,
    )
    ref_season = st.selectbox(
        "Reference season for levelling",
        options=season_options if season_options else ["N/A"],
        index=0,
        disabled=(not enable_levelling) or (not season_options),
    )

    st.divider()
    st.header("4. Grouping & Sample Filters")
    group_by_feature = st.radio(
        "Standard color & grouping feature",
        options=["Transect", "Distance (m)"],
        index=0,
    )

    selected_seasons = st.multiselect(
        "Filter by Season",
        options=season_options,
        default=season_options,
    )

    transect_vals = (
        sorted(df_mapped["Transect"].dropna().unique(), key=str)
        if "Transect" in df_mapped.columns
        else []
    )
    selected_transects = st.multiselect(
        "Filter by Transect",
        options=transect_vals,
        default=transect_vals,
    )

    if "Distance (m)" in df_mapped.columns and df_mapped["Distance (m)"].notna().any():
        dist_vals = sorted(df_mapped["Distance (m)"].dropna().unique())
        selected_distances = st.multiselect(
            "Filter by Distance (m)",
            options=dist_vals,
            default=dist_vals,
        )
    else:
        selected_distances = []

    ref_vals = [r for r in REF_GROUP_ORDER if r in set(df_mapped["Ref_Group"].dropna())]
    selected_ref_groups = st.multiselect(
        "Filter by Reference Type (REF-1..3 vs REF-4..5)",
        options=ref_vals,
        default=ref_vals,
    )

active_element_cols = [
    col_meta["element_unit_map"][el][selected_role]
    for el in col_meta["elements"]
    if selected_role in col_meta["element_unit_map"][el]
]

# Step A: Always clean negatives & NaNs BEFORE levelling
numeric_clean_targets = list(
    dict.fromkeys(
        active_element_cols
        + [
            c
            for c in [
                "Change in mass (mg)",
                "(mg/dm2/day)",
                "Geochem quarter weight (g)",
                "Days in Field",
                "Distance (m)",
            ]
            if c in df_mapped.columns
        ]
    )
)
df_cleaned, neg_replacement_log = clean_negatives_and_nans(
    df_mapped,
    target_cols=numeric_clean_targets,
    nan_strategy=nan_strategy,
)

# Step B: Apply seasonal levelling only when toggled ON
if enable_levelling:
    df_processed = apply_seasonal_levelling(
        df_cleaned,
        target_cols=active_element_cols,
        method=levelling_method,
        reference_season=ref_season,
    )
else:
    df_processed = df_cleaned.copy()

# Apply sample filters
df_filtered = df_processed.copy()


if "Season" in df_filtered.columns and selected_seasons:
    df_filtered = df_filtered[df_filtered["Season"].isin(selected_seasons)]
if "Transect" in df_filtered.columns and selected_transects:
    df_filtered = df_filtered[df_filtered["Transect"].isin(selected_transects)]
if "Distance (m)" in df_filtered.columns and selected_distances:
    df_filtered = df_filtered[df_filtered["Distance (m)"].isin(selected_distances)]
if "Ref_Group" in df_filtered.columns and selected_ref_groups:
    df_filtered = df_filtered[df_filtered["Ref_Group"].isin(selected_ref_groups)]

group_series = (
    df_filtered[group_by_feature]
    if group_by_feature in df_filtered.columns
    else pd.Series([], dtype=object)
)
group_color_map = get_group_color_map(group_series, group_type=group_by_feature)
element_color_map = get_element_color_map(col_meta["elements"])

# Store shared context for all pages
st.session_state["geochem_ctx"] = {
    "sheet_choice": sheet_choice,
    "selected_role": selected_role,
    "active_element_cols": active_element_cols,
    "col_meta": col_meta,
    "df_mapped": df_mapped,
    "df_cleaned": df_cleaned,
    "df_filtered": df_filtered,
    "neg_replacement_log": neg_replacement_log,
    "enable_levelling": enable_levelling,
    "levelling_method": levelling_method,
    "ref_season": ref_season,
    "group_by_feature": group_by_feature,
    "group_color_map": group_color_map,
    "element_color_map": element_color_map,
}

# Prominent banner drawing attention to seasonal levelling state
if not enable_levelling:
    st.warning(
        "**Seasonal Levelling is currently OFF (Default).** "
        "Values shown across pages reflect pre-levelling cleaned data. "
        "Toggle **Enable Seasonal Levelling** in the sidebar to level across seasons.",
        icon="⚠️",
    )
else:
    st.info(
        f"**Seasonal Levelling is ON** — Method: **`{levelling_method}`** | "
        f"Reference Season: **`{ref_season}`** (applied after negative/NaN cleaning).",
        icon="ℹ️",
    )

pages = [
    st.Page(
        "pages/01_distributions_and_top_filters.py",
        title="1. Distributions & Top Filters",
        icon="📊",
        default=True,
    ),
    st.Page(
        "pages/02_pca_and_clustering.py",
        title="2. PCA & Clustering",
        icon="🧭",
    ),
    st.Page(
        "pages/03_correlations.py",
        title="3. Correlations",
        icon="🔗",
    ),
    st.Page(
        "pages/04_element_ratios.py",
        title="4. Element Ratios",
        icon="⚖️",
    ),
    st.Page(
        "pages/05_levelling_comparison.py",
        title="5. Levelling Comparison",
        icon="🔄",
    ),
]

nav = st.navigation(pages)
nav.run()