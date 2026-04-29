from __future__ import annotations

from hrkit.templates import render_detail_page


def test_detail_page_editor_uses_better_controls_and_raw_fields():
    html = render_detail_page(
        title="Review",
        nav_active="performance",
        fields=[
            ("Status", "draft"),
            ("Score", "7.5"),
            ("Comments", "Good"),
            ("Created", "2026-04-01"),
        ],
        item_id=12,
        api_path="/api/m/performance",
        delete_redirect="/m/performance",
        field_options={"status": ["draft", "submitted"]},
    )

    assert "openEditDialog" in html
    assert "edit-advanced-fields" in html
    assert '<select name="status"' in html
    assert 'type="number"' in html
    assert '<textarea name="comments"' in html
    assert 'name="created"' not in html
    assert "/api/m/performance/12" in html
