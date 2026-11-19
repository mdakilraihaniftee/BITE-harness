#!/usr/bin/env python3
"""Build a source submission ZIP without local credentials, runs or environments."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DIRECTORIES = (".github", "LICENSES", "configs", "docs", "evaluation_kit", "examples",
               "openvlharness", "results", "scripts", "tests")
ROOT_FILES = ("README.md", "pyproject.toml", "MANIFEST.in", ".env.example", ".gitignore",
              "LICENSE", "THIRD_PARTY_LICENSES.md", "CITATION.cff", "SECURITY.md", "run_benchmark.py")
EXCLUDED = {"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", "node_modules",
            ".git", ".venv", ".venvs", ".cache", ".local_archive", ".aws", ".agents", ".codex"}


def submission_files(root: Path) -> list[Path]:
    missing = [name for name in ROOT_FILES if not (root / name).is_file()]
    if missing:
        raise ValueError("Missing submission files: " + ", ".join(missing))
    paths = [root / name for name in ROOT_FILES]
    for name in DIRECTORIES:
        for path in (root / name).rglob("*"):
            relative = path.relative_to(root)
            if (path.is_symlink() or any(part in EXCLUDED for part in relative.parts)
                    or path.name == ".env" or path.name.startswith(".env.")
                    or path.suffix in {".pyc", ".pyo", ".log"} or path.name == ".DS_Store"):
                continue
            if path.is_file():
                paths.append(path)
    return sorted(paths)


def build(root: Path, output: Path) -> tuple[int, str]:
    paths = submission_files(root)
    if output.resolve().is_relative_to((root / "results").resolve()):
        raise ValueError("Write packages under dist/, outside the included source directories")
    # Do not accidentally package a previous archive placed in a source folder.
    if any(output.resolve() == path.resolve() for path in paths):
        raise ValueError("Output archive overlaps a submitted source file")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in paths:
            archive.write(path, "parsec-vl/" + path.relative_to(root).as_posix())
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(output.suffix + ".sha256").write_text(f"{digest}  {output.name}\n")
    return len(paths), digest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "dist/parsec-vl-submission.zip")
    args = parser.parse_args()
    count, digest = build(ROOT, args.out)
    print(f"Submission: {args.out.resolve()}")
    print(f"Files: {count}; size: {args.out.stat().st_size:,} bytes")
    print(f"SHA-256: {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
