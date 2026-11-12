"""公開發布檔案政策。

私人主庫會鏡像推送到公開部署庫，因此所有被 git 追蹤的檔案都必須：
1. 符合允許清單（ALLOWED_PATTERNS）；且
2. 不符合禁止清單（FORBIDDEN_PATTERNS）。

禁止清單優先於允許清單。新增檔案類型時，請先確認可公開，再加入允許清單。
"""

from __future__ import annotations

from fnmatch import fnmatchcase
from pathlib import PurePosixPath
from typing import Iterable

# 可公開的追蹤檔案（POSIX 路徑，fnmatch 樣式；* 可跨目錄）。
ALLOWED_PATTERNS: tuple[str, ...] = (
    # 根目錄文件與設定
    ".env.example",
    ".gitignore",
    "AGENTS.md",
    "CLOUD_DEPLOYMENT.md",
    "DEVELOPMENT_REPORT.md",
    "README.md",
    "README_SKILL_PACK.md",
    "STATUS.md",
    "keywords.txt",
    "packages.txt",
    "requirements.txt",
    "requirements-cloud.txt",
    ".streamlit/config.toml",
    ".github/workflows/*.yml",
    # 程式、測試、提示詞與寫作規則
    "app/*.py",
    "scripts/*.py",
    "tests/*.py",
    "prompts/*.md",
    "skills/*.md",
    "docs/*.md",
    # 公開評議書資料集
    "data/appeal_cases.db",
    "data/cases.csv",
    "data/crawl_state.json",
    "data/discovered_cids.txt",
    "data/downloaded_cids.txt",
    "data/failed_cids.txt",
    "data/raw_html/*.html",
    "data/texts/*.txt",
    # Next.js 公開前端原始碼（建置產物與資料由 .gitignore 排除）
    "web/.gitignore",
    "web/.vercelignore",
    "web/README.md",
    "web/next-env.d.ts",
    "web/next.config.ts",
    "web/package.json",
    "web/package-lock.json",
    "web/tsconfig.json",
    "web/vercel.json",
    "web/app/*.tsx",
    "web/app/*.ts",
    "web/app/*.css",
    "web/lib/*.ts",
    "web/scripts/*.mjs",
    "web/public/*.svg",
    "web/public/*.ico",
    "web/public/*.png",
)

# 不論位於哪個目錄都不得追蹤的檔名或路徑片段。
FORBIDDEN_NAMES: tuple[str, ...] = (
    "secrets.toml",
    "private_cases.db",
    "auth_users.json",
    "module_permissions.json",
)
FORBIDDEN_DIRS: tuple[str, ...] = (
    "uploaded_cases",
    "browser_profiles",
    "exports",
    "ai_exports",
    "audit_reports",
    "streamlit_logs",
    "update_runs",
    ".venv",
    "__pycache__",
    "node_modules",
    ".next",
    ".vercel",
)


def is_forbidden(path: str) -> bool:
    parts = PurePosixPath(path).parts
    if not parts:
        return False
    name = parts[-1]
    if name in FORBIDDEN_NAMES:
        return True
    # .env、.env.local、.env.production 等；範本 .env.example 例外。
    if (name == ".env" or name.startswith(".env.")) and name != ".env.example":
        return True
    if name.endswith((".db-wal", ".db-shm", ".log", ".pyc")):
        return True
    return any(part in FORBIDDEN_DIRS for part in parts[:-1])


def is_allowed(path: str) -> bool:
    return any(fnmatchcase(path, pattern) for pattern in ALLOWED_PATTERNS)


def find_violations(paths: Iterable[str]) -> dict[str, list[str]]:
    """回傳 {"forbidden": [...], "not_allowed": [...]}。"""
    forbidden: list[str] = []
    not_allowed: list[str] = []
    for path in paths:
        path = path.strip()
        if not path:
            continue
        if is_forbidden(path):
            forbidden.append(path)
        elif not is_allowed(path):
            not_allowed.append(path)
    return {"forbidden": forbidden, "not_allowed": not_allowed}
