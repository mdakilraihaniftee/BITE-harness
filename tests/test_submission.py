"""A source export must retain runnable inputs without copying private local files."""
from pathlib import Path
import zipfile

from scripts.package_submission import ROOT_FILES, build


def test_submission_excludes_credentials_runs_and_caches(tmp_path: Path):
    root = tmp_path / "project"
    root.mkdir()
    for name in ROOT_FILES:
        (root / name).write_text("example\n")
    allowed = ["openvlharness/agent.py", "docs/REPORT.md", "scripts/run_custom_inference.sh",
               "results/reference/manifest.json", "tests/test_example.py"]
    excluded = [".env", ".env.private", "outputs/run/events.jsonl", "data/private.jpg",
                ".local_archive/old.md", ".git/config", ".venv/bin/python", ".aws/credentials",
                "openvlharness/__pycache__/agent.pyc", "scripts/.env.secret", "scripts/debug.log"]
    for name in allowed + excluded:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("example\n")
    output = tmp_path / "submission.zip"
    count, digest = build(root, output)
    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        assert names == {"parsec-vl/" + name for name in list(ROOT_FILES) + allowed}
        assert archive.testzip() is None
    assert count == len(names)
    assert digest in output.with_suffix(".zip.sha256").read_text()
