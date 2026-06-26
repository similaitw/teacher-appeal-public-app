from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import batch_status_server  # noqa: E402


def test_dashboard_html_uses_ajax_polling():
    html = batch_status_server.dashboard_html("batch1")
    assert "fetch(`/api/batch?batch=${batch}`" in html
    assert "setInterval(load, 5000)" in html
    assert "批次 AI 分析儀表板" in html


def test_safe_batch_dir_rejects_path_traversal(tmp_path, monkeypatch):
    root = tmp_path / "web_ai_batches"
    good = root / "batch1"
    good.mkdir(parents=True)
    monkeypatch.setattr(batch_status_server, "WEB_AI_BATCHES_DIR", root)

    assert batch_status_server.safe_batch_dir("batch1") == good.resolve()

    try:
        batch_status_server.safe_batch_dir("../batch1")
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("Expected path traversal to be rejected")
