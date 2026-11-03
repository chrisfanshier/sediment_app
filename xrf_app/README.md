# Itrax XRF workflow — step 1 (Streamlit)

Minimal interactive Python GUI that walks through the **Itrax / itraxR teaching workflow** for one CD166-style core section, as outlined in [the itraxR package chapter](https://tombishop1.github.io/itraxBook/the-itraxr-package.html) and [itraxBook](https://tombishop1.github.io/itraxBook/).

This lives under `sediment_app/xrf_app/` so it fits the existing Streamlit-oriented repo. It is a **clean-room Python reimplementation** of documented behaviour for the example path — not a vendored copy of the R sources.

## Citation & license note

- Workflow and example data inspired by **[itraxR](https://github.com/tombishop1/itraxR)** (GPL-3) and **[itraxBook](https://github.com/tombishop1/itraxBook)** (Tom Bishop et al.).
- Bundled example files are downloaded from itraxR `inst/extdata` (CD166_19_S1 teaching subset).
- Do **not** copy GPL R code into a differently licensed tree without checking license compatibility. This package reimplements parsers/QC/plots from documented file formats and book recipes.

## Install

From the repo root (or this folder):

```bash
cd xrf_app
python3 -m pip install -r requirements.txt
```

Example data is already staged under `data/example/CD166_19_S1/`. To re-fetch or pull the fuller itraxBook S1 tree:

```bash
python3 scripts/fetch_example_data.py
python3 scripts/fetch_example_data.py --book          # fuller S1 + RAD (no spectra zip)
python3 scripts/fetch_example_data.py --book --with-spectra-zip   # large
```

## Run

```bash
cd xrf_app
python3 -m streamlit run app.py
```

Then open the local URL Streamlit prints (typically http://localhost:8501).

### Smoke test (no GUI)

```bash
cd xrf_app
python3 tests/test_workflow.py
```

## What step 1 covers

| Book / itraxR step | Status |
|---|---|
| Point at section folder (`document.txt`, `Results.txt`, images, optional `*.spe`) | Done |
| `itrax_meta`-style metadata import | Done (tolerant CD166 layout) |
| `itrax_import`-style XRF + `depth_top` | Done (`all` / `some` columns) |
| QC flags: validity, cps, MSE, surface slope, Ar | Done (editable thresholds) |
| Ratios / log-ratios / Mo-inc normalisation | Done |
| Stratigraphic plot of selected elements | Done |
| Optical / radiograph overlay | Done (approximate alignment) |
| CLR correlation + CLR-PCA sketch | Done (optional tab) |
| Multi-section `itrax_join` at scale | Deferred |
| Raw spectra heatmaps / `itrax_restspectra` | Deferred (one sample spe only) |
| CloudCal / peak fitting / Q-Spec parity | Out of scope |
| Constrained clustering, calib sample picker, `itrax_reduce` | Deferred |
| Bit-parity via rpy2 | Out of scope |

## Example data layout

Bundled path (flattened from itraxR extdata):

```
data/example/CD166_19_S1/
  document.txt
  Results.txt
  optical.tif
  radiograph.tif
  rad_document.txt
  Results_settings.dfl
  L000676.spe
```

The GUI also accepts a real lab folder shaped like itraxBook `CD166_19_(2020)/CD166_19_S1/CD166_19_S1/`.

## Package layout

```
xrf_app/
  app.py                 # Streamlit UI
  requirements.txt
  scripts/fetch_example_data.py
  data/example/…
  xrf_workflow/          # import, QC, transforms, plots, CLR-PCA
  tests/test_workflow.py
```
