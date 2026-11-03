"""Streamlit step-1 GUI for the Itrax XRF teaching workflow.

Run from the xrf_app directory:
    streamlit run app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from xrf_workflow import (  # noqa: E402
    apply_qc_flags,
    clr_pca,
    correlation_matrix,
    default_qc_params,
    discover_section,
    import_meta,
    import_xrf,
    load_image,
    load_spectrum,
)
from xrf_workflow.elements import element_columns  # noqa: E402
from xrf_workflow.plotting import qc_overview_figure, stratigraphic_figure  # noqa: E402
from xrf_workflow.qc import qc_summary  # noqa: E402
from xrf_workflow.transforms import add_log_ratio, add_mo_inc_norm, add_ratio  # noqa: E402

EXAMPLE_DIR = ROOT / "data" / "example" / "CD166_19_S1"

st.set_page_config(
    page_title="Itrax XRF — step 1",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("Itrax XRF workflow (step 1)")
st.caption(
    "Minimal Python GUI mirroring the itraxBook / itraxR teaching path for one "
    "CD166-style section. Clean-room reimplementation — cites itraxR (GPL-3) / itraxBook."
)


def _load_section(folder: Path, depth_top: float, parameters: str):
    paths = discover_section(folder)
    meta = import_meta(paths.document) if paths.document else pd.DataFrame()
    if paths.results is None:
        raise FileNotFoundError("No Results.txt / result.txt found in folder")
    xrf = import_xrf(paths.results, depth_top=depth_top, parameters=parameters)
    optical = load_image(paths.optical) if paths.optical else None
    radiograph = load_image(paths.radiograph) if paths.radiograph else None
    spectrum = None
    if paths.spectra:
        spectrum = load_spectrum(paths.spectra[0], dfl=paths.dfl)
    return paths, meta, xrf, optical, radiograph, spectrum


# --- Sidebar: data source ---
with st.sidebar:
    st.header("1. Section folder")
    use_example = st.checkbox("Use bundled CD166_19_S1 example", value=True)
    if use_example:
        section_path = EXAMPLE_DIR
        st.code(str(section_path), language=None)
        if not section_path.exists():
            st.error("Example data missing. Run: python scripts/fetch_example_data.py")
    else:
        typed = st.text_input("Path to section folder", value=str(EXAMPLE_DIR))
        section_path = Path(typed).expanduser()

    depth_top = st.number_input(
        "depth_top (mm) — coring depth at top of section",
        value=0.0,
        step=1.0,
        help="Not in document.txt; lab-book offset used by itrax_import.",
    )
    parameters = st.selectbox("Import columns", options=["all", "some"], index=0)

    st.header("2. QC thresholds")
    qp = default_qc_params()
    qp["require_validity"] = st.checkbox("Require validity==True", value=True)
    cps_mode = st.selectbox("cps mode", ["band", "sd", "off"], index=0)
    qp["cps_mode"] = cps_mode
    if cps_mode == "band":
        c1, c2 = st.columns(2)
        qp["cps_min"] = c1.number_input("cps min", value=float(qp["cps_min"]), step=1000.0)
        qp["cps_max"] = c2.number_input("cps max", value=float(qp["cps_max"]), step=1000.0)
    elif cps_mode == "sd":
        qp["cps_sd"] = st.number_input("cps ± n·sd", value=float(qp["cps_sd"]), step=0.5)

    qp["use_mse"] = st.checkbox("MSE threshold", value=True)
    if qp["use_mse"]:
        qp["mse_max"] = st.number_input("MSE max", value=float(qp["mse_max"]), step=0.1)

    qp["use_slope"] = st.checkbox("Surface slope check", value=True)
    if qp["use_slope"]:
        qp["slope_max_abs"] = st.number_input(
            "|Δ sample surface| max (mm/step)",
            value=float(qp["slope_max_abs"]),
            step=0.05,
            format="%.2f",
        )

    ar_on = st.checkbox("Ar (air path) check", value=True)
    qp["ar_mode"] = "mean_plus_sd" if ar_on else "off"
    if ar_on:
        qp["ar_sd"] = st.number_input("Ar mean + n·sd", value=float(qp["ar_sd"]), step=0.5)

    load_btn = st.button("Load / refresh", type="primary")


@st.cache_data(show_spinner="Loading section…")
def cached_load(folder: str, depth_top: float, parameters: str):
    paths, meta, xrf, optical, radiograph, spectrum = _load_section(
        Path(folder), depth_top, parameters
    )
    # Cache-friendly: return arrays + path strings
    return {
        "paths": {k: (str(v) if v is not None and not isinstance(v, list) else v) for k, v in paths.__dict__.items()},
        "meta": meta,
        "xrf": xrf,
        "optical": optical,
        "radiograph": radiograph,
        "spectrum": spectrum,
        "spectra_list": [str(p) for p in paths.spectra],
    }


if load_btn or "xrf_bundle" not in st.session_state:
    try:
        if not Path(section_path).exists():
            st.error(f"Folder not found: {section_path}")
            st.stop()
        bundle = cached_load(str(Path(section_path).resolve()), float(depth_top), parameters)
        st.session_state["xrf_bundle"] = bundle
        st.session_state["qc_params"] = qp
    except Exception as exc:  # noqa: BLE001 — show in UI
        st.exception(exc)
        st.stop()
else:
    st.session_state["qc_params"] = qp

bundle = st.session_state["xrf_bundle"]
xrf_raw = bundle["xrf"]
meta = bundle["meta"]
optical = bundle["optical"]
radiograph = bundle["radiograph"]
spectrum = bundle["spectrum"]

xrf = apply_qc_flags(xrf_raw, st.session_state["qc_params"])

# --- Main tabs ---
tab_import, tab_qc, tab_xform, tab_plot, tab_mv = st.tabs(
    ["Import", "QC", "Transforms", "Strat plot", "CLR-PCA / corr"]
)

with tab_import:
    st.subheader("Discovered files")
    paths_info = bundle["paths"]
    st.json(
        {
            "root": paths_info.get("root"),
            "results": paths_info.get("results"),
            "document": paths_info.get("document"),
            "optical": paths_info.get("optical"),
            "radiograph": paths_info.get("radiograph"),
            "dfl": paths_info.get("dfl"),
            "spectra": bundle.get("spectra_list", [])[:5],
            "spectra_zip": paths_info.get("spectra_zip"),
        }
    )
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Metadata (document.txt)")
        if meta is not None and not meta.empty:
            st.dataframe(meta, use_container_width=True, height=360)
        else:
            st.info("No document.txt found")
    with c2:
        st.subheader("XRF table preview")
        st.write(f"{len(xrf)} rows × {xrf.shape[1]} columns")
        st.dataframe(xrf.head(50), use_container_width=True, height=360)

    if spectrum is not None:
        st.subheader("Sample spectrum (first *.spe)")
        fig, ax = plt.subplots(figsize=(8, 3))
        xcol = "energy" if "energy" in spectrum.columns else "channel"
        ax.plot(spectrum[xcol], spectrum["count"], color="#33415c", lw=0.8)
        ax.set_xlabel(xcol)
        ax.set_ylabel("counts")
        ax.set_title("MCA spectrum sketch")
        st.pyplot(fig)
        plt.close(fig)

with tab_qc:
    st.subheader("QC pass rates")
    summary = qc_summary(xrf)
    st.dataframe(summary, use_container_width=True)
    st.write(
        f"Rows passing combined `qc`: **{int(xrf['qc'].sum())}** / {len(xrf)} "
        f"({100.0 * float(xrf['qc'].mean()):.1f}%)"
    )
    fig = qc_overview_figure(xrf)
    st.pyplot(fig)
    plt.close(fig)
    with st.expander("Flagged rows (qc == False)"):
        cols = [c for c in ["position", "depth", "validity", "cps", "MSE", "Ar", "sample surface", "qc"] if c in xrf.columns]
        st.dataframe(xrf.loc[~xrf["qc"], cols], use_container_width=True)

with tab_xform:
    st.subheader("Ratios & Mo-inc normalisation")
    elems = element_columns(xrf.columns)
    defaults = [e for e in ["Fe", "Ca", "Ti", "Sr", "Br", "Si"] if e in elems]
    c1, c2, c3 = st.columns(3)
    num = c1.selectbox("Numerator", options=elems, index=elems.index(defaults[0]) if defaults else 0)
    den_opts = elems + ([c for c in ["Mo inc", "Mo coh"] if c in xrf.columns])
    den = c2.selectbox(
        "Denominator",
        options=den_opts,
        index=den_opts.index(defaults[1]) if len(defaults) > 1 and defaults[1] in den_opts else 0,
    )
    mode = c3.selectbox("Transform", ["ratio", "log-ratio", "Mo-inc normalize selected"])

    work = xrf.loc[xrf["qc"]].copy() if st.checkbox("Apply to QC-pass rows only", value=True) else xrf.copy()

    if mode == "ratio":
        work = add_ratio(work, num, den)
        new_col = f"{num}/{den}"
    elif mode == "log-ratio":
        work = add_log_ratio(work, num, den)
        new_col = f"ln({num}/{den})"
    else:
        pick = st.multiselect("Elements to normalise by Mo inc", options=elems, default=defaults[:4] or elems[:4])
        scatter = "Mo inc" if "Mo inc" in work.columns else ("Cr inc" if "Cr inc" in work.columns else None)
        if scatter is None:
            st.error("No Mo inc / Cr inc column present")
            new_col = None
        else:
            work = add_mo_inc_norm(work, pick, scatter=scatter)
            new_col = f"{pick[0]}_/{scatter}" if pick else None

    if new_col and new_col in work.columns:
        fig, ax = plt.subplots(figsize=(4, 6))
        depth_col = "depth" if "depth" in work.columns and work["depth"].notna().any() else "position"
        ax.plot(work[new_col], work[depth_col], color="#1f4e79", lw=1.0)
        ax.invert_yaxis()
        ax.set_xlabel(new_col)
        ax.set_ylabel(depth_col + " (mm)")
        ax.grid(True, alpha=0.25)
        st.pyplot(fig)
        plt.close(fig)
        st.dataframe(work[[depth_col, new_col]].head(30), use_container_width=True)

with tab_plot:
    st.subheader("Stratigraphic plot")
    elems = element_columns(xrf.columns)
    default_plot = [e for e in ["Ca", "Fe", "Ti", "Sr", "Br", "Si", "K"] if e in elems]
    selected = st.multiselect("Elements / series", options=elems, default=default_plot or elems[:5])
    show_opt = st.checkbox("Overlay optical", value=optical is not None, disabled=optical is None)
    show_rad = st.checkbox("Overlay radiograph", value=False, disabled=radiograph is None)
    only_qc = st.checkbox("Plot QC-pass rows only (grey = fail when unchecked)", value=False)

    plot_df = xrf.loc[xrf["qc"]].copy() if only_qc else xrf
    if selected:
        fig = stratigraphic_figure(
            plot_df if only_qc else xrf,
            selected,
            optical=optical if show_opt else None,
            radiograph=radiograph if show_rad else None,
            qc_col=None if only_qc else "qc",
            title="CD166-style section — peak areas vs depth",
        )
        st.pyplot(fig)
        plt.close(fig)
    else:
        st.info("Select at least one element")

with tab_mv:
    st.subheader("CLR-PCA & correlation (optional stretch)")
    elems = element_columns(xrf.columns)
    # Prefer common major/minor set; drop Ar (air) by default for CoDa
    default_mv = [e for e in ["Al", "Si", "K", "Ca", "Ti", "Mn", "Fe", "Br", "Rb", "Sr", "Zr"] if e in elems]
    mv_elems = st.multiselect("Elements for multivariate", options=elems, default=default_mv or elems[:10])
    zero_policy = st.selectbox("Zero policy", ["addone", "limit"], index=0)
    use_qc = st.checkbox("QC-pass rows only", value=True, key="mv_qc")
    mv_df = xrf.loc[xrf["qc"]].copy() if use_qc else xrf.copy()

    if len(mv_elems) >= 2:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Pearson correlation (CLR)**")
            corr = correlation_matrix(mv_df, mv_elems, use_clr=True, zero_policy=zero_policy)
            fig, ax = plt.subplots(figsize=(5, 4))
            im = ax.imshow(corr.to_numpy(), cmap="coolwarm", vmin=-1, vmax=1, aspect="auto")
            ax.set_xticks(range(len(corr.columns)))
            ax.set_yticks(range(len(corr.index)))
            ax.set_xticklabels(corr.columns, rotation=90, fontsize=7)
            ax.set_yticklabels(corr.index, fontsize=7)
            fig.colorbar(im, ax=ax, fraction=0.046)
            st.pyplot(fig)
            plt.close(fig)
        with c2:
            st.markdown("**CLR-PCA scores vs depth**")
            try:
                pca = clr_pca(mv_df, mv_elems, n_components=3, zero_policy=zero_policy)
                st.write(
                    "Variance explained: "
                    + ", ".join(f"PC{i+1}={v*100:.1f}%" for i, v in enumerate(pca.explained_variance_ratio))
                )
                depth_col = "depth" if "depth" in pca.scores.columns else "position"
                fig, axes = plt.subplots(1, min(3, pca.scores.shape[1] - 1), figsize=(6, 5), sharey=True)
                if min(3, pca.scores.shape[1] - 1) == 1:
                    axes = [axes]
                pcs = [c for c in pca.scores.columns if c.startswith("PC")]
                for ax, pc in zip(axes, pcs):
                    ax.plot(pca.scores[pc], pca.scores[depth_col], color="#1f4e79", lw=1.0)
                    ax.set_xlabel(pc)
                    ax.invert_yaxis()
                    ax.grid(True, alpha=0.25)
                axes[0].set_ylabel(depth_col + " (mm)")
                st.pyplot(fig)
                plt.close(fig)
                with st.expander("Loadings"):
                    st.dataframe(pca.loadings, use_container_width=True)
            except Exception as exc:  # noqa: BLE001
                st.error(f"PCA failed: {exc}")
    else:
        st.info("Pick at least two elements")

st.divider()
st.markdown(
    "Sources: [itraxR](https://github.com/tombishop1/itraxR) (GPL-3) · "
    "[itraxBook](https://tombishop1.github.io/itraxBook/) · "
    "example data from itraxR `inst/extdata` (CD166_19_S1)."
)
