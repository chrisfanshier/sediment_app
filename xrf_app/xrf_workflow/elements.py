"""Periodic-table helpers for detecting element columns in Results.txt."""

from __future__ import annotations

# Symbols through U (including Xx placeholder used by some Itrax exports).
PERIODIC_SYMBOLS = frozenset(
    {
        "H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne",
        "Na", "Mg", "Al", "Si", "P", "S", "Cl", "Ar", "K", "Ca",
        "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn",
        "Ga", "Ge", "As", "Se", "Br", "Kr", "Rb", "Sr", "Y", "Zr",
        "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd", "In", "Sn",
        "Sb", "Te", "I", "Xe", "Cs", "Ba", "La", "Ce", "Pr", "Nd",
        "Pm", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb",
        "Lu", "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg",
        "Tl", "Pb", "Bi", "Po", "At", "Rn", "Fr", "Ra", "Ac", "Th",
        "Pa", "U", "Xx",
    }
)

# Scatter / instrument columns often useful alongside elements (itraxR "others").
OTHER_USEFUL = frozenset(
    {
        "Mo inc", "Mo coh", "Cr inc", "Cr coh",
        "Fe a*2", "Fe a+b", "S1", "S2", "S3",
    }
)


def is_element_column(name: str) -> bool:
    return name in PERIODIC_SYMBOLS


def element_columns(columns) -> list[str]:
    return [c for c in columns if is_element_column(c)]
