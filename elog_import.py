"""Parse Elog CSV exports and match events to a core by its Cast value.

Pure logic (no Streamlit) so it can be unit tested.
"""
import difflib
import re
from dataclasses import dataclass, field

import pandas as pd

# Normalised Elog "Action" text -> cores column
ACTION_TO_FIELD = {
    "deploy": "deploy_utc",
    "on bottom": "bottom_utc",
    "pull out": "pullout_utc",
    "pullout": "pullout_utc",
    "off bottom": "pullout_utc",
    "breakout": "pullout_utc",
    "recover": "recover_utc",
}

EVENT_FIELDS = ["deploy_utc", "bottom_utc", "pullout_utc", "recover_utc"]

FIELD_LABELS = {
    "deploy_utc": "Deploy",
    "bottom_utc": "Bottom",
    "pullout_utc": "Pullout",
    "recover_utc": "Recover",
}

REQUIRED_COLUMNS = ["Action", "Cast", "Latitude", "Longitude", "dateTime8601"]


@dataclass
class ElogCandidate:
    """One Elog row that matches a field for the selected cast."""
    message_id: str
    timestamp: pd.Timestamp  # tz-aware UTC
    latitude: float | None
    longitude: float | None

    def label(self):
        pos = (f"{self.latitude:.5f}, {self.longitude:.5f}"
               if self.latitude is not None and self.longitude is not None else "no position")
        return f"{self.timestamp.strftime('%Y-%m-%d %H:%M:%S')} UTC ({pos}) [msg {self.message_id}]"


@dataclass
class ElogMatch:
    cast: str
    candidates: dict = field(default_factory=dict)   # field -> [ElogCandidate] sorted oldest first
    missing: list = field(default_factory=list)      # fields with no candidate
    near_casts: list = field(default_factory=list)   # similar Cast values that did not match
    unknown_actions: list = field(default_factory=list)  # Action text for this cast we could not map

    @property
    def matched(self):
        return [f for f in EVENT_FIELDS if f in self.candidates]


def normalise_action(action):
    return re.sub(r"\s+", " ", str(action).strip().lower())


def _clean(value):
    value = str(value).strip()
    return "" if value.lower() in ("nan", "none") else value


def _to_float(value):
    value = _clean(value)
    try:
        return float(value) if value else None
    except ValueError:
        return None


def parse_elog_csv(file):
    """Read an Elog export (path or file-like) into a DataFrame of cleaned rows."""
    df = pd.read_csv(file, dtype=str, keep_default_na=False)
    df.columns = [c.strip() for c in df.columns]
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Not an Elog export - missing column(s): {', '.join(missing)}")

    out = pd.DataFrame({
        "message_id": df["Message ID"].map(_clean) if "Message ID" in df.columns else "",
        "action": df["Action"].map(normalise_action),
        "cast": df["Cast"].map(_clean),
        "latitude": df["Latitude"].map(_to_float),
        "longitude": df["Longitude"].map(_to_float),
        "timestamp": pd.to_datetime(df["dateTime8601"].map(_clean), utc=True, errors="coerce"),
    })
    return out[out["timestamp"].notna()].reset_index(drop=True)


def match_elog_events(df, core_name):
    """Find the Elog events for core_name (Cast match is exact, case-insensitive, trimmed)."""
    wanted = core_name.strip().upper()
    match = ElogMatch(cast=core_name.strip())

    casts = [c for c in df["cast"].unique() if c]
    exact = df[df["cast"].str.upper() == wanted]

    for _, row in exact.iterrows():
        fld = ACTION_TO_FIELD.get(row["action"])
        if fld is None:
            if row["action"] not in match.unknown_actions:
                match.unknown_actions.append(row["action"])
            continue
        match.candidates.setdefault(fld, []).append(
            ElogCandidate(row["message_id"], row["timestamp"], row["latitude"], row["longitude"])
        )
    for cands in match.candidates.values():
        cands.sort(key=lambda c: c.timestamp)

    match.missing = [f for f in EVENT_FIELDS if f not in match.candidates]

    if wanted:
        upper = {c.upper(): c for c in casts}
        close = difflib.get_close_matches(wanted, list(upper), n=3, cutoff=0.6)
        close += [u for u in upper if (wanted in u or u in wanted) and u not in close and u != wanted]
        match.near_casts = [upper[u] for u in close if u != wanted]
    return match


def resolve_positions(selection, mode):
    """Choose positions from the selected candidates.

    selection: field -> ElogCandidate (the user's pick per field).
    mode "core":   latitude/longitude from bottom (fallback deploy); no end position.
    mode "dredge": start from deploy, end from recover.
    Returns {"latitude","longitude","latitude_end","longitude_end"} with only the keys that can be filled.
    """
    def pos(*fields):
        for f in fields:
            c = selection.get(f)
            if c is not None and c.latitude is not None and c.longitude is not None:
                return c.latitude, c.longitude
        return None

    result = {}
    start = pos("deploy_utc") if mode == "dredge" else pos("bottom_utc", "deploy_utc")
    if start:
        result["latitude"], result["longitude"] = start
    if mode == "dredge":
        end = pos("recover_utc")
        if end:
            result["latitude_end"], result["longitude_end"] = end
    return result
