import pandas as pd
import streamlit as st

from geochem_core import (
    SEASON_FILTER,
    get_top_recurring_samples,
    plot_interactive_boxplots,
    plot_interactive_histograms,
)

ctx = st.session_state["geochem_ctx"]
sheet_choice = ctx["sheet_choice"]
active_element_cols = ctx["active_element_cols"]
col_meta = ctx["col_meta"]
df_mapped = ctx["df_mapped"]
df_filtered = ctx["df_filtered"]
neg_replacement_log = ctx["neg_replacement_log"]
group_by_feature = ctx["group_by_feature"]
group_color_map = ctx["group_color_map"]
element_color_map = ctx["element_color_map"]

st.subheader(f"Dataset Overview — Sheet `{sheet_choice}`")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Raw Rows", len(df_mapped))
c2.metric("Filtered Rows", len(df_filtered))
c3.metric("Elements Detected", len(col_meta["elements"]))
c4.metric("Negative-Replaced Cols", len(neg_replacement_log))

with st.expander("Inspect Column Remapping & Pre-Levelling Negative Replacements"):
    st.write("**Remapped Element Columns (sample):**")
    st.json({k: v for k, v in list(col_meta["rename_map"].items())[:15]})
    if neg_replacement_log:
        st.write("**Negative Value Replacements (min_positive / sqrt(2)):**")
        st.dataframe(pd.DataFrame.from_dict(neg_replacement_log, orient="index"), use_container_width=True)
    else:
        st.caption("No negative values found in selected analytical columns.")

st.divider()
st.subheader("Quantile Filtering & Element Selection")

q_col1, q_col2, q_col3 = st.columns([2, 1, 1])
with q_col1:
    selected_cols_t1 = st.multiselect(
        "Select element columns to plot",
        options=active_element_cols,
        default=active_element_cols[: min(8, len(active_element_cols))],
    )
with q_col2:
    q_low, q_high = st.slider(
        "Quantile filter range",
        min_value=0.0,
        max_value=1.0,
        value=(0.0, 1.0),
        step=0.01,
    )
with q_col3:
    q_ref_col = st.selectbox(
        "Quantile filter column",
        options=selected_cols_t1 if selected_cols_t1 else active_element_cols,
        index=0,
    )

df_p1 = df_filtered.copy()
if q_ref_col in df_p1.columns and (q_low > 0.0 or q_high < 1.0):
    s_ref = pd.to_numeric(df_p1[q_ref_col], errors="coerce")
    df_p1 = df_p1[(s_ref >= s_ref.quantile(q_low)) & (s_ref <= s_ref.quantile(q_high))]

st.markdown("### Interactive Histograms")
h1, h2, h3, h4 = st.columns(4)
with h1:
    hist_log = st.checkbox("Log10 scale", value=True, key="p1_hist_log")
with h2:
    hist_split_season = st.checkbox("Overlay seasons (shaded)", value=False, key="p1_hist_season")
with h3:
    hist_ncols = st.number_input("Histogram columns", min_value=1, max_value=6, value=4, key="p1_hist_ncols")
with h4:
    auto_bins = st.checkbox("Auto bin count", value=True, key="p1_hist_autobins")
    hist_bins = None if auto_bins else st.slider("Bins", 5, 80, 25, key="p1_hist_bins")

if selected_cols_t1 and not df_p1.empty:
    fig_hist = plot_interactive_histograms(
        dataframe=df_p1,
        cols_interest=selected_cols_t1,
        log_scale=hist_log,
        n_cols=int(hist_ncols),
        n_bins=hist_bins,
        element_color_map=element_color_map,
        split_by_season=hist_split_season,
        season_order=SEASON_FILTER,
    )
    st.plotly_chart(fig_hist, use_container_width=True)
else:
    st.info("Select at least one element column with non-empty data to display histograms.")

st.divider()
st.markdown(f"### Interactive Boxplots by `{group_by_feature}`")
b1, b2, b3, b4 = st.columns(4)
with b1:
    box_log = st.checkbox("Log y-axis", value=True, key="p1_box_log")
with b2:
    box_split_season = st.checkbox("Separate seasons side-by-side", value=False, key="p1_box_season")
with b3:
    point_opt = st.selectbox("Points mode", options=["outliers", "all", "False"], index=0, key="p1_box_pts")
with b4:
    box_ncols = st.number_input("Boxplot columns", min_value=1, max_value=4, value=2, key="p1_box_ncols")

if selected_cols_t1 and group_by_feature in df_p1.columns and not df_p1.empty:
    fig_box = plot_interactive_boxplots(
        dataframe=df_p1,
        cols_plot=selected_cols_t1,
        group_col=group_by_feature,
        group_color_map=group_color_map,
        id_col="Sample ID",
        n_cols=int(box_ncols),
        point_mode=False if point_opt == "False" else point_opt,
        log_scale=box_log,
        split_by_season=box_split_season,
        season_order=SEASON_FILTER,
    )
    st.plotly_chart(fig_box, use_container_width=True)
else:
    st.info(f"Ensure `{group_by_feature}` and element columns are available to render boxplots.")

st.divider()
st.markdown("### Samples / Filters Recurring in Top-N Concentrations")
top_n_val = st.slider("Top-N per element", min_value=1, max_value=20, value=5, key="p1_top_n")
top_summary_df = get_top_recurring_samples(
    df=df_p1,
    target_cols=selected_cols_t1 if selected_cols_t1 else active_element_cols,
    top_n=top_n_val,
    id_col="Sample ID",
)
if not top_summary_df.empty:
    st.dataframe(top_summary_df, use_container_width=True)
else:
    st.caption("No top-N records available for the current filter selection.")