from pathlib import Path


def test_ci_workflow_exists():
    path = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "test.yml"
    text = path.read_text()
    assert "pytest -q" in text
    assert "3.11" in text and "3.12" in text
