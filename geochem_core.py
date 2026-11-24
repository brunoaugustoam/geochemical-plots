"""
Shared data processing, reference sample classification, seasonal levelling,
and interactive Plotly plotting helpers for the Bulk Geochemical Analysis app.
"""

import os
import re
from io import BytesIO
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from scipy import stats
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
import streamlit as st

from color_standards import (
    REF_GROUP_COLORS,
    adjust_hex_lightness,
    get_element_color_map,
    get_group_color_map,
    get_ref_group_color_map,
    get_season_shade_factors,
)

# -----------------------------------------------------------------------------
# Reference Constants
# -----------------------------------------------------------------------------
DEFAULT_ROOT = os.getcwd()
DEFAULT_FOLDER = "May25_Aug25_Nov25"
DEFAULT_FILE = "NAL_Filters REPORT_2026_02_20_edit.xlsx"
DEFAULT_SHEET = "ms"

INFO_COLS = [
    "Sample ID",
    "Season",
    "Dust sampler_ID",
    "Transect",
    "Distance (m)",
    "Change in mass (mg)",
]

SEASON_FILTER = [
    "Winter 2024",
    "Spring-Summer 2025",
    "Fall 2025",
    "Winter 2025",
    "Spring-Summer 2026",
    "Fall 2026",
]

OTHER_COL_INTEREST = [
    "Change in mass (mg)",
    "(mg/dm2/day)",
    "Geochem quarter weight (g)",
    "Days in Field",
    "Distance (m)",
    "LatDMS",
    "LonDMS",
]

MS_ELEMENTS = [
    "As", "Ba", "Be", "Ce", "Co", "Cr", "Cu",
    "Li", "Nb", "Pb", "Rb", "Tl", "V",
]

OES_ELEMENTS = [
    "Al", "As", "Ba", "Bi", "Ca", "Cd", "Co", "Cr", "Cu", "Fe",
    "K", "Li", "Mg", "Mn", "Mo", "Na", "Ni", "P", "Pb", "S (ICP)",
    "Sb", "Se", "Si", "Sr", "Ti", "V", "Zn", "Zr",
]

# REF-1, REF-2, REF-3 = Background references; REF-4, REF-5 = Site references
REF_GROUP_ORDER = [
    "Background Ref (REF-1..3)",
    "Site Ref (REF-4..5)",
    "Non-Reference",
]


# -----------------------------------------------------------------------------
# Workbook Loading, Column Remapping & Reference Classification
# -----------------------------------------------------------------------------
def _make_unique_headers(raw_columns) -> list[str]:
    """Ensure every column header is a unique non-null string."""
    seen = {}
    unique_cols = []
    for col in raw_columns:
        base = "Unnamed" if pd.isna(col) else str(col).strip()
        count = seen.get(base, 0) + 1
        seen[base] = count
        unique_cols.append(base if count == 1 else f"{base} [dup{count}]")
    return unique_cols


@st.cache_data(show_spinner="Reading Excel workbook...")
def load_excel_sheet(
    file_bytes: bytes | None, local_path: str, sheet_name: str
) -> pd.DataFrame:
    """Load a worksheet from uploaded .xlsx bytes or a local fallback path."""
    if file_bytes is not None:
        return pd.read_excel(BytesIO(file_bytes), sheet_name=sheet_name)
    return pd.read_excel(local_path, sheet_name=sheet_name)


def remap_geochem_columns(df_raw: pd.DataFrame, sheet_name: str):
    """
    Deduplicate headers and remap repeated element columns in 'ms' (10 cols/el)
    and 'oes' (5 cols/el) into unambiguous role-named columns.
    """
    df = df_raw.copy()
    df.columns = _make_unique_headers(df.columns)

    sheet_key = sheet_name.strip().lower()
    elements = MS_ELEMENTS if sheet_key == "ms" else OES_ELEMENTS

    rename_map = {}
    element_unit_map = {el: {} for el in elements}
    primary_conc_cols = []
    all_element_cols = []

    if sheet_key == "ms":
        slot_names_tmpl = [
            "{el} [% #1]",
            "{el} [%/g filter #1]",
            "{el} [%/g filter #2]",
            "{el} [% #2]",
            "{el} [Mult req]",
            "{el} [ppb #1]",
            "{el} [ppb/g filter #1]",
            "{el} [ppb/g filter #2]",
            "{el} [ppb #2]",
            "{el} [ug/dm2/day]",
        ]
        role_keys = [
            "pct_1",
            "pct_per_g_1",
            "pct_per_g_2",
            "pct_2",
            "mult_req",
            "ppb_1",
            "ppb_per_g_1",
            "ppb_per_g_2",
            "ppb_2",
            "flux_ug_dm2_day",
        ]
        for el in elements:
            anchor = f"[{el}] (%)"
            if anchor not in df.columns:
                continue
            start_idx = df.columns.get_loc(anchor)
            if isinstance(start_idx, (slice, np.ndarray)):
                start_idx = int(np.flatnonzero(start_idx)[0])

            block_cols = list(df.columns[start_idx : start_idx + 10])
            for orig_c, tmpl, role in zip(block_cols, slot_names_tmpl, role_keys):
                new_c = tmpl.format(el=el)
                rename_map[orig_c] = new_c
                element_unit_map[el][role] = new_c
                if role != "mult_req":
                    all_element_cols.append(new_c)

            if "ppb_1" in element_unit_map[el]:
                primary_conc_cols.append(element_unit_map[el]["ppb_1"])
    else:
        slot_names_tmpl = [
            "{el} [ppm #1]",
            "{el} [ppm/g filter #1]",
            "{el} [ppm/g filter #2]",
            "{el} [ppm #2]",
            "{el} [mg/dm2/day]",
        ]
        role_keys = [
            "ppm_1",
            "ppm_per_g_1",
            "ppm_per_g_2",
            "ppm_2",
            "flux_mg_dm2_day",
        ]
        for el in elements:
            anchor = f"[{el}] (ppm)"
            if anchor not in df.columns:
                continue
            start_idx = df.columns.get_loc(anchor)
            if isinstance(start_idx, (slice, np.ndarray)):
                start_idx = int(np.flatnonzero(start_idx)[0])

            block_cols = list(df.columns[start_idx : start_idx + 5])
            for orig_c, tmpl, role in zip(block_cols, slot_names_tmpl, role_keys):
                new_c = tmpl.format(el=el)
                rename_map[orig_c] = new_c
                element_unit_map[el][role] = new_c
                all_element_cols.append(new_c)

            if "ppm_1" in element_unit_map[el]:
                primary_conc_cols.append(element_unit_map[el]["ppm_1"])

    df = df.rename(columns=rename_map)

    for col in all_element_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    for num_meta in [
        "Distance (m)",
        "Days in Field",
        "Change in mass (g)",
        "Change in mass (mg)",
        "(mg/m2/day)",
        "(mg/dm2/day)",
        "Geochem quarter weight (g)",
    ]:
        if num_meta in df.columns:
            df[num_meta] = pd.to_numeric(df[num_meta], errors="coerce")

    meta = {
        "sheet_key": sheet_key,
        "elements": [el for el in elements if len(element_unit_map[el]) > 0],
        "element_unit_map": element_unit_map,
        "primary_conc_cols": primary_conc_cols,
        "all_element_cols": all_element_cols,
        "rename_map": rename_map,
    }
    return df, meta


def classify_reference_samples(df_in: pd.DataFrame) -> pd.DataFrame:
    """
    Add an independent 'Ref_Group' column without altering 'Transect' or 'Distance (m)':
    - REF-1, REF-2, REF-3 -> 'Background Ref (REF-1..3)'
    - REF-4, REF-5 -> 'Site Ref (REF-4..5)'
    - All other rows -> 'Non-Reference'
    """
    df = df_in.copy()
    id_cols = [c for c in ["Sample ID", "Dust sampler_ID"] if c in df.columns]
    if not id_cols:
        df["Ref_Group"] = "Non-Reference"
        return df

    def _detect_ref(row) -> str:
        combined = " ".join(str(row[c]) for c in id_cols if pd.notna(row[c])).upper()
        if re.search(r"\bREF[-_]?[123](?!\d)", combined):
            return "Background Ref (REF-1..3)"
        if re.search(r"\bREF[-_]?[45](?!\d)", combined):
            return "Site Ref (REF-4..5)"
        return "Non-Reference"

    df["Ref_Group"] = df.apply(_detect_ref, axis=1)
    return df


# -----------------------------------------------------------------------------
# Pre-Levelling Cleaning & Optional Seasonal Levelling
# -----------------------------------------------------------------------------
def clean_negatives_and_nans(
    df_in: pd.DataFrame,
    target_cols: list[str],
    nan_strategy: str = "Keep as NaN",
) -> tuple[pd.DataFrame, dict]:
    """
    Replace negative values with min_positive / sqrt(2) and apply NaN handling
    BEFORE seasonal levelling, regardless of whether levelling is active.
    """
    df = df_in.copy()
    replacement_log = {}

    for col in target_cols:
        if col not in df.columns:
            continue
        series = pd.to_numeric(df[col], errors="coerce")
        pos_vals = series[series > 0]
        neg_mask = series < 0

        if neg_mask.any():
            repl_val = float(pos_vals.min()) / np.sqrt(2.0) if not pos_vals.empty else 1e-6
            series.loc[neg_mask] = repl_val
            replacement_log[col] = {
                "neg_count": int(neg_mask.sum()),
                "min_pos": float(pos_vals.min()) if not pos_vals.empty else np.nan,
                "replacement": float(repl_val),
            }
        df[col] = series

    valid_cols = [c for c in target_cols if c in df.columns]
    if nan_strategy == "Fill with column median" and valid_cols:
        df[valid_cols] = df[valid_cols].fillna(df[valid_cols].median(numeric_only=True))
    elif nan_strategy == "Fill with 0" and valid_cols:
        df[valid_cols] = df[valid_cols].fillna(0.0)

    return df, replacement_log


def apply_seasonal_levelling(
    df_in: pd.DataFrame,
    target_cols: list[str],
    method: str = "MedianShift",
    reference_season: str | None = None,
) -> pd.DataFrame:
    """Level target numerical columns across 'Season' relative to reference_season."""
    if "Season" not in df_in.columns or not target_cols:
        return df_in.copy()

    df = df_in.copy()
    seasons = [s for s in df["Season"].dropna().unique()]
    if len(seasons) < 2:
        return df

    ref_season = reference_season if reference_season in seasons else seasons[0]
    ref_mask = df["Season"] == ref_season

    for col in target_cols:
        if col not in df.columns:
            continue
        s = pd.to_numeric(df[col], errors="coerce")
        ref_vals = s[ref_mask].dropna()
        if ref_vals.empty:
            continue

        leveled_series = s.copy()
        for seas in seasons:
            if seas == ref_season:
                continue
            m = df["Season"] == seas
            cur_vals = s[m].dropna()
            if cur_vals.empty:
                continue

            if method == "MedianShift":
                leveled_series.loc[m] = s.loc[m] + float(ref_vals.median() - cur_vals.median())
            elif method == "ZRobust":
                med_ref = float(ref_vals.median())
                med_cur = float(cur_vals.median())
                mad_ref = float(stats.median_abs_deviation(ref_vals, nan_policy="omit"))
                mad_cur = float(stats.median_abs_deviation(cur_vals, nan_policy="omit"))
                if mad_cur > 0 and mad_ref > 0:
                    leveled_series.loc[m] = ((s.loc[m] - med_cur) / mad_cur) * mad_ref + med_ref
                else:
                    leveled_series.loc[m] = s.loc[m] + (med_ref - med_cur)
            elif method == "ZScore":
                mean_ref = float(ref_vals.mean())
                mean_cur = float(cur_vals.mean())
                std_ref = float(ref_vals.std())
                std_cur = float(cur_vals.std())
                if pd.notna(std_cur) and std_cur > 0 and pd.notna(std_ref) and std_ref > 0:
                    leveled_series.loc[m] = ((s.loc[m] - mean_cur) / std_cur) * std_ref + mean_ref
                else:
                    leveled_series.loc[m] = s.loc[m] + (mean_ref - mean_cur)

        df[col] = leveled_series

    return df


# -----------------------------------------------------------------------------
# Interactive Plotly Plotting Functions
# -----------------------------------------------------------------------------
def plot_interactive_histograms(
    dataframe: pd.DataFrame,
    cols_interest: list[str],
    log_scale: bool = True,
    n_cols: int = 4,
    n_bins: int | None = None,
    element_color_map: dict | None = None,
    split_by_season: bool = False,
    season_order: list[str] | None = None,
) -> go.Figure:
    """
    Interactive Plotly multi-panel histograms.
    - When split_by_season=False, pools all data with no shading and no extra legend.
    - When split_by_season=True, overlays seasons with light/dark shades of each
      element's standard color, transparency, and a seasonal legend.
    """
    valid_cols = [c for c in cols_interest if c in dataframe.columns]
    n_plots = len(valid_cols)
    n_rows = int(np.ceil(n_plots / n_cols))
    v_spacing = min(0.14, 0.6 / max(n_rows - 1, 1)) if n_rows > 1 else 0.14

    fig = make_subplots(
        rows=n_rows,
        cols=n_cols,
        subplot_titles=valid_cols,
        vertical_spacing=v_spacing,
        horizontal_spacing=0.08,
    )

    has_season = bool(split_by_season) and ("Season" in dataframe.columns)

    if has_season:
        present_s = set(dataframe["Season"].dropna())
        ordered_seasons = (
            [s for s in season_order if s in present_s]
            if season_order
            else sorted(present_s, key=str)
        )
        for s in sorted(present_s, key=str):
            if s not in ordered_seasons:
                ordered_seasons.append(s)
        season_shades = get_season_shade_factors(len(ordered_seasons))
    else:
        ordered_seasons = [None]
        season_shades = [1.0]

    show_legend_once = {"mean": True, "median": True}
    season_legend_shown = set()

    for idx, col in enumerate(valid_cols):
        r = idx // n_cols + 1
        c = idx % n_cols + 1

        el_symbol = col.split(" ")[0]
        base_color = (
            element_color_map.get(el_symbol)
            if element_color_map and el_symbol in element_color_map
            else "#377eb8"
        )

        all_series = pd.to_numeric(dataframe[col], errors="coerce").dropna()
        if log_scale:
            all_series = all_series[all_series > 0]
            all_vals = np.log10(all_series.to_numpy(dtype=float))
            x_label = f"log10({col})"
        else:
            all_vals = all_series.to_numpy(dtype=float)
            x_label = col

        if len(all_vals) == 0:
            continue

        bins_count = n_bins if n_bins is not None else max(5, len(all_vals) // 3)
        vmin, vmax = float(np.min(all_vals)), float(np.max(all_vals))
        bin_size = (vmax - vmin) / bins_count if vmax > vmin else 0.1
        y_max_global = 1

        for seas, shade in zip(ordered_seasons, season_shades):
            if has_season and seas is not None:
                sub_s = pd.to_numeric(
                    dataframe.loc[dataframe["Season"] == seas, col], errors="coerce"
                ).dropna()
            else:
                sub_s = pd.to_numeric(dataframe[col], errors="coerce").dropna()

            if log_scale:
                sub_s = sub_s[sub_s > 0]
                vals = np.log10(sub_s.to_numpy(dtype=float))
            else:
                vals = sub_s.to_numpy(dtype=float)

            if len(vals) == 0:
                continue

            bar_color = adjust_hex_lightness(base_color, shade) if has_season else base_color

            show_seas_leg = False
            trace_name = col
            if has_season and seas is not None:
                trace_name = str(seas)
                if seas not in season_legend_shown:
                    season_legend_shown.add(seas)
                    show_seas_leg = True

            hover_prefix = f"Season: {seas}<br>" if (has_season and seas is not None) else ""

            fig.add_trace(
                go.Histogram(
                    x=vals,
                    xbins=dict(start=vmin, end=vmax + 1e-9, size=bin_size),
                    marker=dict(
                        color=bar_color,
                        line=dict(color="rgba(0,0,0,0.55)", width=0.8),
                    ),
                    opacity=0.55 if has_season else 0.88,
                    name=trace_name,
                    legendgroup=trace_name if has_season else col,
                    showlegend=show_seas_leg,
                    hovertemplate=(
                        hover_prefix
                        + f"{x_label}: %{{x:.3f}}<br>Count: %{{y}}<extra></extra>"
                    ),
                ),
                row=r,
                col=c,
            )

            hist_counts, _ = np.histogram(vals, bins=bins_count, range=(vmin, vmax))
            if len(hist_counts) > 0:
                y_max_global = max(y_max_global, int(hist_counts.max()))

            med_val = float(np.median(vals))
            mean_val = float(np.mean(vals))

            fig.add_trace(
                go.Scatter(
                    x=[med_val, med_val],
                    y=[0, y_max_global * 1.05],
                    mode="lines",
                    line=dict(
                        color=bar_color if has_season else "crimson",
                        width=2,
                        dash="dash",
                    ),
                    name="Median" if not has_season else f"Median ({trace_name})",
                    legendgroup="median" if not has_season else f"med_{trace_name}",
                    showlegend=show_legend_once["median"] if not has_season else False,
                    hovertemplate=hover_prefix + f"Median ({col}): {med_val:.3f}<extra></extra>",
                ),
                row=r,
                col=c,
            )
            if not has_season:
                show_legend_once["median"] = False

            fig.add_trace(
                go.Scatter(
                    x=[mean_val, mean_val],
                    y=[0, y_max_global * 1.05],
                    mode="lines",
                    line=dict(
                        color=bar_color if has_season else "black",
                        width=2,
                        dash="dot",
                    ),
                    name="Mean" if not has_season else f"Mean ({trace_name})",
                    legendgroup="mean" if not has_season else f"mean_{trace_name}",
                    showlegend=show_legend_once["mean"] if not has_season else False,
                    hovertemplate=hover_prefix + f"Mean ({col}): {mean_val:.3f}<extra></extra>",
                ),
                row=r,
                col=c,
            )
            if not has_season:
                show_legend_once["mean"] = False

        fig.update_xaxes(title_text=x_label, row=r, col=c)
        fig.update_yaxes(title_text="Count", row=r, col=c)

    fig.update_layout(
        height=max(360, 320 * n_rows),
        title_text=(
            "Interactive Histograms (Shaded by Season)"
            if has_season
            else "Interactive Histograms"
        ),
        barmode="overlay",
        showlegend=has_season,
        hovermode="closest",
        template="plotly_white",
    )
    return fig

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
#     separate_ref_groups: bool = False,
#     season_order: list[str] | None = None,
# ) -> go.Figure:
#     """
#     Interactive Plotly boxplots grouped by Transect or Distance (m) with Sample ID
#     on hover, supporting side-by-side season splits and/or independent
#     REF-1..3 vs REF-4..5 splits.
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
#     has_ref = separate_ref_groups and ("Ref_Group" in dataframe.columns)

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
#     else:
#         ordered_seasons = [None]

#     if has_ref:
#         present_r = set(dataframe["Ref_Group"].dropna())
#         ordered_refs = [r for r in REF_GROUP_ORDER if r in present_r]
#         for r_val in sorted(present_r, key=str):
#             if r_val not in ordered_refs:
#                 ordered_refs.append(r_val)
#     else:
#         ordered_refs = [None]

#     ref_color_map = get_ref_group_color_map(ordered_refs) if has_ref else {}
#     legend_shown = set()
#     use_grouped_mode = has_season or has_ref

#     for idx, col in enumerate(valid_cols):
#         r = idx // n_cols + 1
#         c = idx % n_cols + 1

#         cols_needed = (
#             [group_col, col]
#             + ([id_col] if has_id else [])
#             + (["Season"] if has_season else [])
#             + (["Ref_Group"] if has_ref else [])
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

#         if not use_grouped_mode:
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
#             strata = [(seas, ref_g) for seas in ordered_seasons for ref_g in ordered_refs]
#             shades = get_season_shade_factors(max(len(strata), 1))

#             for (seas, ref_g), shade in zip(strata, shades):
#                 mask = pd.Series(True, index=sub.index)
#                 if seas is not None:
#                     mask &= sub["Season"] == seas
#                 if ref_g is not None:
#                     mask &= sub["Ref_Group"] == ref_g

#                 s_df = sub[mask]
#                 if s_df.empty:
#                     continue

#                 x_all, y_all, ids_all = [], [], []
#                 for grp in groups_present:
#                     g_sub = s_df[s_df[group_col] == grp]
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

#                 if has_ref and not has_season:
#                     box_color = ref_color_map.get(ref_g, "#4c78a8")
#                 elif has_ref and has_season:
#                     base_ref_c = ref_color_map.get(ref_g, "#4c78a8")
#                     box_color = adjust_hex_lightness(base_ref_c, shade)
#                 else:
#                     box_color = adjust_hex_lightness("#4c78a8", shade)

#                 parts = []
#                 if seas is not None:
#                     parts.append(str(seas))
#                 if ref_g is not None:
#                     parts.append(str(ref_g))
#                 stratum_label = " | ".join(parts)

#                 show_leg = stratum_label not in legend_shown
#                 if show_leg:
#                     legend_shown.add(stratum_label)

#                 extra_hover = "".join(f"{p}<br>" for p in parts)

#                 fig.add_trace(
#                     go.Box(
#                         x=x_all,
#                         y=y_all,
#                         customdata=ids_all,
#                         name=stratum_label,
#                         legendgroup=stratum_label,
#                         offsetgroup=stratum_label,
#                         showlegend=show_leg,
#                         fillcolor=box_color,
#                         line=dict(color="#222222", width=1.3),
#                         marker=dict(
#                             color=box_color,
#                             size=5,
#                             line=dict(color="#222222", width=0.6),
#                         ),
#                         boxpoints=point_mode,
#                         jitter=0.25,
#                         pointpos=0.0,
#                         hovertemplate=(
#                             f"<b>Sample ID: %{{customdata}}</b><br>"
#                             + extra_hover
#                             + f"{group_col}: %{{x}}<br>"
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
#         title_text=f"Interactive Boxplots by {group_col}",
#         boxmode="group" if use_grouped_mode else "overlay",
#         boxgroupgap=0.25,
#         boxgap=0.12,
#         template="plotly_white",
#     )
#     return fig
def plot_interactive_boxplots(
    dataframe: pd.DataFrame,
    cols_plot: list[str],
    group_col: str,
    group_color_map: dict,
    id_col: str = "Sample ID",
    n_cols: int = 2,
    point_mode: str | bool = "outliers",
    log_scale: bool = True,
    log_floor: float = 1e-6,
    split_by_season: bool = False,
    season_order: list[str] | None = None,
) -> go.Figure:
    """
    Interactive Plotly boxplots grouped by Transect or Distance (m) with Sample ID
    on hover, using standard group colors for all groups.
    """
    valid_cols = [c for c in cols_plot if c in dataframe.columns]
    n_plots = len(valid_cols)
    n_rows = max(1, int(np.ceil(n_plots / max(1, n_cols))))
    v_spacing = min(0.14, 0.65 / max(n_rows - 1, 1)) if n_rows > 1 else 0.14

    fig = make_subplots(
        rows=n_rows,
        cols=n_cols,
        subplot_titles=valid_cols,
        vertical_spacing=v_spacing,
        horizontal_spacing=0.08,
    )

    groups_present = [
        g for g in group_color_map.keys() if g in set(dataframe[group_col].dropna())
    ]
    has_id = id_col in dataframe.columns
    has_season = bool(split_by_season) and ("Season" in dataframe.columns)

    if has_season:
        present_s = set(dataframe["Season"].dropna())
        ordered_seasons = (
            [s for s in season_order if s in present_s]
            if season_order
            else sorted(present_s, key=str)
        )
        for s in sorted(present_s, key=str):
            if s not in ordered_seasons:
                ordered_seasons.append(s)
        shade_factors = get_season_shade_factors(len(ordered_seasons))
    else:
        ordered_seasons = [None]
        shade_factors = [1.0]

    legend_shown = set()

    for idx, col in enumerate(valid_cols):
        r = idx // n_cols + 1
        c = idx % n_cols + 1

        cols_needed = (
            [group_col, col]
            + ([id_col] if has_id else [])
            + (["Season"] if has_season else [])
        )
        sub = dataframe[cols_needed].copy()
        sub[col] = pd.to_numeric(sub[col], errors="coerce")
        sub = sub.dropna(subset=[group_col, col])

        if log_scale:
            sub = sub[np.isfinite(sub[col])]
            if log_floor is not None:
                sub[col] = sub[col].clip(lower=log_floor)
            else:
                sub = sub[sub[col] > 0]

        if not has_season:
            for grp in groups_present:
                grp_df = sub[sub[group_col] == grp]
                if grp_df.empty:
                    continue

                grp_vals = grp_df[col].to_numpy(dtype=float)
                grp_ids = (
                    grp_df[id_col].astype(str).tolist()
                    if has_id
                    else [str(i) for i in grp_df.index]
                )
                grp_color = group_color_map[grp]

                show_leg = grp not in legend_shown
                if show_leg:
                    legend_shown.add(grp)

                fig.add_trace(
                    go.Box(
                        x=[str(grp)] * len(grp_vals),
                        y=grp_vals,
                        customdata=grp_ids,
                        name=str(grp),
                        legendgroup=str(grp),
                        showlegend=show_leg,
                        width=0.55,
                        fillcolor=grp_color,
                        line=dict(color="#222222", width=1.5),
                        marker=dict(
                            color=grp_color,
                            size=6,
                            line=dict(color="#222222", width=0.7),
                        ),
                        boxpoints=point_mode,
                        jitter=0.25,
                        pointpos=0.0,
                        hovertemplate=(
                            f"<b>Sample ID: %{{customdata}}</b><br>"
                            f"{group_col}: {grp}<br>"
                            f"{col}: %{{y:.4g}}<extra></extra>"
                        ),
                    ),
                    row=r,
                    col=c,
                )
        else:
            for seas, shade in zip(ordered_seasons, shade_factors):
                seas_df = sub[sub["Season"] == seas]
                if seas_df.empty:
                    continue

                for grp in groups_present:
                    g_sub = seas_df[seas_df[group_col] == grp]
                    if g_sub.empty:
                        continue
                    vals = g_sub[col].to_numpy(dtype=float)
                    ids = (
                        g_sub[id_col].astype(str).tolist()
                        if has_id
                        else [str(i) for i in g_sub.index]
                    )
                    shaded_color = adjust_hex_lightness(group_color_map[grp], shade)
                    trace_label = f"{grp} ({seas})"

                    show_leg = trace_label not in legend_shown
                    if show_leg:
                        legend_shown.add(trace_label)

                    fig.add_trace(
                        go.Box(
                            x=[str(grp)] * len(vals),
                            y=vals,
                            customdata=ids,
                            name=trace_label,
                            legendgroup=str(grp),
                            offsetgroup=str(seas),
                            showlegend=show_leg,
                            fillcolor=shaded_color,
                            line=dict(color="#222222", width=1.3),
                            marker=dict(
                                color=shaded_color,
                                size=5,
                                line=dict(color="#222222", width=0.6),
                            ),
                            boxpoints=point_mode,
                            jitter=0.25,
                            pointpos=0.0,
                            hovertemplate=(
                                f"<b>Sample ID: %{{customdata}}</b><br>"
                                f"Season: {seas}<br>"
                                f"{group_col}: {grp}<br>"
                                f"{col}: %{{y:.4g}}<extra></extra>"
                            ),
                        ),
                        row=r,
                        col=c,
                    )

        if log_scale:
            fig.update_yaxes(type="log", row=r, col=c)
        fig.update_xaxes(
            title_text=group_col,
            categoryorder="array",
            categoryarray=[str(g) for g in groups_present],
            row=r,
            col=c,
        )
        fig.update_yaxes(title_text=col, row=r, col=c)

    fig.update_layout(
        height=max(480, 420 * n_rows),
        title_text=(
            f"Interactive Boxplots by {group_col} (Side-by-Side by Season)"
            if has_season
            else f"Interactive Boxplots by {group_col}"
        ),
        boxmode="group",
        boxgroupgap=0.25,
        boxgap=0.12,
        template="plotly_white",
    )
    return fig



def get_top_recurring_samples(
    df: pd.DataFrame,
    target_cols: list[str],
    top_n: int = 5,
    id_col: str = "Sample ID",
) -> pd.DataFrame:
    """Identify samples recurring most frequently in top-N concentrations per column."""
    records = []
    for col in target_cols:
        if col not in df.columns:
            continue
        s = pd.to_numeric(df[col], errors="coerce").dropna()
        top_idx = s.nlargest(min(top_n, len(s))).index
        for rank, idx in enumerate(top_idx, start=1):
            records.append(
                {
                    "row_index": idx,
                    id_col: df.loc[idx, id_col] if id_col in df.columns else idx,
                    "Transect": df.loc[idx, "Transect"] if "Transect" in df.columns else np.nan,
                    "Distance (m)": df.loc[idx, "Distance (m)"] if "Distance (m)" in df.columns else np.nan,
                    "Season": df.loc[idx, "Season"] if "Season" in df.columns else np.nan,
                    "Ref_Group": df.loc[idx, "Ref_Group"] if "Ref_Group" in df.columns else np.nan,
                    "element_col": col,
                    "rank_in_col": rank,
                    "value": float(df.loc[idx, col]),
                }
            )

    if not records:
        return pd.DataFrame()

    long_df = pd.DataFrame(records)
    return (
        long_df.groupby(["row_index", id_col], as_index=False)
        .agg(
            top_appearances=("element_col", "count"),
            elements_featured=(
                "element_col",
                lambda s: ", ".join(sorted(set(x.split(" ")[0] for x in s))),
            ),
            Transect=("Transect", "first"),
            **{
                "Distance (m)": ("Distance (m)", "first"),
                "Season": ("Season", "first"),
                "Ref_Group": ("Ref_Group", "first"),
            },
        )
        .sort_values(by="top_appearances", ascending=False)
        .reset_index(drop=True)
    )


def run_pca_and_clustering(
    df_in: pd.DataFrame,
    feature_cols: list[str],
    n_clusters: int = 5,
    n_components: int = 7,
    random_state: int = 42,
):
    """Min-max normalize feature_cols, fit K-Means clusters, and fit PCA."""
    valid_cols = [c for c in feature_cols if c in df_in.columns]
    sub = df_in.dropna(subset=valid_cols).copy()
    if len(sub) < 2 or len(valid_cols) < 2:
        return None

    feat_df = sub[valid_cols].astype(float)
    denom = feat_df.max() - feat_df.min()
    norm_df = ((feat_df - feat_df.min()) / denom.replace(0, np.nan)).fillna(0.0)

    actual_clusters = min(n_clusters, len(sub))
    kmeans = KMeans(n_clusters=actual_clusters, random_state=random_state, n_init=10)
    sub["Cluster"] = [f"Cluster {k}" for k in kmeans.fit_predict(norm_df)]

    max_pcs = min(n_components, len(valid_cols), len(sub) - 1)
    pca = PCA(n_components=max_pcs)
    scores = pca.fit_transform(norm_df)

    pc_names = [f"PC{i + 1}" for i in range(max_pcs)]
    scores_df = pd.DataFrame(scores, columns=pc_names, index=sub.index)
    scores_df["Cluster"] = sub["Cluster"]
    for meta_c in ["Sample ID", "Season", "Transect", "Distance (m)", "Ref_Group"]:
        if meta_c in sub.columns:
            scores_df[meta_c] = sub[meta_c]

    short_names = [c.split(" ")[0].lstrip("[") for c in valid_cols]
    loadings_df = pd.DataFrame(pca.components_, columns=short_names, index=pc_names)

    return {
        "df_aligned": sub,
        "norm_df": norm_df,
        "kmeans": kmeans,
        "pca": pca,
        "scores_df": scores_df,
        "loadings_df": loadings_df,
        "pc_names": pc_names,
    }


def symlog_array(values: np.ndarray, linthresh: float = 1.0) -> np.ndarray:
    """Symmetric log transform: linear near 0 (|u| <= 1), log beyond linthresh."""
    arr = np.asarray(values, dtype=float)
    lt = max(float(linthresh), 1e-12)
    u = arr / lt
    abs_u = np.abs(u)
    transformed_u = np.where(
        abs_u <= 1.0,
        u,
        np.sign(u) * (1.0 + np.log10(np.maximum(abs_u, 1.0))),
    )
    return transformed_u * lt


def _symlog_ticks(min_orig: float, max_orig: float, linthresh: float = 1.0):
    """Generate clean tick positions and original-scale labels for symlog axes."""
    candidates = [-1000, -100, -10, -linthresh, 0.0, linthresh, 10, 100, 1000]
    uniq_orig = []
    for v in candidates:
        if min_orig * 1.1 <= v <= max_orig * 1.1 and all(abs(v - u) > 1e-9 for u in uniq_orig):
            uniq_orig.append(float(v))
    if not uniq_orig:
        uniq_orig = [float(min_orig), 0.0, float(max_orig)]

    tickvals = symlog_array(np.array(uniq_orig, dtype=float), linthresh=linthresh).tolist()
    ticktext = [f"{v:g}" for v in uniq_orig]
    return tickvals, ticktext


def plot_interactive_scree(pca: PCA, threshold: float = 0.95) -> go.Figure:
    """Interactive scree plot with individual and cumulative explained variance."""
    evr = pca.explained_variance_ratio_
    cum_evr = np.cumsum(evr)
    pcs = [f"PC{i + 1}" for i in range(len(evr))]
    k_idx = int(np.argmax(cum_evr >= threshold))

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=pcs,
            y=evr,
            name="Explained Variance Ratio",
            marker_color="#4c78a8",
            opacity=0.8,
            hovertemplate="%{x}: %{y:.1%}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=pcs,
            y=cum_evr,
            name="Cumulative Variance",
            mode="lines+markers",
            line=dict(color="#111111", width=2.5),
            marker=dict(size=8),
            hovertemplate="%{x} Cumulative: %{y:.1%}<extra></extra>",
        )
    )
    fig.add_hline(
        y=threshold,
        line_dash="dash",
        line_color="crimson",
        annotation_text=f"{int(threshold * 100)}% Threshold ({pcs[k_idx]}: {cum_evr[k_idx]:.1%})",
        annotation_position="top left",
    )
    fig.update_layout(
        title="PCA Scree Plot & Cumulative Explained Variance",
        xaxis_title="Principal Component",
        yaxis_title="Explained Variance Ratio",
        yaxis=dict(range=[0, 1.06]),
        template="plotly_white",
        height=420,
    )
    return fig


def plot_interactive_pca_scores(
    scores_df: pd.DataFrame,
    pc_x: str,
    pc_y: str,
    color_by: str,
    group_color_map: dict | None = None,
    annotate_col: str | None = None,
    symlog_pca: bool = True,
    linthresh: float = 1.0,
) -> go.Figure:
    """Interactive PCA score plot with optional symlog scaling to resolve tight clusters."""
    hover_cols = [
        c
        for c in ["Sample ID", "Season", "Transect", "Distance (m)", "Ref_Group", "Cluster"]
        if c in scores_df.columns
    ]

    color_discrete_map = None
    if color_by in ("Transect", "Distance (m)") and group_color_map:
        color_discrete_map = {str(k): v for k, v in group_color_map.items()}
    elif color_by == "Ref_Group":
        color_discrete_map = REF_GROUP_COLORS

    plot_df = scores_df.copy()
    raw_x = plot_df[pc_x].to_numpy(dtype=float)
    raw_y = plot_df[pc_y].to_numpy(dtype=float)
    plot_df["_orig_x"] = raw_x
    plot_df["_orig_y"] = raw_y

    if color_by in plot_df.columns:
        plot_df[color_by] = plot_df[color_by].astype(str)

    if symlog_pca:
        plot_df["_plot_x"] = symlog_array(raw_x, linthresh=linthresh)
        plot_df["_plot_y"] = symlog_array(raw_y, linthresh=linthresh)
        x_col, y_col = "_plot_x", "_plot_y"
        x_title = f"{pc_x} (symlog, linthresh={linthresh:g})"
        y_title = f"{pc_y} (symlog, linthresh={linthresh:g})"
    else:
        x_col, y_col = pc_x, pc_y
        x_title, y_title = pc_x, pc_y

    extra_hover = {c: True for c in hover_cols}
    extra_hover["_orig_x"] = ":.3f"
    extra_hover["_orig_y"] = ":.3f"

    fig = px.scatter(
        plot_df,
        x=x_col,
        y=y_col,
        color=color_by if color_by in plot_df.columns else None,
        color_discrete_map=color_discrete_map,
        hover_data=extra_hover,
        text=annotate_col if annotate_col and annotate_col in plot_df.columns else None,
        title=f"PCA Scores: {pc_x} vs {pc_y} — Colored by {color_by}",
        template="plotly_white",
        height=540,
    )

    if symlog_pca:
        xt_vals, xt_text = _symlog_ticks(float(np.nanmin(raw_x)), float(np.nanmax(raw_x)), linthresh)
        yt_vals, yt_text = _symlog_ticks(float(np.nanmin(raw_y)), float(np.nanmax(raw_y)), linthresh)
        fig.update_xaxes(tickmode="array", tickvals=xt_vals, ticktext=xt_text)
        fig.update_yaxes(tickmode="array", tickvals=yt_vals, ticktext=yt_text)

    if annotate_col:
        fig.update_traces(textposition="top center", textfont=dict(size=10))
    fig.update_traces(marker=dict(size=9, opacity=0.85, line=dict(width=0.6, color="white")))
    fig.update_layout(
        xaxis_title=x_title,
        yaxis_title=y_title,
        legend_title_text=color_by,
    )
    return fig


def plot_interactive_loadings_matrix(
    loadings_df: pd.DataFrame,
    selected_pcs: list[str],
    element_color_map: dict,
) -> go.Figure:
    """
    Matrix across selected PCs:
    - Diagonal: Ordered bar chart of loadings by |loading|
    - Upper triangle: 2D loadings scatter
    - Lower triangle: |loading| magnitude comparison scatter
    """
    m = len(selected_pcs)
    fig = make_subplots(
        rows=m,
        cols=m,
        subplot_titles=[
            f"{pc_r} vs {pc_c}" if i != j else f"{pc_r} Ordered Loadings"
            for i, pc_r in enumerate(selected_pcs)
            for j, pc_c in enumerate(selected_pcs)
        ],
        horizontal_spacing=0.07,
        vertical_spacing=0.10,
    )

    elements = list(loadings_df.columns)
    legend_seen = set()

    for i, pc_i in enumerate(selected_pcs):
        for j, pc_j in enumerate(selected_pcs):
            row_idx = i + 1
            col_idx = j + 1

            if i == j:
                s = loadings_df.loc[pc_i]
                order = s.abs().sort_values(ascending=False).index
                s_ord = s.loc[order]
                colors = [element_color_map.get(el, "#377eb8") for el in s_ord.index]
                fig.add_trace(
                    go.Bar(
                        x=list(s_ord.index),
                        y=s_ord.values,
                        marker_color=colors,
                        showlegend=False,
                        hovertemplate="%{x}<br>Loading (" + pc_i + "): %{y:.3f}<extra></extra>",
                    ),
                    row=row_idx,
                    col=col_idx,
                )
                fig.update_xaxes(title_text="Element (by |loading|)", row=row_idx, col=col_idx)
                fig.update_yaxes(title_text="Loading", row=row_idx, col=col_idx)

            elif i < j:
                x_vals = loadings_df.loc[pc_j, elements].values
                y_vals = loadings_df.loc[pc_i, elements].values
                for el, xv, yv in zip(elements, x_vals, y_vals):
                    show_leg = el not in legend_seen
                    if show_leg:
                        legend_seen.add(el)
                    fig.add_trace(
                        go.Scatter(
                            x=[xv],
                            y=[yv],
                            mode="markers+text",
                            text=[el],
                            textposition="top center",
                            textfont=dict(size=9),
                            name=el,
                            legendgroup=el,
                            showlegend=show_leg,
                            marker=dict(size=9, color=element_color_map.get(el, "#377eb8")),
                            hovertemplate=f"{el}<br>{pc_j}: {xv:.3f}<br>{pc_i}: {yv:.3f}<extra></extra>",
                        ),
                        row=row_idx,
                        col=col_idx,
                    )
                fig.update_xaxes(title_text=pc_j, zeroline=True, row=row_idx, col=col_idx)
                fig.update_yaxes(title_text=pc_i, zeroline=True, row=row_idx, col=col_idx)

            else:
                x_abs = np.abs(loadings_df.loc[pc_j, elements].values)
                y_abs = np.abs(loadings_df.loc[pc_i, elements].values)
                fig.add_trace(
                    go.Scatter(
                        x=x_abs,
                        y=y_abs,
                        mode="markers+text",
                        text=elements,
                        textposition="top center",
                        textfont=dict(size=9),
                        showlegend=False,
                        marker=dict(
                            size=9,
                            color=[element_color_map.get(el, "#377eb8") for el in elements],
                        ),
                        hovertemplate="%{text}<br>|" + pc_j + "|: %{x:.3f}<br>|" + pc_i + "|: %{y:.3f}<extra></extra>",
                    ),
                    row=row_idx,
                    col=col_idx,
                )
                fig.update_xaxes(title_text=f"|{pc_j}|", row=row_idx, col=col_idx)
                fig.update_yaxes(title_text=f"|{pc_i}|", row=row_idx, col=col_idx)

    fig.update_layout(
        height=max(450, 340 * m),
        title_text="PCA Loadings Matrix (Diagonal: Ordered Bars | Upper: Loadings | Lower: |Loadings|)",
        template="plotly_white",
    )
    return fig


def plot_levelling_overlay_histograms(
    df_pre: pd.DataFrame,
    df_post: pd.DataFrame,
    cols_interest: list[str],
    log_scale: bool = True,
    n_cols: int = 4,
    n_bins: int | None = None,
    element_color_map: dict | None = None,
) -> go.Figure:
    """
    Overlay pre-levelling and post-levelling histograms for each selected column.
    Uses light/dark shading of the element's standard color with transparency so
    both distributions remain legible.
    """
    valid_cols = [c for c in cols_interest if c in df_pre.columns and c in df_post.columns]
    n_plots = len(valid_cols)
    n_rows = int(np.ceil(n_plots / n_cols))

    fig = make_subplots(
        rows=n_rows,
        cols=n_cols,
        subplot_titles=valid_cols,
        vertical_spacing=0.14,
        horizontal_spacing=0.08,
    )

    stages = [
        ("Pre-Levelling", df_pre, 1.32),
        ("Post-Levelling", df_post, 0.72),
    ]
    legend_shown = set()

    for idx, col in enumerate(valid_cols):
        r = idx // n_cols + 1
        c = idx % n_cols + 1

        el_symbol = col.split(" ")[0]
        base_color = (
            element_color_map.get(el_symbol)
            if element_color_map and el_symbol in element_color_map
            else "#377eb8"
        )

        combined_vals = []
        stage_arrays = {}
        for stage_label, df_s, _ in stages:
            ser = pd.to_numeric(df_s[col], errors="coerce").dropna()
            if log_scale:
                ser = ser[ser > 0]
                arr = np.log10(ser.to_numpy(dtype=float))
            else:
                arr = ser.to_numpy(dtype=float)
            stage_arrays[stage_label] = arr
            if len(arr) > 0:
                combined_vals.append(arr)

        if not combined_vals:
            continue

        all_vals = np.concatenate(combined_vals)
        x_label = f"log10({col})" if log_scale else col
        bins_count = n_bins if n_bins is not None else max(5, len(all_vals) // 3)
        vmin, vmax = float(np.min(all_vals)), float(np.max(all_vals))
        bin_size = (vmax - vmin) / bins_count if vmax > vmin else 0.1

        for stage_label, _, shade in stages:
            vals = stage_arrays.get(stage_label, np.array([]))
            if len(vals) == 0:
                continue

            bar_color = adjust_hex_lightness(base_color, shade)
            show_leg = stage_label not in legend_shown
            if show_leg:
                legend_shown.add(stage_label)

            fig.add_trace(
                go.Histogram(
                    x=vals,
                    xbins=dict(start=vmin, end=vmax + 1e-9, size=bin_size),
                    marker=dict(
                        color=bar_color,
                        line=dict(color="rgba(0,0,0,0.55)", width=0.8),
                    ),
                    opacity=0.55,
                    name=stage_label,
                    legendgroup=stage_label,
                    showlegend=show_leg,
                    hovertemplate=(
                        f"{stage_label}<br>"
                        f"{x_label}: %{{x:.3f}}<br>Count: %{{y}}<extra></extra>"
                    ),
                ),
                row=r,
                col=c,
            )

        fig.update_xaxes(title_text=x_label, row=r, col=c)
        fig.update_yaxes(title_text="Count", row=r, col=c)

    fig.update_layout(
        height=max(360, 320 * n_rows),
        title_text="Pre vs. Post Levelling — Overlaid Histograms",
        barmode="overlay",
        hovermode="closest",
        template="plotly_white",
    )
    return fig


# def plot_levelling_side_by_side_boxplots(
#     df_pre: pd.DataFrame,
#     df_post: pd.DataFrame,
#     cols_plot: list[str],
#     group_col: str,
#     group_color_map: dict,
#     id_col: str = "Sample ID",
#     n_cols: int = 2,
#     point_mode: str | bool = "outliers",
#     log_scale: bool = True,
#     log_floor: float = 1e-6,
#     separate_ref_groups: bool = False,
# ) -> go.Figure:
#     """
#     Side-by-side boxplots comparing Pre-Levelling vs. Post-Levelling across
#     the active grouping column (Transect or Distance (m)), with Sample ID on hover.
#     """
#     valid_cols = [c for c in cols_plot if c in df_pre.columns and c in df_post.columns]
#     n_plots = len(valid_cols)
#     n_rows = max(1, int(np.ceil(n_plots / max(1, n_cols))))
#     v_spacing = min(0.14, 0.65 / max(n_rows - 1, 1)) if n_rows > 1 else 0.14

#     fig = make_subplots(
#         rows=n_rows,
#         cols=n_cols,
#         subplot_titles=valid_cols,
#         vertical_spacing=v_spacing,
#         horizontal_spacing=0.08,
#     )

#     groups_present = [
#         g for g in group_color_map.keys() if g in set(df_pre[group_col].dropna())
#     ]
#     has_id = id_col in df_pre.columns
#     has_ref = bool(separate_ref_groups) and ("Ref_Group" in df_pre.columns)
#     ref_groups = (
#         ["Background Ref (REF-1..3)", "Site Ref (REF-4..5)", "Non-Reference"]
#         if has_ref
#         else [None]
#     )

#     stages = [
#         ("Pre-Levelling", df_pre, 1.28),
#         ("Post-Levelling", df_post, 0.78),
#     ]
#     legend_shown = set()

#     for idx, col in enumerate(valid_cols):
#         r = idx // n_cols + 1
#         c = idx % n_cols + 1

#         for stage_label, df_s, shade in stages:
#             cols_needed = [group_col, col] + ([id_col] if has_id else []) + (["Ref_Group"] if has_ref else [])
#             sub = df_s[cols_needed].copy()
#             sub[col] = pd.to_numeric(sub[col], errors="coerce")
#             sub = sub.dropna(subset=[group_col, col])

#             if log_scale:
#                 sub = sub[np.isfinite(sub[col])]
#                 if log_floor is not None:
#                     sub[col] = sub[col].clip(lower=log_floor)
#                 else:
#                     sub = sub[sub[col] > 0]

#             for ref_g in ref_groups:
#                 s_sub = sub[sub["Ref_Group"] == ref_g] if ref_g is not None else sub
#                 if s_sub.empty:
#                     continue

#                 x_all, y_all, ids_all = [], [], []
#                 for grp in groups_present:
#                     g_df = s_sub[s_sub[group_col] == grp]
#                     if g_df.empty:
#                         continue
#                     vals = g_df[col].to_numpy(dtype=float)
#                     ids = (
#                         g_df[id_col].astype(str).tolist()
#                         if has_id
#                         else [str(i) for i in g_df.index]
#                     )
#                     x_all.extend([str(grp)] * len(vals))
#                     y_all.extend(vals.tolist())
#                     ids_all.extend(ids)

#                 if not x_all:
#                     continue

#                 base_c = (
#                     get_ref_group_color_map([ref_g]).get(ref_g, "#4c78a8")
#                     if ref_g is not None
#                     else "#4c78a8"
#                 )
#                 box_color = adjust_hex_lightness(base_c, shade)
#                 series_label = f"{stage_label} | {ref_g}" if ref_g is not None else stage_label

#                 show_leg = series_label not in legend_shown
#                 if show_leg:
#                     legend_shown.add(series_label)

#                 ref_hover = f"Reference: {ref_g}<br>" if ref_g is not None else ""

#                 fig.add_trace(
#                     go.Box(
#                         x=x_all,
#                         y=y_all,
#                         customdata=ids_all,
#                         name=series_label,
#                         legendgroup=series_label,
#                         offsetgroup=series_label,
#                         showlegend=show_leg,
#                         fillcolor=box_color,
#                         line=dict(color="#222222", width=1.3),
#                         marker=dict(
#                             color=box_color,
#                             size=5,
#                             line=dict(color="#222222", width=0.6),
#                         ),
#                         boxpoints=point_mode,
#                         jitter=0.25,
#                         pointpos=0.0,
#                         hovertemplate=(
#                             f"<b>Sample ID: %{{customdata}}</b><br>"
#                             f"Stage: {stage_label}<br>"
#                             + ref_hover
#                             + f"{group_col}: %{{x}}<br>"
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
#         title_text=f"Pre vs. Post Levelling — Side-by-Side Boxplots by {group_col}",
#         boxmode="group",
#         boxgroupgap=0.25,
#         boxgap=0.12,
#         template="plotly_white",
#     )
#     return fig


def plot_levelling_side_by_side_boxplots(
    df_pre: pd.DataFrame,
    df_post: pd.DataFrame,
    cols_plot: list[str],
    group_col: str,
    group_color_map: dict,
    id_col: str = "Sample ID",
    n_cols: int = 2,
    point_mode: str | bool = "outliers",
    log_scale: bool = True,
    log_floor: float = 1e-6,
) -> go.Figure:
    """
    Side-by-side boxplots comparing Pre-Levelling vs. Post-Levelling across
    the active grouping column using standard group colors for every group.
    """
    valid_cols = [c for c in cols_plot if c in df_pre.columns and c in df_post.columns]
    n_plots = len(valid_cols)
    n_rows = max(1, int(np.ceil(n_plots / max(1, n_cols))))
    v_spacing = min(0.14, 0.4 / max(n_rows - 1, 1)) if n_rows > 1 else 0.14

    fig = make_subplots(
        rows=n_rows,
        cols=n_cols,
        subplot_titles=valid_cols,
        vertical_spacing=v_spacing,
        horizontal_spacing=0.08,
    )

    groups_present = [
        g for g in group_color_map.keys() if g in set(df_pre[group_col].dropna())
    ]
    has_id = id_col in df_pre.columns

    stages = [
        ("Pre-Levelling", df_pre, 1.28),
        ("Post-Levelling", df_post, 0.78),
    ]
    legend_shown = set()

    for idx, col in enumerate(valid_cols):
        r = idx // n_cols + 1
        c = idx % n_cols + 1

        for stage_label, df_s, shade in stages:
            cols_needed = [group_col, col] + ([id_col] if has_id else [])
            sub = df_s[cols_needed].copy()
            sub[col] = pd.to_numeric(sub[col], errors="coerce")
            sub = sub.dropna(subset=[group_col, col])

            if log_scale:
                sub = sub[np.isfinite(sub[col])]
                if log_floor is not None:
                    sub[col] = sub[col].clip(lower=log_floor)
                else:
                    sub = sub[sub[col] > 0]

            for grp in groups_present:
                g_df = sub[sub[group_col] == grp]
                if g_df.empty:
                    continue

                vals = g_df[col].to_numpy(dtype=float)
                ids = (
                    g_df[id_col].astype(str).tolist()
                    if has_id
                    else [str(i) for i in g_df.index]
                )
                stage_color = adjust_hex_lightness(group_color_map[grp], shade)
                series_label = f"{grp} ({stage_label})"

                show_leg = series_label not in legend_shown
                if show_leg:
                    legend_shown.add(series_label)

                fig.add_trace(
                    go.Box(
                        x=[str(grp)] * len(vals),
                        y=vals,
                        customdata=ids,
                        name=series_label,
                        legendgroup=str(grp),
                        offsetgroup=stage_label,
                        showlegend=show_leg,
                        fillcolor=stage_color,
                        line=dict(color="#222222", width=1.3),
                        marker=dict(
                            color=stage_color,
                            size=5,
                            line=dict(color="#222222", width=0.6),
                        ),
                        boxpoints=point_mode,
                        jitter=0.25,
                        pointpos=0.0,
                        hovertemplate=(
                            f"<b>Sample ID: %{{customdata}}</b><br>"
                            f"Stage: {stage_label}<br>"
                            f"{group_col}: {grp}<br>"
                            f"{col}: %{{y:.4g}}<extra></extra>"
                        ),
                    ),
                    row=r,
                    col=c,
                )

        if log_scale:
            fig.update_yaxes(type="log", row=r, col=c)
        fig.update_xaxes(
            title_text=group_col,
            categoryorder="array",
            categoryarray=[str(g) for g in groups_present],
            row=r,
            col=c,
        )
        fig.update_yaxes(title_text=col, row=r, col=c)

    fig.update_layout(
        height=max(480, 420 * n_rows),
        title_text=f"Pre vs. Post Levelling — Side-by-Side Boxplots by {group_col}",
        boxmode="group",
        boxgroupgap=0.25,
        boxgap=0.12,
        template="plotly_white",
    )
    return fig

def compute_correlation_matrix(
    df_in: pd.DataFrame,
    cols: list[str],
    method: str = "pearson",
    only_meaningful: bool = True,
    r_threshold: float = 0.50,
    alpha: float = 0.05,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Compute pairwise correlation matrix (`r`), two-sided p-values (`p`), and a
    filtered matrix (`r_display`) where non-significant or weak correlations are
    masked out when `only_meaningful=True`. Diagonal entries are kept as 1.0.
    """
    valid_cols = [c for c in cols if c in df_in.columns]
    short_labels = [c.split(" ")[0].lstrip("[").rstrip("]") for c in valid_cols]

    if len(valid_cols) < 2:
        empty = pd.DataFrame()
        return empty, empty, empty

    num_df = df_in[valid_cols].apply(pd.to_numeric, errors="coerce")
    n_vars = len(valid_cols)
    r_mat = np.eye(n_vars, dtype=float)
    p_mat = np.zeros((n_vars, n_vars), dtype=float)

    method_key = method.strip().lower()
    for i in range(n_vars):
        xi = num_df.iloc[:, i]
        for j in range(i + 1, n_vars):
            xj = num_df.iloc[:, j]
            pair = pd.concat([xi, xj], axis=1).dropna()
            if len(pair) < 3:
                r_val, p_val = np.nan, np.nan
            else:
                if method_key == "spearman":
                    res = stats.spearmanr(pair.iloc[:, 0], pair.iloc[:, 1])
                    r_val, p_val = float(res.statistic), float(res.pvalue)
                else:
                    res = stats.pearsonr(pair.iloc[:, 0], pair.iloc[:, 1])
                    r_val, p_val = float(res.statistic), float(res.pvalue)

            r_mat[i, j] = r_mat[j, i] = r_val
            p_mat[i, j] = p_mat[j, i] = p_val

    r_df = pd.DataFrame(r_mat, index=short_labels, columns=short_labels)
    p_df = pd.DataFrame(p_mat, index=short_labels, columns=short_labels)

    if only_meaningful:
        r_disp = r_df.copy()
        for i in range(n_vars):
            for j in range(n_vars):
                if i == j:
                    r_disp.iloc[i, j] = 1.0
                else:
                    rv = r_df.iloc[i, j]
                    pv = p_df.iloc[i, j]
                    is_meaningful = (
                        pd.notna(rv)
                        and pd.notna(pv)
                        and (abs(rv) >= r_threshold)
                        and (pv < alpha)
                    )
                    if not is_meaningful:
                        r_disp.iloc[i, j] = np.nan
    else:
        r_disp = r_df.copy()

    return r_df, p_df, r_disp


def plot_interactive_correlation_heatmap(
    r_disp_df: pd.DataFrame,
    r_full_df: pd.DataFrame,
    p_df: pd.DataFrame,
    full_col_names: list[str],
    method_label: str,
    only_meaningful: bool,
) -> go.Figure:
    """Interactive Plotly heatmap for element correlation matrices."""
    labels = list(r_disp_df.columns)
    z_vals = r_disp_df.to_numpy(dtype=float)

    text_vals = []
    hover_text = []
    for i, r_lbl in enumerate(labels):
        row_txt = []
        row_hov = []
        col_i_full = full_col_names[i] if i < len(full_col_names) else r_lbl
        for j, c_lbl in enumerate(labels):
            col_j_full = full_col_names[j] if j < len(full_col_names) else c_lbl
            rv_disp = z_vals[i, j]
            rv_full = r_full_df.iloc[i, j]
            pv = p_df.iloc[i, j]

            if np.isnan(rv_disp):
                row_txt.append("")
            else:
                row_txt.append(f"{rv_disp:.2f}")

            r_str = "N/A" if pd.isna(rv_full) else f"{rv_full:.3f}"
            p_str = "N/A" if pd.isna(pv) else f"{pv:.2e}"
            status = (
                    "Diagonal"
                    if i == j
                    else ("Kept" if not np.isnan(rv_disp) else "Filtered out")
                )
            row_hov.append(
                f"<b>{r_lbl} vs {c_lbl}</b><br>"
                f"Columns: {col_i_full} / {col_j_full}<br>"
                f"{method_label} r: {r_str}<br>"
                f"p-value: {p_str}<br>"
                f"Status: {status}<extra></extra>"
            )
        text_vals.append(row_txt)
        hover_text.append(row_hov)

    title_suffix = "Meaningful Only" if only_meaningful else "All Pairs"
    fig = go.Figure(
        data=go.Heatmap(
            z=z_vals,
            x=labels,
            y=labels,
            colorscale="RdBu_r",
            zmin=-1.0,
            zmax=1.0,
            zmid=0.0,
            text=text_vals,
            texttemplate="%{text}",
            textfont=dict(size=10),
            hovertemplate=hover_text,
            colorbar=dict(title=f"{method_label} r"),
        )
    )

    n_vars = len(labels)
    fig.update_layout(
        title=f"Element Correlation Matrix ({method_label} — {title_suffix})",
        xaxis=dict(title="Element", side="bottom"),
        yaxis=dict(title="Element", autorange="reversed"),
        height=max(500, 36 * n_vars + 160),
        template="plotly_white",
    )
    return fig


def _runs_test_stats(values: np.ndarray) -> dict:
    """
    Wald-Wolfowitz runs test around the sample median on a 1D numeric array.
    Returns observed runs, expected runs, Z-score, and two-sided p-value.
    """
    x = np.asarray(values, dtype=float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 4:
        return {
            "n": n,
            "n_runs": np.nan,
            "expected_runs": np.nan,
            "z_score": np.nan,
            "p_value": np.nan,
            "lag1_autocorr": np.nan,
        }

    med = float(np.median(x))
    binary = x >= med
    n1 = int(np.sum(binary))
    n2 = int(n - n1)
    n_runs = int(1 + np.sum(binary[1:] != binary[:-1]))

    if n1 == 0 or n2 == 0:
        z_val = np.nan
        p_val = np.nan
        expected = np.nan
    else:
        expected = float(1.0 + (2.0 * n1 * n2) / (n1 + n2))
        denom = float(((n1 + n2) ** 2) * (n1 + n2 - 1))
        var_runs = float((2.0 * n1 * n2 * (2.0 * n1 * n2 - n1 - n2)) / denom) if denom > 0 else 0.0
        if var_runs > 0:
            z_val = float((n_runs - expected) / np.sqrt(var_runs))
            p_val = float(2.0 * (1.0 - stats.norm.cdf(abs(z_val))))
        else:
            z_val = np.nan
            p_val = np.nan

    # Lag-1 serial autocorrelation along current row order
    if n >= 3 and np.std(x[:-1]) > 0 and np.std(x[1:]) > 0:
        lag1 = float(np.corrcoef(x[:-1], x[1:])[0, 1])
    else:
        lag1 = np.nan

    return {
        "n": n,
        "n_runs": n_runs,
        "expected_runs": expected,
        "z_score": z_val,
        "p_value": p_val,
        "lag1_autocorr": lag1,
    }


def compute_randomness_and_dcor(
    df_in: pd.DataFrame,
    target_col: str,
    compare_cols: list[str],
    n_permutations: int = 499,
    random_state: int = 42,
) -> dict:
    """
    Evaluate randomness/sequential structure of `target_col` via runs test,
    lag-1 autocorrelation, and permutation surrogates, plus distance correlation
    (`dcor`) against `compare_cols` if `dcor` is installed.
    """
    rng = np.random.default_rng(random_state)
    obs_series = pd.to_numeric(df_in[target_col], errors="coerce").dropna()
    obs_arr = obs_series.to_numpy(dtype=float)
    runs_stats = _runs_test_stats(obs_arr)

    perm_z = []
    perm_lag1 = []
    if len(obs_arr) >= 4 and n_permutations > 0:
        for _ in range(int(n_permutations)):
            shuffled = rng.permutation(obs_arr)
            st_p = _runs_test_stats(shuffled)
            if np.isfinite(st_p["z_score"]):
                perm_z.append(st_p["z_score"])
            if np.isfinite(st_p["lag1_autocorr"]):
                perm_lag1.append(st_p["lag1_autocorr"])

    perm_z_arr = np.asarray(perm_z, dtype=float)
    perm_lag1_arr = np.asarray(perm_lag1, dtype=float)

    obs_z = runs_stats["z_score"]
    z_perm_pval = (
        float(np.mean(np.abs(perm_z_arr) >= abs(obs_z)))
        if (len(perm_z_arr) > 0 and np.isfinite(obs_z))
        else np.nan
    )

    obs_lag1 = runs_stats["lag1_autocorr"]
    lag1_perm_pval = (
        float(np.mean(np.abs(perm_lag1_arr) >= abs(obs_lag1)))
        if (len(perm_lag1_arr) > 0 and np.isfinite(obs_lag1))
        else np.nan
    )

    # Distance correlation against peer columns
    try:
        import dcor  # type: ignore

        dcor_available = True
    except ImportError:
        dcor = None
        dcor_available = False

    dcor_rows = []
    if dcor_available:
        for col in compare_cols:
            if col == target_col or col not in df_in.columns:
                continue
            pair = pd.concat(
                [
                    pd.to_numeric(df_in[target_col], errors="coerce"),
                    pd.to_numeric(df_in[col], errors="coerce"),
                ],
                axis=1,
            ).dropna()
            if len(pair) < 4:
                continue
            x_vec = pair.iloc[:, 0].to_numpy(dtype=float)
            y_vec = pair.iloc[:, 1].to_numpy(dtype=float)
            dc_val = float(dcor.distance_correlation(x_vec, y_vec))

            # Permutation p-value for distance correlation
            n_dc_perm = min(int(n_permutations), 199)
            if n_dc_perm > 0:
                exceed = 0
                for _ in range(n_dc_perm):
                    y_shuf = rng.permutation(y_vec)
                    if float(dcor.distance_correlation(x_vec, y_shuf)) >= dc_val:
                        exceed += 1
                dc_pval = float(exceed / n_dc_perm)
            else:
                dc_pval = np.nan

            pear_r = float(np.corrcoef(x_vec, y_vec)[0, 1]) if np.std(x_vec) > 0 and np.std(y_vec) > 0 else np.nan
            dcor_rows.append(
                {
                    "Element": col.split(" ")[0].lstrip("[").rstrip("]"),
                    "Column": col,
                    "N": len(pair),
                    "Distance Corr (dCor)": dc_val,
                    "dCor Perm p-value": dc_pval,
                    "Pearson r": pear_r,
                }
            )

    dcor_df = pd.DataFrame(dcor_rows)
    if not dcor_df.empty:
        dcor_df = dcor_df.sort_values(by="Distance Corr (dCor)", ascending=False).reset_index(drop=True)

    return {
        "runs": runs_stats,
        "perm_z": perm_z_arr,
        "z_perm_pval": z_perm_pval,
        "perm_lag1": perm_lag1_arr,
        "lag1_perm_pval": lag1_perm_pval,
        "dcor_available": dcor_available,
        "dcor_df": dcor_df,
    }


def plot_permutation_null_hist(
    null_vals: np.ndarray,
    obs_val: float,
    metric_label: str,
    title: str,
) -> go.Figure:
    """Plot permutation null distribution with observed statistic vertical line."""
    fig = go.Figure()
    if len(null_vals) > 0:
        fig.add_trace(
            go.Histogram(
                x=null_vals,
                nbinsx=25,
                name="Permuted Null",
                marker_color="#7f7f7f",
                opacity=0.75,
                hovertemplate=f"{metric_label} (permuted): %{{x:.3f}}<br>Count: %{{y}}<extra></extra>",
            )
        )
    if np.isfinite(obs_val):
        fig.add_vline(
            x=float(obs_val),
            line_width=2.5,
            line_dash="dash",
            line_color="#d62728",
            annotation_text=f"Observed: {obs_val:.3f}",
            annotation_position="top right",
        )
    fig.update_layout(
        title=title,
        xaxis_title=metric_label,
        yaxis_title="Count",
        template="plotly_white",
        height=340,
    )
    return fig

from sklearn.feature_selection import mutual_info_regression
from sklearn.linear_model import HuberRegressor
from sklearn.preprocessing import StandardScaler


def _morans_i_stats(
    values: np.ndarray,
    lat: np.ndarray,
    lon: np.ndarray,
    k_neighbors: int = 4,
    n_permutations: int = 499,
    seed: int = 42,
) -> dict:
    """Compute Spatial Moran's I using (LatDMS, LonDMS) k-NN weights and permutation p-value."""
    x = np.asarray(values, dtype=float)
    lat_a = np.asarray(lat, dtype=float)
    lon_a = np.asarray(lon, dtype=float)

    valid = np.isfinite(x) & np.isfinite(lat_a) & np.isfinite(lon_a)
    x, lat_a, lon_a = x[valid], lat_a[valid], lon_a[valid]
    n = len(x)
    if n < 5:
        return {
            "n_spatial": n,
            "morans_i": np.nan,
            "expected_i": np.nan,
            "z_score": np.nan,
            "p_value": np.nan,
            "null_i": np.array([], dtype=float),
        }

    dlat = lat_a[:, None] - lat_a[None, :]
    dlon = lon_a[:, None] - lon_a[None, :]
    dist = np.hypot(dlat, dlon)
    np.fill_diagonal(dist, np.inf)

    k = min(max(1, int(k_neighbors)), n - 1)
    w = np.zeros((n, n), dtype=float)
    nn_idx = np.argsort(dist, axis=1)[:, :k]
    for i in range(n):
        w[i, nn_idx[i]] = 1.0 / k

    w_sum = float(np.sum(w))
    expected_i = float(-1.0 / (n - 1)) if n > 1 else np.nan

    def _calc_i(vec: np.ndarray) -> float:
        diff = vec - np.mean(vec)
        denom = float(np.sum(diff ** 2))
        if denom <= 0 or w_sum <= 0:
            return np.nan
        num = float(np.sum(w * np.outer(diff, diff)))
        return float((n / w_sum) * (num / denom))

    obs_i = _calc_i(x)
    if not np.isfinite(obs_i):
        return {
            "n_spatial": n,
            "morans_i": np.nan,
            "expected_i": expected_i,
            "z_score": np.nan,
            "p_value": np.nan,
            "null_i": np.array([], dtype=float),
        }

    rng = np.random.default_rng(seed)
    null_vals = np.array(
        [_calc_i(rng.permutation(x)) for _ in range(int(n_permutations))],
        dtype=float,
    )
    null_vals = null_vals[np.isfinite(null_vals)]
    p_val = float(np.mean(np.abs(null_vals) >= abs(obs_i))) if len(null_vals) > 0 else np.nan
    z_val = (
        float((obs_i - np.mean(null_vals)) / np.std(null_vals))
        if (len(null_vals) > 1 and np.std(null_vals) > 0)
        else np.nan
    )

    return {
        "n_spatial": n,
        "morans_i": obs_i,
        "expected_i": expected_i,
        "z_score": z_val,
        "p_value": p_val,
        "null_i": null_vals,
    }


def run_contamination_diagnostics(
    df_in: pd.DataFrame,
    suspect_col: str,
    peer_cols: list[str],
    lat_col: str = "LatDMS",
    lon_col: str = "LonDMS",
    k_neighbors: int = 4,
    n_permutations: int = 499,
    seed: int = 42,
) -> dict:
    """
    Run five randomness / contamination checks on `suspect_col` relative to `peer_cols`
    and spatial coordinates (`LatDMS`, `LonDMS`):
      1. Distribution comparison (KS test vs. pooled peer values)
      2. Spatial Moran's I (using LatDMS & LonDMS with permutation test)
      3. Mutual information (nonlinear dependence against peers)
      4. Variance comparison (log-IQR / MAD dispersion relative to peers + Levene test)
      5. Robust regression residuals (HuberRegressor R^2 and normalized residual ratio)
    """
    peers = [c for c in peer_cols if c != suspect_col and c in df_in.columns]
    s_suspect = pd.to_numeric(df_in[suspect_col], errors="coerce")

    # 1. Distribution comparison (log10 positive values when available)
    x_pos = s_suspect[s_suspect > 0]
    x_dist = np.log10(x_pos.to_numpy(dtype=float)) if len(x_pos) >= 5 else s_suspect.dropna().to_numpy(dtype=float)

    peer_dist_parts = []
    for c in peers:
        sc = pd.to_numeric(df_in[c], errors="coerce")
        if len(x_pos) >= 5:
            sc_pos = sc[sc > 0]
            if len(sc_pos) > 0:
                peer_dist_parts.append(np.log10(sc_pos.to_numpy(dtype=float)))
        else:
            sc_clean = sc.dropna()
            if len(sc_clean) > 0:
                peer_dist_parts.append(sc_clean.to_numpy(dtype=float))

    if len(x_dist) >= 3 and peer_dist_parts:
        pooled_peers = np.concatenate(peer_dist_parts)
        ks_res = stats.ks_2samp(x_dist, pooled_peers)
        dist_info = {
            "ks_stat": float(ks_res.statistic),
            "ks_p": float(ks_res.pvalue),
            "skew": float(stats.skew(x_dist)) if len(x_dist) >= 3 else np.nan,
        }
    else:
        dist_info = {"ks_stat": np.nan, "ks_p": np.nan, "skew": np.nan}

    # 2. Spatial Moran's I using LatDMS & LonDMS
    has_coords = (lat_col in df_in.columns) and (lon_col in df_in.columns)
    if has_coords:
        lat_vals = pd.to_numeric(df_in[lat_col], errors="coerce").to_numpy(dtype=float)
        lon_vals = pd.to_numeric(df_in[lon_col], errors="coerce").to_numpy(dtype=float)
        spatial_info = _morans_i_stats(
            values=s_suspect.to_numpy(dtype=float),
            lat=lat_vals,
            lon=lon_vals,
            k_neighbors=k_neighbors,
            n_permutations=n_permutations,
            seed=seed,
        )
    else:
        spatial_info = {
            "n_spatial": 0,
            "morans_i": np.nan,
            "expected_i": np.nan,
            "z_score": np.nan,
            "p_value": np.nan,
            "null_i": np.array([], dtype=float),
        }

    # 3. Mutual Information & 4. Variance Comparison across peer elements
    mi_rows = []
    var_rows = []

    def _robust_dispersion(arr: np.ndarray) -> float:
        clean = arr[np.isfinite(arr)]
        if len(clean) < 3:
            return np.nan
        pos = clean[clean > 0]
        target_arr = np.log10(pos) if len(pos) >= 3 else clean
        iqr = float(np.percentile(target_arr, 75) - np.percentile(target_arr, 25))
        return iqr

    suspect_disp = _robust_dispersion(s_suspect.to_numpy(dtype=float))
    levene_groups = []
    levene_names = []

    for c in [suspect_col] + peers:
        el_lbl = c.split(" ")[0].lstrip("[").rstrip("]")
        arr_c = pd.to_numeric(df_in[c], errors="coerce").to_numpy(dtype=float)
        clean_c = arr_c[np.isfinite(arr_c)]
        pos_c = clean_c[clean_c > 0]
        scaled_c = np.log10(pos_c) if len(pos_c) >= 4 else clean_c
        if len(scaled_c) >= 4:
            # Center & scale by MAD so dispersion is comparable across scales
            med_c = float(np.median(scaled_c))
            mad_c = float(stats.median_abs_deviation(scaled_c, nan_policy="omit"))
            if mad_c > 0:
                levene_groups.append((scaled_c - med_c) / mad_c)
                levene_names.append(el_lbl)

        var_rows.append(
            {
                "Element": el_lbl,
                "Column": c,
                "N": int(len(clean_c)),
                "Dispersion (Log-IQR)": _robust_dispersion(arr_c),
                "CV (std/mean)": float(np.std(clean_c) / np.mean(clean_c))
                if (len(clean_c) > 1 and np.mean(clean_c) != 0)
                else np.nan,
            }
        )

    if len(levene_groups) >= 2:
        lev_res = stats.levene(*levene_groups)
        levene_stat, levene_p = float(lev_res.statistic), float(lev_res.pvalue)
    else:
        levene_stat, levene_p = np.nan, np.nan

    var_df = pd.DataFrame(var_rows)
    peer_disp_med = (
        float(var_df.loc[var_df["Column"] != suspect_col, "Dispersion (Log-IQR)"].median())
        if len(var_df) > 1
        else np.nan
    )
    disp_ratio = (
        float(suspect_disp / peer_disp_med)
        if (np.isfinite(suspect_disp) and pd.notna(peer_disp_med) and peer_disp_med > 0)
        else np.nan
    )

    if peers:
        feat_df = df_in[peers].apply(pd.to_numeric, errors="coerce")
        joint = pd.concat([s_suspect.rename("_y"), feat_df], axis=1).dropna()
        if len(joint) >= 5 and len(peers) >= 1:
            y_vec = joint["_y"].to_numpy(dtype=float)
            X_mat = joint[peers].to_numpy(dtype=float)
            mi_scores = mutual_info_regression(X_mat, y_vec, random_state=seed)
            for c, mi_val in zip(peers, mi_scores):
                r_val = (
                    float(np.corrcoef(y_vec, df_in.loc[joint.index, c].astype(float))[0, 1])
                    if np.std(y_vec) > 0 and np.std(df_in.loc[joint.index, c].astype(float)) > 0
                    else np.nan
                )
                mi_rows.append(
                    {
                        "Element": c.split(" ")[0].lstrip("[").rstrip("]"),
                        "Column": c,
                        "Mutual Information": float(mi_val),
                        "Pearson r": r_val,
                    }
                )

            # 5. Robust regression residuals (HuberRegressor predicting suspect from peers)
            scaler = StandardScaler()
            X_scaled = scaler.fit_transform(X_mat)
            huber = HuberRegressor(max_iter=500)
            huber.fit(X_scaled, y_vec)
            y_pred = huber.predict(X_scaled)
            residuals = y_vec - y_pred

            ss_res = float(np.sum(residuals ** 2))
            ss_tot = float(np.sum((y_vec - np.mean(y_vec)) ** 2))
            r2_robust = float(1.0 - ss_res / ss_tot) if ss_tot > 0 else np.nan
            mad_resid = float(stats.median_abs_deviation(residuals, nan_policy="omit"))
            mad_y = float(stats.median_abs_deviation(y_vec, nan_policy="omit"))
            resid_to_y_mad = float(mad_resid / mad_y) if mad_y > 0 else np.nan

            resid_info = {
                "n_reg": len(joint),
                "r2_robust": r2_robust,
                "resid_to_y_mad": resid_to_y_mad,
                "median_abs_resid": float(np.median(np.abs(residuals))),
            }
        else:
            resid_info = {
                "n_reg": len(joint),
                "r2_robust": np.nan,
                "resid_to_y_mad": np.nan,
                "median_abs_resid": np.nan,
            }
    else:
        resid_info = {
            "n_reg": 0,
            "r2_robust": np.nan,
            "resid_to_y_mad": np.nan,
            "median_abs_resid": np.nan,
        }

    mi_df = pd.DataFrame(mi_rows)
    if not mi_df.empty:
        mi_df = mi_df.sort_values(by="Mutual Information", ascending=False).reset_index(drop=True)

    return {
        "has_coords": has_coords,
        "dist": dist_info,
        "spatial": spatial_info,
        "mi_df": mi_df,
        "var_df": var_df,
        "disp_ratio": disp_ratio,
        "levene_stat": levene_stat,
        "levene_p": levene_p,
        "resid": resid_info,
    }


def find_element_col(element_cols: list[str], symbol: str) -> str | None:
    """Find the active column matching an element symbol (e.g., 'Li' or 'Ca')."""
    target = symbol.strip().upper()
    for col in element_cols:
        el_sym = col.split(" ")[0].lstrip("[").rstrip("]").strip().upper()
        if el_sym == target:
            return col
    return None


def build_ratio_dataframe(
    df_in: pd.DataFrame,
    numerator_cols: list[str],
    divisor_col: str,
    zero_or_neg_policy: str = "NaN",
) -> tuple[pd.DataFrame, dict[str, str]]:
    """
    Create ratio columns (`{num_el}/{div_el}`) on a copy of `df_in`.
    Returns `(df_with_ratios, ratio_col_map)` where `ratio_col_map` maps
    `num_col -> ratio_col_name`.
    """
    df = df_in.copy()
    ratio_col_map: dict[str, str] = {}
    if not divisor_col or divisor_col not in df.columns:
        return df, ratio_col_map

    div_el = divisor_col.split(" ")[0].lstrip("[").rstrip("]").strip()
    denom_raw = pd.to_numeric(df[divisor_col], errors="coerce")

    for num_col in numerator_cols:
        if num_col not in df.columns:
            continue
        num_el = num_col.split(" ")[0].lstrip("[").rstrip("]").strip()
        ratio_name = f"{num_el} / {div_el}"

        num_raw = pd.to_numeric(df[num_col], errors="coerce")
        valid_denom = denom_raw.where(denom_raw != 0, np.nan)
        ratio_vals = num_raw / valid_denom
        ratio_vals = ratio_vals.replace([np.inf, -np.inf], np.nan)

        if zero_or_neg_policy == "Set <= 0 to NaN":
            ratio_vals = ratio_vals.where(ratio_vals > 0, np.nan)

        df[ratio_name] = ratio_vals
        ratio_col_map[num_col] = ratio_name

    return df, ratio_col_map


def plot_bivariate_element_scatter(
    df_in: pd.DataFrame,
    y_cols: list[str],
    x_col: str,
    group_col: str,
    group_color_map: dict,
    y_label_override: str | None = None,
    x_label_override: str | None = None,
    log_x: bool = True,
    log_y: bool = True,
    n_cols: int = 3,
    title: str = "Bivariate Scatter vs. Reference Element",
) -> go.Figure:
    """
    Multi-panel bivariate scatter plots of selected `y_cols` against `x_col`,
    colored consistently by `group_col` with `Sample ID` on hover.
    """
    valid_y = [c for c in y_cols if c in df_in.columns and c != x_col]
    if not valid_y or x_col not in df_in.columns:
        return go.Figure()

    n_plots = len(valid_y)
    n_rows = max(1, int(np.ceil(n_plots / max(1, n_cols))))
    v_spacing = min(0.14, 0.65 / max(n_rows - 1, 1)) if n_rows > 1 else 0.14

    subplot_titles = [
        f"{y_label_override or c} vs. {x_label_override or x_col}"
        if y_label_override
        else f"{c.split(' ')[0]} vs. {x_col.split(' ')[0]}"
        for c in valid_y
    ]

    fig = make_subplots(
        rows=n_rows,
        cols=n_cols,
        subplot_titles=subplot_titles,
        vertical_spacing=v_spacing,
        horizontal_spacing=0.08,
    )

    groups_present = [
        g for g in group_color_map.keys() if g in set(df_in[group_col].dropna())
    ] if group_col in df_in.columns else []
    has_id = "Sample ID" in df_in.columns
    has_season = "Season" in df_in.columns
    legend_shown = set()

    for idx, yc in enumerate(valid_y):
        r = idx // n_cols + 1
        c = idx % n_cols + 1

        needed = [x_col, yc] + ([group_col] if group_col in df_in.columns else []) + (["Sample ID"] if has_id else []) + (["Season"] if has_season else [])
        sub = df_in[needed].copy()
        sub[x_col] = pd.to_numeric(sub[x_col], errors="coerce")
        sub[yc] = pd.to_numeric(sub[yc], errors="coerce")
        sub = sub.dropna(subset=[x_col, yc])

        if log_x:
            sub = sub[sub[x_col] > 0]
        if log_y:
            sub = sub[sub[yc] > 0]

        if sub.empty:
            continue

        if not groups_present:
            ids = sub["Sample ID"].astype(str).tolist() if has_id else [str(i) for i in sub.index]
            fig.add_trace(
                go.Scatter(
                    x=sub[x_col].to_numpy(dtype=float),
                    y=sub[yc].to_numpy(dtype=float),
                    mode="markers",
                    customdata=ids,
                    name=yc.split(" ")[0],
                    showlegend=False,
                    marker=dict(size=7, opacity=0.82, color="#377eb8"),
                    hovertemplate=(
                        f"<b>Sample ID: %{{customdata}}</b><br>"
                        f"{x_label_override or x_col}: %{{x:.4g}}<br>"
                        f"{y_label_override or yc}: %{{y:.4g}}<extra></extra>"
                    ),
                ),
                row=r,
                col=c,
            )
        else:
            for grp in groups_present:
                g_df = sub[sub[group_col] == grp]
                if g_df.empty:
                    continue
                ids = g_df["Sample ID"].astype(str).tolist() if has_id else [str(i) for i in g_df.index]
                seasons = g_df["Season"].astype(str).tolist() if has_season else [""] * len(g_df)
                cdata = np.column_stack([ids, seasons])

                show_leg = grp not in legend_shown
                if show_leg:
                    legend_shown.add(grp)

                fig.add_trace(
                    go.Scatter(
                        x=g_df[x_col].to_numpy(dtype=float),
                        y=g_df[yc].to_numpy(dtype=float),
                        mode="markers",
                        customdata=cdata,
                        name=str(grp),
                        legendgroup=str(grp),
                        showlegend=show_leg,
                        marker=dict(
                            size=7,
                            opacity=0.85,
                            color=group_color_map[grp],
                            line=dict(width=0.5, color="#222222"),
                        ),
                        hovertemplate=(
                            f"<b>Sample ID: %{{customdata[0]}}</b><br>"
                            + (f"Season: %{{customdata[1]}}<br>" if has_season else "")
                            + f"{group_col}: {grp}<br>"
                            f"{x_label_override or x_col}: %{{x:.4g}}<br>"
                            f"{y_label_override or yc}: %{{y:.4g}}<extra></extra>"
                        ),
                    ),
                    row=r,
                    col=c,
                )

        if log_x:
            fig.update_xaxes(type="log", row=r, col=c)
        if log_y:
            fig.update_yaxes(type="log", row=r, col=c)
        fig.update_xaxes(title_text=x_label_override or x_col, row=r, col=c)
        fig.update_yaxes(title_text=y_label_override or yc, row=r, col=c)

    fig.update_layout(
        height=max(440, 380 * n_rows),
        title_text=title,
        template="plotly_white",
    )
    return fig


def get_combined_ms_oes_df(
    df_ms: pd.DataFrame | None,
    ms_cols: list[str],
    df_oes: pd.DataFrame | None,
    oes_cols: list[str],
    join_how: str = "inner",
) -> tuple[pd.DataFrame, list[str]]:
    """
    Combine cleaned/filtered MS and OES DataFrames on `Sample ID` with
    explicit `[MS]` / `[OES]` prefixes on element columns so both sheets can
    be analyzed together without column collisions.
    """
    meta_candidates = [
        "Sample ID",
        "Transect",
        "Distance (m)",
        "Season",
        "LatDMS",
        "LonDMS",
    ]

    def _prep_sheet(df_s: pd.DataFrame | None, cols: list[str], tag: str) -> tuple[pd.DataFrame, list[str]]:
        if df_s is None or df_s.empty or "Sample ID" not in df_s.columns:
            return pd.DataFrame(), []
        present_meta = [c for c in meta_candidates if c in df_s.columns]
        present_els = [c for c in cols if c in df_s.columns]
        out = df_s[present_meta + present_els].copy()
        out["Sample ID"] = out["Sample ID"].astype(str).str.strip()
        out = out.drop_duplicates(subset=["Sample ID"], keep="first")

        rename_map = {}
        prefixed_els = []
        for c in present_els:
            clean_el = c.split(" [")[0].strip()
            new_name = f"{clean_el} [{tag}]"
            rename_map[c] = new_name
            prefixed_els.append(new_name)
        out = out.rename(columns=rename_map)
        return out, prefixed_els

    ms_part, ms_prefixed = _prep_sheet(df_ms, ms_cols, "MS")
    oes_part, oes_prefixed = _prep_sheet(df_oes, oes_cols, "OES")

    if ms_part.empty and oes_part.empty:
        return pd.DataFrame(), []
    if ms_part.empty:
        return oes_part, oes_prefixed
    if oes_part.empty:
        return ms_part, ms_prefixed

    merged = pd.merge(
        ms_part,
        oes_part,
        on="Sample ID",
        how=join_how,
        suffixes=("", "_oes"),
    )

    for col in ["Transect", "Distance (m)", "Season", "LatDMS", "LonDMS"]:
        alt = f"{col}_oes"
        if alt in merged.columns:
            if col in merged.columns:
                merged[col] = merged[col].combine_first(merged[alt])
            else:
                merged[col] = merged[alt]
            merged = merged.drop(columns=[alt])

    return merged, ms_prefixed + oes_prefixed