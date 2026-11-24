# """
# Streamlit Bulk Geochemical Analysis App (MS & OES Filter/Dust Datasets).

# Implemented in this version:
# - Drag-and-drop .xlsx uploader (default sheet_name = 'ms', supports 'oes')
# - Column deduplication and explicit remapping of repeated element/metadata columns
# - Negative-value and NaN handling BEFORE optional seasonal levelling
# - Seasonal levelling control in the sidebar (OFF by default) with an explicit
#   prominent banner drawing attention to its state
# - Standard color mappings for Transect, Distance (m), and Elements
# - Tab 1: Data Overview, Distributions, Quantile Filter & Top Filters (Plotly)
# - Tab 2: PCA & K-Means Clustering (Plotly)
# - Tabs 3–5: Structured placeholders for Correlations, Element Ratios, and
#   Seasonal Levelling Comparison
# """

# import os
# import itertools
# import numpy as np
# import pandas as pd
# import plotly.express as px
# import plotly.graph_objects as go
# from plotly.subplots import make_subplots
# from scipy import stats
# from sklearn.cluster import KMeans
# from sklearn.decomposition import PCA
# import streamlit as st

# from color_standards import (
#     get_element_color_map,
#     get_group_color_map,
# )

# # -----------------------------------------------------------------------------
# # Page Configuration & Reference Metadata
# # -----------------------------------------------------------------------------
# st.set_page_config(
#     page_title="Bulk Geochemical Analysis",
#     page_icon="🧪",
#     layout="wide",
# )

# DEFAULT_ROOT = os.getcwd()
# DEFAULT_FOLDER = "May25_Aug25_Nov25"
# DEFAULT_FILE = "NAL_Filters REPORT_2026_02_20_edit.xlsx"
# DEFAULT_SHEET = "ms"

# INFO_COLS = [
#     "Sample ID",
#     "Season",
#     "Dust sampler_ID",
#     "Transect",
#     "Distance (m)",
#     "Change in mass (mg)",
# ]

# SEASON_FILTER = [
#     "Winter 2024",
#     "Spring-Summer 2025",
#     "Fall 2025",
#     "Winter 2025",
#     "Spring-Summer 2026",
#     "Fall 2026",
# ]

# OTHER_COL_INTEREST = [
#     "Change in mass (mg)",
#     "(mg/dm2/day)",
#     "Geochem quarter weight (g)",
#     "Days in Field",
#     "Distance (m)",
#     "LatDMS",
#     "LonDMS",
# ]

# MS_ELEMENTS = [
#     "As", "Ba", "Be", "Ce", "Co", "Cr", "Cu",
#     "Li", "Nb", "Pb", "Rb", "Tl", "V",
# ]

# OES_ELEMENTS = [
#     "Al", "As", "Ba", "Bi", "Ca", "Cd", "Co", "Cr", "Cu", "Fe",
#     "K", "Li", "Mg", "Mn", "Mo", "Na", "Ni", "P", "Pb", "S (ICP)",
#     "Sb", "Se", "Si", "Sr", "Ti", "V", "Zn", "Zr",
# ]

# # Positional unit slots per element block:
# # - In 'ms': each element block has 10 columns:
# #     [0] [Elem] (%)
# #     [1] [Elem] (%/g of filter)   [first occurrence]
# #     [2] [Elem] (%/g of filter)   [second occurrence]
# #     [3] [Elem] (%)               [second occurrence]
# #     [4] Data multiplication required
# #     [5] [Elem] (ppb)             [first occurrence]
# #     [6] [Elem] (ppb/g of filter) [first occurrence]
# #     [7] [Elem] (ppb/g of filter) [second occurrence]
# #     [8] [Elem] (ppb)             [second occurrence]
# #     [9] µg/dm^2/day
# # - In 'oes': each element block has 5 columns:
# #     [0] [Elem] (ppm)             [first occurrence]
# #     [1] [Elem] (ppm/g of filter) [first occurrence]
# #     [2] [Elem] (ppm/g of filter) [second occurrence]
# #     [3] [Elem] (ppm)             [second occurrence]
# #     [4] mg/dm^2/day


# # -----------------------------------------------------------------------------
# # Data Loading, Deduplication & Column Remapping
# # -----------------------------------------------------------------------------
# def _make_unique_headers(raw_columns) -> list[str]:
#     """
#     Convert raw Excel column names into unique strings so pandas/Streamlit never
#     return a DataFrame instead of a Series when indexing a column name.
#     """
#     seen = {}
#     unique_cols = []
#     for col in raw_columns:
#         base = "Unnamed" if pd.isna(col) else str(col).strip()
#         count = seen.get(base, 0) + 1
#         seen[base] = count
#         if count == 1:
#             unique_cols.append(base)
#         else:
#             unique_cols.append(f"{base} [dup{count}]")
#     return unique_cols


# def remap_geochem_columns(df_raw: pd.DataFrame, sheet_name: str):
#     """
#     Deduplicate raw headers and create clean, unambiguous column names for
#     duplicated element unit columns in 'ms' and 'oes' sheets.

#     Returns:
#         df_mapped (pd.DataFrame): Copy of dataframe with unique/remapped names.
#         meta (dict): Dictionaries mapping element symbols, canonical unit keys,
#                      and human-readable labels to actual column names.
#     """
#     df = df_raw.copy()
#     df.columns = _make_unique_headers(df.columns)

#     sheet_key = sheet_name.strip().lower()
#     elements = MS_ELEMENTS if sheet_key == "ms" else OES_ELEMENTS

#     # Rename map: old_unique_col_name -> new_clean_col_name
#     rename_map = {}

#     # Track element -> {unit_role: clean_col_name}
#     element_unit_map = {el: {} for el in elements}
#     # Primary concentration column per element (ppb for MS, ppm for OES)
#     primary_conc_cols = []
#     # All numeric/analytical element columns (excluding flags/text if any)
#     all_element_cols = []

#     if sheet_key == "ms":
#         # Anchor each element block at "[Elem] (%)" and step through the 10-col block
#         for el in elements:
#             anchor = f"[{el}] (%)"
#             if anchor not in df.columns:
#                 continue
#             start_idx = df.columns.get_loc(anchor)
#             if isinstance(start_idx, (slice, np.ndarray)):
#                 start_idx = int(np.flatnonzero(start_idx)[0])

#             block_cols = list(df.columns[start_idx : start_idx + 10])
#             slot_names = [
#                 f"{el} [% #1]",
#                 f"{el} [%/g filter #1]",
#                 f"{el} [%/g filter #2]",
#                 f"{el} [% #2]",
#                 f"{el} [Mult req]",
#                 f"{el} [ppb #1]",
#                 f"{el} [ppb/g filter #1]",
#                 f"{el} [ppb/g filter #2]",
#                 f"{el} [ppb #2]",
#                 f"{el} [ug/dm2/day]",
#             ]
#             role_keys = [
#                 "pct_1",
#                 "pct_per_g_1",
#                 "pct_per_g_2",
#                 "pct_2",
#                 "mult_req",
#                 "ppb_1",
#                 "ppb_per_g_1",
#                 "ppb_per_g_2",
#                 "ppb_2",
#                 "flux_ug_dm2_day",
#             ]

#             for orig_c, new_c, role in zip(block_cols, slot_names, role_keys):
#                 rename_map[orig_c] = new_c
#                 element_unit_map[el][role] = new_c
#                 if role != "mult_req":
#                     all_element_cols.append(new_c)

#             if "ppb_1" in element_unit_map[el]:
#                 primary_conc_cols.append(element_unit_map[el]["ppb_1"])

#     else:
#         # 'oes' sheet: anchor each element block at "[Elem] (ppm)" (5 columns per element)
#         for el in elements:
#             anchor = f"[{el}] (ppm)"
#             if anchor not in df.columns:
#                 continue
#             start_idx = df.columns.get_loc(anchor)
#             if isinstance(start_idx, (slice, np.ndarray)):
#                 start_idx = int(np.flatnonzero(start_idx)[0])

#             block_cols = list(df.columns[start_idx : start_idx + 5])
#             slot_names = [
#                 f"{el} [ppm #1]",
#                 f"{el} [ppm/g filter #1]",
#                 f"{el} [ppm/g filter #2]",
#                 f"{el} [ppm #2]",
#                 f"{el} [mg/dm2/day]",
#             ]
#             role_keys = [
#                 "ppm_1",
#                 "ppm_per_g_1",
#                 "ppm_per_g_2",
#                 "ppm_2",
#                 "flux_mg_dm2_day",
#             ]

#             for orig_c, new_c, role in zip(block_cols, slot_names, role_keys):
#                 rename_map[orig_c] = new_c
#                 element_unit_map[el][role] = new_c
#                 all_element_cols.append(new_c)

#             if "ppm_1" in element_unit_map[el]:
#                 primary_conc_cols.append(element_unit_map[el]["ppm_1"])

#     df = df.rename(columns=rename_map)

#     # Coerce analytical element columns to numeric safely
#     for col in all_element_cols:
#         if col in df.columns:
#             df[col] = pd.to_numeric(df[col], errors="coerce")

#     # Coerce key numeric metadata columns if present
#     for num_meta in [
#         "Distance (m)",
#         "Days in Field",
#         "Change in mass (g)",
#         "Change in mass (mg)",
#         "(mg/m2/day)",
#         "(mg/dm2/day)",
#         "Geochem quarter weight (g)",
#     ]:
#         if num_meta in df.columns:
#             df[num_meta] = pd.to_numeric(df[num_meta], errors="coerce")

#     meta = {
#         "sheet_key": sheet_key,
#         "elements": [el for el in elements if len(element_unit_map[el]) > 0],
#         "element_unit_map": element_unit_map,
#         "primary_conc_cols": primary_conc_cols,
#         "all_element_cols": all_element_cols,
#         "rename_map": rename_map,
#     }
#     return df, meta


# @st.cache_data(show_spinner="Reading Excel workbook...")
# def load_excel_sheet(file_bytes: bytes | None, local_path: str, sheet_name: str) -> pd.DataFrame:
#     """Load a sheet from an uploaded .xlsx byte buffer or a local fallback path."""
#     if file_bytes is not None:
#         from io import BytesIO
#         return pd.read_excel(BytesIO(file_bytes), sheet_name=sheet_name)
#     return pd.read_excel(local_path, sheet_name=sheet_name)


# def clean_negatives_and_nans(
#     df_in: pd.DataFrame,
#     target_cols: list[str],
#     nan_strategy: str = "Keep as NaN",
# ) -> tuple[pd.DataFrame, dict]:
#     """
#     Handle negative values and missing values (NaNs) BEFORE seasonal levelling.

#     Negative values in target_cols are replaced with:
#         min_positive_value / sqrt(2)
#     (falling back to a small positive constant if a column has no positive values).
#     """
#     df = df_in.copy()
#     replacement_log = {}

#     for col in target_cols:
#         if col not in df.columns:
#             continue
#         series = pd.to_numeric(df[col], errors="coerce")
#         pos_vals = series[series > 0]
#         neg_mask = series < 0

#         if neg_mask.any():
#             if not pos_vals.empty:
#                 min_val = float(pos_vals.min())
#                 repl_val = min_val / np.sqrt(2.0)
#             else:
#                 min_val = np.nan
#                 repl_val = 1e-6

#             series.loc[neg_mask] = repl_val
#             replacement_log[col] = {
#                 "neg_count": int(neg_mask.sum()),
#                 "min_pos": min_val,
#                 "replacement": float(repl_val),
#             }

#         df[col] = series

#     # Optional NaN handling prior to levelling
#     if nan_strategy == "Fill with column median" and target_cols:
#         valid_cols = [c for c in target_cols if c in df.columns]
#         df[valid_cols] = df[valid_cols].fillna(df[valid_cols].median(numeric_only=True))
#     elif nan_strategy == "Fill with 0" and target_cols:
#         valid_cols = [c for c in target_cols if c in df.columns]
#         df[valid_cols] = df[valid_cols].fillna(0.0)

#     return df, replacement_log


# def apply_seasonal_levelling(
#     df_in: pd.DataFrame,
#     target_cols: list[str],
#     method: str = "MedianShift",
#     reference_season: str | None = None,
# ) -> pd.DataFrame:
#     """
#     Level selected numerical columns across 'Season' relative to a reference season.
#     Runs AFTER negative/NaN cleaning and ONLY when seasonal levelling is enabled.
#     """
#     if "Season" not in df_in.columns or not target_cols:
#         return df_in.copy()

#     df = df_in.copy()
#     seasons = [s for s in df["Season"].dropna().unique()]
#     if len(seasons) < 2:
#         return df

#     ref_season = reference_season if reference_season in seasons else seasons[0]
#     ref_mask = df["Season"] == ref_season

#     for col in target_cols:
#         if col not in df.columns:
#             continue
#         s = pd.to_numeric(df[col], errors="coerce")
#         ref_vals = s[ref_mask].dropna()
#         if ref_vals.empty:
#             continue

#         leveled_series = s.copy()

#         for seas in seasons:
#             if seas == ref_season:
#                 continue
#             m = df["Season"] == seas
#             cur_vals = s[m].dropna()
#             if cur_vals.empty:
#                 continue

#             if method == "MedianShift":
#                 shift = float(ref_vals.median() - cur_vals.median())
#                 leveled_series.loc[m] = s.loc[m] + shift

#             elif method == "ZRobust":
#                 med_ref = float(ref_vals.median())
#                 med_cur = float(cur_vals.median())
#                 mad_ref = float(stats.median_abs_deviation(ref_vals, nan_policy="omit"))
#                 mad_cur = float(stats.median_abs_deviation(cur_vals, nan_policy="omit"))
#                 if mad_cur > 0 and mad_ref > 0:
#                     leveled_series.loc[m] = ((s.loc[m] - med_cur) / mad_cur) * mad_ref + med_ref
#                 else:
#                     leveled_series.loc[m] = s.loc[m] + (med_ref - med_cur)

#             elif method == "ZScore":
#                 mean_ref = float(ref_vals.mean())
#                 mean_cur = float(cur_vals.mean())
#                 std_ref = float(ref_vals.std())
#                 std_cur = float(cur_vals.std())
#                 if pd.notna(std_cur) and std_cur > 0 and pd.notna(std_ref) and std_ref > 0:
#                     leveled_series.loc[m] = ((s.loc[m] - mean_cur) / std_cur) * std_ref + mean_ref
#                 else:
#                     leveled_series.loc[m] = s.loc[m] + (mean_ref - mean_cur)

#         df[col] = leveled_series

#     return df


# # -----------------------------------------------------------------------------
# # Interactive Plotly Plotting Functions (Tabs 1 & 2)
# # -----------------------------------------------------------------------------
# from color_standards import (
#     adjust_hex_lightness,
#     get_element_color_map,
#     get_group_color_map,
#     get_season_shade_factors,
# )


# # def plot_interactive_histograms(
# #     dataframe: pd.DataFrame,
# #     cols_interest: list[str],
# #     log_scale: bool = True,
# #     n_cols: int = 4,
# #     n_bins: int | None = None,
# #     element_color_map: dict | None = None,
# #     split_by_season: bool = False,
# #     season_order: list[str] | None = None,
# # ) -> go.Figure:
# #     """
# #     Interactive Plotly multi-panel histograms.
# #     When split_by_season=True, seasons are overlaid together (`barmode='overlay'`)
# #     using lighter-to-darker shades of each element's standard color with transparency.
# #     """
# #     valid_cols = [c for c in cols_interest if c in dataframe.columns]
# #     n_plots = len(valid_cols)
# #     n_rows = int(np.ceil(n_plots / n_cols))

# #     fig = make_subplots(
# #         rows=n_rows,
# #         cols=n_cols,
# #         subplot_titles=valid_cols,
# #         vertical_spacing=0.12,
# #         horizontal_spacing=0.08,
# #     )

# #     has_season = split_by_season and ("Season" in dataframe.columns)
# #     if has_season:
# #         present = set(dataframe["Season"].dropna())
# #         ordered_seasons = (
# #             [s for s in season_order if s in present]
# #             if season_order
# #             else sorted(present, key=str)
# #         )
# #         # Include any unexpected season values not in SEASON_FILTER
# #         for s in sorted(present, key=str):
# #             if s not in ordered_seasons:
# #                 ordered_seasons.append(s)
# #         shade_factors = get_season_shade_factors(len(ordered_seasons))
# #     else:
# #         ordered_seasons = [None]
# #         shade_factors = [1.0]

# #     show_legend_once = {"mean": True, "median": True}
# #     season_legend_shown = set()

# #     for idx, col in enumerate(valid_cols):
# #         r = idx // n_cols + 1
# #         c = idx % n_cols + 1

# #         el_symbol = col.split(" ")[0]
# #         base_color = (
# #             element_color_map.get(el_symbol)
# #             if element_color_map and el_symbol in element_color_map
# #             else "#377eb8"
# #         )

# #         # Shared bin range across seasons in the same subplot for fair visual overlap
# #         all_series = pd.to_numeric(dataframe[col], errors="coerce").dropna()
# #         if log_scale:
# #             all_series = all_series[all_series > 0]
# #             all_vals = np.log10(all_series.to_numpy(dtype=float))
# #             x_label = f"log10({col})"
# #         else:
# #             all_vals = all_series.to_numpy(dtype=float)
# #             x_label = col

# #         if len(all_vals) == 0:
# #             continue

# #         bins_count = n_bins if n_bins is not None else max(5, len(all_vals) // 3)
# #         vmin, vmax = float(np.min(all_vals)), float(np.max(all_vals))
# #         bin_size = (vmax - vmin) / bins_count if vmax > vmin else 0.1
# #         y_max_global = 1

# #         for seas, shade in zip(ordered_seasons, shade_factors):
# #             if seas is not None:
# #                 sub_s = pd.to_numeric(
# #                     dataframe.loc[dataframe["Season"] == seas, col], errors="coerce"
# #                 ).dropna()
# #             else:
# #                 sub_s = pd.to_numeric(dataframe[col], errors="coerce").dropna()

# #             if log_scale:
# #                 sub_s = sub_s[sub_s > 0]
# #                 vals = np.log10(sub_s.to_numpy(dtype=float))
# #             else:
# #                 vals = sub_s.to_numpy(dtype=float)

# #             if len(vals) == 0:
# #                 continue

# #             bar_color = adjust_hex_lightness(base_color, shade)
# #             trace_name = str(seas) if seas is not None else col
# #             show_leg = (seas is not None) and (seas not in season_legend_shown)
# #             if show_leg:
# #                 season_legend_shown.add(seas)

# #             fig.add_trace(
# #                 go.Histogram(
# #                     x=vals,
# #                     xbins=dict(start=vmin, end=vmax + 1e-9, size=bin_size),
# #                     marker=dict(
# #                         color=bar_color,
# #                         line=dict(color="rgba(0,0,0,0.55)", width=0.8),
# #                     ),
# #                     opacity=0.52 if has_season else 0.85,
# #                     name=trace_name,
# #                     legendgroup=trace_name,
# #                     showlegend=show_leg,
# #                     hovertemplate=(
# #                         (f"Season: {seas}<br>" if seas is not None else "")
# #                         + f"{x_label}: %{{x:.3f}}<br>Count: %{{y}}<extra></extra>"
# #                     ),
# #                 ),
# #                 row=r,
# #                 col=c,
# #             )

# #             hist_counts, _ = np.histogram(vals, bins=bins_count, range=(vmin, vmax))
# #             if len(hist_counts) > 0:
# #                 y_max_global = max(y_max_global, int(hist_counts.max()))

# #             # Per-season or overall median/mean vertical lines
# #             med_val = float(np.median(vals))
# #             mean_val = float(np.mean(vals))

# #             fig.add_trace(
# #                 go.Scatter(
# #                     x=[med_val, med_val],
# #                     y=[0, y_max_global * 1.05],
# #                     mode="lines",
# #                     line=dict(
# #                         color=bar_color if has_season else "crimson",
# #                         width=2,
# #                         dash="dash",
# #                     ),
# #                     name="Median" if not has_season else f"Median ({seas})",
# #                     legendgroup="median" if not has_season else f"med_{seas}",
# #                     showlegend=show_legend_once["median"] if not has_season else False,
# #                     hovertemplate=(
# #                         (f"Season: {seas}<br>" if seas is not None else "")
# #                         + f"Median ({col}): {med_val:.3f}<extra></extra>"
# #                     ),
# #                 ),
# #                 row=r,
# #                 col=c,
# #             )
# #             if not has_season:
# #                 show_legend_once["median"] = False

# #             fig.add_trace(
# #                 go.Scatter(
# #                     x=[mean_val, mean_val],
# #                     y=[0, y_max_global * 1.05],
# #                     mode="lines",
# #                     line=dict(
# #                         color=bar_color if has_season else "black",
# #                         width=2,
# #                         dash="dot",
# #                     ),
# #                     name="Mean" if not has_season else f"Mean ({seas})",
# #                     legendgroup="mean" if not has_season else f"mean_{seas}",
# #                     showlegend=show_legend_once["mean"] if not has_season else False,
# #                     hovertemplate=(
# #                         (f"Season: {seas}<br>" if seas is not None else "")
# #                         + f"Mean ({col}): {mean_val:.3f}<extra></extra>"
# #                     ),
# #                 ),
# #                 row=r,
# #                 col=c,
# #             )
# #             if not has_season:
# #                 show_legend_once["mean"] = False

# #         fig.update_xaxes(title_text=x_label, row=r, col=c)
# #         fig.update_yaxes(title_text="Count", row=r, col=c)

# #     fig.update_layout(
# #         height=max(360, 320 * n_rows),
# #         title_text=(
# #             "Interactive Histograms (Overlaid by Season)"
# #             if has_season
# #             else "Interactive Histograms"
# #         ),
# #         barmode="overlay",
# #         hovermode="closest",
# #         template="plotly_white",
# #     )
# #     return fig
# def plot_interactive_histograms(
#     dataframe: pd.DataFrame,
#     cols_interest: list[str],
#     log_scale: bool = True,
#     n_cols: int = 4,
#     n_bins: int | None = None,
#     element_color_map: dict | None = None,
#     split_by_season: bool = False,
#     split_by_ref_group: bool = False,
#     season_order: list[str] | None = None,
# ) -> go.Figure:
#     """
#     Interactive Plotly multi-panel histograms with optional season overlay and/or
#     independent reference-group split (REF-1..3 background vs REF-4..5 site).
#     """
#     valid_cols = [c for c in cols_interest if c in dataframe.columns]
#     n_plots = len(valid_cols)
#     n_rows = int(np.ceil(n_plots / n_cols))

#     fig = make_subplots(
#         rows=n_rows,
#         cols=n_cols,
#         subplot_titles=valid_cols,
#         vertical_spacing=0.12,
#         horizontal_spacing=0.08,
#     )

#     has_season = split_by_season and ("Season" in dataframe.columns)
#     has_ref = split_by_ref_group and ("Ref_Group" in dataframe.columns)

#     if has_season:
#         present_s = set(dataframe["Season"].dropna())
#         ordered_seasons = (
#             [s for s in season_order if s in present_s]
#             if season_order
#             else sorted(present_s, key=str)
#         )
#         for s in sorted(present_s, key=str):
#             if s not in ordered_seasons:
#                 ordered_seasons.append(s)
#         season_shades = dict(
#             zip(ordered_seasons, get_season_shade_factors(len(ordered_seasons)))
#         )
#     else:
#         ordered_seasons = [None]
#         season_shades = {None: 1.0}

#     if has_ref:
#         present_r = set(dataframe["Ref_Group"].dropna())
#         ordered_refs = [r for r in REF_GROUP_ORDER if r in present_r]
#         for r_val in sorted(present_r, key=str):
#             if r_val not in ordered_refs:
#                 ordered_refs.append(r_val)
#         ref_shades = dict(
#             zip(ordered_refs, get_season_shade_factors(len(ordered_refs)))
#         )
#     else:
#         ordered_refs = [None]
#         ref_shades = {None: 1.0}

#     # Build (season, ref_group) combinations
#     strata = [
#         (seas, ref_g)
#         for seas in ordered_seasons
#         for ref_g in ordered_refs
#     ]
#     n_strata = max(len(strata), 1)
#     strata_shades = get_season_shade_factors(n_strata)

#     show_legend_once = {"mean": True, "median": True}
#     strata_legend_shown = set()

#     for idx, col in enumerate(valid_cols):
#         r = idx // n_cols + 1
#         c = idx % n_cols + 1

#         el_symbol = col.split(" ")[0]
#         base_color = (
#             element_color_map.get(el_symbol)
#             if element_color_map and el_symbol in element_color_map
#             else "#377eb8"
#         )

#         all_series = pd.to_numeric(dataframe[col], errors="coerce").dropna()
#         if log_scale:
#             all_series = all_series[all_series > 0]
#             all_vals = np.log10(all_series.to_numpy(dtype=float))
#             x_label = f"log10({col})"
#         else:
#             all_vals = all_series.to_numpy(dtype=float)
#             x_label = col

#         if len(all_vals) == 0:
#             continue

#         bins_count = n_bins if n_bins is not None else max(5, len(all_vals) // 3)
#         vmin, vmax = float(np.min(all_vals)), float(np.max(all_vals))
#         bin_size = (vmax - vmin) / bins_count if vmax > vmin else 0.1
#         y_max_global = 1
#         is_stratified = has_season or has_ref

#         for (seas, ref_g), shade in zip(strata, strata_shades):
#             mask = pd.Series(True, index=dataframe.index)
#             if seas is not None:
#                 mask &= dataframe["Season"] == seas
#             if ref_g is not None:
#                 mask &= dataframe["Ref_Group"] == ref_g

#             sub_s = pd.to_numeric(dataframe.loc[mask, col], errors="coerce").dropna()
#             if log_scale:
#                 sub_s = sub_s[sub_s > 0]
#                 vals = np.log10(sub_s.to_numpy(dtype=float))
#             else:
#                 vals = sub_s.to_numpy(dtype=float)

#             if len(vals) == 0:
#                 continue

#             bar_color = adjust_hex_lightness(base_color, shade) if is_stratified else base_color

#             label_parts = []
#             if seas is not None:
#                 label_parts.append(str(seas))
#             if ref_g is not None:
#                 label_parts.append(str(ref_g))
#             trace_name = " | ".join(label_parts) if label_parts else col

#             show_leg = is_stratified and (trace_name not in strata_legend_shown)
#             if show_leg:
#                 strata_legend_shown.add(trace_name)

#             hover_prefix = "".join(f"{p}<br>" for p in label_parts)

#             fig.add_trace(
#                 go.Histogram(
#                     x=vals,
#                     xbins=dict(start=vmin, end=vmax + 1e-9, size=bin_size),
#                     marker=dict(
#                         color=bar_color,
#                         line=dict(color="rgba(0,0,0,0.55)", width=0.8),
#                     ),
#                     opacity=0.50 if is_stratified else 0.85,
#                     name=trace_name,
#                     legendgroup=trace_name,
#                     showlegend=show_leg,
#                     hovertemplate=(
#                         hover_prefix
#                         + f"{x_label}: %{{x:.3f}}<br>Count: %{{y}}<extra></extra>"
#                     ),
#                 ),
#                 row=r,
#                 col=c,
#             )

#             hist_counts, _ = np.histogram(vals, bins=bins_count, range=(vmin, vmax))
#             if len(hist_counts) > 0:
#                 y_max_global = max(y_max_global, int(hist_counts.max()))

#             med_val = float(np.median(vals))
#             mean_val = float(np.mean(vals))

#             fig.add_trace(
#                 go.Scatter(
#                     x=[med_val, med_val],
#                     y=[0, y_max_global * 1.05],
#                     mode="lines",
#                     line=dict(
#                         color=bar_color if is_stratified else "crimson",
#                         width=2,
#                         dash="dash",
#                     ),
#                     name="Median" if not is_stratified else f"Median ({trace_name})",
#                     legendgroup="median" if not is_stratified else f"med_{trace_name}",
#                     showlegend=show_legend_once["median"] if not is_stratified else False,
#                     hovertemplate=hover_prefix + f"Median ({col}): {med_val:.3f}<extra></extra>",
#                 ),
#                 row=r,
#                 col=c,
#             )
#             if not is_stratified:
#                 show_legend_once["median"] = False

#             fig.add_trace(
#                 go.Scatter(
#                     x=[mean_val, mean_val],
#                     y=[0, y_max_global * 1.05],
#                     mode="lines",
#                     line=dict(
#                         color=bar_color if is_stratified else "black",
#                         width=2,
#                         dash="dot",
#                     ),
#                     name="Mean" if not is_stratified else f"Mean ({trace_name})",
#                     legendgroup="mean" if not is_stratified else f"mean_{trace_name}",
#                     showlegend=show_legend_once["mean"] if not is_stratified else False,
#                     hovertemplate=hover_prefix + f"Mean ({col}): {mean_val:.3f}<extra></extra>",
#                 ),
#                 row=r,
#                 col=c,
#             )
#             if not is_stratified:
#                 show_legend_once["mean"] = False

#         fig.update_xaxes(title_text=x_label, row=r, col=c)
#         fig.update_yaxes(title_text="Count", row=r, col=c)

#     fig.update_layout(
#         height=max(360, 320 * n_rows),
#         title_text="Interactive Histograms",
#         barmode="overlay",
#         hovermode="closest",
#         template="plotly_white",
#     )
#     return fig

# def plot_interactive_boxplots(
#     dataframe: pd.DataFrame,
#     cols_plot: list[str],
#     group_col: str,
#     group_color_map: dict,
#     id_col: str = "Sample ID",
#     n_cols: int = 2,
#     point_mode: str | bool = "outliers",
#     log_scale: bool = True,
#     log_floor: float = 1e-6,
#     split_by_season: bool = False,
#     season_order: list[str] | None = None,
# ) -> go.Figure:
#     """
#     Interactive Plotly boxplots grouped by Transect or Distance (m) with Sample ID
#     on hover. When split_by_season=True, plots seasons side-by-side within each
#     Transect/Distance using lighter-to-darker shades of the group color.
#     """
#     valid_cols = [c for c in cols_plot if c in dataframe.columns]
#     n_plots = len(valid_cols)
#     n_rows = int(np.ceil(n_plots / n_cols))

#     fig = make_subplots(
#         rows=n_rows,
#         cols=n_cols,
#         subplot_titles=valid_cols,
#         vertical_spacing=0.14,
#         horizontal_spacing=0.08,
#     )

#     groups_present = [
#         g for g in group_color_map.keys() if g in set(dataframe[group_col].dropna())
#     ]
#     has_id = id_col in dataframe.columns
#     has_season = split_by_season and ("Season" in dataframe.columns)

#     if has_season:
#         present_seasons = set(dataframe["Season"].dropna())
#         ordered_seasons = (
#             [s for s in season_order if s in present_seasons]
#             if season_order
#             else sorted(present_seasons, key=str)
#         )
#         for s in sorted(present_seasons, key=str):
#             if s not in ordered_seasons:
#                 ordered_seasons.append(s)
#         shade_factors = get_season_shade_factors(len(ordered_seasons))
#     else:
#         ordered_seasons = [None]
#         shade_factors = [1.0]

#     legend_shown = set()

#     for idx, col in enumerate(valid_cols):
#         r = idx // n_cols + 1
#         c = idx % n_cols + 1

#         cols_needed = (
#             [group_col, col]
#             + ([id_col] if has_id else [])
#             + (["Season"] if has_season else [])
#         )
#         sub = dataframe[cols_needed].copy()
#         sub[col] = pd.to_numeric(sub[col], errors="coerce")
#         sub = sub.dropna(subset=[group_col, col])

#         if log_scale:
#             sub = sub[np.isfinite(sub[col])]
#             if log_floor is not None:
#                 sub[col] = sub[col].clip(lower=log_floor)
#             else:
#                 sub = sub[sub[col] > 0]

#         if not has_season:
#             # Single box per Transect / Distance
#             for grp in groups_present:
#                 grp_df = sub[sub[group_col] == grp]
#                 if grp_df.empty:
#                     continue

#                 grp_vals = grp_df[col].to_numpy(dtype=float)
#                 grp_ids = (
#                     grp_df[id_col].astype(str).tolist()
#                     if has_id
#                     else [str(i) for i in grp_df.index]
#                 )

#                 show_leg = grp not in legend_shown
#                 if show_leg:
#                     legend_shown.add(grp)

#                 fig.add_trace(
#                     go.Box(
#                         x=[str(grp)] * len(grp_vals),
#                         y=grp_vals,
#                         customdata=grp_ids,
#                         name=str(grp),
#                         legendgroup=str(grp),
#                         showlegend=show_leg,
#                         width=0.55,
#                         fillcolor=group_color_map[grp],
#                         line=dict(color="#222222", width=1.5),
#                         marker=dict(
#                             color=group_color_map[grp],
#                             size=6,
#                             line=dict(color="#222222", width=0.7),
#                         ),
#                         boxpoints=point_mode,
#                         jitter=0.25,
#                         pointpos=0.0,
#                         hovertemplate=(
#                             f"<b>Sample ID: %{{customdata}}</b><br>"
#                             f"{group_col}: {grp}<br>"
#                             f"{col}: %{{y:.4g}}<extra></extra>"
#                         ),
#                     ),
#                     row=r,
#                     col=c,
#                 )
#         else:
#             # Side-by-side seasonal boxes per Transect / Distance
#             for seas, shade in zip(ordered_seasons, shade_factors):
#                 seas_df = sub[sub["Season"] == seas]
#                 if seas_df.empty:
#                     continue

#                 x_all, y_all, ids_all = [], [], []
#                 for grp in groups_present:
#                     g_sub = seas_df[seas_df[group_col] == grp]
#                     if g_sub.empty:
#                         continue
#                     vals = g_sub[col].to_numpy(dtype=float)
#                     ids = (
#                         g_sub[id_col].astype(str).tolist()
#                         if has_id
#                         else [str(i) for i in g_sub.index]
#                     )
#                     x_all.extend([str(grp)] * len(vals))
#                     y_all.extend(vals.tolist())
#                     ids_all.extend(ids)

#                 if not x_all:
#                     continue

#                 # Neutral grey shaded by season in legend while keeping distinct tones
#                 seas_color = adjust_hex_lightness("#4c78a8", shade)
#                 show_leg = seas not in legend_shown
#                 if show_leg:
#                     legend_shown.add(seas)

#                 fig.add_trace(
#                     go.Box(
#                         x=x_all,
#                         y=y_all,
#                         customdata=ids_all,
#                         name=str(seas),
#                         legendgroup=str(seas),
#                         offsetgroup=str(seas),
#                         showlegend=show_leg,
#                         fillcolor=seas_color,
#                         line=dict(color="#222222", width=1.3),
#                         marker=dict(
#                             color=seas_color,
#                             size=5,
#                             line=dict(color="#222222", width=0.6),
#                         ),
#                         boxpoints=point_mode,
#                         jitter=0.25,
#                         pointpos=0.0,
#                         hovertemplate=(
#                             f"<b>Sample ID: %{{customdata}}</b><br>"
#                             f"Season: {seas}<br>"
#                             f"{group_col}: %{{x}}<br>"
#                             f"{col}: %{{y:.4g}}<extra></extra>"
#                         ),
#                     ),
#                     row=r,
#                     col=c,
#                 )

#         if log_scale:
#             fig.update_yaxes(type="log", row=r, col=c)
#         fig.update_xaxes(
#             title_text=group_col,
#             categoryorder="array",
#             categoryarray=[str(g) for g in groups_present],
#             row=r,
#             col=c,
#         )
#         fig.update_yaxes(title_text=col, row=r, col=c)

#     fig.update_layout(
#         height=max(420, 390 * n_rows),
#         title_text=(
#             f"Interactive Boxplots by {group_col} (Side-by-Side by Season)"
#             if has_season
#             else f"Interactive Boxplots by {group_col}"
#         ),
#         boxmode="group" if has_season else "overlay",
#         boxgroupgap=0.25,
#         boxgap=0.12,
#         template="plotly_white",
#     )
#     return fig
# # -----------------------------------------------------------------------------
# # 1. Updated Interactive Boxplots (with Sample ID on hover & clean boxes)
# # -----------------------------------------------------------------------------
# # def plot_interactive_boxplots(
# #     dataframe: pd.DataFrame,
# #     cols_plot: list[str],
# #     group_col: str,
# #     group_color_map: dict,
# #     id_col: str = "Sample ID",
# #     n_cols: int = 2,
# #     point_mode: str = "outliers",  # "outliers", "all", or False
# #     log_scale: bool = True,
# #     log_floor: float = 1e-6,
# #     show_points: bool = True,
# # ) -> go.Figure:
# #     """
# #     Create interactive Plotly boxplots grouped by Transect or Distance (m)
# #     with Sample ID shown on hover and consistent standard group colors.
# #     """
# #     valid_cols = [c for c in cols_plot if c in dataframe.columns]
# #     n_plots = len(valid_cols)
# #     n_rows = int(np.ceil(n_plots / n_cols))

# #     fig = make_subplots(
# #         rows=n_rows,
# #         cols=n_cols,
# #         subplot_titles=valid_cols,
# #         vertical_spacing=0.14,
# #         horizontal_spacing=0.08,
# #     )

# #     groups_present = [
# #         g for g in group_color_map.keys() if g in set(dataframe[group_col].dropna())
# #     ]
# #     legend_shown = set()

# #     has_id = id_col in dataframe.columns

# #     for idx, col in enumerate(valid_cols):
# #         r = idx // n_cols + 1
# #         c = idx % n_cols + 1

# #         cols_needed = [group_col, col] + ([id_col] if has_id else [])
# #         sub = dataframe[cols_needed].copy()
# #         sub[col] = pd.to_numeric(sub[col], errors="coerce")
# #         sub = sub.dropna(subset=[group_col, col])

# #         if log_scale:
# #             sub = sub[np.isfinite(sub[col])]
# #             if log_floor is not None:
# #                 sub[col] = sub[col].clip(lower=log_floor)
# #             else:
# #                 sub = sub[sub[col] > 0]

# #         for grp in groups_present:
# #             grp_df = sub[sub[group_col] == grp]
# #             if grp_df.empty:
# #                 continue

# #             grp_vals = grp_df[col].to_numpy(dtype=float)
# #             grp_ids = (
# #                 grp_df[id_col].astype(str).tolist()
# #                 if has_id
# #                 else [str(i) for i in grp_df.index]
# #             )

# #             show_leg = grp not in legend_shown
# #             if show_leg:
# #                 legend_shown.add(grp)

# #             fig.add_trace(
# #                 go.Box(
# #                     x=[str(grp)] * len(grp_vals),
# #                     y=grp_vals,
# #                     text=grp_ids,
# #                     customdata=grp_ids,
# #                     name=str(grp),
# #                     legendgroup=str(grp),
# #                     showlegend=show_leg,
# #                     width=0.55,
# #                     fillcolor=group_color_map[grp],
# #                     line=dict(color="#222222", width=1.5),
# #                     marker=dict(
# #                         color=group_color_map[grp],
# #                         size=6,
# #                         line=dict(color="#222222", width=0.7),
# #                     ),
# #                     # boxpoints=point_mode,
# #                     boxpoints="all" if show_points else "outliers",
# #                     jitter=0.25,
# #                     pointpos=0.0,
# #                     hovertemplate=(
# #                         f"<b>Sample ID: %{{customdata}}</b><br>"
# #                         f"{group_col}: {grp}<br>"
# #                         f"{col}: %{{y:.4g}}<extra></extra>"
# #                     ),
# #                 ),
# #                 row=r,
# #                 col=c,
# #             )

# #         if log_scale:
# #             fig.update_yaxes(type="log", row=r, col=c)
# #         fig.update_xaxes(title_text=group_col, row=r, col=c)
# #         fig.update_yaxes(title_text=col, row=r, col=c)

# #     fig.update_layout(
# #         height=max(400, 380 * n_rows),
# #         title_text=f"Interactive Boxplots by {group_col}",
# #         boxmode="overlay",
# #         template="plotly_white",
# #     )
# #     return fig


# # -----------------------------------------------------------------------------
# # 2. Symlog Helper & Updated PCA Score Plot
# # -----------------------------------------------------------------------------
# def symlog_array(values: np.ndarray, linthresh: float = 1.0) -> np.ndarray:
#     """
#     Symmetric log transform matching Matplotlib's symlog behavior:
#     linear near 0 (|x| <= linthresh), logarithmic beyond linthresh.
#     """
#     arr = np.asarray(values, dtype=float)
#     lt = max(float(linthresh), 1e-12)
#     # Smoothly continuous at +/- linthresh in value and derivative:
#     # For |u| <= 1: u ; for |u| > 1: sign(u) * (1 + ln10(|u|))
#     u = arr / lt
#     abs_u = np.abs(u)
#     transformed_u = np.where(
#         abs_u <= 1.0,
#         u,
#         np.sign(u) * (1.0 + np.log10(np.maximum(abs_u, 1.0))),
#     )
#     return transformed_u * lt


# def _symlog_ticks(min_orig: float, max_orig: float, linthresh: float = 1.0):
#     """Generate clean tick positions (in transformed space) and original labels."""
#     candidates = [
#         -1000, -100, -10, -linthresh, 0.0, linthresh, 10, 100, 1000
#     ]
#     # Deduplicate while preserving order
#     uniq_orig = []
#     for v in candidates:
#         if min_orig * 1.1 <= v <= max_orig * 1.1 and all(abs(v - u) > 1e-9 for u in uniq_orig):
#             uniq_orig.append(float(v))
#     if not uniq_orig:
#         uniq_orig = [float(min_orig), 0.0, float(max_orig)]

#     tickvals = symlog_array(np.array(uniq_orig, dtype=float), linthresh=linthresh).tolist()
#     ticktext = [f"{v:g}" for v in uniq_orig]
#     return tickvals, ticktext


# def plot_interactive_pca_scores(
#     scores_df: pd.DataFrame,
#     pc_x: str,
#     pc_y: str,
#     color_by: str,
#     group_color_map: dict | None = None,
#     annotate_col: str | None = None,
#     symlog_pca: bool = True,  # "linear" or "symlog"
#     linthresh: float = 1.0,
# ) -> go.Figure:
#     """
#     Interactive PCA score plot supporting both linear and symmetric-log (symlog)
#     axes to spread out dense central clusters while keeping outliers visible.
#     """
#     hover_cols = [
#         c for c in ["Sample ID" ]
#         if c in scores_df.columns
#     ]

#     color_discrete_map = None
#     if color_by in ("Transect", "Distance (m)") and group_color_map:
#         color_discrete_map = {str(k): v for k, v in group_color_map.items()}

#     plot_df = scores_df.copy()
#     raw_x = plot_df[pc_x].to_numpy(dtype=float)
#     raw_y = plot_df[pc_y].to_numpy(dtype=float)
#     plot_df["_orig_x"] = raw_x
#     plot_df["_orig_y"] = raw_y

#     if color_by in plot_df.columns:
#         plot_df[color_by] = plot_df[color_by].astype(str)

#     if symlog_pca:
#         plot_df["_plot_x"] = symlog_array(raw_x, linthresh=linthresh)
#         plot_df["_plot_y"] = symlog_array(raw_y, linthresh=linthresh)
#         x_col, y_col = "_plot_x", "_plot_y"
#         x_title = f"{pc_x} (symlog, linthresh={linthresh:g})"
#         y_title = f"{pc_y} (symlog, linthresh={linthresh:g})"
#     else:
#         x_col, y_col = pc_x, pc_y
#         x_title, y_title = pc_x, pc_y

#     # extra_hover = {c: True for c in hover_cols}
#     # extra_hover["_orig_x"] = ":.3f"
#     # extra_hover["_orig_y"] = ":.3f"

#     fig = px.scatter(
#         plot_df,
#         x=x_col,
#         y=y_col,
#         color=color_by if color_by in plot_df.columns else None,
#         color_discrete_map=color_discrete_map,
#         hover_data=hover_cols,
#         text=annotate_col if annotate_col and annotate_col in plot_df.columns else None,
#         title=f"PCA Scores: {pc_x} vs {pc_y}  — Colored by {color_by}",
#         template="plotly_white",
#         height=540,
#     )

#     if symlog_pca:
#         xt_vals, xt_text = _symlog_ticks(float(np.nanmin(raw_x)), float(np.nanmax(raw_x)), linthresh)
#         yt_vals, yt_text = _symlog_ticks(float(np.nanmin(raw_y)), float(np.nanmax(raw_y)), linthresh)
#         fig.update_xaxes(tickmode="array", tickvals=xt_vals, ticktext=xt_text)
#         fig.update_yaxes(tickmode="array", tickvals=yt_vals, ticktext=yt_text)

#     if annotate_col:
#         fig.update_traces(textposition="top center", textfont=dict(size=10))
#     fig.update_traces(marker=dict(size=9, opacity=0.85, line=dict(width=0.6, color="white")))
#     fig.update_layout(
#         xaxis_title=x_title,
#         yaxis_title=y_title,
#         legend_title_text=color_by,
#     )
#     return fig

# def get_top_recurring_samples(
#     df: pd.DataFrame,
#     target_cols: list[str],
#     top_n: int = 5,
#     id_col: str = "Sample ID",
# ) -> pd.DataFrame:
#     """
#     Identify samples that repeatedly appear in the top-N highest concentrations
#     across target_cols.
#     """
#     records = []
#     for col in target_cols:
#         if col not in df.columns:
#             continue
#         s = pd.to_numeric(df[col], errors="coerce").dropna()
#         top_idx = s.nlargest(min(top_n, len(s))).index
#         for rank, idx in enumerate(top_idx, start=1):
#             records.append(
#                 {
#                     "row_index": idx,
#                     id_col: df.loc[idx, id_col] if id_col in df.columns else idx,
#                     "Transect": df.loc[idx, "Transect"] if "Transect" in df.columns else np.nan,
#                     "Distance (m)": df.loc[idx, "Distance (m)"] if "Distance (m)" in df.columns else np.nan,
#                     "Season": df.loc[idx, "Season"] if "Season" in df.columns else np.nan,
#                     "element_col": col,
#                     "rank_in_col": rank,
#                     "value": float(df.loc[idx, col]),
#                 }
#             )

#     if not records:
#         return pd.DataFrame()

#     long_df = pd.DataFrame(records)
#     summary = (
#         long_df.groupby(["row_index", id_col], as_index=False)
#         .agg(
#             top_appearances=("element_col", "count"),
#             elements_featured=("element_col", lambda s: ", ".join(sorted(set(x.split(" ")[0] for x in s)))),
#             Transect=("Transect", "first"),
#             **{"Distance (m)": ("Distance (m)", "first"), "Season": ("Season", "first")},
#         )
#         .sort_values(by="top_appearances", ascending=False)
#         .reset_index(drop=True)
#     )
#     return summary


# def run_pca_and_clustering(
#     df_in: pd.DataFrame,
#     feature_cols: list[str],
#     n_clusters: int = 5,
#     n_components: int = 7,
#     random_state: int = 42,
# ):
#     """
#     Min-max normalize feature_cols, fit K-Means clusters, and fit PCA.
#     Returns a clean subset DataFrame aligned with PCA scores, cluster labels,
#     PCA model, components DataFrame, and loadings DataFrame.
#     """
#     valid_cols = [c for c in feature_cols if c in df_in.columns]
#     sub = df_in.dropna(subset=valid_cols).copy()
#     if len(sub) < 2 or len(valid_cols) < 2:
#         return None

#     feat_df = sub[valid_cols].astype(float)
#     denom = feat_df.max() - feat_df.min()
#     # Avoid division by zero for constant columns
#     norm_df = (feat_df - feat_df.min()) / denom.replace(0, np.nan)
#     norm_df = norm_df.fillna(0.0)

#     actual_clusters = min(n_clusters, len(sub))
#     kmeans = KMeans(n_clusters=actual_clusters, random_state=random_state, n_init=10)
#     cluster_labels = kmeans.fit_predict(norm_df)
#     sub["Cluster"] = [f"Cluster {k}" for k in cluster_labels]

#     max_pcs = min(n_components, len(valid_cols), len(sub) - 1)
#     pca = PCA(n_components=max_pcs)
#     scores = pca.fit_transform(norm_df)

#     pc_names = [f"PC{i + 1}" for i in range(max_pcs)]
#     scores_df = pd.DataFrame(scores, columns=pc_names, index=sub.index)
#     scores_df["Cluster"] = sub["Cluster"]
#     for meta_c in ["Sample ID", "Season", "Transect", "Distance (m)"]:
#         if meta_c in sub.columns:
#             scores_df[meta_c] = sub[meta_c]

#     # Clean element names for loadings columns
#     short_names = [c.split(" ")[0].lstrip("[") for c in valid_cols]
#     loadings_df = pd.DataFrame(pca.components_, columns=short_names, index=pc_names)

#     return {
#         "df_aligned": sub,
#         "norm_df": norm_df,
#         "kmeans": kmeans,
#         "pca": pca,
#         "scores_df": scores_df,
#         "loadings_df": loadings_df,
#         "pc_names": pc_names,
#     }


# def plot_interactive_scree(pca: PCA, threshold: float = 0.95) -> go.Figure:
#     """Interactive scree plot showing individual explained variance and cumulative variance."""
#     evr = pca.explained_variance_ratio_
#     cum_evr = np.cumsum(evr)
#     pcs = [f"PC{i + 1}" for i in range(len(evr))]
#     k_idx = int(np.argmax(cum_evr >= threshold))

#     fig = go.Figure()
#     fig.add_trace(
#         go.Bar(
#             x=pcs,
#             y=evr,
#             name="Explained Variance Ratio",
#             marker_color="#4c78a8",
#             opacity=0.8,
#             hovertemplate="%{x}: %{y:.1%}<extra></extra>",
#         )
#     )
#     fig.add_trace(
#         go.Scatter(
#             x=pcs,
#             y=cum_evr,
#             name="Cumulative Variance",
#             mode="lines+markers",
#             line=dict(color="#111111", width=2.5),
#             marker=dict(size=8),
#             hovertemplate="%{x} Cumulative: %{y:.1%}<extra></extra>",
#         )
#     )
#     fig.add_hline(
#         y=threshold,
#         line_dash="dash",
#         line_color="crimson",
#         annotation_text=f"{int(threshold * 100)}% Threshold ({pcs[k_idx]}: {cum_evr[k_idx]:.1%})",
#         annotation_position="top left",
#     )
#     fig.update_layout(
#         title="PCA Scree Plot & Cumulative Explained Variance",
#         xaxis_title="Principal Component",
#         yaxis_title="Explained Variance Ratio",
#         yaxis=dict(range=[0, 1.06]),
#         template="plotly_white",
#         height=420,
#     )
#     return fig

# # -----------------------------------------------------------------------------
# # 2. Symlog Helper & Updated PCA Score Plot
# # -----------------------------------------------------------------------------
# def symlog_array(values: np.ndarray, linthresh: float = 1.0) -> np.ndarray:
#     """
#     Symmetric log transform matching Matplotlib's symlog behavior:
#     linear near 0 (|x| <= linthresh), logarithmic beyond linthresh.
#     """
#     arr = np.asarray(values, dtype=float)
#     lt = max(float(linthresh), 1e-12)
#     # Smoothly continuous at +/- linthresh in value and derivative:
#     # For |u| <= 1: u ; for |u| > 1: sign(u) * (1 + ln10(|u|))
#     u = arr / lt
#     abs_u = np.abs(u)
#     transformed_u = np.where(
#         abs_u <= 1.0,
#         u,
#         np.sign(u) * (1.0 + np.log10(np.maximum(abs_u, 1.0))),
#     )
#     return transformed_u * lt


# def _symlog_ticks(min_orig: float, max_orig: float, linthresh: float = 1.0):
#     """Generate clean tick positions (in transformed space) and original labels."""
#     candidates = [
#         -1000, -100, -10, -linthresh, 0.0, linthresh, 10, 100, 1000
#     ]
#     # Deduplicate while preserving order
#     uniq_orig = []
#     for v in candidates:
#         if min_orig * 1.1 <= v <= max_orig * 1.1 and all(abs(v - u) > 1e-9 for u in uniq_orig):
#             uniq_orig.append(float(v))
#     if not uniq_orig:
#         uniq_orig = [float(min_orig), 0.0, float(max_orig)]

#     tickvals = symlog_array(np.array(uniq_orig, dtype=float), linthresh=linthresh).tolist()
#     ticktext = [f"{v:g}" for v in uniq_orig]
#     return tickvals, ticktext



# def plot_interactive_loadings_matrix(
#     loadings_df: pd.DataFrame,
#     selected_pcs: list[str],
#     element_color_map: dict,
# ) -> go.Figure:
#     """
#     Interactive matrix comparing selected PCs:
#     - Diagonal: Ordered bar chart of loadings for each PC (sorted by |loading|)
#     - Upper triangle: Interactive scatter of element loadings between PC_i and PC_j
#     - Lower triangle: Magnitude / cosine-like alignment scatter between PC_i and PC_j
#     """
#     m = len(selected_pcs)
#     fig = make_subplots(
#         rows=m,
#         cols=m,
#         subplot_titles=[
#             f"{pc_r} vs {pc_c}" if i != j else f"{pc_r} Ordered Loadings"
#             for i, pc_r in enumerate(selected_pcs)
#             for j, pc_c in enumerate(selected_pcs)
#         ],
#         horizontal_spacing=0.07,
#         vertical_spacing=0.10,
#     )

#     elements = list(loadings_df.columns)
#     legend_seen = set()

#     for i, pc_i in enumerate(selected_pcs):
#         for j, pc_j in enumerate(selected_pcs):
#             row_idx = i + 1
#             col_idx = j + 1

#             if i == j:
#                 # Diagonal: sorted by absolute loading, colored by element
#                 s = loadings_df.loc[pc_i]
#                 order = s.abs().sort_values(ascending=False).index
#                 s_ord = s.loc[order]
#                 colors = [element_color_map.get(el, "#377eb8") for el in s_ord.index]

#                 fig.add_trace(
#                     go.Bar(
#                         x=list(s_ord.index),
#                         y=s_ord.values,
#                         marker_color=colors,
#                         showlegend=False,
#                         hovertemplate="%{x}<br>Loading (" + pc_i + "): %{y:.3f}<extra></extra>",
#                     ),
#                     row=row_idx,
#                     col=col_idx,
#                 )
#                 fig.update_xaxes(title_text="Element (by |loading|)", row=row_idx, col=col_idx)
#                 fig.update_yaxes(title_text="Loading", row=row_idx, col=col_idx)

#             elif i < j:
#                 # Upper triangle: 2D loadings scatter (PC_j on x, PC_i on y)
#                 x_vals = loadings_df.loc[pc_j, elements].values
#                 y_vals = loadings_df.loc[pc_i, elements].values
#                 for el, xv, yv in zip(elements, x_vals, y_vals):
#                     show_leg = el not in legend_seen
#                     if show_leg:
#                         legend_seen.add(el)
#                     fig.add_trace(
#                         go.Scatter(
#                             x=[xv],
#                             y=[yv],
#                             mode="markers+text",
#                             text=[el],
#                             textposition="top center",
#                             textfont=dict(size=9),
#                             name=el,
#                             legendgroup=el,
#                             showlegend=show_leg,
#                             marker=dict(size=9, color=element_color_map.get(el, "#377eb8")),
#                             hovertemplate=f"{el}<br>{pc_j}: {xv:.3f}<br>{pc_i}: {yv:.3f}<extra></extra>",
#                         ),
#                         row=row_idx,
#                         col=col_idx,
#                     )
#                 fig.update_xaxes(title_text=pc_j, zeroline=True, row=row_idx, col=col_idx)
#                 fig.update_yaxes(title_text=pc_i, zeroline=True, row=row_idx, col=col_idx)

#             else:
#                 # Lower triangle: absolute loading magnitude comparison (|PC_j| vs |PC_i|)
#                 x_abs = np.abs(loadings_df.loc[pc_j, elements].values)
#                 y_abs = np.abs(loadings_df.loc[pc_i, elements].values)
#                 fig.add_trace(
#                     go.Scatter(
#                         x=x_abs,
#                         y=y_abs,
#                         mode="markers+text",
#                         text=elements,
#                         textposition="top center",
#                         textfont=dict(size=9),
#                         showlegend=False,
#                         marker=dict(
#                             size=9,
#                             color=[element_color_map.get(el, "#377eb8") for el in elements],
#                         ),
#                         hovertemplate="%{text}<br>|" + pc_j + "|: %{x:.3f}<br>|" + pc_i + "|: %{y:.3f}<extra></extra>",
#                     ),
#                     row=row_idx,
#                     col=col_idx,
#                 )
#                 fig.update_xaxes(title_text=f"|{pc_j}|", row=row_idx, col=col_idx)
#                 fig.update_yaxes(title_text=f"|{pc_i}|", row=row_idx, col=col_idx)

#     fig.update_layout(
#         height=max(450, 340 * m),
#         title_text="PCA Loadings Matrix (Diagonal: Ordered Bars | Upper: Loadings | Lower: |Loadings|)",
#         template="plotly_white",
#     )
#     return fig


# # -----------------------------------------------------------------------------
# # Sidebar: File Upload, Sheet Selection, Filters & Seasonal Levelling
# # -----------------------------------------------------------------------------
# st.title("🧪 Bulk Geochemical Data Explorer")

# with st.sidebar:
#     st.header("1. Workbook & Sheet")
#     uploaded_file = st.file_uploader(
#         "Drag and drop an .xlsx file here",
#         type=["xlsx"],
#         help="Defaults to sheet 'ms' if left as 'ms'. Falls back to local file only if nothing is uploaded.",
#     )
#     sheet_choice = st.selectbox(
#         "Worksheet name",
#         options=["ms", "oes"],
#         index=0,  # Default is 'ms'
#     )

#     st.divider()
#     st.header("2. Data Cleaning (Pre-Levelling)")
#     nan_strategy = st.selectbox(
#         "Missing value (NaN) handling before levelling",
#         options=["Keep as NaN", "Fill with column median", "Fill with 0"],
#         index=0,
#     )

#     st.divider()
#     st.header("3. Seasonal Levelling")
#     # Explicitly OFF by default as requested
#     enable_levelling = st.toggle(
#         "Enable Seasonal Levelling",
#         value=False,
#         help="Off by default. When enabled, levels selected numerical columns across seasons.",
#     )
#     levelling_method = st.selectbox(
#         "Levelling method",
#         options=["MedianShift", "ZRobust", "ZScore"],
#         index=0,
#         disabled=not enable_levelling,
#     )

# # Load raw sheet
# local_fallback_path = os.path.join(DEFAULT_ROOT, DEFAULT_FOLDER, DEFAULT_FILE)
# file_bytes = uploaded_file.getvalue() if uploaded_file is not None else None

# if file_bytes is None and not os.path.exists(local_fallback_path):
#     st.info(
#         "Please drag and drop an `.xlsx` file in the sidebar to begin "
#         f"(no local fallback file found at `{local_fallback_path}`)."
#     )
#     st.stop()

# df_raw = load_excel_sheet(
#     file_bytes=file_bytes,
#     local_path=local_fallback_path,
#     sheet_name=sheet_choice,
# )

# # Remap duplicated columns cleanly
# df_mapped, col_meta = remap_geochem_columns(df_raw, sheet_choice)

# import re

# REF_GROUP_ORDER = [
#     "Background Ref (REF-1..3)",
#     "Site Ref (REF-4..5)",
#     "Non-Reference",
# ]


# def classify_reference_samples(df_in: pd.DataFrame) -> pd.DataFrame:
#     """
#     Create an independent 'Ref_Group' column without altering 'Transect' or 'Distance (m)':
#     - REF-1, REF-2, REF-3 -> 'Background Ref (REF-1..3)'
#     - REF-4, REF-5 -> 'Site Ref (REF-4..5)'
#     - All other rows -> 'Non-Reference'
#     """
#     df = df_in.copy()
#     id_cols = [c for c in ["Sample ID", "Dust sampler_ID"] if c in df.columns]

#     def _detect_ref(row) -> str:
#         combined = " ".join(
#             str(row[c]) for c in id_cols if pd.notna(row[c])
#         ).upper()
#         # Match REF-1..3 or REF1..3 as a complete token (not followed by another digit)
#         if re.search(r"\bREF[-_]?[123](?!\d)", combined):
#             return "Background Ref (REF-1..3)"
#         # Match REF-4..5 or REF4..5 as a complete token
#         if re.search(r"\bREF[-_]?[45](?!\d)", combined):
#             return "Site Ref (REF-4..5)"
#         return "Non-Reference"

#     if id_cols:
#         df["Ref_Group"] = df.apply(_detect_ref, axis=1)
#     else:
#         df["Ref_Group"] = "Non-Reference"

#     return df

# ref_vals = [
#         r for r in REF_GROUP_ORDER if r in set(df_mapped["Ref_Group"].dropna())
#     ]
# selected_ref_groups = st.multiselect(
#     "Filter by Reference Type (REF-1..3 vs REF-4..5)",
#     options=ref_vals,
#     default=ref_vals,
# )
# if "Ref_Group" in df_filtered.columns and selected_ref_groups:
#     df_filtered = df_filtered[df_filtered["Ref_Group"].isin(selected_ref_groups)]

# # Choose unit slot for element analysis (defaults to primary ppb/ppm, or user can switch)
# with st.sidebar:
#     available_roles = sorted({
#         role
#         for roles in col_meta["element_unit_map"].values()
#         for role in roles.keys()
#         if role != "mult_req"
#     })
#     default_role = "ppb_1" if col_meta["sheet_key"] == "ms" else "ppm_1"
#     default_idx = available_roles.index(default_role) if default_role in available_roles else 0
#     selected_role = st.selectbox(
#         "Unit column role for element analysis",
#         options=available_roles,
#         index=default_idx,
#     )

# active_element_cols = [
#     col_meta["element_unit_map"][el][selected_role]
#     for el in col_meta["elements"]
#     if selected_role in col_meta["element_unit_map"][el]
# ]

# # Reference season selector (enabled once df_mapped is loaded)
# with st.sidebar:
#     season_options = (
#         [s for s in SEASON_FILTER if s in set(df_mapped["Season"].dropna())]
#         if "Season" in df_mapped.columns
#         else []
#     )
#     if not season_options and "Season" in df_mapped.columns:
#         season_options = list(df_mapped["Season"].dropna().unique())

#     ref_season = st.selectbox(
#         "Reference season for levelling",
#         options=season_options if season_options else ["N/A"],
#         index=0,
#         disabled=(not enable_levelling) or (not season_options),
#     )

#     st.divider()
#     st.header("4. Grouping & Sample Filters")
#     group_by_feature = st.radio(
#         "Standard color & grouping feature",
#         options=["Transect", "Distance (m)"],
#         index=0,
#     )

#     selected_seasons = st.multiselect(
#         "Filter by Season",
#         options=season_options,
#         default=season_options,
#     )

#     transect_vals = (
#         sorted(df_mapped["Transect"].dropna().unique(), key=str)
#         if "Transect" in df_mapped.columns
#         else []
#     )
#     selected_transects = st.multiselect(
#         "Filter by Transect",
#         options=transect_vals,
#         default=transect_vals,
#     )

#     if "Distance (m)" in df_mapped.columns and df_mapped["Distance (m)"].notna().any():
#         dist_vals = sorted(df_mapped["Distance (m)"].dropna().unique())
#         selected_distances = st.multiselect(
#             "Filter by Distance (m)",
#             options=dist_vals,
#             default=dist_vals,
#         )
#     else:
#         selected_distances = []

# # -----------------------------------------------------------------------------
# # Explicit Visible Banner Drawing Attention to Seasonal Levelling State
# # -----------------------------------------------------------------------------
# if not enable_levelling:
#     st.warning(
#         "**Seasonal Levelling is currently OFF (Default).** "
#         "Data shown across tabs reflects raw/cleaned values without cross-season levelling. "
#         "Toggle **Enable Seasonal Levelling** in the sidebar to apply season adjustments.",
#         icon="⚠️",
#     )
# else:
#     st.info(
#         f"**Seasonal Levelling is ON** — Method: **`{levelling_method}`** | "
#         f"Reference Season: **`{ref_season}`** (applied after negative/NaN cleaning).",
#         icon="ℹ️",
#     )

# # -----------------------------------------------------------------------------
# # Step A: Clean Negatives & NaNs BEFORE Levelling (Always Executed)
# # -----------------------------------------------------------------------------
# numeric_clean_targets = list(
#     dict.fromkeys(
#         active_element_cols
#         + [
#             c
#             for c in [
#                 "Change in mass (mg)",
#                 "(mg/dm2/day)",
#                 "Geochem quarter weight (g)",
#                 "Days in Field",
#                 "Distance (m)",
#             ]
#             if c in df_mapped.columns
#         ]
#     )
# )

# df_cleaned, neg_replacement_log = clean_negatives_and_nans(
#     df_mapped,
#     target_cols=numeric_clean_targets,
#     nan_strategy=nan_strategy,
# )

# # -----------------------------------------------------------------------------
# # Step B: Apply Seasonal Levelling Only If Active
# # -----------------------------------------------------------------------------
# if enable_levelling:
#     df_processed = apply_seasonal_levelling(
#         df_cleaned,
#         target_cols=active_element_cols,
#         method=levelling_method,
#         reference_season=ref_season,
#     )
# else:
#     df_processed = df_cleaned.copy()

# # Apply sidebar sample filters
# df_filtered = df_processed.copy()
# if "Season" in df_filtered.columns and selected_seasons:
#     df_filtered = df_filtered[df_filtered["Season"].isin(selected_seasons)]
# if "Transect" in df_filtered.columns and selected_transects:
#     df_filtered = df_filtered[df_filtered["Transect"].isin(selected_transects)]
# if "Distance (m)" in df_filtered.columns and selected_distances:
#     df_filtered = df_filtered[df_filtered["Distance (m)"].isin(selected_distances)]

# # Build consistent standard color maps for groups and elements
# group_series = (
#     df_filtered[group_by_feature]
#     if group_by_feature in df_filtered.columns
#     else pd.Series([], dtype=object)
# )
# group_color_map = get_group_color_map(group_series, group_type=group_by_feature)
# element_color_map = get_element_color_map(col_meta["elements"])

# # -----------------------------------------------------------------------------
# # Tabs (2 First Tabs Implemented + Remaining Tabs as Placeholders)
# # -----------------------------------------------------------------------------
# tab1, tab2, tab3, tab4, tab5 = st.tabs([
#     "1. Distributions & Top Filters",
#     "2. PCA & Clustering",
#     "3. Correlations (Placeholder)",
#     "4. Element Ratios (Placeholder)",
#     "5. Levelling Comparison (Placeholder)",
# ])

# # =============================================================================
# # TAB 1: Overview, Quantile Filter, Interactive Histograms/Boxplots & Top Filters
# # =============================================================================
# with tab1:
#     st.subheader(f"Dataset Overview — Sheet `{sheet_choice}`")

#     c1, c2, c3, c4 = st.columns(4)
#     c1.metric("Raw Rows", len(df_mapped))
#     c2.metric("Filtered Rows", len(df_filtered))
#     c3.metric("Elements Detected", len(col_meta["elements"]))
#     c4.metric("Negative-Replaced Cols", len(neg_replacement_log))

#     with st.expander("Inspect Column Remapping & Pre-Levelling Negative Replacements"):
#         st.write("**Remapped Element Columns (sample):**")
#         st.json({k: v for k, v in list(col_meta["rename_map"].items())[:15]})
#         if neg_replacement_log:
#             st.write("**Negative Value Replacements (min_positive / sqrt(2)):**")
#             st.dataframe(pd.DataFrame.from_dict(neg_replacement_log, orient="index"))
#         else:
#             st.caption("No negative values found in selected analytical columns.")

#     st.divider()
#     st.subheader("Quantile Filtering & Element Selection")

#     q_col1, q_col2, q_col3 = st.columns([2, 1, 1])
#     with q_col1:
#         selected_cols_t1 = st.multiselect(
#             "Select element columns to plot",
#             options=active_element_cols,
#             default=active_element_cols[: min(8, len(active_element_cols))],
#         )
#     with q_col2:
#         q_low, q_high = st.slider(
#             "Quantile filter range",
#             min_value=0.0,
#             max_value=1.0,
#             value=(0.0, 1.0),
#             step=0.01,
#             help="Filters rows within [q_low, q_high] quantiles of the selected quantile reference column.",
#         )
#     with q_col3:
#         q_ref_col = st.selectbox(
#             "Quantile filter column",
#             options=selected_cols_t1 if selected_cols_t1 else active_element_cols,
#             index=0,
#         )

#     df_tab1 = df_filtered.copy()
#     if q_ref_col in df_tab1.columns and (q_low > 0.0 or q_high < 1.0):
#         s_ref = pd.to_numeric(df_tab1[q_ref_col], errors="coerce")
#         low_thr = s_ref.quantile(q_low)
#         high_thr = s_ref.quantile(q_high)
#         df_tab1 = df_tab1[(s_ref >= low_thr) & (s_ref <= high_thr)]

#     # Interactive Histograms
#     st.markdown("### Interactive Histograms")
#     # Interactive Histograms controls
#     h_opt1, h_opt2, h_opt3, h_opt4 = st.columns(4)
#     with h_opt1:
#         hist_log = st.checkbox("Log10 scale (histograms)", value=True)
#     with h_opt2:
#         hist_split_season = st.checkbox("Overlay seasons (shaded)", value=True)
#     with h_opt3:
#         hist_ncols = st.number_input("Histogram columns", min_value=1, max_value=6, value=4)
#     with h_opt4:
#         auto_bins = st.checkbox("Auto bin count", value=True)
#         hist_bins = None if auto_bins else st.slider("Bins per histogram", 5, 80, 25)

#     if selected_cols_t1 and not df_tab1.empty:
#         fig_hist = plot_interactive_histograms(
#             dataframe=df_tab1,
#             cols_interest=selected_cols_t1,
#             log_scale=hist_log,
#             n_cols=int(hist_ncols),
#             n_bins=hist_bins,
#             element_color_map=element_color_map,
#             split_by_season=hist_split_season,
#             season_order=SEASON_FILTER,
#         )
#         st.plotly_chart(fig_hist, use_container_width=True)

#     # Interactive Boxplots controls
#     b_opt1, b_opt2, b_opt3, b_opt4 = st.columns(4)
#     with b_opt1:
#         box_log = st.checkbox("Log y-axis (boxplots)", value=True, key=64)
#     with b_opt2:
#         box_split_season = st.checkbox("Separate seasons side-by-side", value=False)
#     with b_opt3:
#         point_opt = st.selectbox(
#             "Boxplot points",
#             options=["outliers", "all", "False"],
#             index=0,
#         )
#     with b_opt4:
#         box_ncols = st.number_input("Boxplot columns", min_value=1, max_value=4, value=2, key=78)

#     if selected_cols_t1 and group_by_feature in df_tab1.columns and not df_tab1.empty:
#         fig_box = plot_interactive_boxplots(
#             dataframe=df_tab1,
#             cols_plot=selected_cols_t1,
#             group_col=group_by_feature,
#             group_color_map=group_color_map,
#             id_col="Sample ID",
#             n_cols=int(box_ncols),
#             point_mode=False if point_opt == "False" else point_opt,
#             log_scale=box_log,
#             split_by_season=box_split_season,
#             season_order=SEASON_FILTER,
#         )
#         st.plotly_chart(fig_box, use_container_width=True)
#     else:
#         st.info("Select at least one element column with non-empty data to display histograms.")

#     st.divider()

#     # Interactive Boxplots grouped by Transect or Distance (m)
#     st.markdown(f"### Interactive Boxplots by `{group_by_feature}`")
#     b_opt1, b_opt2, b_opt3 = st.columns(3)
#     with b_opt1:
#         box_log = st.checkbox("Log y-axis (boxplots)", value=True)
#     with b_opt2:
#         box_points = st.checkbox("Show individual sample points", value=True)
#     with b_opt3:
#         box_ncols = st.number_input("Boxplot columns", min_value=1, max_value=4, value=2)

#     if selected_cols_t1 and group_by_feature in df_tab1.columns and not df_tab1.empty:
#         fig_box = plot_interactive_boxplots(
#             dataframe=df_tab1,
#             cols_plot=selected_cols_t1,
#             group_col=group_by_feature,
#             group_color_map=group_color_map,
#             n_cols=int(box_ncols),
#             # show_points=box_points,
#             log_scale=box_log,
#         )
#         st.plotly_chart(fig_box, use_container_width=True,key=98)
#     else:
#         st.info(f"Ensure `{group_by_feature}` and element columns are available to render boxplots.")

#     st.divider()

#     # Top Recurring High-Concentration Filters/Samples
#     st.markdown("### Samples / Filters Recurring in Top-N Concentrations")
#     top_n_val = st.slider("Top-N per element", min_value=1, max_value=20, value=5)
#     top_summary_df = get_top_recurring_samples(
#         df=df_tab1,
#         target_cols=selected_cols_t1 if selected_cols_t1 else active_element_cols,
#         top_n=top_n_val,
#         id_col="Sample ID",
#     )
#     if not top_summary_df.empty:
#         st.dataframe(top_summary_df, use_container_width=True)
#     else:
#         st.caption("No top-N records available for the current filter selection.")


# # =============================================================================
# # TAB 2: PCA & K-Means Clustering
# # =============================================================================
# with tab2:
#     st.subheader("Principal Component Analysis (PCA) & K-Means Clustering")

#     pca_c1, pca_c2, pca_c3 = st.columns([2, 1, 1])
#     with pca_c1:
#         pca_features = st.multiselect(
#             "Features for normalization, K-Means & PCA",
#             options=active_element_cols,
#             default=active_element_cols,
#             key="pca_features_select",
#         )
#     with pca_c2:
#         n_clusters_val = st.slider("Number of K-Means clusters", min_value=2, max_value=12, value=5)
#     with pca_c3:
#         n_pcs_val = st.slider("Max PCA components", min_value=2, max_value=10, value=7)

#     pca_bundle = run_pca_and_clustering(
#         df_in=df_filtered,
#         feature_cols=pca_features,
#         n_clusters=n_clusters_val,
#         n_components=n_pcs_val,
#     )

#     if pca_bundle is None:
#         st.warning("Need at least 2 valid rows and 2 features without NaNs to run PCA & clustering.")
#     else:
#         pca_model = pca_bundle["pca"]
#         scores_df = pca_bundle["scores_df"]
#         loadings_df = pca_bundle["loadings_df"]
#         pc_names = pca_bundle["pc_names"]

#         # Scree plot
#         var_thresh = st.slider("Cumulative variance threshold", min_value=0.50, max_value=0.99, value=0.95, step=0.01)
#         fig_scree = plot_interactive_scree(pca_model, threshold=var_thresh)
#         st.plotly_chart(fig_scree, use_container_width=True)

#         st.divider()

#         # PCA Scores Scatter
#         st.markdown("### PCA Scores Plot")
#         sc1, sc2, sc3, sc4 = st.columns(4)
#         with sc1:
#             pc_x = st.selectbox("X-axis PC", options=pc_names, index=0)
#         with sc2:
#             pc_y = st.selectbox("Y-axis PC", options=pc_names, index=min(1, len(pc_names) - 1))
#         with sc3:
#             color_choices = ["Cluster"] + [
#                 c for c in ["Transect", "Distance (m)", "Season"] if c in scores_df.columns
#             ]
#             default_color_idx = (
#                 color_choices.index(group_by_feature)
#                 if group_by_feature in color_choices
#                 else 0
#             )
#             pca_color_by = st.selectbox("Color points by", options=color_choices, index=default_color_idx)
#         with sc4:
#             ann_choices = ["None"] + [
#                 c for c in ["Sample ID", "Dust sampler_ID", "Season", "Transect"] if c in pca_bundle["df_aligned"].columns
#             ]
#             ann_choice = st.selectbox("Annotate points", options=ann_choices, index=0)

#         scores_with_ann = scores_df.copy()
#         if ann_choice != "None" and ann_choice in pca_bundle["df_aligned"].columns:
#             scores_with_ann[ann_choice] = pca_bundle["df_aligned"][ann_choice]

#         symlog_pca = st.checkbox("SymLog10 scale (PCA)", value=True)
#         fig_scores = plot_interactive_pca_scores(
#             scores_df=scores_with_ann,
#             pc_x=pc_x,
#             pc_y=pc_y,
#             color_by=pca_color_by,
#             group_color_map=group_color_map,
#             annotate_col=None if ann_choice == "None" else ann_choice,
#             symlog_pca = symlog_pca
#         )
#         st.plotly_chart(fig_scores, use_container_width=True)

#         st.divider()

#         # Combined Loadings Matrix (Diagonal ordered bars, upper scatter, lower |loading|)
#         st.markdown("### PCA Loadings Matrix")
#         matrix_pcs = st.multiselect(
#             "Select PCs for loadings matrix (2–4 recommended)",
#             options=pc_names,
#             default=pc_names[: min(3, len(pc_names))],
#         )
#         if len(matrix_pcs) >= 2:
#             fig_load_mat = plot_interactive_loadings_matrix(
#                 loadings_df=loadings_df,
#                 selected_pcs=matrix_pcs,
#                 element_color_map=element_color_map,
#             )
#             st.plotly_chart(fig_load_mat, use_container_width=True)
#         else:
#             st.info("Select at least 2 PCs to render the loadings matrix.")

#         with st.expander("View PCA Loadings Table & Clustered Sample Data"):
#             st.dataframe(loadings_df.round(4), use_container_width=True)
#             st.dataframe(scores_df, use_container_width=True)


# # =============================================================================
# # PLACEHOLDER TABS (3, 4, 5) — To Be Implemented Next
# # =============================================================================
# with tab3:
#     st.info(
#         "**Placeholder — Tab 3: Element Correlations** "
#         "(Pearson / Spearman full & significant correlation heatmaps and pegmatite vs. "
#         "non-pegmatite deposition notes will be implemented here next.)"
#     )

# with tab4:
#     st.info(
#         "**Placeholder — Tab 4: Element Ratios** "
#         "(Exploring ratios such as Element / Ca or custom numerator/denominator pairs, "
#         "grouped and colored consistently by Transect or Distance (m).)"
#     )

# with tab5:
#     st.info(
#         "**Placeholder — Tab 5: Seasonal Levelling Comparison** "
#         "(Side-by-side comparison of raw/cleaned vs. seasonally levelled distributions "
#         "across seasons using MedianShift, ZRobust, or ZScore.)"
#     )