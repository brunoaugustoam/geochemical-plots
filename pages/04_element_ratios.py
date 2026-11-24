import pandas as pd
import streamlit as st

from geochem_core import (
    SEASON_FILTER,
    attach_oes_ppm2_divisors,
    build_ratio_dataframe,
    compute_single_ratio_series,
    find_element_col,
    plot_bivariate_element_scatter,
    plot_interactive_boxplots,
)
from color_standards import get_group_color_map

ctx = st.session_state.get("geochem_ctx", {})
sheet_choice = str(ctx.get("sheet_choice", "ms")).strip().lower()
active_element_cols = list(ctx.get("active_element_cols", []))
df_filtered = ctx.get("df_filtered", pd.DataFrame())
group_by_feature = ctx.get("group_by_feature", "Transect")
group_color_map = ctx.get("group_color_map", {})

st.subheader("Element Ratios & Bivariate Relationships")

if len(active_element_cols) < 2 or df_filtered.empty:
    st.info("Need at least two active element columns and non-empty filtered data to plot ratios.")
    st.stop()

# When viewing the `ms` sheet, attach OES `ppm_2` columns (e.g., `Ca ppm_2 [OES]`) for divisor selection
df_page4 = df_filtered.copy()
oes_ppm2_divisor_cols = []
if sheet_choice == "ms":
    oes_ref_df = ctx.get("df_oes_raw") if ctx.get("df_oes_raw") is not None else st.session_state.get("df_oes_raw")
    df_page4, oes_ppm2_divisor_cols = attach_oes_ppm2_divisors(df_page4, oes_ref_df)

divisor_options = list(dict.fromkeys(active_element_cols + oes_ppm2_divisor_cols))

li_col = find_element_col(active_element_cols, "Li") or active_element_cols[0]
ca_col = find_element_col(divisor_options, "Ca")

preferred_div_symbol = "Ca" if sheet_choice == "oes" else "Li"
default_div_col = (
    find_element_col(divisor_options, preferred_div_symbol)
    or find_element_col(divisor_options, "Ca")
    or find_element_col(divisor_options, "Li")
    or divisor_options[0]
)
default_div_idx = divisor_options.index(default_div_col)

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
        df_in=df_page4,
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
# 2. Normalized Element (Element n / Divisor) vs. Element m OR Element m / Element k
# -----------------------------------------------------------------------------
st.divider()
st.markdown("### 2. Normalized Element (`Element n / Divisor`) vs. `Element m` (or `Element m / Element k`)")

s2_c1, s2_c2, s2_c3 = st.columns([2, 1, 1])
with s2_c1:
    default_norm_num = [c for c in active_element_cols if c not in {li_col, default_div_col}]
    norm_num_cols = st.multiselect(
        "Numerator elements (Element n) for Y = Element n / Divisor",
        options=active_element_cols,
        default=default_norm_num[: min(8, len(default_norm_num))],
        key=f"p4_s2_num_{sheet_choice}",
    )
with s2_c2:
    norm_div_col = st.selectbox(
        "Divisor (includes OES ppm_2 on MS)" if oes_ppm2_divisor_cols else "Divisor",
        options=divisor_options,
        index=default_div_idx,
        key=f"p4_s2_div_{sheet_choice}",
    )
with s2_c3:
    x_axis_mode = st.selectbox(
        "X-axis expression",
        options=["Element m", "Element m / Element k"],
        index=0,
        key="p4_s2_x_mode",
    )

xm_c1, xm_c2, xm_c3, xm_c4 = st.columns([1, 1, 1, 1])
with xm_c1:
    elem_m_col = st.selectbox(
        "Element m (X numerator)",
        options=active_element_cols,
        index=active_element_cols.index(li_col),
        key="p4_s2_elem_m",
    )
with xm_c2:
    default_k_idx = (
        divisor_options.index(ca_col)
        if (ca_col in divisor_options and ca_col != elem_m_col)
        else (1 if len(divisor_options) > 1 else 0)
    )
    elem_k_col = st.selectbox(
        "Element k (X divisor)",
        options=divisor_options,
        index=default_k_idx,
        disabled=(x_axis_mode != "Element m / Element k"),
        key="p4_s2_elem_k",
    )
with xm_c3:
    s2_ncols = st.number_input("Scatter columns", min_value=1, max_value=5, value=3, key="p4_s2_ncols")
with xm_c4:
    s2_log = st.checkbox("Log-log axes", value=True, key="p4_s2_log")

df_norm_scatter, norm_map = build_ratio_dataframe(
    df_in=df_page4,
    numerator_cols=list(dict.fromkeys(norm_num_cols)),
    divisor_col=norm_div_col,
    zero_or_neg_policy="Set <= 0 to NaN" if s2_log else "NaN",
)

if x_axis_mode == "Element m / Element k":
    x_series, x_plot_col = compute_single_ratio_series(
        df_norm_scatter,
        num_col=elem_m_col,
        den_col=elem_k_col,
        zero_or_neg_to_nan=s2_log,
    )
    df_norm_scatter[x_plot_col] = x_series
    x_label_str = f"{x_plot_col} ({elem_m_col} / {elem_k_col})"
else:
    x_plot_col = elem_m_col
    x_label_str = elem_m_col

y_norm_targets = [norm_map[c] for c in norm_num_cols if c in norm_map]

if y_norm_targets and x_plot_col in df_norm_scatter.columns:
    fig_s2 = plot_bivariate_element_scatter(
        df_in=df_norm_scatter,
        y_cols=y_norm_targets,
        x_col=x_plot_col,
        group_col=group_by_feature,
        group_color_map=group_color_map,
        x_label_override=x_label_str,
        log_x=s2_log,
        log_y=s2_log,
        n_cols=int(s2_ncols),
        title=f"Element n / ({norm_div_col}) vs. {x_plot_col}",
    )
    st.plotly_chart(fig_s2, use_container_width=True)
else:
    st.info("Select numerator elements to render this plot.")

# -----------------------------------------------------------------------------
# 3. Ratio Boxplots: Element / Divisor
# -----------------------------------------------------------------------------
st.divider()
st.markdown("### 3. Ratio Boxplots (`Element / Divisor`)")

rb_c1, rb_c2 = st.columns([2, 1])
with rb_c1:
    default_box_num = [c for c in active_element_cols if c != default_div_col]
    box_ratio_num_cols = st.multiselect(
        "Numerator elements for boxplots",
        options=active_element_cols,
        default=default_box_num[: min(6, len(default_box_num))],
        key=f"p4_rb_num_{sheet_choice}",
    )
with rb_c2:
    box_ratio_div_col = st.selectbox(
        "Divisor (includes OES ppm_2 on MS)" if oes_ppm2_divisor_cols else "Divisor",
        options=divisor_options,
        index=default_div_idx,
        key=f"p4_rb_div_{sheet_choice}",
    )

b1, b2, b3, b4 = st.columns(4)
with b1:
    rb_log = st.checkbox("Log y-axis", value=True, key="p4_rb_log")
with b2:
    rb_split_season = st.checkbox("Separate seasons side-by-side", value=False, key="p4_rb_season")
with b3:
    rb_show_points = st.checkbox("Show points", value=True, key="p4_rb_show_pts")
with b4:
    rb_ncols = st.number_input("Boxplot columns", min_value=1, max_value=4, value=2, key="p4_rb_ncols")

nums_for_box = list(box_ratio_num_cols)

df_ratio_box, box_ratio_map = build_ratio_dataframe(
    df_in=df_page4,
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
        point_mode="all" if rb_show_points else False,
        log_scale=rb_log,
        split_by_season=rb_split_season,
        season_order=SEASON_FILTER,
    )
    st.plotly_chart(fig_rb, use_container_width=True)
else:
    st.info("Select numerator elements and a valid grouping column to render ratio boxplots.")