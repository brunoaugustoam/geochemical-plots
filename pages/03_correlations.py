import numpy as np
import pandas as pd
import streamlit as st

from geochem_core import (
    compute_correlation_matrix,
    plot_interactive_correlation_heatmap,
    plot_permutation_null_hist,
    run_contamination_diagnostics,
)

ctx = st.session_state["geochem_ctx"]
active_element_cols = ctx["active_element_cols"]
df_filtered = ctx["df_filtered"]

st.subheader("Element Correlations")

c1, c2, c3 = st.columns([2, 1, 1])
with c1:
    corr_cols = st.multiselect(
        "Select element columns",
        options=active_element_cols,
        default=active_element_cols,
        key="p3_corr_cols",
    )
with c2:
    corr_method = st.selectbox(
        "Correlation method",
        options=["Pearson", "Spearman"],
        index=0,
        key="p3_corr_method",
    )
with c3:
    only_meaningful = st.checkbox(
        "Keep only meaningful correlations",
        value=True,
        help="Filters out pairs that do not meet both the minimum |r| and p-value significance threshold.",
        key="p3_only_meaningful",
    )

f1, f2 = st.columns(2)
with f1:
    r_thresh = st.slider(
        "Minimum |r| threshold",
        min_value=0.0,
        max_value=0.95,
        value=0.50,
        step=0.05,
        disabled=not only_meaningful,
        key="p3_r_thresh",
    )
with f2:
    p_alpha = st.select_slider(
        "Significance threshold (p < alpha)",
        options=[0.001, 0.01, 0.05, 0.10],
        value=0.05,
        disabled=not only_meaningful,
        key="p3_p_alpha",
    )

if len(corr_cols) < 2 or df_filtered.empty:
    st.info("Select at least 2 element columns with non-empty data to compute correlations.")
else:
    r_full_df, p_df, r_disp_df = compute_correlation_matrix(
        df_in=df_filtered,
        cols=corr_cols,
        method=corr_method.lower(),
        only_meaningful=only_meaningful,
        r_threshold=float(r_thresh),
        alpha=float(p_alpha),
    )

    fig_corr = plot_interactive_correlation_heatmap(
        r_disp_df=r_disp_df,
        r_full_df=r_full_df,
        p_df=p_df,
        full_col_names=corr_cols,
        method_label=corr_method,
        only_meaningful=only_meaningful,
    )
    st.plotly_chart(fig_corr, use_container_width=True)

    with st.expander("View Correlation & p-Value Tables"):
        st.write(f"**Displayed {corr_method} Correlation Matrix:**")
        st.dataframe(r_disp_df.round(3), use_container_width=True)
        st.write(f"**Full {corr_method} Correlation Matrix:**")
        st.dataframe(r_full_df.round(3), use_container_width=True)
        st.write("**Two-Sided p-Values:**")
        st.dataframe(p_df.round(4), use_container_width=True)

# -----------------------------------------------------------------------------
# Randomness & Contamination Diagnostic Suite
# -----------------------------------------------------------------------------
st.divider()
st.subheader("Randomness & Contamination Diagnostics")

diag_cols = active_element_cols if active_element_cols else corr_cols
cd_matches = [
    i for i, col_name in enumerate(diag_cols)
    if col_name.split(" ")[0].lstrip("[").rstrip("]") == "Cd"
]
default_suspect_idx = cd_matches[0] if cd_matches else 0

d1, d2, d3, d4 = st.columns([2, 1, 1, 1])
with d1:
    suspect_col = st.selectbox(
        "Suspect element to test",
        options=diag_cols,
        index=default_suspect_idx,
        key="p3_suspect_col",
    )
with d2:
    knn_k = st.slider("Spatial k-NN", min_value=2, max_value=10, value=4, key="p3_knn_k")
with d3:
    n_perms = st.slider("Permutations", min_value=99, max_value=999, value=499, step=50, key="p3_n_perms")
with d4:
    seed_val = st.number_input("Seed", min_value=0, max_value=99999, value=42, key="p3_seed")

if suspect_col and suspect_col in df_filtered.columns and not df_filtered.empty:
    peer_pool = [c for c in (corr_cols if corr_cols else diag_cols) if c != suspect_col]
    res = run_contamination_diagnostics(
        df_in=df_filtered,
        suspect_col=suspect_col,
        peer_cols=peer_pool,
        lat_col="LatDMS",
        lon_col="LonDMS",
        k_neighbors=int(knn_k),
        n_permutations=int(n_perms),
        seed=int(seed_val),
    )

    suspect_sym = suspect_col.split(" ")[0].lstrip("[").rstrip("]")
    dist_i = res["dist"]
    spat_i = res["spatial"]
    resid_i = res["resid"]

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric(
        "1. KS vs. Peers",
        f"{dist_i['ks_stat']:.3f}" if np.isfinite(dist_i["ks_stat"]) else "N/A",
        delta=f"p={dist_i['ks_p']:.3e}" if np.isfinite(dist_i["ks_p"]) else None,
        delta_color="off",
    )
    m2.metric(
        "2. Moran's I (Lat/Lon)",
        f"{spat_i['morans_i']:.3f}" if np.isfinite(spat_i["morans_i"]) else "N/A",
        delta=f"perm p={spat_i['p_value']:.3f}" if np.isfinite(spat_i["p_value"]) else ("No LatDMS/LonDMS" if not res["has_coords"] else None),
        delta_color="off",
    )
    max_mi = float(res["mi_df"]["Mutual Information"].max()) if not res["mi_df"].empty else np.nan
    top_mi_el = str(res["mi_df"].iloc[0]["Element"]) if not res["mi_df"].empty else ""
    m3.metric(
        "3. Max Mutual Info",
        f"{max_mi:.3f}" if np.isfinite(max_mi) else "N/A",
        delta=f"with {top_mi_el}" if top_mi_el else None,
        delta_color="off",
    )
    m4.metric(
        "4. Dispersion Ratio",
        f"{res['disp_ratio']:.2f}x" if np.isfinite(res["disp_ratio"]) else "N/A",
        delta=f"Levene p={res['levene_p']:.3e}" if np.isfinite(res["levene_p"]) else None,
        delta_color="off",
    )
    m5.metric(
        "5. Robust R² (Peers)",
        f"{resid_i['r2_robust']:.3f}" if np.isfinite(resid_i["r2_robust"]) else "N/A",
        delta=f"Res/Y MAD={resid_i['resid_to_y_mad']:.2f}" if np.isfinite(resid_i["resid_to_y_mad"]) else None,
        delta_color="off",
    )

    # Automated diagnostic summary & interpretations
    st.markdown("#### Diagnostic Interpretation")

    if np.isfinite(dist_i["ks_stat"]):
        ks_interp = (
            f"**Distribution comparison:** KS = {dist_i['ks_stat']:.3f} (p = {dist_i['ks_p']:.3e}, skew = {dist_i['skew']:.2f}). "
            + (
                f"{suspect_sym}'s distribution differs noticeably from pooled peer elements—check for heavy tails, spikes, or censored/contaminated values."
                if dist_i["ks_p"] < 0.05
                else f"{suspect_sym}'s distribution is broadly similar to pooled peer elements."
            )
        )
    else:
        ks_interp = "**Distribution comparison:** Insufficient valid data to compare distributions."

    if not res["has_coords"]:
        spat_interp = "**Spatial Moran's I:** `LatDMS` and `LonDMS` were not found in the active dataset."
    elif np.isfinite(spat_i["morans_i"]):
        if spat_i["p_value"] < 0.05 and spat_i["morans_i"] > spat_i["expected_i"]:
            spat_interp = (
                f"**Spatial Moran's I:** I = {spat_i['morans_i']:.3f} (expected {spat_i['expected_i']:.3f}, perm p = {spat_i['p_value']:.3f} across N = {spat_i['n_spatial']} mapped rows). "
                f"Significant positive spatial clustering in `(LatDMS, LonDMS)` suggests localized spatial structure or a geographic hotspot rather than pure spatial white noise."
            )
        elif spat_i["p_value"] < 0.05 and spat_i["morans_i"] < spat_i["expected_i"]:
            spat_interp = (
                f"**Spatial Moran's I:** I = {spat_i['morans_i']:.3f} (perm p = {spat_i['p_value']:.3f}). "
                f"Significant negative spatial autocorrelation indicates sharp neighbor-to-neighbor jumps across `(LatDMS, LonDMS)`."
            )
        else:
            spat_interp = (
                f"**Spatial Moran's I:** I = {spat_i['morans_i']:.3f} (perm p = {spat_i['p_value']:.3f}). "
                f"No statistically significant spatial clustering across `(LatDMS, LonDMS)`—consistent with spatially scattered or random variation."
            )
    else:
        spat_interp = "**Spatial Moran's I:** Insufficient valid coordinate pairs (`LatDMS`, `LonDMS`) to compute Moran's I."

    if not res["mi_df"].empty:
        mi_interp = (
            f"**Mutual information:** Highest MI is {max_mi:.3f} with **{top_mi_el}**. "
            + (
                f"Non-zero MI alongside low linear correlation indicates nonlinear structure with {top_mi_el}."
                if max_mi > 0.15
                else f"Low mutual information across peers indicates little shared nonlinear signal with the rest of the assemblage."
            )
        )
    else:
        mi_interp = "**Mutual information:** Select at least one peer element to evaluate mutual information."

    if np.isfinite(res["disp_ratio"]):
        var_interp = (
            f"**Variance comparison:** Log-IQR dispersion is {res['disp_ratio']:.2f}x the peer median (Levene p = {res['levene_p']:.3e}). "
            + (
                f"Elevated dispersion supports erratic or sporadic contamination spikes relative to other elements."
                if res["disp_ratio"] > 1.35
                else f"Dispersion is comparable to or tighter than typical peer elements."
            )
        )
    else:
        var_interp = "**Variance comparison:** Insufficient data to compare dispersion."

    if np.isfinite(resid_i["r2_robust"]):
        resid_interp = (
            f"**Robust regression residuals:** Huber R² = {resid_i['r2_robust']:.3f} (residual/target MAD ratio = {resid_i['resid_to_y_mad']:.2f} across N = {resid_i['n_reg']}). "
            + (
                f"Low R² and high residual dispersion mean peer elements explain little of {suspect_sym}, consistent with an independent/random or exogenous contamination source."
                if resid_i["r2_robust"] < 0.25
                else f"Peer elements account for a substantial share of {suspect_sym}'s variation."
            )
        )
    else:
        resid_interp = "**Robust regression residuals:** Insufficient complete rows across peers to fit robust regression."

    for line in [ks_interp, spat_interp, mi_interp, var_interp, resid_interp]:
        st.markdown(f"* {line}")

    if res["has_coords"] and len(spat_i["null_i"]) > 0:
        st.plotly_chart(
            plot_permutation_null_hist(
                null_vals=spat_i["null_i"],
                obs_val=spat_i["morans_i"],
                metric_label="Spatial Moran's I",
                title=f"{suspect_sym} — Spatial Moran's I vs. Coordinate Permutations (LatDMS, LonDMS)",
            ),
            use_container_width=True,
        )

    t_col1, t_col2 = st.columns(2)
    with t_col1:
        st.markdown("##### Mutual Information with Peer Elements")
        if not res["mi_df"].empty:
            st.dataframe(res["mi_df"].round(4), use_container_width=True)
        else:
            st.caption("No mutual information table available.")
    with t_col2:
        st.markdown("##### Dispersion & Variance Across Elements")
        st.dataframe(res["var_df"].round(4), use_container_width=True)