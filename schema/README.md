# schema/

The contract between `mod/` and `harness/`, as a formal specification.

- **`state.schema.json`** — JSON Schema (draft 2020-12) for the per-turn state file the mod writes (one file per turn under a per-game folder in `state/`, e.g. `state/LEADER_HATSHEPSUT_1738531200000/turn_0005.json`). This is the reference for field names, types, and visibility semantics; the field descriptions inside it are the documentation.
- **`state.example.json`** — a hand-written, synthetic example of a complete turn-5 export, kept valid against the schema. Illustrative only — **not** a real capture. Real captures from actual play sessions live in `samples/` (see its README) and are the ground truth for what the mod actually produces.

The mod itself can't use this schema (its embedded Python 2.4 predates any JSON tooling) — it exists for humans designing the contract and for harness-side validation of mod output later. `meta.schemaVersion` in the state file is bumped on breaking changes so the harness can reject stale samples.

Validate the example (or any capture) with the `jsonschema` package:

```
python -c "import json, jsonschema; jsonschema.Draft202012Validator(json.load(open('schema/state.schema.json'))).validate(json.load(open('schema/state.example.json')))"
```
