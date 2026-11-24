import streamlit as st

from geochem_core import (
    plot_interactive_loadings_matrix,
    plot_interactive_pca_scores,
    plot_interactive_scree,
    run_pca_and_clustering,
)

ctx = st.session_state["geochem_ctx"]
active_element_cols = ctx["active_element_cols"]
df_filtered = ctx["df_filtered"]
group_by_feature = ctx["group_by_feature"]
group_color_map = ctx["group_color_map"]
element_color_map = ctx["element_color_map"]

st.subheader("Principal Component Analysis (PCA) & K-Means Clustering")

default_pca_features = [
    col
    for col in active_element_cols
    if col.split(" ")[0].lstrip("[").rstrip("]") != "Cd"
]

pca_c1, pca_c2, pca_c3 = st.columns([2, 1, 1])
with pca_c1:
    pca_features = st.multiselect(
        "Features for normalization, K-Means & PCA",
        options=active_element_cols,
        default=default_pca_features,
        key="p2_pca_features",
    )
with pca_c2:
    n_clusters_val = st.slider("Number of K-Means clusters", min_value=2, max_value=12, value=5, key="p2_clusters")
with pca_c3:
    n_pcs_val = st.slider("Max PCA components", min_value=2, max_value=10, value=7, key="p2_max_pcs")

pca_bundle = run_pca_and_clustering(
    df_in=df_filtered,
    feature_cols=pca_features,
    n_clusters=n_clusters_val,
    n_components=n_pcs_val,
)

if pca_bundle is None:
    st.warning("Need at least 2 valid rows and 2 features without NaNs to run PCA & clustering.")
else:
    pca_model = pca_bundle["pca"]
    scores_df = pca_bundle["scores_df"]
    loadings_df = pca_bundle["loadings_df"]
    pc_names = pca_bundle["pc_names"]

    var_thresh = st.slider(
        "Cumulative variance threshold",
        min_value=0.50,
        max_value=0.99,
        value=0.95,
        step=0.01,
        key="p2_var_thresh",
    )
    st.plotly_chart(plot_interactive_scree(pca_model, threshold=var_thresh), use_container_width=True)

    st.divider()
    st.markdown("### PCA Scores Plot")
    sc1, sc2, sc3, sc4 = st.columns(4)
    with sc1:
        pc_x = st.selectbox("X-axis PC", options=pc_names, index=0, key="p2_pc_x")
    with sc2:
        pc_y = st.selectbox("Y-axis PC", options=pc_names, index=min(1, len(pc_names) - 1), key="p2_pc_y")
    with sc3:
        color_choices = ["Cluster"] + [
            c for c in ["Transect", "Distance (m)", "Season", "Ref_Group"] if c in scores_df.columns
        ]
        default_color_idx = color_choices.index(group_by_feature) if group_by_feature in color_choices else 1
        pca_color_by = st.selectbox("Color points by", options=color_choices, index=default_color_idx, key="p2_color_by")
    with sc4:
        ann_choices = ["None"] + [
            c for c in ["Sample ID", "Dust sampler_ID", "Season", "Transect", "Ref_Group"]
            if c in pca_bundle["df_aligned"].columns
        ]
        ann_choice = st.selectbox("Annotate points", options=ann_choices, index=0, key="p2_ann")

    s_opt1, s_opt2 = st.columns(2)
    with s_opt1:
        symlog_pca = st.checkbox("SymLog10 scale (PCA)", value=True, key="p2_symlog")
    with s_opt2:
        linthresh_val = st.number_input(
            "Symlog linear threshold",
            min_value=0.01,
            max_value=100.0,
            value=1.0,
            step=0.1,
            disabled=not symlog_pca,
            key="p2_linthresh",
        )

    scores_with_ann = scores_df.copy()
    if ann_choice != "None" and ann_choice in pca_bundle["df_aligned"].columns:
        scores_with_ann[ann_choice] = pca_bundle["df_aligned"][ann_choice]

    fig_scores = plot_interactive_pca_scores(
        scores_df=scores_with_ann,
        pc_x=pc_x,
        pc_y=pc_y,
        color_by=pca_color_by,
        group_color_map=group_color_map,
        annotate_col=None if ann_choice == "None" else ann_choice,
        symlog_pca=symlog_pca,
        linthresh=float(linthresh_val),
    )
    st.plotly_chart(fig_scores, use_container_width=True)

    st.divider()
    st.markdown("### PCA Loadings Matrix")
    matrix_pcs = st.multiselect(
        "Select PCs for loadings matrix (2–4 recommended)",
        options=pc_names,
        default=pc_names[: min(3, len(pc_names))],
        key="p2_mat_pcs",
    )
    if len(matrix_pcs) >= 2:
        st.plotly_chart(
            plot_interactive_loadings_matrix(
                loadings_df=loadings_df,
                selected_pcs=matrix_pcs,
                element_color_map=element_color_map,
            ),
            use_container_width=True,
        )
    else:
        st.info("Select at least 2 PCs to render the loadings matrix.")

    with st.expander("View PCA Loadings Table & Clustered Sample Data"):
        st.dataframe(loadings_df.round(4), use_container_width=True)
        st.dataframe(scores_df, use_container_width=True)