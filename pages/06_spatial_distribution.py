import pandas as pd
import streamlit as st

from color_standards import get_group_color_map
from geochem_core import (
    attach_oes_ppm2_divisors,
    build_ratio_dataframe,
    find_element_col,
    plot_spatial_xy_bubble_map,
)

ctx = st.session_state.get("geochem_ctx", {})
sheet_choice = str(ctx.get("sheet_choice", "ms")).strip().lower()
active_element_cols = list(ctx.get("active_element_cols", []))
df_filtered = ctx.get("df_filtered", pd.DataFrame())
default_group = ctx.get("group_by_feature", "Transect")

st.subheader("6. Spatial XY Distributions")

if df_filtered.empty or not active_element_cols:
    st.info("Upload a workbook and ensure active element columns and filtered samples are available.")
    st.stop()

if "LatDMS" not in df_filtered.columns or "LonDMS" not in df_filtered.columns:
    st.error("Coordinate columns `LatDMS` and `LonDMS` were not found in the active dataset.")
    st.stop()

# Attach OES [ppm #2] columns on `ms` so ratios can also use OES divisors
df_spatial = df_filtered.copy()
oes_ppm2_cols = []
if sheet_choice == "ms":
    oes_ref_df = ctx.get("df_oes_raw") if ctx.get("df_oes_raw") is not None else st.session_state.get("df_oes_raw")
    df_spatial, oes_ppm2_cols = attach_oes_ppm2_divisors(df_spatial, oes_ref_df)

divisor_options = list(dict.fromkeys(active_element_cols + oes_ppm2_cols))
preferred_div_symbol = "Ca" if sheet_choice == "oes" else "Li"
default_div_col = (
    find_element_col(divisor_options, preferred_div_symbol)
    or find_element_col(divisor_options, "Ca")
    or find_element_col(divisor_options, "Li")
    or divisor_options[0]
)
default_div_idx = divisor_options.index(default_div_col)

# Top controls: Mode (Concentrations vs Ratios), Color-by, Aggregation, Size scaling
c1, c2, c3, c4 = st.columns([1.2, 1.1, 1.3, 1.1])
with c1:
    metric_mode = st.radio(
        "Bubble size metric",
        options=["Element Concentrations", "Element Ratios (Element / Divisor)"],
        index=0,
        key="p6_metric_mode",
    )
with c2:
    color_options = [c for c in ["Transect", "Distance (m)"] if c in df_spatial.columns]
    default_color_idx = color_options.index(default_group) if default_group in color_options else 0
    spatial_color_by = st.selectbox(
        "Color points by",
        options=color_options if color_options else ["Transect"],
        index=default_color_idx,
        key="p6_color_by",
    )
with c3:
    agg_mode = st.selectbox(
        "Shared coordinates handling",
        options=[
            "Median per location",
            "Mean per location",
            "Max per location",
            "Raw points (no aggregation)",
        ],
        index=0,
        help="Samples with the same ID share identical coordinates across seasons.",
        key="p6_agg_mode",
    )
with c4:
    size_scale_mode = st.selectbox(
        "Bubble size scaling",
        options=["Sqrt", "Log10", "Linear"],
        index=0,
        key="p6_size_scale",
    )

o1, o2, o3, o4 = st.columns([1, 1, 1, 1])
with o1:
    p6_ncols = st.number_input("Map columns", min_value=1, max_value=4, value=2, key="p6_ncols")
with o2:
    max_bubble = st.slider("Max bubble size", min_value=16, max_value=60, value=34, key="p6_max_bubble")
with o3:
    min_bubble = st.slider("Min bubble size", min_value=3, max_value=16, value=6, key="p6_min_bubble")
with o4:
    show_station_labels = st.checkbox("Show station ID labels", value=False, key="p6_show_labels")

if metric_mode == "Element Concentrations":
    plot_cols = st.multiselect(
        "Select elements to map",
        options=active_element_cols,
        default=active_element_cols[: min(4, len(active_element_cols))],
        key=f"p6_el_cols_{sheet_choice}",
    )
    df_plot = df_spatial
    map_title = f"Spatial XY Element Distribution ({sheet_choice.upper()})"
else:
    r_c1, r_c2 = st.columns([2, 1])
    with r_c1:
        default_nums = [c for c in active_element_cols if c != default_div_col]
        ratio_nums = st.multiselect(
            "Numerator elements for spatial ratios",
            options=active_element_cols,
            default=default_nums[: min(4, len(default_nums))],
            key=f"p6_ratio_nums_{sheet_choice}",
        )
    with r_c2:
        ratio_div = st.selectbox(
            "Divisor (includes OES [ppm #2] on MS)" if oes_ppm2_cols else "Divisor",
            options=divisor_options,
            index=default_div_idx,
            key=f"p6_ratio_div_{sheet_choice}",
        )

    df_plot, ratio_map = build_ratio_dataframe(
        df_in=df_spatial,
        numerator_cols=ratio_nums,
        divisor_col=ratio_div,
        zero_or_neg_policy="Set <= 0 to NaN" if size_scale_mode == "Log10" else "NaN",
    )
    plot_cols = [ratio_map[c] for c in ratio_nums if c in ratio_map]
    map_title = f"Spatial XY Ratio Distribution (Divisor: {ratio_div})"

if not plot_cols:
    st.info("Select at least one element or ratio above to render the spatial map.")
    st.stop()

spatial_cmap = get_group_color_map(df_plot[spatial_color_by], group_type=spatial_color_by)

fig_spatial = plot_spatial_xy_bubble_map(
    df_in=df_plot,
    value_cols=plot_cols,
    lat_col="LatDMS",
    lon_col="LonDMS",
    color_by=spatial_color_by,
    group_color_map=spatial_cmap,
    agg_mode=agg_mode,
    size_scale_mode=size_scale_mode,
    max_marker_size=int(max_bubble),
    min_marker_size=int(min_bubble),
    show_labels=show_station_labels,
    n_cols=int(p6_ncols),
    title=map_title,
)
st.plotly_chart(fig_spatial, use_container_width=True)