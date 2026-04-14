#!/usr/bin/env python3
"""
Core Correlator GUI — Compare and correlate geological core sections
using CT imagery and MSCL data side by side with vertical drag alignment.

Connects directly to the sediment_cores PostgreSQL database via db_util.
Cruise → Core → Section selection is driven by database queries against
the ct_xml, cores, cruises, and mscl_files tables.

Image types supported: giXRayImage, giCTOrthogonalView
"""

import sys
import os
import numpy as np
import xml.etree.ElementTree as ET
from pathlib import Path
from collections import defaultdict
from PIL import Image, ImageDraw, ImageFont
import pyqtgraph as pg
pg.setConfigOptions(useOpenGL=False, antialias=True, background="w", foreground="k")

# Enable high-DPI rendering before QApplication is created
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QListWidget, QListWidgetItem, QLabel,
    QScrollArea, QCheckBox, QComboBox, QSlider, QLineEdit,
    QGroupBox, QStatusBar, QMessageBox, QSizePolicy)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QPixmap, QImage, QWheelEvent, QPainter, QColor, QPen

# ── Import path for db_util / config when running standalone ───────────────────
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
for _candidate in [
    os.path.join(_SCRIPT_DIR, "scripts"),
    _SCRIPT_DIR,
    r"c:\sediment_app\scripts",
]:
    if os.path.isdir(_candidate) and _candidate not in sys.path:
        sys.path.insert(0, _candidate)

from sqlalchemy import text as sa_text
from db_util import get_connection
from config import get_full_path, ROOT_DIRECTORY

# ── Constants ──────────────────────────────────────────────────────────────────
FALLBACK_PX_PER_CM  = 35.0
UI_PX_PER_CM        = 22.0
RENDER_SCALE        = 4       # internal render multiplier for crisp output
CROP_COL_THRESH     = 0.15
CROP_ROW_THRESH     = 0.25

# Image types the app supports (maps display label -> image_type value in ct_xml)
SUPPORTED_IMAGE_TYPES = {
    "XRay (giXRayImage)":                "giXRayImage",
    "CT Orthogonal (giCTOrthogonalView)": "giCTOrthogonalView",
}

MSCL_COLORS = [
    "#1f77b4", "#d62728", "#2ca02c", "#ff7f0e",
    "#9467bd", "#8c564b", "#17becf", "#e377c2",
]

STRIP_BG     = (255, 255, 255)
HEADER_BG    = (235, 235, 245)
SCALE_FG     = (60, 60, 60)
SECTION_LINE = (180, 180, 200)
LABEL_COLOR  = (30, 30, 30)


# ── Database helpers ───────────────────────────────────────────────────────────

def db_get_cruises_with_ct():
    """Return [(cruise_id, cruise_name), ...] for cruises that have ct_xml data."""
    with get_connection() as conn:
        rows = conn.execute(sa_text("""
            SELECT DISTINCT cr.cruise_id, cr.cruise_name
            FROM cruises cr
            JOIN cores c  ON c.cruise_id = cr.cruise_id
            JOIN ct_xml x ON x.core_name = c.core_name
            ORDER BY cr.cruise_name
        """)).fetchall()
    return [(r[0], r[1]) for r in rows]


def db_get_cores_for_cruise(cruise_id, image_type=None):
    """Return [core_name, ...] for a cruise that have ct_xml rows.
    Optionally filter to a specific image_type."""
    q = """
        SELECT DISTINCT c.core_name
        FROM cores c
        JOIN ct_xml x ON x.core_name = c.core_name
        WHERE c.cruise_id = :cruise_id
    """
    params = {"cruise_id": cruise_id}
    if image_type:
        q += " AND x.image_type = :image_type"
        params["image_type"] = image_type
    q += " ORDER BY c.core_name"
    with get_connection() as conn:
        rows = conn.execute(sa_text(q), params).fetchall()
    return [r[0] for r in rows]


def db_get_suffixes_for_core(core_name, image_type):
    """Discover filename suffixes present for a core + image_type.
    Returns a sorted list of suffix strings found between the base stem
    and .tif extension (e.g. '_corrected', '_filtered', '').
    Empty string means no suffix (plain filename)."""
    with get_connection() as conn:
        rows = conn.execute(sa_text("""
            SELECT tif_filename, xml_path FROM ct_xml
            WHERE core_name = :cn AND image_type = :it
        """), {"cn": core_name, "it": image_type}).fetchall()
    suffixes = set()
    for r in rows:
        fn = r[0] or ""
        if not fn and r[1]:
            fn = os.path.splitext(os.path.basename(r[1]))[0] + ".tif"
        if not fn:
            continue
        stem = os.path.splitext(fn)[0]
        lower = stem.lower()
        # Compare against the xml basename to isolate the suffix
        xml_stem = ""
        if r[1]:
            xml_stem = os.path.splitext(os.path.basename(r[1]))[0].lower()
        if xml_stem and lower.startswith(xml_stem) and lower != xml_stem:
            suffixes.add(stem[len(xml_stem):])  # preserve original case
        elif xml_stem and lower == xml_stem:
            suffixes.add("")   # no suffix — original file
        else:
            # Fallback: detect common known suffixes
            for known in ("_beam_hardening_corrected", "_corrected", "_filtered"):
                if lower.endswith(known):
                    suffixes.add(known)
                    break
            else:
                suffixes.add("")
    return sorted(suffixes)


def db_get_sections_for_core(core_name, image_type, suffix_filter=None):
    """
    Return ct_xml rows for (core_name, image_type), ordered by section_number.
    Each row dict: tiff_folder, xml_path, tif_filename, section_number,
    processing_stage, xml_root_tag.

    suffix_filter: if not None, only rows whose tif filename ends with that
    suffix (before extension) are returned.  '' means only un-suffixed files.
    """
    with get_connection() as conn:
        rows = conn.execute(sa_text("""
            SELECT section_number, tiff_folder, xml_path,
                   tif_filename, processing_stage, xml_root_tag
            FROM ct_xml
            WHERE core_name  = :cn
              AND image_type = :it
            ORDER BY CAST(section_number AS INTEGER)
        """), {"cn": core_name, "it": image_type}).fetchall()

    result = []
    for r in rows:
        d = dict(r._mapping)
        if suffix_filter is not None:
            fn = d.get("tif_filename") or ""
            if not fn and d.get("xml_path"):
                fn = os.path.splitext(os.path.basename(d["xml_path"]))[0] + ".tif"
            stem = os.path.splitext(fn)[0].lower() if fn else ""
            xml_stem = ""
            if d.get("xml_path"):
                xml_stem = os.path.splitext(
                    os.path.basename(d["xml_path"]))[0].lower()
            if suffix_filter == "":
                # Only plain (un-suffixed) files
                if xml_stem and stem != xml_stem:
                    continue
            else:
                if not stem.endswith(suffix_filter.lower()):
                    continue
        result.append(d)
    return result


def db_get_px_per_cm_from_xml(xml_rel_path):
    """Parse an XML metadata file to extract pixels-per-cm."""
    if not xml_rel_path:
        return FALLBACK_PX_PER_CM
    xml_abs = get_full_path(xml_rel_path)
    if not os.path.exists(xml_abs):
        return FALLBACK_PX_PER_CM
    try:
        root = ET.parse(xml_abs).getroot()
        for tag in ("horizontal-resolution", "pixels-per-CM",
                    "pixels-per-cm", "PixelsPerCM"):
            el = root.find(f".//{tag}")
            if el is not None and el.text:
                return float(el.text.strip())
    except Exception:
        pass
    return FALLBACK_PX_PER_CM


def db_resolve_tif_path(row):
    """
    Find the absolute path of the TIF for a ct_xml row dict.
    Strategy:
      1. Use tif_filename from DB if present.
      2. Derive from xml_path stem (same name, .tif extension).
      3. Search tiff_folder for any .tif / .tiff file.
    Returns None if nothing found on disk.
    """
    folder_abs = get_full_path(row["tiff_folder"])
    tif_fn     = row.get("tif_filename")

    candidates = []
    if tif_fn:
        candidates.append(os.path.join(folder_abs, tif_fn))
    if row.get("xml_path"):
        stem = os.path.splitext(os.path.basename(row["xml_path"]))[0]
        candidates.append(os.path.join(folder_abs, stem + ".tif"))
        candidates.append(os.path.join(folder_abs, stem + ".tiff"))

    for c in candidates:
        if os.path.exists(c):
            return c

    # Last resort: first .tif in the folder
    if os.path.isdir(folder_abs):
        for f in sorted(os.listdir(folder_abs)):
            if f.lower().endswith((".tif", ".tiff")):
                return os.path.join(folder_abs, f)

    return None


def db_get_section_files(core_name, image_type):
    """Return {section_number: [row_dict, ...], ...} for all ct_xml rows
    matching (core_name, image_type).  Each row_dict contains the full
    ct_xml columns needed to resolve a TIF path.  Sections are sorted
    numerically and files within each section are sorted by tif_filename."""
    with get_connection() as conn:
        rows = conn.execute(sa_text("""
            SELECT section_number, tiff_folder, xml_path,
                   tif_filename, processing_stage, xml_root_tag
            FROM ct_xml
            WHERE core_name  = :cn
              AND image_type = :it
            ORDER BY CAST(section_number AS INTEGER), tif_filename
        """), {"cn": core_name, "it": image_type}).fetchall()
    result = defaultdict(list)
    for r in rows:
        d = dict(r._mapping)
        sec = int(d["section_number"] or 0)
        result[sec].append(d)
    return dict(result)


def db_get_mscl_files_for_core(core_name):
    """Return [(file_name, file_path, remarks), ...] for MSCL files linked to this core."""
    with get_connection() as conn:
        rows = conn.execute(sa_text("""
            SELECT mf.file_name, mf.file_path, mf.remarks
            FROM mscl_files mf
            JOIN cores c ON c.core_id = mf.core_id
            WHERE c.core_name = :cn
            ORDER BY mf.file_name
        """), {"cn": core_name}).fetchall()
    return [(r[0], r[1], r[2]) for r in rows]


# ── Image Processing ───────────────────────────────────────────────────────────

def auto_crop(arr):
    max_val = arr.max()
    if max_val == 0:
        return arr, 0
    col_means = arr.mean(axis=0)
    row_means = arr.mean(axis=1)
    left   = int(np.argmax(col_means > max_val * CROP_COL_THRESH))
    right  = int(len(col_means)
                 - np.argmax(col_means[::-1] > max_val * CROP_COL_THRESH) - 1)
    top    = int(np.argmax(row_means > max_val * CROP_ROW_THRESH))
    bottom = int(len(row_means)
                 - np.argmax(row_means[::-1] > max_val * CROP_ROW_THRESH) - 1)
    if right > left and bottom > top:
        return arr[top:bottom + 1, left:right + 1], top
    return arr, 0


def load_tif_scientific(tif_path, px_per_cm=FALLBACK_PX_PER_CM):
    """Load TIF, auto-crop, contrast-stretch.
    Returns (PIL L-mode image, px_per_cm, crop_top_px, original_px_h).
    """
    img = Image.open(tif_path)
    if img.mode in ("I;16", "I;16B", "I"):
        arr = np.array(img, dtype=np.float32)
    else:
        arr = np.array(img.convert("L"), dtype=np.float32)
    original_px_h = arr.shape[0]
    arr, crop_top_px = auto_crop(arr)
    lo, hi = np.percentile(arr, (1, 99))
    if hi > lo:
        arr = np.clip(arr, lo, hi)
        arr = (arr - lo) / (hi - lo) * 255.0
    else:
        arr[:] = 0
    return (Image.fromarray(arr.astype(np.uint8)),
            px_per_cm, crop_top_px, original_px_h)


# ── Image Cache ────────────────────────────────────────────────────────────────

class ImageCache:
    def __init__(self):
        self._cache = {}

    def get(self, tif_path: str, px_per_cm: float):
        key = str(tif_path)
        if key not in self._cache:
            self._cache[key] = load_tif_scientific(tif_path, px_per_cm)
        return self._cache[key]

    def clear(self):
        self._cache = {}


# ── MSCL Data Parsing ──────────────────────────────────────────────────────────

def parse_mscl_file(filepath):
    lines = Path(filepath).read_text(
        encoding="utf-8", errors="replace").splitlines()
    header_idx = None
    for i, line in enumerate(lines):
        if line.strip().upper().startswith("SB DEPTH"):
            header_idx = i
            break
    if header_idx is None:
        return None, []

    headers    = [h.strip() for h in lines[header_idx].split("\t")]
    data_start = header_idx + 2
    skip_cols  = {"SB DEPTH", "SECT NUM", "SECT DEPTH"}
    data_columns = [h for h in headers
                    if h and h.upper() not in {s.upper() for s in skip_cols}]

    sect_num_idx   = next((i for i, h in enumerate(headers)
                           if h.upper() == "SECT NUM"), None)
    sect_depth_idx = next((i for i, h in enumerate(headers)
                           if h.upper() == "SECT DEPTH"), None)
    if sect_num_idx is None or sect_depth_idx is None:
        return None, []

    section_data = defaultdict(
        lambda: {c: [] for c in ["SECT DEPTH"] + data_columns})

    for line in lines[data_start:]:
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < len(headers):
            continue
        raw_sec = parts[sect_num_idx].strip()
        if "cal" in raw_sec.lower():
            continue
        try:
            sec_num    = int(raw_sec)
            sect_depth = float(parts[sect_depth_idx].strip())
        except ValueError:
            continue
        section_data[sec_num]["SECT DEPTH"].append(sect_depth)
        for col in data_columns:
            idx = headers.index(col)
            try:
                section_data[sec_num][col].append(float(parts[idx].strip()))
            except (ValueError, IndexError):
                section_data[sec_num][col].append(float("nan"))

    for sec in section_data:
        for col in section_data[sec]:
            section_data[sec][col] = np.array(section_data[sec][col])

    return dict(section_data), data_columns


# ── Font helper ────────────────────────────────────────────────────────────────

def _pil_font(size):
    for path in ("arialbd.ttf", "arial.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()


# ── Draggable Core Panel ───────────────────────────────────────────────────

class DraggableCoreStrip(QWidget):
    """Composite widget: CT image + optional pyqtgraph MSCL plots side by side.
    The entire panel is draggable vertically for correlation alignment."""
    offset_changed = Signal()

    def __init__(self, core_id, px_per_cm_display, parent=None):
        super().__init__(parent)
        self.core_id           = core_id
        self.px_per_cm_display = px_per_cm_display
        self.offset_px         = 0
        self.locked            = False
        self._drag_active      = False
        self._drag_start_y     = 0
        self._drag_start_offset = 0

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        # CT image label (pixmap includes header + data + padding)
        self._ct_label = QLabel()
        self._ct_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._layout.addWidget(self._ct_label)

        # Right-side container for MSCL plots with header spacer
        self._plots_container = QWidget()
        self._plots_vlayout   = QVBoxLayout(self._plots_container)
        self._plots_vlayout.setContentsMargins(0, 0, 0, 0)
        self._plots_vlayout.setSpacing(0)

        self._header_spacer = QWidget()
        self._header_spacer.setFixedHeight(0)
        self._plots_vlayout.addWidget(self._header_spacer)

        self._plots_row = QHBoxLayout()
        self._plots_row.setContentsMargins(0, 0, 0, 0)
        self._plots_row.setSpacing(2)
        self._plots_vlayout.addLayout(self._plots_row, 1)

        self._plots_container.hide()
        self._layout.addWidget(self._plots_container, 0, Qt.AlignTop)

        self._plot_widgets = []
        self.setCursor(Qt.OpenHandCursor)

    @property
    def offset_cm(self):
        if self.px_per_cm_display > 0:
            return self.offset_px / self.px_per_cm_display
        return 0.0

    def set_pixmap(self, pixmap):
        self._ct_label.setPixmap(pixmap)
        dpr = pixmap.devicePixelRatio()
        w = int(pixmap.width() / dpr)
        h = int(pixmap.height() / dpr)
        self._ct_label.setFixedSize(w, h)
        self._update_size()

    def set_mscl_plots(self, plot_widgets, data_height, header_height):
        """Attach pyqtgraph PlotWidgets to the right of the CT image.
        data_height: pixel height of the CT data area (excludes header).
        header_height: pixel height of the CT header area."""
        # Clear old plots
        for pw in self._plot_widgets:
            self._plots_row.removeWidget(pw)
            pw.deleteLater()
        self._plot_widgets = []

        if not plot_widgets:
            self._plots_container.hide()
            self._update_size()
            return

        # The bottom axis label consumes some height inside the PlotWidget,
        # so the widget must be taller than the CT data area to compensate.
        BOTTOM_AXIS_H = 18
        self._header_spacer.setFixedHeight(header_height)
        widget_h = data_height + BOTTOM_AXIS_H
        for pw in plot_widgets:
            pw.setFixedHeight(widget_h)
            self._plots_row.addWidget(pw)
            self._plot_widgets.append(pw)
        self._plots_container.setFixedHeight(
            header_height + widget_h)
        self._plots_container.show()
        self._update_size()

    def _update_size(self):
        ct_w = self._ct_label.width()
        ct_h = self._ct_label.height()
        plots_w = sum(pw.width() for pw in self._plot_widgets)
        if plots_w > 0:
            plots_w += 2 * max(0, len(self._plot_widgets) - 1)  # spacing
        self.setFixedSize(ct_w + plots_w, ct_h)

    def set_locked(self, locked):
        self.locked = locked
        self.setCursor(Qt.ForbiddenCursor if locked else Qt.OpenHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and not self.locked:
            self._drag_active       = True
            self._drag_start_y      = event.globalPosition().y()
            self._drag_start_offset = self.offset_px
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_active:
            delta          = event.globalPosition().y() - self._drag_start_y
            self.offset_px = self._drag_start_offset + int(delta)
            self.offset_changed.emit()
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_active = False
            if not self.locked:
                self.setCursor(Qt.OpenHandCursor)
            event.accept()


# ── Correlation Canvas ─────────────────────────────────────────────────────────

class CorrelationCanvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.strips      = []
        self._pad_top    = 600
        self._pad_sides  = 20
        self._gap        = 20
        self._guide_y    = -1
        self._show_guide = False
        self.setMouseTracking(True)
        self.setStyleSheet("background-color: #f5f5f5;")

    def clear(self):
        for s in self.strips:
            s.setParent(None)
            s.deleteLater()
        self.strips = []
        self.setMinimumSize(100, 100)

    def add_strip(self, strip: DraggableCoreStrip):
        strip.setParent(self)
        strip.offset_changed.connect(self._reposition)
        self.strips.append(strip)
        self._reposition()

    def _reposition(self):
        x          = self._pad_sides
        max_bottom = 0
        for strip in self.strips:
            y = self._pad_top + strip.offset_px
            strip.move(x, y)
            strip.show()
            x         += strip.width() + self._gap
            max_bottom = max(max_bottom, y + strip.height())
        total_w = x + self._pad_sides
        total_h = max(max_bottom + 200, self._pad_top * 2)
        self.setMinimumSize(total_w, total_h)

    def reset_offsets(self):
        for s in self.strips:
            s.offset_px = 0
        self._reposition()

    def set_show_guide(self, show):
        self._show_guide = show
        self.update()

    def mouseMoveEvent(self, event):
        if self._show_guide:
            self._guide_y = int(event.position().y())
            self.update()
        super().mouseMoveEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._show_guide and self._guide_y >= 0:
            p   = QPainter(self)
            pen = QPen(QColor(255, 0, 0, 150), 1, Qt.DashLine)
            p.setPen(pen)
            p.drawLine(0, self._guide_y, self.width(), self._guide_y)
            p.end()


# ── Zoomable Scroll Area ───────────────────────────────────────────────────────

class ZoomableScrollArea(QScrollArea):
    zoom_changed = Signal(int)

    def wheelEvent(self, event: QWheelEvent):
        if event.modifiers() & Qt.ControlModifier:
            self.zoom_changed.emit(event.angleDelta().y())
            event.accept()
        else:
            super().wheelEvent(event)


# ── Main Application ───────────────────────────────────────────────────────────

class CoreCorrelatorApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Core Correlator")
        self.resize(1500, 950)

        # DB-driven state
        self._cruises: list      = []   # [(cruise_id, cruise_name), ...]
        self._core_names: list   = []   # available for selected cruise

        # Section cache: (core_name, image_type, suffix) -> [section dicts]
        self.core_sections: dict = {}
        self.image_cache         = ImageCache()

        # Display state
        self.zoom_factor = 1.0

        # MSCL state
        self.mscl_store       = {}
        self.mscl_col_rows    = {}
        self.all_mscl_columns = []

        self._build_ui()
        self._populate_cruises()

    # ── UI Construction ────────────────────────────────────────────────────

    def _build_ui(self):
        central     = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)

        # ── Left panel (scrollable) ─────────────────────────────────
        left_inner = QWidget()
        left_inner.setMinimumWidth(290)
        lv = QVBoxLayout(left_inner)
        lv.setContentsMargins(4, 4, 4, 4)

        left_scroll = QScrollArea()
        left_scroll.setWidget(left_inner)
        left_scroll.setWidgetResizable(True)
        left_scroll.setMaximumWidth(380)
        left_scroll.setMinimumWidth(290)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # ── Data Source ────────────────────────────────────────────────
        grp = QGroupBox("Data Source")
        gl  = QVBoxLayout(grp)

        gl.addWidget(QLabel("Cruise:"))
        self.combo_cruise = QComboBox()
        self.combo_cruise.currentIndexChanged.connect(self._on_cruise_changed)
        gl.addWidget(self.combo_cruise)

        self.btn_refresh = QPushButton("↻ Refresh from Database")
        self.btn_refresh.clicked.connect(self._populate_cruises)
        gl.addWidget(self.btn_refresh)

        self.lbl_db = QLabel("")
        self.lbl_db.setWordWrap(True)
        self.lbl_db.setStyleSheet("color: #aaa; font-size: 11px;")
        gl.addWidget(self.lbl_db)
        lv.addWidget(grp)

        # ── Image Type + Suffix ────────────────────────────────────────
        grp = QGroupBox("Image Type")
        gl  = QVBoxLayout(grp)
        self.combo_type = QComboBox()
        for label in SUPPORTED_IMAGE_TYPES:
            self.combo_type.addItem(label)
        self.combo_type.currentIndexChanged.connect(self._on_type_changed)
        gl.addWidget(self.combo_type)

        gl.addWidget(QLabel("Filename suffix filter:"))
        self.combo_suffix = QComboBox()
        self.combo_suffix.addItem("(all variants)")
        self.combo_suffix.currentIndexChanged.connect(self._on_suffix_changed)
        gl.addWidget(self.combo_suffix)
        lv.addWidget(grp)

        # ── Core / Section selection ───────────────────────────────────
        grp = QGroupBox("Cores / Sections")
        gl  = QVBoxLayout(grp)

        self.list_cores = QListWidget()
        self.list_cores.itemChanged.connect(self._on_core_checked)
        gl.addWidget(self.list_cores)

        # Per-section controls (scrollable area below core list)
        self._sec_inner   = QWidget()
        self._sec_vlayout = QVBoxLayout(self._sec_inner)
        self._sec_vlayout.setContentsMargins(2, 2, 2, 2)
        self._sec_vlayout.setSpacing(2)
        self.sec_scroll = QScrollArea()
        self.sec_scroll.setWidget(self._sec_inner)
        self.sec_scroll.setWidgetResizable(True)
        gl.addWidget(self.sec_scroll, 1)

        # { core_name: { section_num: {"check": QCheckBox, "combo": QComboBox,
        #                               "files": [row_dict, ...]} } }
        self._section_widgets = {}

        lv.addWidget(grp, 1)   # stretch so it fills available space

        # ── MSCL ──────────────────────────────────────────────────────
        grp = QGroupBox("MSCL Data")
        gl  = QVBoxLayout(grp)

        gl.addWidget(QLabel("Core:"))
        self.combo_mscl_core = QComboBox()
        self.combo_mscl_core.currentIndexChanged.connect(self._on_mscl_core_changed)
        gl.addWidget(self.combo_mscl_core)

        gl.addWidget(QLabel("MSCL File:"))
        self.combo_mscl_file = QComboBox()
        gl.addWidget(self.combo_mscl_file)

        self.btn_mscl_load = QPushButton("Load from DB")
        self.btn_mscl_load.clicked.connect(self._load_mscl_from_db)
        gl.addWidget(self.btn_mscl_load)

        self.lbl_mscl = QLabel("")
        self.lbl_mscl.setWordWrap(True)
        gl.addWidget(self.lbl_mscl)

        self.chk_mscl = QCheckBox("Show MSCL Plots")
        self.chk_mscl.setChecked(True)
        self.chk_mscl.stateChanged.connect(self.refresh_display)
        gl.addWidget(self.chk_mscl)

        wr = QHBoxLayout()
        self.lbl_mscl_w    = QLabel("Plot width: 150")
        self.slider_mscl_w = QSlider(Qt.Horizontal)
        self.slider_mscl_w.setRange(40, 800)
        self.slider_mscl_w.setValue(150)
        self.slider_mscl_w.valueChanged.connect(self._on_mscl_width)
        wr.addWidget(self.lbl_mscl_w)
        wr.addWidget(self.slider_mscl_w)
        gl.addLayout(wr)

        gl.addWidget(QLabel("Columns (check  min  max):"))
        self._mscl_inner   = QWidget()
        self._mscl_vlayout = QVBoxLayout(self._mscl_inner)
        self._mscl_vlayout.setContentsMargins(2, 2, 2, 2)
        self._mscl_vlayout.setSpacing(2)
        self.mscl_col_area = QScrollArea()
        self.mscl_col_area.setWidget(self._mscl_inner)
        self.mscl_col_area.setWidgetResizable(True)
        self.mscl_col_area.setMaximumHeight(180)
        gl.addWidget(self.mscl_col_area)
        lv.addWidget(grp)

        # ── Display options ────────────────────────────────────────────
        grp = QGroupBox("Display")
        gl  = QVBoxLayout(grp)
        self.chk_scale = QCheckBox("Show Depth Scale")
        self.chk_scale.setChecked(True)
        self.chk_scale.stateChanged.connect(self.refresh_display)
        gl.addWidget(self.chk_scale)
        self.chk_sec_lines = QCheckBox("Show Section Boundaries")
        self.chk_sec_lines.setChecked(True)
        self.chk_sec_lines.stateChanged.connect(self.refresh_display)
        gl.addWidget(self.chk_sec_lines)
        self.chk_guide = QCheckBox("Horizontal Guide Line")
        self.chk_guide.setChecked(False)
        self.chk_guide.stateChanged.connect(
            lambda s: self.canvas.set_show_guide(s == Qt.Checked.value))
        gl.addWidget(self.chk_guide)
        zr = QHBoxLayout()
        self.lbl_zoom = QLabel("Zoom: 100%")
        btn_zi = QPushButton("+")
        btn_zo = QPushButton("−")
        btn_zi.setFixedWidth(30)
        btn_zo.setFixedWidth(30)
        btn_zi.clicked.connect(
            lambda: self._set_zoom(self.zoom_factor + 0.2))
        btn_zo.clicked.connect(
            lambda: self._set_zoom(self.zoom_factor - 0.2))
        zr.addWidget(self.lbl_zoom)
        zr.addWidget(btn_zo)
        zr.addWidget(btn_zi)
        gl.addLayout(zr)
        gl.addWidget(QLabel("Ctrl+Scroll to zoom"))
        lv.addWidget(grp)

        # ── Offset controls ───────────────────────────────────────────
        grp = QGroupBox("Correlation Offset")
        gl  = QVBoxLayout(grp)
        self.lbl_offsets = QLabel("Drag cores up/down to align")
        self.lbl_offsets.setWordWrap(True)
        gl.addWidget(self.lbl_offsets)
        self.btn_reset = QPushButton("Reset All Offsets")
        self.btn_reset.clicked.connect(self._reset_offsets)
        gl.addWidget(self.btn_reset)
        lv.addWidget(grp)

        lv.addStretch()

        # ── Right panel (canvas) ──────────────────────────────────────
        self.scroll_area = ZoomableScrollArea()
        self.scroll_area.zoom_changed.connect(self._on_wheel_zoom)
        self.canvas = CorrelationCanvas()
        self.scroll_area.setWidget(self.canvas)
        self.scroll_area.setWidgetResizable(False)
        self.scroll_area.setStyleSheet("background-color: #f5f5f5;")

        main_layout.addWidget(left_scroll, 0)
        main_layout.addWidget(self.scroll_area, 1)

        self.status = QStatusBar()
        self.setStatusBar(self.status)

    # ── Cruise / core population ───────────────────────────────────────────

    def _populate_cruises(self):
        try:
            self._cruises = db_get_cruises_with_ct()
        except Exception as e:
            QMessageBox.critical(self, "Database Error",
                                 f"Could not connect to database:\n{e}")
            self._cruises = []

        self.combo_cruise.blockSignals(True)
        self.combo_cruise.clear()
        for cid, cname in self._cruises:
            self.combo_cruise.addItem(cname, userData=cid)
        self.combo_cruise.blockSignals(False)

        if self._cruises:
            self.combo_cruise.setCurrentIndex(0)
            self._on_cruise_changed()
        self.lbl_db.setText(
            f"Connected to PostgreSQL\n"
            f"{len(self._cruises)} cruises with CT data")
        self.status.showMessage("Database loaded", 3000)

    def _on_cruise_changed(self):
        idx = self.combo_cruise.currentIndex()
        if idx < 0 or idx >= len(self._cruises):
            return
        cruise_id = self._cruises[idx][0]

        label      = self.combo_type.currentText()
        image_type = SUPPORTED_IMAGE_TYPES.get(label)

        try:
            self._core_names = db_get_cores_for_cruise(
                cruise_id, image_type=image_type)
        except Exception as e:
            self.status.showMessage(f"Error loading cores: {e}", 5000)
            self._core_names = []

        self._populate_core_list()
        self._populate_suffix_combo()

    def _populate_core_list(self):
        self.list_cores.blockSignals(True)
        self.list_cores.clear()
        for cname in self._core_names:
            li = QListWidgetItem(cname)
            li.setFlags(li.flags() | Qt.ItemIsUserCheckable)
            li.setCheckState(Qt.Unchecked)
            li.setData(Qt.UserRole, cname)
            self.list_cores.addItem(li)
        self.list_cores.blockSignals(False)

        # MSCL dropdown
        self.combo_mscl_core.clear()
        for cname in self._core_names:
            self.combo_mscl_core.addItem(cname)

        # Clear section widgets & stale caches
        self._clear_section_widgets()
        self.core_sections = {}
        self.image_cache.clear()
        self.canvas.clear()

    def _clear_section_widgets(self):
        """Remove all per-section widgets from the scroll area."""
        self._section_widgets = {}
        while self._sec_vlayout.count():
            child = self._sec_vlayout.takeAt(0)
            w = child.widget()
            if w:
                w.deleteLater()

    def _on_core_checked(self, item):
        """Rebuild section widgets when a core is checked/unchecked."""
        self._rebuild_section_panel()
        self._auto_load_mscl_for_checked()
        self.refresh_display()

    def _auto_load_mscl_for_checked(self):
        """Auto-load the first MSCL .out file for each checked core
        that doesn't already have MSCL data loaded."""
        for cname in self._checked_cores():
            if cname in self.mscl_store:
                continue
            try:
                files = db_get_mscl_files_for_core(cname)
            except Exception:
                continue
            out_files = [(fn, fp) for fn, fp, _r in files
                         if fn.lower().endswith(".out")]
            if not out_files:
                continue
            fn, fp = out_files[0]
            full = get_full_path(os.path.join(fp, fn))
            if os.path.exists(full):
                self._parse_and_store_mscl(cname, full, fn)

    def _rebuild_section_panel(self):
        """Rebuild the per-section dropdown panel for all checked cores."""
        self._clear_section_widgets()

        label      = self.combo_type.currentText()
        image_type = SUPPORTED_IMAGE_TYPES.get(label, "")
        if not image_type:
            return

        checked = self._checked_cores()
        if not checked:
            return

        for core_name in checked:
            try:
                sec_files = db_get_section_files(core_name, image_type)
            except Exception as e:
                self.status.showMessage(f"Error loading sections: {e}", 5000)
                continue
            if not sec_files:
                continue

            # Core header label
            hdr = QLabel(f"  {core_name}")
            hdr.setStyleSheet("font-weight: bold; color: #ccc; margin-top: 4px;")
            self._sec_vlayout.addWidget(hdr)

            self._section_widgets[core_name] = {}

            for sec_num in sorted(sec_files.keys()):
                files = sec_files[sec_num]
                row_w = QWidget()
                rl    = QHBoxLayout(row_w)
                rl.setContentsMargins(12, 0, 0, 0)
                rl.setSpacing(4)

                chk = QCheckBox(f"S{sec_num}")
                chk.setChecked(True)
                chk.stateChanged.connect(self.refresh_display)

                combo = QComboBox()
                combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                for f in files:
                    fn = f.get("tif_filename") or ""
                    if not fn and f.get("xml_path"):
                        fn = os.path.splitext(
                            os.path.basename(f["xml_path"]))[0] + ".tif"
                    stage = f.get("processing_stage") or ""
                    display = fn if not stage else f"{fn}  [{stage}]"
                    combo.addItem(display, userData=f)
                combo.currentIndexChanged.connect(
                    lambda _idx: self.refresh_display())

                rl.addWidget(chk)
                rl.addWidget(combo, 1)
                self._sec_vlayout.addWidget(row_w)

                self._section_widgets[core_name][sec_num] = {
                    "check": chk, "combo": combo, "files": files}

        self._sec_vlayout.addStretch()

    def _checked_cores(self):
        """Return list of core names that are currently checked."""
        checked = []
        for i in range(self.list_cores.count()):
            it = self.list_cores.item(i)
            if it.checkState() == Qt.Checked:
                checked.append(it.data(Qt.UserRole))
        return checked

    def _populate_suffix_combo(self):
        """Discover available filename suffixes across all cores in the current cruise."""
        label      = self.combo_type.currentText()
        image_type = SUPPORTED_IMAGE_TYPES.get(label, "")
        all_suffixes = set()
        for cname in self._core_names:
            try:
                for s in db_get_suffixes_for_core(cname, image_type):
                    all_suffixes.add(s)
            except Exception:
                pass

        self.combo_suffix.blockSignals(True)
        self.combo_suffix.clear()
        self.combo_suffix.addItem("(all variants)", userData=None)
        for s in sorted(all_suffixes):
            display = s if s else "(original / no suffix)"
            self.combo_suffix.addItem(display, userData=s)
        self.combo_suffix.blockSignals(False)

        # Default to _corrected if available
        for i in range(self.combo_suffix.count()):
            if self.combo_suffix.itemData(i) == "_corrected":
                self.combo_suffix.setCurrentIndex(i)
                return
        self.combo_suffix.setCurrentIndex(0)

    # ── Image type / suffix changes ────────────────────────────────────────

    def _on_type_changed(self):
        self.core_sections = {}
        self.image_cache.clear()
        self._on_cruise_changed()

    def _on_suffix_changed(self):
        self.image_cache.clear()
        self._rebuild_section_panel()
        self.refresh_display()

    # ── Zoom ───────────────────────────────────────────────────────────────

    def _set_zoom(self, factor):
        self.zoom_factor = max(0.3, min(factor, 5.0))
        self.lbl_zoom.setText(f"Zoom: {int(self.zoom_factor * 100)}%")
        self.refresh_display()

    def _on_wheel_zoom(self, delta):
        self._set_zoom(self.zoom_factor + (0.15 if delta > 0 else -0.15))

    def _on_mscl_width(self, val):
        self.lbl_mscl_w.setText(f"Plot width: {val}")
        self.refresh_display()

    # ── MSCL ───────────────────────────────────────────────────────────────

    def _on_mscl_core_changed(self):
        """Populate the MSCL file dropdown when the core selection changes."""
        self.combo_mscl_file.clear()
        core_name = self.combo_mscl_core.currentText()
        if not core_name:
            return
        try:
            files = db_get_mscl_files_for_core(core_name)
        except Exception as e:
            self.lbl_mscl.setText(f"DB error: {e}")
            return
        out_files = [(fn, fp, remarks) for fn, fp, remarks in files
                     if fn.lower().endswith(".out")]
        if not out_files:
            self.lbl_mscl.setText(f"No .out files in DB for {core_name}")
            return
        for fn, fp, remarks in out_files:
            label = fn if not remarks else f"{fn}  ({remarks})"
            self.combo_mscl_file.addItem(label, userData=(fn, fp))
        self.lbl_mscl.setText("")

    def _load_mscl_from_db(self):
        """Load MSCL .out file for the selected core via database path."""
        core_name = self.combo_mscl_core.currentText()
        if not core_name:
            return
        file_data = self.combo_mscl_file.currentData()
        if not file_data:
            self.lbl_mscl.setText(f"No MSCL file selected for {core_name}")
            return
        fn, fp = file_data
        full = get_full_path(os.path.join(fp, fn))
        if os.path.exists(full):
            self._parse_and_store_mscl(core_name, full, fn)
        else:
            self.lbl_mscl.setText(f"File not found on disk:\n{full}")

    def _parse_and_store_mscl(self, core_name, filepath, display_name):
        data, columns = parse_mscl_file(filepath)
        if data is None:
            self.lbl_mscl.setText(f"Failed to parse {display_name}")
            return
        self.mscl_store[core_name] = {
            "data": data, "columns": columns, "file": display_name}
        loaded = [f"{cid}: {s['file']}"
                  for cid, s in self.mscl_store.items()]
        self.lbl_mscl.setText("\n".join(loaded))
        self._rebuild_mscl_cols()
        self.refresh_display()

    def _rebuild_mscl_cols(self):
        all_cols, seen = [], set()
        for store in self.mscl_store.values():
            for c in store["columns"]:
                if c not in seen:
                    all_cols.append(c)
                    seen.add(c)
        self.all_mscl_columns = all_cols

        old = {}
        for col, row_widgets in self.mscl_col_rows.items():
            old[col] = {
                "chk": row_widgets["check"].isChecked(),
                "mn":  row_widgets["min_edit"].text(),
                "mx":  row_widgets["max_edit"].text()}
        self.mscl_col_rows = {}
        while self._mscl_vlayout.count():
            child = self._mscl_vlayout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        for col in all_cols:
            rw = QWidget()
            rl = QHBoxLayout(rw)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.setSpacing(4)
            chk = QCheckBox(col)
            chk.setChecked(old[col]["chk"] if col in old else col == "Den1")
            chk.stateChanged.connect(self.refresh_display)
            mn = QLineEdit()
            mn.setPlaceholderText("auto")
            mn.setFixedWidth(52)
            if col in old and old[col]["mn"]:
                mn.setText(old[col]["mn"])
            mn.editingFinished.connect(self.refresh_display)
            mx = QLineEdit()
            mx.setPlaceholderText("auto")
            mx.setFixedWidth(52)
            if col in old and old[col]["mx"]:
                mx.setText(old[col]["mx"])
            mx.editingFinished.connect(self.refresh_display)
            rl.addWidget(chk)
            rl.addStretch()
            rl.addWidget(QLabel("min"))
            rl.addWidget(mn)
            rl.addWidget(QLabel("max"))
            rl.addWidget(mx)
            self._mscl_vlayout.addWidget(rw)
            self.mscl_col_rows[col] = {
                "check": chk, "min_edit": mn, "max_edit": mx}
        self._mscl_vlayout.addStretch()

    def _selected_mscl_cols(self):
        return [c for c, r in self.mscl_col_rows.items()
                if r["check"].isChecked()]

    def _displayed_section_nums(self, core_name):
        """Return set of section numbers currently checked for a core."""
        sw = self._section_widgets.get(core_name, {})
        return {sn for sn, w in sw.items() if w["check"].isChecked()}

    def _global_mscl_ranges(self, cols, core_ids):
        ranges = {}
        for col in cols:
            all_vals = []
            for cid in core_ids:
                store = self.mscl_store.get(cid)
                if not store:
                    continue
                displayed = self._displayed_section_nums(cid)
                for sec_num, sec_data in store["data"].items():
                    if sec_num not in displayed:
                        continue
                    if col in sec_data:
                        v = sec_data[col]
                        all_vals.append(v[~np.isnan(v)])
            if not all_vals:
                continue
            combined = np.concatenate(all_vals)
            if len(combined) < 2:
                continue
            v_lo, v_hi = np.percentile(combined, (2, 98))
            if v_hi <= v_lo:
                v_lo, v_hi = combined.min(), combined.max()
            if v_hi <= v_lo:
                continue
            row_widgets = self.mscl_col_rows.get(col, {})
            if row_widgets.get("min_edit"):
                try:
                    v_lo = float(row_widgets["min_edit"].text().strip())
                except ValueError:
                    pass
            if row_widgets.get("max_edit"):
                try:
                    v_hi = float(row_widgets["max_edit"].text().strip())
                except ValueError:
                    pass
            ranges[col] = (v_lo, v_hi)
        return ranges

    # ── Section loading from widget selections ──────────────────────────

    def _get_sections_for_core(self, core_name: str,
                                image_type: str) -> list[dict]:
        """Build section list from the per-section widget selections.
        Only includes sections whose checkbox is checked, using the
        file chosen in each section's dropdown."""
        sec_widgets = self._section_widgets.get(core_name, {})
        if not sec_widgets:
            return []

        sections = []
        for sec_num in sorted(sec_widgets.keys()):
            sw = sec_widgets[sec_num]
            if not sw["check"].isChecked():
                continue
            row = sw["combo"].currentData()
            if row is None:
                continue
            tif_path = db_resolve_tif_path(row)
            if tif_path is None:
                self.status.showMessage(
                    f"⚠️ TIF not found for {core_name} "
                    f"section {sec_num}", 3000)
                continue
            px_per_cm = db_get_px_per_cm_from_xml(
                row.get("xml_path", ""))
            sections.append({
                "tif":            tif_path,
                "section_number": sec_num,
                "px_per_cm":      px_per_cm,
                "core_id":        core_name,
            })
        return sections

    # ── Display Refresh ────────────────────────────────────────────────────

    def refresh_display(self):
        old_offsets = {s.core_id: s.offset_px for s in self.canvas.strips}
        self.canvas.clear()

        label      = self.combo_type.currentText()
        image_type = SUPPORTED_IMAGE_TYPES.get(label, "")
        if not image_type:
            return

        checked = self._checked_cores()
        if not checked:
            return

        px_per_cm  = UI_PX_PER_CM * self.zoom_factor
        show_mscl  = self.chk_mscl.isChecked()
        show_scale = self.chk_scale.isChecked()
        show_sec   = self.chk_sec_lines.isChecked()
        mscl_w_per_col = int(self.slider_mscl_w.value()) if show_mscl else 0
        sel_cols   = self._selected_mscl_cols()
        ranges     = {}
        if show_mscl and sel_cols:
            ranges = self._global_mscl_ranges(sel_cols, checked)

        for cid in checked:
            sections = self._get_sections_for_core(cid, image_type)
            if not sections:
                self.status.showMessage(
                    f"No {label} TIFs found for {cid}", 3000)
                continue

            pix, total_cm, logical_h, header_h, data_h = \
                self._render_strip(
                    cid, sections, px_per_cm, show_scale, show_sec)
            strip = DraggableCoreStrip(cid, px_per_cm, self.canvas)
            strip.set_pixmap(pix)

            # Attach per-column pyqtgraph MSCL plots
            if show_mscl and sel_cols and ranges:
                plots = self._create_mscl_plots(
                    cid, total_cm, sel_cols, ranges,
                    mscl_w_per_col, sections)
                if plots:
                    strip.set_mscl_plots(plots, data_h, header_h)

            strip.offset_changed.connect(self._update_offsets)
            if cid in old_offsets:
                strip.offset_px = old_offsets[cid]
            self.canvas.add_strip(strip)

        self._update_offsets()

    def _render_strip(self, core_id, sections, px_per_cm,
                      show_scale, show_sec):
        """Render CT image strip with scale bar. MSCL is handled separately
        via pyqtgraph widgets."""
        S = RENDER_SCALE
        px_per_cm_r = px_per_cm * S

        # Pre-process sections
        processed  = []
        cumul      = 0.0
        max_img_w  = 0
        for sec in sections:
            meta_ppcm = sec["px_per_cm"]
            pil_img, _, crop_top_px, orig_h = self.image_cache.get(
                sec["tif"], meta_ppcm)
            phys_cm = orig_h / meta_ppcm
            scale   = px_per_cm_r / meta_ppcm
            iw      = int(pil_img.size[0] * scale)
            ih      = int(pil_img.size[1] * scale)
            cy      = int(crop_top_px * scale)
            processed.append({
                "pil":     pil_img,
                "sec":     sec["section_number"],
                "phys_cm": phys_cm,
                "cum_cm":  cumul,
                "iw": iw, "ih": ih, "cy": cy,
                "ppcm":    meta_ppcm,
            })
            max_img_w  = max(max_img_w, iw)
            cumul     += phys_cm

        total_cm = cumul
        total_h  = int(total_cm * px_per_cm_r)

        HEADER_H = max(30 * S, int(36 * self.zoom_factor * S))
        SCALE_W  = int(50 * self.zoom_factor * S) if show_scale else 0
        ct_w     = max_img_w
        strip_w  = SCALE_W + ct_w
        strip_h  = HEADER_H + total_h + 20 * S

        img  = Image.new("RGB", (strip_w, strip_h), STRIP_BG)
        draw = ImageDraw.Draw(img)
        y0   = HEADER_H

        # Header
        draw.rectangle([(0, 0), (strip_w - 1, HEADER_H - 1)], fill=HEADER_BG)
        hf = _pil_font(int(18 * self.zoom_factor * S))
        bb = draw.textbbox((0, 0), core_id, font=hf)
        draw.text(((strip_w - (bb[2] - bb[0])) // 2, 4 * S),
                  core_id, fill=LABEL_COLOR, font=hf)

        # Scale bar
        if show_scale:
            sf = _pil_font(int(14 * self.zoom_factor * S))
            bx = SCALE_W - 2
            draw.line([(bx, y0), (bx, y0 + total_h)],
                      fill=SCALE_FG, width=S)
            tick = 0
            while tick <= int(total_cm) + 1:
                ty = y0 + int(tick * px_per_cm_r)
                if ty > y0 + total_h:
                    break
                if tick % 10 == 0:
                    draw.line([(bx - 6 * S, ty), (bx, ty)],
                              fill=SCALE_FG, width=S)
                    draw.text((2 * S, ty - 8 * S), f"{tick}",
                              fill=SCALE_FG, font=sf)
                elif tick % 5 == 0:
                    draw.line([(bx - 4 * S, ty), (bx, ty)],
                              fill=(140, 140, 140), width=S)
                else:
                    draw.line([(bx - 2 * S, ty), (bx, ty)],
                              fill=(180, 180, 180), width=S)
                tick += 1

        # CT sections
        ctx = SCALE_W
        for sec in processed:
            sy      = y0 + int(sec["cum_cm"] * px_per_cm_r)
            resized = sec["pil"].resize(
                (sec["iw"], sec["ih"]),
                Image.Resampling.LANCZOS).convert("RGB")
            xoff = ctx + (ct_w - sec["iw"]) // 2
            img.paste(resized, (xoff, sy + sec["cy"]))
            if show_sec:
                bot = sy + int(sec["phys_cm"] * px_per_cm_r)
                draw.line([(ctx, bot), (ctx + ct_w, bot)],
                          fill=SECTION_LINE, width=S)
                fs = _pil_font(max(8 * S, int(10 * self.zoom_factor * S)))
                draw.text((ctx + 3 * S, sy + 2 * S),
                          f"S{sec['sec']}", fill=(100, 100, 140), font=fs)

        # Down-sample to logical size for the QPixmap
        logical_w = strip_w // S
        logical_h = strip_h // S
        img = img.resize((logical_w, logical_h), Image.Resampling.LANCZOS)
        qimg = QImage(img.tobytes(), logical_w, logical_h,
                      logical_w * 3, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(qimg.copy())
        header_h_logical = HEADER_H // S
        data_h_logical   = total_h // S
        return pixmap, total_cm, logical_h, header_h_logical, data_h_logical

    # ── MSCL pyqtgraph rendering ──────────────────────────────────────────

    def _create_mscl_plots(self, core_id, total_cm, sel_cols, mscl_ranges,
                            col_width, sections):
        """Return a list of per-column PlotWidgets for one core.

        Each PlotWidget has its own x-range so columns don't rescale
        each other. Returns [] if no data.
        """
        store = self.mscl_store.get(core_id)
        if not store or not sel_cols:
            return []

        sec_widgets = self._section_widgets.get(core_id, {})
        displayed_secs = {sn for sn, w in sec_widgets.items()
                          if w["check"].isChecked()}

        # Compute cumulative depth offsets from the actually-displayed
        # section images (same order as _render_strip stacks them).
        cumul = 0.0
        sec_offsets = {}
        for sec in sections:
            sn = sec["section_number"]
            meta_ppcm = sec["px_per_cm"]
            _, _, _, orig_h = self.image_cache.get(sec["tif"], meta_ppcm)
            phys_cm = orig_h / meta_ppcm
            sec_offsets[sn] = cumul
            cumul += phys_cm

        plots = []
        for ci, cn in enumerate(sel_cols):
            v_lo, v_hi = mscl_ranges.get(cn, (0, 1))
            if v_lo == v_hi:
                v_hi = v_lo + 1

            pw = pg.PlotWidget()
            pw.setFixedWidth(col_width)
            pw.setBackground("w")
            pw.showGrid(x=True, y=True, alpha=0.3)

            # Remove all internal margins so Y-axis maps pixel-perfectly
            # to the widget height — this keeps MSCL aligned with CT.
            pw.getPlotItem().setContentsMargins(0, 0, 0, 0)
            pw.getPlotItem().getViewBox().setDefaultPadding(0)
            pw.getAxis("left").setWidth(0)
            pw.getAxis("left").setStyle(showValues=False, tickLength=0)
            pw.getAxis("right").setWidth(0)
            pw.getAxis("top").setHeight(0)
            pw.getAxis("bottom").setHeight(18)
            pw.getAxis("bottom").setStyle(tickLength=-5)
            pw.setLabel("bottom", cn, **{"font-size": "8pt"})
            pw.setLabel("left", "")
            pw.setYRange(0, total_cm, padding=0)
            pw.setXRange(v_lo, v_hi, padding=0)
            pw.invertY(True)
            pw.setMouseEnabled(x=False, y=False)
            pw.hideButtons()
            pw.getViewBox().setMenuEnabled(False)
            pw.enableAutoRange(axis="x", enable=False)
            pw.enableAutoRange(axis="y", enable=False)

            color = MSCL_COLORS[ci % len(MSCL_COLORS)]
            has_data = False
            for sec_num in sorted(displayed_secs):
                sd = store["data"].get(sec_num)
                if not sd or "SECT DEPTH" not in sd or cn not in sd:
                    continue
                depths = sd["SECT DEPTH"]
                vals   = sd[cn]
                mask   = ~np.isnan(vals)
                if mask.sum() < 2:
                    continue
                offset = sec_offsets.get(sec_num, 0.0)
                abs_depth = offset + depths[mask]
                vv = vals[mask]
                pw.plot(vv, abs_depth, pen=pg.mkPen(color, width=2))
                has_data = True

            if has_data:
                plots.append(pw)
            else:
                pw.deleteLater()

        return plots

    # ── Offset management ──────────────────────────────────────────────────

    def _update_offsets(self):
        lines = []
        for s in self.canvas.strips:
            lines.append(f"{s.core_id}: {s.offset_cm:+.1f} cm")
        self.lbl_offsets.setText(
            "\n".join(lines) if lines else "Drag cores up/down to align")
        self.canvas._reposition()

    def _reset_offsets(self):
        self.canvas.reset_offsets()
        self._update_offsets()


# ── Entry Point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = CoreCorrelatorApp()
    window.show()
    sys.exit(app.exec())
