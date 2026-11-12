"""網頁版 AI 分析包（web/lib/ai-package.ts）必須與 scripts/public_ai_export.py 產出逐字一致。

需要 Node.js 22.18 以上與 web/node_modules（cd web && npm ci）；缺少時略過。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT_DIR / "web"
sys.path.insert(0, str(ROOT_DIR / "scripts"))

import public_ai_export  # noqa: E402

FIXED_TIME = "2026-01-02T03:04:05"


def node_ready() -> bool:
    node = shutil.which("node")
    if not node or not (WEB_DIR / "node_modules" / "csv-parse").exists():
        return False
    version = subprocess.run([node, "-p", "process.versions.node"], capture_output=True, text=True).stdout.strip()
    try:
        major, minor = (int(part) for part in version.split(".")[:2])
    except ValueError:
        return False
    return (major, minor) >= (22, 18)


pytestmark = pytest.mark.skipif(not node_ready(), reason="需要 Node.js >= 22.18 與 web/node_modules")


@pytest.fixture(scope="module")
def web_data() -> None:
    subprocess.run(["node", "scripts/export-web-data.mjs", "--check"], cwd=WEB_DIR, check=True, capture_output=True)


def python_bundle(cids: list[str], mode: str, tmp_path: Path, monkeypatch) -> dict[str, str]:
    monkeypatch.setattr(public_ai_export, "export_time", lambda: FIXED_TIME)
    result = public_ai_export.export_public_case_bundle(
        cids,
        mode=mode,
        output_root=tmp_path / "bundles",
        canonical_output_root=tmp_path / "public_cases",
    )
    files: dict[str, str] = {}
    for path in sorted(result.bundle_dir.rglob("*")):
        if path.is_file():
            # 以 bytes 解碼並保留換行與 BOM，才能逐字比對。
            text = path.read_bytes().decode("utf-8")
            files[path.relative_to(result.bundle_dir).as_posix()] = text
    return files


def web_bundle(cids: list[str], mode: str) -> dict[str, str]:
    result = subprocess.run(
        ["node", "scripts/dump-ai-package.mjs", mode, FIXED_TIME, *cids],
        cwd=WEB_DIR,
        check=True,
        capture_output=True,
    )
    return json.loads(result.stdout.decode("utf-8"))


def normalize(files: dict[str, str]) -> dict[str, str]:
    # Windows 上 Python 以文字模式寫檔會把 \n 轉成 \r\n；CSV 本來就是 \r\n。
    return {name: text if name.endswith(".csv") else text.replace("\r\n", "\n") for name, text in files.items()}


def all_cids() -> list[str]:
    return [row["cid"] for row in public_ai_export.load_public_cases()]


def test_every_public_case_matches_python_export(web_data, tmp_path, monkeypatch):
    cids = all_cids()
    assert cids
    expected = normalize(python_bundle(cids, "single", tmp_path, monkeypatch))
    actual = normalize(web_bundle(cids, "single"))
    assert sorted(actual) == sorted(expected)
    mismatched = [name for name in expected if actual[name] != expected[name]]
    assert not mismatched, f"{len(mismatched)} 個檔案不一致，例如 {mismatched[:5]}"


def test_compare_mode_matches_python_export(web_data, tmp_path, monkeypatch):
    cids = all_cids()[:3]
    expected = normalize(python_bundle(cids, "compare", tmp_path, monkeypatch))
    actual = normalize(web_bundle(cids, "compare"))
    assert actual == expected
