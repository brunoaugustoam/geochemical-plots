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

    fig = make_subplots(
        rows=n_rows,
        cols=n_cols,
        subplot_titles=valid_cols,
        vertical_spacing=0.14,
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
    separate_ref_groups: bool = False,
    season_order: list[str] | None = None,
) -> go.Figure:
    """
    Interactive Plotly boxplots grouped by Transect or Distance (m) with Sample ID
    on hover, supporting side-by-side season splits and/or independent
    REF-1..3 vs REF-4..5 splits.
    """
    valid_cols = [c for c in cols_plot if c in dataframe.columns]
    n_plots = len(valid_cols)
    n_rows = int(np.ceil(n_plots / n_cols))

    fig = make_subplots(
        rows=n_rows,
        cols=n_cols,
        subplot_titles=valid_cols,
        vertical_spacing=0.14,
        horizontal_spacing=0.08,
    )

    groups_present = [
        g for g in group_color_map.keys() if g in set(dataframe[group_col].dropna())
    ]
    has_id = id_col in dataframe.columns
    has_season = split_by_season and ("Season" in dataframe.columns)
    has_ref = separate_ref_groups and ("Ref_Group" in dataframe.columns)

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
    else:
        ordered_seasons = [None]

    if has_ref:
        present_r = set(dataframe["Ref_Group"].dropna())
        ordered_refs = [r for r in REF_GROUP_ORDER if r in present_r]
        for r_val in sorted(present_r, key=str):
            if r_val not in ordered_refs:
                ordered_refs.append(r_val)
    else:
        ordered_refs = [None]

    ref_color_map = get_ref_group_color_map(ordered_refs) if has_ref else {}
    legend_shown = set()
    use_grouped_mode = has_season or has_ref

    for idx, col in enumerate(valid_cols):
        r = idx // n_cols + 1
        c = idx % n_cols + 1

        cols_needed = (
            [group_col, col]
            + ([id_col] if has_id else [])
            + (["Season"] if has_season else [])
            + (["Ref_Group"] if has_ref else [])
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

        if not use_grouped_mode:
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
                        fillcolor=group_color_map[grp],
                        line=dict(color="#222222", width=1.5),
                        marker=dict(
                            color=group_color_map[grp],
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
            strata = [(seas, ref_g) for seas in ordered_seasons for ref_g in ordered_refs]
            shades = get_season_shade_factors(max(len(strata), 1))

            for (seas, ref_g), shade in zip(strata, shades):
                mask = pd.Series(True, index=sub.index)
                if seas is not None:
                    mask &= sub["Season"] == seas
                if ref_g is not None:
                    mask &= sub["Ref_Group"] == ref_g

                s_df = sub[mask]
                if s_df.empty:
                    continue

                x_all, y_all, ids_all = [], [], []
                for grp in groups_present:
                    g_sub = s_df[s_df[group_col] == grp]
                    if g_sub.empty:
                        continue
                    vals = g_sub[col].to_numpy(dtype=float)
                    ids = (
                        g_sub[id_col].astype(str).tolist()
                        if has_id
                        else [str(i) for i in g_sub.index]
                    )
                    x_all.extend([str(grp)] * len(vals))
                    y_all.extend(vals.tolist())
                    ids_all.extend(ids)

                if not x_all:
                    continue

                if has_ref and not has_season:
                    box_color = ref_color_map.get(ref_g, "#4c78a8")
                elif has_ref and has_season:
                    base_ref_c = ref_color_map.get(ref_g, "#4c78a8")
                    box_color = adjust_hex_lightness(base_ref_c, shade)
                else:
                    box_color = adjust_hex_lightness("#4c78a8", shade)

                parts = []
                if seas is not None:
                    parts.append(str(seas))
                if ref_g is not None:
                    parts.append(str(ref_g))
                stratum_label = " | ".join(parts)

                show_leg = stratum_label not in legend_shown
                if show_leg:
                    legend_shown.add(stratum_label)

                extra_hover = "".join(f"{p}<br>" for p in parts)

                fig.add_trace(
                    go.Box(
                        x=x_all,
                        y=y_all,
                        customdata=ids_all,
                        name=stratum_label,
                        legendgroup=stratum_label,
                        offsetgroup=stratum_label,
                        showlegend=show_leg,
                        fillcolor=box_color,
                        line=dict(color="#222222", width=1.3),
                        marker=dict(
                            color=box_color,
                            size=5,
                            line=dict(color="#222222", width=0.6),
                        ),
                        boxpoints=point_mode,
                        jitter=0.25,
                        pointpos=0.0,
                        hovertemplate=(
                            f"<b>Sample ID: %{{customdata}}</b><br>"
                            + extra_hover
                            + f"{group_col}: %{{x}}<br>"
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
        height=max(420, 390 * n_rows),
        title_text=f"Interactive Boxplots by {group_col}",
        boxmode="group" if use_grouped_mode else "overlay",
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