# harness/

External Python 3 project. Reads the state JSON written by `mod/`, sends it (plus static XML-derived rules data) to the Claude API, and prints back strategic advice.

## Constraints

- Modern Python 3 — no constraints inherited from `mod/`.
- No dependency on Civ IV being installed. Developable/testable purely against saved sample files in `samples/`.
- Currently reads a **single static file** — no polling, no file-watching, no live loop. See root `CLAUDE.md` for current phase scope.

## Setup

Plain venv + `requirements.txt`:

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Nothing is implemented yet — this is scaffolding only.
