# pages/04_element_ratios_placeholder.py
import streamlit as st

st.subheader("4. Element Ratios")
st.info(
    "**Element Ratios:** Element ratios (such as `Element / Ca` or custom "
    "numerator/denominator selections) grouped by `Transect` or `Distance (m)` will be implemented here."
)



import numpy as np
import pandas as pd
import streamlit as st

from color_standards import get_group_color_map
from geochem_core import (
    SEASON_FILTER,
    find_element_col,
    build_ratio_dataframe,
    plot_bivariate_element_scatter,
    plot_interactive_boxplots,

)

ctx = st.session_state["geochem_ctx"]
active_element_cols = ctx["active_element_cols"]
df_filtered = ctx["df_filtered"]
group_by_feature = ctx["group_by_feature"]
group_color_map = ctx["group_color_map"]

st.subheader("Element Ratios & Bivariate Relationships")

if len(active_element_cols) < 2 or df_filtered.empty:
    st.info("Need at least two active element columns and non-empty filtered data to plot ratios.")
    st.stop()

li_col = find_element_col(active_element_cols, "Li") or active_element_cols[0]
ca_col = find_element_col(active_element_cols, "Ca")

# -----------------------------------------------------------------------------
# 1. Bivariate Scatter: Selected Elements vs. Li (default)
# -----------------------------------------------------------------------------
st.markdown("### 1. Bivariate Scatter vs. `Li`")

s1_c1, s1_c2, s1_c3, s1_c4 = st.columns([2, 1, 1, 1])
with s1_c1:
    default_y_candidates = [c for c in active_element_cols if c != li_col]
    scatter_y_cols = st.multiselect(
        "Elements to plot on Y-axis",
        options=active_element_cols,
        default=default_y_candidates[: min(8, len(default_y_candidates))],
        key="p4_s1_y",
    )
with s1_c2:
    x_ref_col = st.selectbox(
        "X-axis element",
        options=active_element_cols,
        index=active_element_cols.index(li_col),
        key="p4_s1_x",
    )
with s1_c3:
    s1_ncols = st.number_input("Scatter columns", min_value=1, max_value=5, value=3, key="p4_s1_ncols")
with s1_c4:
    s1_log = st.checkbox("Log-log axes", value=True, key="p4_s1_log")

if scatter_y_cols:
    fig_s1 = plot_bivariate_element_scatter(
        df_in=df_filtered,
        y_cols=scatter_y_cols,
        x_col=x_ref_col,
        group_col=group_by_feature,
        group_color_map=group_color_map,
        log_x=s1_log,
        log_y=s1_log,
        n_cols=int(s1_ncols),
        title=f"Bivariate Scatter vs. {x_ref_col.split(' ')[0]}",
    )
    st.plotly_chart(fig_s1, use_container_width=True)
else:
    st.info("Select one or more Y-axis elements above.")

# -----------------------------------------------------------------------------
# 2. Bivariate Scatter: Element / Divisor (default Ca) vs. Li (with Li / Ca option)
# -----------------------------------------------------------------------------
st.divider()
st.markdown("### 2. Normalized Element (`Element n / Divisor`) vs. `Element m`")

s2_c1, s2_c2, s2_c3, s2_c4 = st.columns([2, 1, 1, 1])
with s2_c1:
    sheet_choice = ctx.get("sheet_choice", "ms").strip().lower()
    preferred_div_symbol = "Ca" if sheet_choice == "oes" else "Li"
    default_div_col = (
        find_element_col(active_element_cols, preferred_div_symbol)
        or find_element_col(active_element_cols, "Ca")
        or find_element_col(active_element_cols, "Li")
        or active_element_cols[0]
    )
    default_norm_num = [
    c for c in active_element_cols if c not in {li_col, default_div_col}
        ]
    
    norm_num_cols = st.multiselect(
        "Numerator elements for Y = Element / Divisor",
        options=active_element_cols,
        default=default_norm_num[: min(8, len(default_norm_num))],
        key="p4_s2_num",
    )
with s2_c2:
    
    

    default_div_idx = active_element_cols.index(default_div_col)
    norm_div_col = st.selectbox(
        "Divisor element",
        options=active_element_cols,
        index=default_div_idx,
        key="p4_s2_div",
    )
with s2_c3:
    include_li_ca = st.checkbox(
        "Include Li / Divisor panel",
        value=True,
        help="Adds Li / [selected divisor, e.g. Ca] alongside the selected normalized elements.",
        key="p4_s2_include_lica",
    )
with s2_c4:
    s2_ncols = st.number_input("Scatter columns", min_value=1, max_value=5, value=3, key="p4_s2_ncols")

s2_log = st.checkbox("Log-log axes (Element/Divisor vs. Li)", value=True, key="p4_s2_log")

df_norm_scatter, norm_map = build_ratio_dataframe(
    df_in=df_filtered,
    numerator_cols=list(dict.fromkeys(norm_num_cols + ([li_col] if include_li_ca else []))),
    divisor_col=norm_div_col,
    zero_or_neg_policy="Set <= 0 to NaN" if s2_log else "NaN",
)

y_norm_targets = [norm_map[c] for c in norm_num_cols if c in norm_map]
if include_li_ca and li_col in norm_map and norm_map[li_col] not in y_norm_targets:
    y_norm_targets.append(norm_map[li_col])

if y_norm_targets:
    div_sym = norm_div_col.split(" ")[0].lstrip("[").rstrip("]")
    li_sym = li_col.split(" ")[0].lstrip("[").rstrip("]")
    fig_s2 = plot_bivariate_element_scatter(
        df_in=df_norm_scatter,
        y_cols=y_norm_targets,
        x_col=li_col,
        group_col=group_by_feature,
        group_color_map=group_color_map,
        x_label_override=f"{li_sym} ({li_col})",
        log_x=s2_log,
        log_y=s2_log,
        n_cols=int(s2_ncols),
        title=f"Element / {div_sym} vs. {li_sym}",
    )
    st.plotly_chart(fig_s2, use_container_width=True)
else:
    st.info("Select numerator elements or enable Li / Divisor to render this plot.")

# -----------------------------------------------------------------------------
# 3. Ratio Boxplots: Element / Divisor (default Ca), same layout as Page 1
# -----------------------------------------------------------------------------
st.divider()
st.markdown("### 3. Ratio Boxplots (`Element / Divisor`)")

rb_c1, rb_c2, rb_c3 = st.columns([2, 1, 1])
with rb_c1:
    default_box_num = [c for c in active_element_cols if c != default_div_col]
    box_ratio_num_cols = st.multiselect(
        "Numerator elements for boxplots",
        options=active_element_cols,
        default=default_box_num[: min(6, len(default_box_num))],
        key="p4_rb_num",
    )
with rb_c2:
    # default_rb_div_idx = active_element_cols.index(ca_col) if ca_col in active_element_cols else 0
    # default_div_idx = active_element_cols.index(default_div_col)
    box_ratio_div_col = st.selectbox(
        "Divisor element",
        options=active_element_cols,
        index=default_div_idx,
        key="p4_rb_div",
    )
with rb_c3:
    include_li_over_div_box = st.checkbox(
        "Ensure Li / Divisor is included",
        value=True,
        key="p4_rb_include_li",
    )

b1, b2, b3, b4, b5 = st.columns(5)
with b1:
    rb_log = st.checkbox("Log y-axis", value=True, key="p4_rb_log")
with b2:
    rb_split_season = st.checkbox("Separate seasons side-by-side", value=False, key="p4_rb_season")
with b3:
    rb_show_points = st.checkbox("Show points", value=True, key="p4_rb_show_pts")
with b4:
    rb_points = st.selectbox(
        "Point display mode",
        options=["all", "outliers", "False"],
        index=0 if rb_show_points else 2,
        key="p4_rb_pts",
    )
with b5:
    rb_ncols = st.number_input("Boxplot columns", min_value=1, max_value=4, value=2, key="p4_rb_ncols")

resolved_rb_points = False if rb_points == "False" else rb_points

nums_for_box = list(box_ratio_num_cols)
if include_li_over_div_box and li_col not in nums_for_box:
    nums_for_box.insert(0, li_col)

df_ratio_box, box_ratio_map = build_ratio_dataframe(
    df_in=df_filtered,
    numerator_cols=nums_for_box,
    divisor_col=box_ratio_div_col,
    zero_or_neg_policy="Set <= 0 to NaN" if rb_log else "NaN",
)
ratio_box_cols = [box_ratio_map[c] for c in nums_for_box if c in box_ratio_map]

if ratio_box_cols and group_by_feature in df_ratio_box.columns:
    fig_rb = plot_interactive_boxplots(
        dataframe=df_ratio_box,
        cols_plot=ratio_box_cols,
        group_col=group_by_feature,
        group_color_map=group_color_map,
        id_col="Sample ID",
        n_cols=int(rb_ncols),
        point_mode=False if rb_points == "False" else rb_points,
        log_scale=rb_log,
        split_by_season=rb_split_season,
        season_order=SEASON_FILTER,
    )
    st.plotly_chart(fig_rb, use_container_width=True)
else:
    st.info("Select numerator elements and a valid grouping column to render ratio boxplots.")
