"""The KPI table: key figures read with Claude, checked, queried through SQLite, and sent with the search results."""

from bankrag.kpi.extract import KPI_YEARS, METRICS, extract_figure, extract_table, failed_checks
from bankrag.kpi.lookup import figure_key, key_figures_for, with_key_figures
from bankrag.kpi.store import build_db, compare_banks, get_kpi, load_figures, save_figures

__all__ = [
    "KPI_YEARS",
    "METRICS",
    "build_db",
    "compare_banks",
    "extract_figure",
    "extract_table",
    "failed_checks",
    "figure_key",
    "get_kpi",
    "key_figures_for",
    "load_figures",
    "save_figures",
    "with_key_figures",
]
