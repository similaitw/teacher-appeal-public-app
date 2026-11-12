from scripts.publish_policy import find_violations, is_allowed, is_forbidden


def test_forbidden_secrets_anywhere():
    for path in [
        ".env",
        "web/.env.local",
        ".streamlit/secrets.toml",
        "data/private_cases.db",
        "private_cases.db",
        "data/auth_users.json",
        "data/module_permissions.json",
        "uploaded_cases/a/b.pdf",
        "data/ai_exports/run.zip",
        "data/audit_reports/x.md",
        "exports/case.md",
        "data/exports/case.md",
        "browser_profiles/chrome/Default/Cookies",
        "scripts/__pycache__/utils.cpython-311.pyc",
        "data/appeal_cases.db-wal",
        "data/crawl_errors.log",
    ]:
        assert is_forbidden(path), path


def test_env_example_allowed():
    assert not is_forbidden(".env.example")
    assert is_allowed(".env.example")


def test_public_files_allowed():
    for path in [
        "app/streamlit_app.py",
        "scripts/crawl_appeal.py",
        "data/cases.csv",
        "data/texts/114070228.txt",
        "data/raw_html/114070228.html",
        "web/app/cases/[cid]/page.tsx",
        ".github/workflows/ci.yml",
        "data/public_analysis/runs/20260619_140759_chatgpt_public_bundle.json",
        "web/app/package/page.tsx",
    ]:
        assert is_allowed(path), path
        assert not is_forbidden(path), path


def test_unknown_files_flagged():
    result = find_violations(["notes/private.docx", "data/new.sqlite", "README.md"])
    assert result["not_allowed"] == ["notes/private.docx", "data/new.sqlite"]
    assert result["forbidden"] == []


def test_forbidden_wins_over_allowed():
    result = find_violations(["data/texts/.env"])
    assert result["forbidden"] == ["data/texts/.env"]


def test_raw_ai_exports_stay_forbidden():
    result = find_violations(["data/ai_exports/analysis_runs/run1/ai_response.md", "data/public_analysis/notes.txt"])
    assert result["forbidden"] == ["data/ai_exports/analysis_runs/run1/ai_response.md"]
    assert result["not_allowed"] == ["data/public_analysis/notes.txt"]
