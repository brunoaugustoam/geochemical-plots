# """
# Standard color definitions for geochemical filter/dust analysis.

# Provides deterministic color mappings for:
# - Transects
# - Distances (Distance (m))
# - Elements (used consistently when plotting multiple elements together)

# Any new category or element encountered in an uploaded workbook automatically
# receives a consistent color from a fallback palette so plots never crash or
# randomly shift colors across reruns.
# """

# import hashlib
# import plotly.express as px
# import numpy as np

# # Fallback palettes (high-contrast qualitative colors)
# _FALLBACK_QUALITATIVE = (
#     px.colors.qualitative.Plotly
#     + px.colors.qualitative.D3
#     + px.colors.qualitative.Set1
#     + px.colors.qualitative.Dark24
# )

# # Standard colors by Transect (extend/customize keys to match your dataset)
# TRANSECT_COLORS = {
#     "T1": "#1f77b4",
#     "T2": "#ff7f0e",
#     "T3": "#2ca02c",
#     "T4": "#d62728",
#     "T5": "#9467bd",
#     "Control": "#7f7f7f",
#     "Reference": "#17becf",
# }

# # Standard colors by Distance (m) — keyed by numeric value or string label
# DISTANCE_COLORS = {
#     0: "#8c564b",
#     50: "#d62728",
#     100: "#ff7f0e",
#     250: "#e377c2",
#     500: "#2ca02c",
#     1000: "#1f77b4",
# }

# # Standard colors by Element symbol (consistent across multi-element plots)
# ELEMENT_COLORS = {
#     # MS elements
#     "As": "#e41a1c",
#     "Ba": "#377eb8",
#     "Be": "#4daf4a",
#     "Ce": "#984ea3",
#     "Co": "#ff7f00",
#     "Cr": "#a65628",
#     "Cu": "#f781bf",
#     "Li": "#00bcd4",
#     "Nb": "#6a3d9a",
#     "Pb": "#33a02c",
#     "Rb": "#fb9a99",
#     "Tl": "#b15928",
#     "V": "#1f78b4",
#     # Additional OES elements
#     "Al": "#8dd3c7",
#     "Bi": "#bebada",
#     "Ca": "#fdb462",
#     "Cd": "#b3de69",
#     "Fe": "#d95f02",
#     "K": "#7570b3",
#     "Mg": "#66a61e",
#     "Mn": "#e7298a",
#     "Mo": "#e6ab02",
#     "Na": "#a6761d",
#     "Ni": "#666666",
#     "P": "#1b9e77",
#     "S (ICP)": "#ffed6f",
#     "Sb": "#cab2d6",
#     "Se": "#ffff99",
#     "Si": "#386cb0",
#     "Sr": "#f0027f",
#     "Ti": "#bf5b17",
#     "Zn": "#fdc086",
#     "Zr": "#3288bd",
# }


# def _deterministic_fallback_color(key: str) -> str:
#     """Return a repeatable color from _FALLBACK_QUALITATIVE based on a string key."""
#     digest = hashlib.md5(str(key).encode("utf-8")).hexdigest()
#     idx = int(digest, 16) % len(_FALLBACK_QUALITATIVE)
#     return _FALLBACK_QUALITATIVE[idx]


# def get_group_color_map(values, group_type: str = "Transect") -> dict:
#     """
#     Build a {category_value: hex_color} dictionary for 'Transect' or 'Distance (m)'.
#     Preserves exact order of first appearance while applying standard colors.
#     """
#     color_map = {}
#     seen = []
#     for val in values:
#         if val is None or (isinstance(val, float) and val != val):  # skip NaN
#             continue
#         if val not in seen:
#             seen.append(val)

#     for val in seen:
#         if group_type == "Transect":
#             if val in TRANSECT_COLORS:
#                 color_map[val] = TRANSECT_COLORS[val]
#             elif str(val).strip() in TRANSECT_COLORS:
#                 color_map[val] = TRANSECT_COLORS[str(val).strip()]
#             else:
#                 color_map[val] = _deterministic_fallback_color(f"transect:{val}")
#         else:  # Distance (m)
#             # Try matching numeric distance first, then string representation
#             matched = None
#             if val in DISTANCE_COLORS:
#                 matched = DISTANCE_COLORS[val]
#             else:
#                 try:
#                     num_val = float(val)
#                     if num_val.is_integer() and int(num_val) in DISTANCE_COLORS:
#                         matched = DISTANCE_COLORS[int(num_val)]
#                     elif num_val in DISTANCE_COLORS:
#                         matched = DISTANCE_COLORS[num_val]
#                 except (ValueError, TypeError):
#                     pass

#             if matched is not None:
#                 color_map[val] = matched
#             else:
#                 color_map[val] = _deterministic_fallback_color(f"distance:{val}")

#     return color_map


# def get_element_color_map(elements) -> dict:
#     """
#     Build a {element_symbol: hex_color} dictionary so multi-element plots
#     always use the same color per element.
#     """
#     color_map = {}
#     for el in elements:
#         if el in ELEMENT_COLORS:
#             color_map[el] = ELEMENT_COLORS[el]
#         elif str(el).strip() in ELEMENT_COLORS:
#             color_map[el] = ELEMENT_COLORS[str(el).strip()]
#         else:
#             color_map[el] = _deterministic_fallback_color(f"element:{el}")
#     return color_map

# def adjust_hex_lightness(hex_color: str, factor: float = 1.0) -> str:
#     """
#     Lighten (factor > 1.0) or darken (factor < 1.0) a '#RRGGBB' hex color
#     while keeping its base hue recognizable across seasons.
#     """
#     h = hex_color.lstrip("#")
#     if len(h) != 6:
#         return hex_color
#     r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

#     if factor >= 1.0:
#         # Blend toward white for lighter seasonal shades
#         t = min(factor - 1.0, 0.75)
#         r = int(r + (255 - r) * t)
#         g = int(g + (255 - g) * t)
#         b = int(b + (255 - b) * t)
#     else:
#         # Scale toward black for darker seasonal shades
#         t = max(factor, 0.25)
#         r = int(r * t)
#         g = int(g * t)
#         b = int(b * t)

#     return f"#{r:02x}{g:02x}{b:02x}"


# def get_season_shade_factors(n_seasons: int) -> list[float]:
#     """
#     Return evenly spaced lightness multipliers from lighter (>1) to darker (<1)
#     so overlaid histograms or side-by-side seasonal boxplots remain distinct.
#     """
#     if n_seasons <= 1:
#         return [1.0]
#     return [float(f) for f in np.linspace(1.38, 0.62, n_seasons)]


import hashlib
import numpy as np
import plotly.express as px

# Fallback palettes (high-contrast qualitative colors)
_FALLBACK_QUALITATIVE = (
    px.colors.qualitative.Plotly
    + px.colors.qualitative.D3
    + px.colors.qualitative.Set1
    + px.colors.qualitative.Dark24
)

# Standard colors by Transect (kept intact so Transect stays independent)
TRANSECT_COLORS = {
    "T1": "#1f77b4",
    "T2": "#ff7f0e",
    "T3": "#2ca02c",
    "T4": "#d62728",
    "T5": "#9467bd",
    "Control": "#7f7f7f",
    "Reference": "#17becf",
}

# Standard colors by Distance (m)
DISTANCE_COLORS = {
    0: "#8c564b",
    50: "#d62728",
    100: "#ff7f0e",
    250: "#e377c2",
    500: "#2ca02c",
    1000: "#1f77b4",
}

# Independent reference sample colors:
# REF-1, REF-2, REF-3 = Background references
# REF-4, REF-5 = Site references
REF_GROUP_COLORS = {
    "Background Ref (REF-1..3)": "#17becf",  # Teal/cyan for background references
    "Site Ref (REF-4..5)": "#bcbd22",        # Olive/gold for site references
    "Non-Reference": "#7f7f7f",              # Neutral slate/grey for standard samples
}

# Standard colors by Element symbol (consistent across multi-element plots)
ELEMENT_COLORS = {
    # MS elements
    "As": "#e41a1c",
    "Ba": "#377eb8",
    "Be": "#4daf4a",
    "Ce": "#984ea3",
    "Co": "#ff7f00",
    "Cr": "#a65628",
    "Cu": "#f781bf",
    "Li": "#00bcd4",
    "Nb": "#6a3d9a",
    "Pb": "#33a02c",
    "Rb": "#fb9a99",
    "Tl": "#b15928",
    "V": "#1f78b4",
    # Additional OES elements
    "Al": "#8dd3c7",
    "Bi": "#bebada",
    "Ca": "#fdb462",
    "Cd": "#b3de69",
    "Fe": "#d95f02",
    "K": "#7570b3",
    "Mg": "#66a61e",
    "Mn": "#e7298a",
    "Mo": "#e6ab02",
    "Na": "#a6761d",
    "Ni": "#666666",
    "P": "#1b9e77",
    "S (ICP)": "#ffed6f",
    "Sb": "#cab2d6",
    "Se": "#ffff99",
    "Si": "#386cb0",
    "Sr": "#f0027f",
    "Ti": "#bf5b17",
    "Zn": "#fdc086",
    "Zr": "#3288bd",
}


def _deterministic_fallback_color(key: str) -> str:
    """Return a repeatable color from _FALLBACK_QUALITATIVE based on a string key."""
    digest = hashlib.md5(str(key).encode("utf-8")).hexdigest()
    idx = int(digest, 16) % len(_FALLBACK_QUALITATIVE)
    return _FALLBACK_QUALITATIVE[idx]


def adjust_hex_lightness(hex_color: str, factor: float = 1.0) -> str:
    """
    Lighten (factor > 1.0) or darken (factor < 1.0) a '#RRGGBB' hex color
    while keeping its base hue recognizable across seasons or sub-groups.
    """
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return hex_color
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

    if factor >= 1.0:
        t = min(factor - 1.0, 0.75)
        r = int(r + (255 - r) * t)
        g = int(g + (255 - g) * t)
        b = int(b + (255 - b) * t)
    else:
        t = max(factor, 0.25)
        r = int(r * t)
        g = int(g * t)
        b = int(b * t)

    return f"#{r:02x}{g:02x}{b:02x}"


def get_season_shade_factors(n_seasons: int) -> list[float]:
    """Return evenly spaced lightness multipliers from lighter (>1) to darker (<1)."""
    if n_seasons <= 1:
        return [1.0]
    return [float(f) for f in np.linspace(1.38, 0.62, n_seasons)]


def get_ref_group_color_map(values) -> dict:
    """Build a consistent color dictionary for independent reference groups."""
    color_map = {}
    for val in values:
        if val is None or (isinstance(val, float) and val != val):
            continue
        if val not in color_map:
            color_map[val] = REF_GROUP_COLORS.get(
                str(val), _deterministic_fallback_color(f"ref:{val}")
            )
    return color_map


def get_group_color_map(values, group_type: str = "Transect") -> dict:
    """
    Build a {category_value: hex_color} dictionary for 'Transect',
    'Distance (m)', or independent reference groups.
    """
    if group_type == "Ref_Group":
        return get_ref_group_color_map(values)

    color_map = {}
    seen = []
    for val in values:
        if val is None or (isinstance(val, float) and val != val):
            continue
        if val not in seen:
            seen.append(val)

    for val in seen:
        if group_type == "Transect":
            if val in TRANSECT_COLORS:
                color_map[val] = TRANSECT_COLORS[val]
            elif str(val).strip() in TRANSECT_COLORS:
                color_map[val] = TRANSECT_COLORS[str(val).strip()]
            else:
                color_map[val] = _deterministic_fallback_color(f"transect:{val}")
        else:  # Distance (m)
            matched = None
            if val in DISTANCE_COLORS:
                matched = DISTANCE_COLORS[val]
            else:
                try:
                    num_val = float(val)
                    if num_val.is_integer() and int(num_val) in DISTANCE_COLORS:
                        matched = DISTANCE_COLORS[int(num_val)]
                    elif num_val in DISTANCE_COLORS:
                        matched = DISTANCE_COLORS[num_val]
                except (ValueError, TypeError):
                    pass

            if matched is not None:
                color_map[val] = matched
            else:
                color_map[val] = _deterministic_fallback_color(f"distance:{val}")

    return color_map


def get_element_color_map(elements) -> dict:
    """Build a {element_symbol: hex_color} dictionary for multi-element plots."""
    color_map = {}
    for el in elements:
        if el in ELEMENT_COLORS:
            color_map[el] = ELEMENT_COLORS[el]
        elif str(el).strip() in ELEMENT_COLORS:
            color_map[el] = ELEMENT_COLORS[str(el).strip()]
        else:
            color_map[el] = _deterministic_fallback_color(f"element:{el}")
    return color_map