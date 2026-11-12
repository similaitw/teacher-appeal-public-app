"""雲端公開模式 smoke test：最壞情況（關閉登入＝所有人都是管理員）也不得碰私人資料。"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("streamlit.testing.v1")
from streamlit.testing.v1 import AppTest  # noqa: E402

ROOT_DIR = Path(__file__).resolve().parents[1]
APP_PATH = ROOT_DIR / "app" / "streamlit_app.py"
PRIVATE_PATHS = [ROOT_DIR / "private_cases.db", ROOT_DIR / "uploaded_cases", ROOT_DIR / "exports"]
PAGES = [
    "總覽",
    "公開評議書搜尋",
    "公開案件閱讀",
    "公開 AI 分析包",
    "資料管理",
    "公開資料更新",
    "資安檢查",
    "私人案件管理",
    "匯入案件文件",
    "案件文件閱讀",
    "Codex 分析資料",
    "AI 分析結果",
    "批次儀表板",
    "誤判風險稽核",
]


@pytest.fixture
def cloud_env(monkeypatch):
    monkeypatch.setenv("APP_MODE", "cloud_public")
    monkeypatch.setenv("AUTH_DISABLED", "1")


@pytest.mark.parametrize("page", PAGES)
def test_cloud_public_pages_do_not_touch_private_data(cloud_env, page):
    existed_before = {path: path.exists() for path in PRIVATE_PATHS}
    at = AppTest.from_file(str(APP_PATH), default_timeout=60)
    at.session_state["selected_page"] = page
    at.run()
    assert not at.exception, f"{page}: {at.exception}"
    for path, existed in existed_before.items():
        if not existed:
            assert not path.exists(), f"{page} 在雲端公開模式建立了 {path.name}"


def test_cloud_public_login_disabled_without_configured_password(monkeypatch):
    """雲端公開版未設定密碼時不得接受公開在原始碼裡的預設密碼。"""
    monkeypatch.setenv("APP_MODE", "cloud_public")
    monkeypatch.delenv("AUTH_DISABLED", raising=False)
    monkeypatch.delenv("DEFAULT_APP_PASSWORD", raising=False)
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    generated = [ROOT_DIR / "data" / "auth_users.json", ROOT_DIR / "data" / "module_permissions.json"]
    existed = {path: path.exists() for path in generated}
    try:
        at = AppTest.from_file(str(APP_PATH), default_timeout=60)
        # 模擬舊的登入狀態殘留：即使 session 裡有 admin，也必須被當成訪客。
        at.session_state["auth_user"] = {"username": "admin", "display_name": "x", "role": "admin"}
        at.session_state["selected_page"] = "帳號管理"
        at.run()
        assert not at.exception
        assert not [item for item in at.text_input if item.label == "密碼"]
        assert "simisimi520" not in " ".join(str(item.value) for item in [*at.caption, *at.info, *at.markdown])
        assert at.session_state["selected_page"] != "帳號管理"
        assert "目前權限：guest" in [item.value for item in at.caption]
    finally:
        for path, was_there in existed.items():
            if not was_there and path.exists():
                path.unlink()
