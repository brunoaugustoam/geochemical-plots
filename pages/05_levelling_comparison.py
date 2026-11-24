# pages/05_levelling_comparison_placeholder.py
import streamlit as st

st.subheader("5. Seasonal Levelling Comparison")
st.info(
    "**Seasonal Levelling Comparison:** Side-by-side comparison of raw/cleaned vs. "
    "seasonally levelled distributions (`MedianShift`, `ZRobust`, `ZScore`) will be implemented here."
)


import pandas as pd
import streamlit as st

from geochem_core import (
    apply_seasonal_levelling,
    plot_levelling_overlay_histograms,
    plot_levelling_side_by_side_boxplots,
)

ctx = st.session_state["geochem_ctx"]
active_element_cols = ctx["active_element_cols"]
df_cleaned = ctx["df_cleaned"]
df_filtered = ctx["df_filtered"]
enable_levelling = ctx["enable_levelling"]
levelling_method = ctx["levelling_method"]
ref_season = ctx["ref_season"]
group_by_feature = ctx["group_by_feature"]
group_color_map = ctx["group_color_map"]
element_color_map = ctx["element_color_map"]

st.subheader("Pre vs. Post Seasonal Levelling Comparison")

if not enable_levelling:
    st.caption(
        f"Seasonal Levelling toggle is currently OFF in the sidebar; showing a preview using "
        f"`{levelling_method}` relative to `{ref_season}` on the cleaned data."
    )

# Align pre-levelling cleaned data to the exact same filtered rows & index as df_filtered
df_pre = df_cleaned.loc[df_filtered.index].copy()

if enable_levelling:
    df_post = df_filtered.copy()
else:
    df_post_full = apply_seasonal_levelling(
        df_cleaned,
        target_cols=active_element_cols,
        method=levelling_method,
        reference_season=ref_season,
    )
    df_post = df_post_full.loc[df_filtered.index].copy()

# Quantile filter & element selection (same disposition as Page 1)
q_col1, q_col2, q_col3 = st.columns([2, 1, 1])
with q_col1:
    selected_cols_p5 = st.multiselect(
        "Select element columns to compare",
        options=active_element_cols,
        default=active_element_cols[: min(8, len(active_element_cols))],
        key="p5_cols",
    )
with q_col2:
    q_low, q_high = st.slider(
        "Quantile filter range",
        min_value=0.0,
        max_value=1.0,
        value=(0.0, 1.0),
        step=0.01,
        key="p5_q_range",
    )
with q_col3:
    q_ref_col = st.selectbox(
        "Quantile filter column",
        options=selected_cols_p5 if selected_cols_p5 else active_element_cols,
        index=0,
        key="p5_q_col",
    )

df_pre_p5 = df_pre.copy()
if q_ref_col in df_pre_p5.columns and (q_low > 0.0 or q_high < 1.0):
    s_ref = pd.to_numeric(df_pre_p5[q_ref_col], errors="coerce")
    keep_idx = df_pre_p5.index[(s_ref >= s_ref.quantile(q_low)) & (s_ref <= s_ref.quantile(q_high))]
    df_pre_p5 = df_pre_p5.loc[keep_idx]

df_post_p5 = df_post.loc[df_pre_p5.index].copy()

st.divider()
st.markdown("### Overlaid Histograms (Pre vs. Post Levelling)")
h1, h2, h3 = st.columns(3)
with h1:
    hist_log = st.checkbox("Log10 scale", value=True, key="p5_hist_log")
with h2:
    hist_ncols = st.number_input("Histogram columns", min_value=1, max_value=6, value=4, key="p5_hist_ncols")
with h3:
    auto_bins = st.checkbox("Auto bin count", value=True, key="p5_hist_autobins")
    hist_bins = None if auto_bins else st.slider("Bins", 5, 80, 25, key="p5_hist_bins")

if selected_cols_p5 and not df_pre_p5.empty:
    fig_hist_cmp = plot_levelling_overlay_histograms(
        df_pre=df_pre_p5,
        df_post=df_post_p5,
        cols_interest=selected_cols_p5,
        log_scale=hist_log,
        n_cols=int(hist_ncols),
        n_bins=hist_bins,
        element_color_map=element_color_map,
    )
    st.plotly_chart(fig_hist_cmp, use_container_width=True)
else:
    st.info("Select at least one element column with non-empty data to display histograms.")

st.divider()
st.markdown(f"### Side-by-Side Boxplots by `{group_by_feature}` (Pre vs. Post Levelling)")
b1, b2, b3 = st.columns(3)
with b1:
    box_log = st.checkbox("Log y-axis", value=True, key="p5_box_log")
with b2:
    point_opt = st.selectbox("Points mode", options=["outliers", "all", "False"], index=0, key="p5_box_pts")
with b3:
    box_ncols = st.number_input("Boxplot columns", min_value=1, max_value=4, value=2, key="p5_box_ncols")

if selected_cols_p5 and group_by_feature in df_pre_p5.columns and not df_pre_p5.empty:
    fig_box_cmp = plot_levelling_side_by_side_boxplots(
        df_pre=df_pre_p5,
        df_post=df_post_p5,
        cols_plot=selected_cols_p5,
        group_col=group_by_feature,
        group_color_map=group_color_map,
        id_col="Sample ID",
        n_cols=int(box_ncols),
        point_mode=False if point_opt == "False" else point_opt,
        log_scale=box_log,
    )
    st.plotly_chart(fig_box_cmp, use_container_width=True)
else:
    st.info(f"Ensure `{group_by_feature}` and element columns are available to render boxplots.")