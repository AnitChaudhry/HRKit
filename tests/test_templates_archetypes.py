"""Tests for hrkit.templates archetype helpers (Phase 4b).

Covers render_stat_grid, render_kanban_board, render_heatmap,
render_donut_svg, render_bar_svg.
"""

from __future__ import annotations

import re

from hrkit import templates as t


# ---------------------------------------------------------------------------
# render_stat_grid
# ---------------------------------------------------------------------------
def test_stat_grid_empty_returns_empty_string():
    assert t.render_stat_grid([]) == ""
    assert t.render_stat_grid(None) == ""


def test_stat_grid_renders_links_and_icons():
    html = t.render_stat_grid([
        {"label": "Employees", "value": 42, "href": "/m/employee", "icon": "E"},
        {"label": "Pending", "value": 3, "delta": "-2", "delta_dir": "down"},
    ])
    assert 'class="stat-grid"' in html
    assert 'class="stat-tile"' in html
    assert 'href="/m/employee"' in html
    assert 'stat-tile-icon' in html
    assert "Employees" in html and "42" in html
    # delta_dir=down yields the 'neg' modifier
    assert 'stat-tile-delta neg' in html


def test_stat_grid_no_href_uses_div():
    html = t.render_stat_grid([{"label": "Total", "value": 7}])
    # Without href, the tile should not be an <a> element
    assert '<a class="stat-tile"' not in html
    assert '<div class="stat-tile">' in html


# ---------------------------------------------------------------------------
# render_kanban_board
# ---------------------------------------------------------------------------
def test_kanban_groups_items_by_column():
    items = [
        {"title": "Alice", "col": "applied"},
        {"title": "Bob", "col": "interview"},
        {"title": "Carol", "col": "applied"},
    ]
    html = t.render_kanban_board(
        columns=[("applied", "Applied"), ("interview", "Interview")],
        items=items,
        get_column=lambda i: i["col"],
        get_id=lambda i: i["title"],
    )
    assert html.count('class="kanban-col"') == 2  # no overflow column
    # exact card count via class attribute (avoids substring matches like
    # "kanban-card-title")
    assert len(re.findall(r'class="kanban-card"', html)) == 3
    assert "Alice" in html and "Bob" in html and "Carol" in html
    # column counters
    assert '<span class="col-count">2</span>' in html  # applied
    assert '<span class="col-count">1</span>' in html  # interview


def test_kanban_overflow_into_other_column():
    """Items pointing to an unknown column slug land in 'Other'."""
    html = t.render_kanban_board(
        columns=[("applied", "Applied")],
        items=[{"title": "Stray", "col": "unknown"}],
        get_column=lambda i: i["col"],
    )
    assert 'data-col="__other__"' in html
    assert "Stray" in html


def test_kanban_empty_column_shows_placeholder():
    html = t.render_kanban_board(
        columns=[("a", "A"), ("b", "B")],
        items=[{"title": "Only A", "col": "a"}],
        get_column=lambda i: i["col"],
    )
    assert 'kanban-empty' in html
    # Counter on the empty col is 0
    assert '<span class="col-count">0</span>' in html


def test_kanban_custom_render_card():
    def custom(it):
        return f'<div class="custom-card">{it["title"]} ({it["score"]})</div>'

    html = t.render_kanban_board(
        columns=[("applied", "Applied")],
        items=[{"title": "Alice", "score": 85, "col": "applied"}],
        get_column=lambda i: i["col"],
        render_card=custom,
    )
    assert 'class="custom-card"' in html
    assert "Alice (85)" in html


# ---------------------------------------------------------------------------
# render_heatmap
# ---------------------------------------------------------------------------
def test_heatmap_levels_match_intensity():
    """Cell levels should ramp from 0 to 5 as values approach max."""
    html = t.render_heatmap(
        row_labels=["A"],
        col_labels=["1", "2", "3", "4", "5"],
        values=[[0, 25, 50, 75, 100]],  # 0%, 25%, 50%, 75%, 100% of max=100
        legend_label="hours",
    )
    # No level for 0; lvl1..lvl5 for the rest
    assert 'class=""' in html  # the 0-value cell
    assert 'class="lvl2"' in html  # 25/100 = 0.25 -> lvl2
    assert 'class="lvl3"' in html  # 50/100 -> lvl3
    assert 'class="lvl4"' in html  # 75/100 -> lvl4
    assert 'class="lvl5"' in html  # 100/100 -> lvl5
    # Legend renders
    assert "Less" in html and "More" in html


def test_heatmap_handles_empty_grid():
    html = t.render_heatmap(
        row_labels=[], col_labels=[], values=[],
    )
    assert "heatmap-table" in html


def test_heatmap_max_value_clamps_ramp():
    """When max_value is supplied, values above it should still cap at lvl5."""
    html = t.render_heatmap(
        row_labels=["A"],
        col_labels=["1"],
        values=[[200]],
        max_value=100,  # value is 2x ceiling
    )
    assert 'class="lvl5"' in html


# ---------------------------------------------------------------------------
# render_donut_svg
# ---------------------------------------------------------------------------
def test_donut_no_data_shows_placeholder():
    html = t.render_donut_svg([], title="Empty")
    assert "chart-svg" in html
    assert "No data yet" in html


def test_donut_renders_arc_paths_per_slice():
    html = t.render_donut_svg(
        [{"label": "A", "value": 10}, {"label": "B", "value": 5}],
        title="Pipeline",
        center_label="Candidates",
    )
    # one <path> per non-zero slice
    assert html.count("<path d=") == 2
    # legend shows percentage labels
    assert "Candidates" in html
    assert "%" in html


def test_donut_skips_zero_values():
    html = t.render_donut_svg([
        {"label": "Hired", "value": 0},
        {"label": "Active", "value": 1},
    ])
    # only the non-zero slice is drawn; a 100% slice must be a visible circle,
    # not a zero-length arc path.
    assert html.count("<path d=") == 0
    assert "<circle" in html


# ---------------------------------------------------------------------------
# render_bar_svg
# ---------------------------------------------------------------------------
def test_bar_no_data_shows_placeholder():
    html = t.render_bar_svg([], title="Empty")
    assert "No data yet" in html


def test_bar_renders_one_rect_per_bar():
    html = t.render_bar_svg([
        {"label": "Mon", "value": 32},
        {"label": "Tue", "value": 41},
        {"label": "Wed", "value": 28},
    ], title="Attendance")
    assert html.count("<rect") == 3
    # tooltip <title> per bar
    assert html.count("<title>") == 3
    # all labels present
    assert "Mon" in html and "Tue" in html and "Wed" in html


def test_bar_uses_palette_when_no_color_specified():
    html = t.render_bar_svg([{"label": "X", "value": 1}])
    # palette starts with var(--accent)
    assert "var(--accent)" in html


def test_bar_single_point_keeps_wide_dashboard_aspect():
    html = t.render_bar_svg([{"label": "2026-03", "value": 1}])
    match = re.search(r'viewBox="0 0 (\d+) (\d+)"', html)
    assert match is not None
    width, height = map(int, match.groups())
    assert width >= 420
    assert width > height
