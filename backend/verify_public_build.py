"""Fail if the student build contains operator/source/private artifacts."""

import sys
from pathlib import Path


def verify_public_build(directory: Path):
    index = directory / "index.html"
    if not index.is_file() or "Intervella" not in index.read_text(encoding="utf-8"):
        raise ValueError("Missing built student entry point")
    for path in directory.rglob("*"):
        if path.is_symlink():
            raise ValueError("Symlink in public build")
        if path.is_dir():
            continue
        if (
            path.is_symlink()
            or "operator" in path.name.lower()
            or path.suffix not in {".html", ".js", ".css", ".svg", ".png", ".woff2"}
        ):
            raise ValueError("Non-student artifact in public build")
        if path.suffix in {".js", ".html"}:
            content = path.read_text(encoding="utf-8")
            if any(
                value in content
                for value in ["OPERATOR_SECRET", "/ops/", "STUDENT_BETA_PASSWORD_HASH"]
            ):
                raise ValueError("Private operations in public build")


if __name__ == "__main__":
    verify_public_build(Path(sys.argv[1]))
    print("Student build contains no operator, source-map or private configuration artifacts.")
