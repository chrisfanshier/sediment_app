"""Streamlit UI for filling core/dredge event times and positions from an Elog CSV export."""
import pandas as pd
import streamlit as st

from elog_import import (EVENT_FIELDS, FIELD_LABELS, match_elog_events, parse_elog_csv,
                         resolve_positions)
from utils import format_utc_datetime


def _apply(updates):
    """on_click callback: runs before the script reruns, so widget keys may be set here."""
    for key, value in updates.items():
        st.session_state[key] = value


def elog_fill_widget(prefix, core_name, mode, key_map):
    """Render the 'Fill in from Elog' control.

    prefix:   unique string for this form's widget keys.
    core_name: name used to match the Elog Cast column.
    mode:     "core" (position from bottom, fallback deploy) or "dredge" (start=deploy, end=recover).
    key_map:  session_state keys of the form widgets: deploy_utc, bottom_utc, pullout_utc,
              recover_utc, latitude, longitude, coord_format and, for dredges, latitude_end,
              longitude_end, coord_format_end.
    """
    with st.expander("Fill in from Elog"):
        uploaded = st.file_uploader("Elog CSV export", type="csv", key=f"{prefix}_elog_file")
        if uploaded is None:
            return
        if not (core_name or "").strip():
            st.info("Enter the core name first - it is matched against the Elog 'Cast' column.")
            return
        try:
            df = parse_elog_csv(uploaded)
        except Exception as e:
            st.error(f"Could not read the Elog file: {e}")
            return

        match = match_elog_events(df, core_name)

        if match.matched:
            st.success("Matched: " + ", ".join(FIELD_LABELS[f] for f in match.matched))
        else:
            st.error(f"No Elog events found with Cast '{match.cast}'.")
        if match.missing and match.matched:
            st.warning("Not found: " + ", ".join(FIELD_LABELS[f] for f in match.missing))
        if match.near_casts:
            st.info("Similar Cast values in this file: " + ", ".join(match.near_casts))
        if match.unknown_actions:
            st.info("Ignored unrecognised actions for this cast: " + ", ".join(match.unknown_actions))
        if not match.matched:
            return

        # Pick one candidate per field (user chooses when an action was logged more than once)
        selection = {}
        for fld in EVENT_FIELDS:
            cands = match.candidates.get(fld)
            if not cands:
                continue
            if len(cands) == 1:
                selection[fld] = cands[0]
            else:
                idx = st.selectbox(
                    f"{FIELD_LABELS[fld]}: {len(cands)} Elog entries - choose one",
                    range(len(cands)), index=len(cands) - 1,
                    format_func=lambda i, c=cands: c[i].label(),
                    key=f"{prefix}_elog_pick_{fld}",
                )
                selection[fld] = cands[idx]

        updates, rows = {}, []

        def plan(label, key, new):
            if key not in key_map:
                return
            old = st.session_state.get(key_map[key], "")
            updates[key_map[key]] = new
            rows.append({"Field": label, "Current": old or "(empty)", "From Elog": new,
                         "Changes value": "yes" if str(old).strip() != new else "no"})

        for fld, cand in selection.items():
            plan(FIELD_LABELS[fld] + " (UTC)", fld, format_utc_datetime(cand.timestamp.to_pydatetime()))

        pos = resolve_positions(selection, mode)
        for key, label in [("latitude", "Latitude"), ("longitude", "Longitude"),
                           ("latitude_end", "End Latitude"), ("longitude_end", "End Longitude")]:
            if key in pos:
                plan(label, key, f"{pos[key]:.5f}")
        if pos:
            if "coord_format" in key_map and ("latitude" in pos):
                updates[key_map["coord_format"]] = "Decimal Degrees"
            if "coord_format_end" in key_map and ("latitude_end" in pos):
                updates[key_map["coord_format_end"]] = "Decimal Degrees"

        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        st.caption("Fields that were not found are left as they are.")
        st.button("Apply Elog values", key=f"{prefix}_elog_apply", on_click=_apply, args=(updates,))
