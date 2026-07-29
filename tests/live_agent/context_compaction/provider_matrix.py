"""State machine and evidence policy for the Provider compaction live matrix."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


BASELINE_CELLS = ("cell_1_pixel_native", "cell_2_cockpit_native_failure")
MAIN_CELLS = ("cell_3_cockpit_rosetta_to_pixel", "cell_4_pixel_to_cockpit_rosetta")


def evaluate_matrix(cells: dict[str, dict[str, Any]]) -> str:
    """Classify a complete or baseline-stopped four-cell result."""

    if not all(cells.get(cell, {}).get("success") is True for cell in BASELINE_CELLS):
        return "blocked"
    return (
        "success"
        if all(cells.get(cell, {}).get("success") is True for cell in MAIN_CELLS)
        else "failure"
    )


def run_matrix(
    run_cell: Callable[[str], dict[str, Any]],
) -> tuple[str, dict[str, dict[str, Any]]]:
    """Run both baselines and, when eligible, both independent main cells."""

    def run_isolated(cell: str) -> dict[str, Any]:
        try:
            return run_cell(cell)
        except Exception as exc:
            return {
                "success": False,
                "classification": "runner_error",
                "error_type": type(exc).__name__,
            }

    cells = {cell: run_isolated(cell) for cell in BASELINE_CELLS}
    if evaluate_matrix(cells) == "blocked":
        return "blocked", cells
    for cell in MAIN_CELLS:
        cells[cell] = run_isolated(cell)
    return evaluate_matrix(cells), cells
