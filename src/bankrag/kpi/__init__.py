"""The KPI table: key figures per bank and year, extracted with Claude, checked, and queried through SQLite."""

from bankrag.kpi.extract import METRICS, extract_figure, extract_table, failed_checks
from bankrag.kpi.store import build_db, compare_banks, get_kpi, load_figures, save_figures

__all__ = [
    "METRICS",
    "build_db",
    "compare_banks",
    "extract_figure",
    "extract_table",
    "failed_checks",
    "get_kpi",
    "load_figures",
    "save_figures",
]
