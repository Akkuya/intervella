# Backend development

Run backend commands from this directory:

```powershell
uv sync
uv run python -m pytest
```

The application import root is `app`. The parser is `app.ingest.parser`,
so use `from app.ingest.parser import parse_schedule`.
From the repository root, tests can also run with:
`backend/.venv/Scripts/python.exe -m pytest -c backend/pyproject.toml backend/tests`.

When opening the repository root in VS Code, the workspace settings configure
backend test discovery and import analysis. Select `backend/.venv/Scripts/python.exe`
with Python: Select Interpreter if VS Code already remembers another interpreter.

## Parser samples and output

- `tests/fixtures/`: commit small sanitized HTML examples and stable expected JSON
  used by tests. Preserve the table structure, classes, rowspans, and time formats;
  replace personal names, identifiers, event details, tokens, and login markup.
  The current tests already contain a small synthetic HTML example inline.
- `data/`: ignored local HTML snapshots and generated JSON. Keep raw intranet
  captures here, outside committed fixtures.
- `run_parser.py`: a manual smoke-test helper; committing it is reasonable.
  Place a local snapshot at `data/exampledata.html`, then run
  `uv run python run_parser.py`. It writes `data/output.json`.
  Automated tests do not need this helper.

The legacy repository-root `exampledata.html` and `output.json` have been
removed from tracked branch history and are ignored to prevent accidental re-addition.
