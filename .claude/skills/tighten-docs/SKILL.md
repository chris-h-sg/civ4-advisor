---
name: tighten-docs
description: Review this repo's markdown for stale claims, self-contradiction, redundancy, over-explanation and dead history — applying the safe fixes and proposing the rest. Use when asked to tighten, trim, condense or clean up the docs, and after any feature lands that touched code the docs describe. Not for code — that is /simplify.
---

# Tighten the docs

Make the markdown shorter without losing anything load-bearing. Prose has no
test suite: a deleted rationale and a deleted filler sentence look identical in
a diff, and the loss only surfaces months later when someone relitigates a
settled decision. So this skill is deliberately asymmetric — it applies only
cuts that cannot lose information, and proposes everything else.

**Expect to find errors, not just bloat.** On the run this skill was written
from, word count barely moved while six factual defects surfaced — and the two
worst were docs instructing the reader to do the wrong thing: a README saying
"restore the .ini to the minimal version before committing" when CLAUDE.md had
settled on the expanded form, and a roadmap item correcting a claim in one
paragraph and repeating it four lines later. **A doc that contradicts itself or
the code is worth more attention than a doc that is merely long**, so verify
before you trim. Adding a missing entry is a legitimate outcome of this skill.

**Most stale docs are freshly stale.** Three of those six defects were written
in the same session that broke them — code moved, docs didn't. The best moment
to run this is right after a feature lands, not as periodic hygiene.

## The file roles, which decide where text belongs

This repo assigns each document one job. A sentence in the wrong file is
usually a **move**, not a deletion — check before cutting.

| File | Job | What does NOT belong |
|---|---|---|
| `harness/AGENT_GUIDE.md` | Instructions for the advising agent: what to run, what trap to avoid | Reasoning, justification, design history. "A guide that argues with itself gets skimmed." |
| `harness/README.md`, `mod/README.md` | Reasons for developers: why each thing is shaped as it is | Usage instructions that duplicate the guide |
| `ROADMAP.md` | A **queue** of unbuilt work | History. When an item lands it is DELETED, its reasoning moved to the relevant README. Git holds the rest. |
| `REFERENCES.md` | Verified findings with their citations | Anything unverified, and any finding stripped of the source that verifies it |
| `CLAUDE.md` | Durable project constraints and settled decisions | Anything derivable from the code, and anything transient |
| `samples/README.md` | Provenance and caveats of captured data | — |

## Tier 1 — apply directly

These cannot lose information. Apply them, then list what you did.

1. **Sentences duplicated near-verbatim across files.** Keep the one in the
   file whose job it is (table above); delete the copy. If the copy is in
   `AGENT_GUIDE.md` and is a *usage* restatement of a README *reason*, that is
   correct as-is — leave both.
2. **Stale cross-references.** A pointer to a renamed/deleted file, function,
   flag or section. Fix the target or drop the pointer. Verify with Grep
   before touching — a reference that still resolves is not stale.
3. **Dead changelog lines in `ROADMAP.md`.** Bookkeeping about items that have
   landed, warnings that no longer apply, lane notes for empty lanes. The
   roadmap is a queue; its own header says so.
4. **Claims contradicted by the current code.** Verify against the source
   before rewriting; a doc that disagrees with the code is worse than no doc.
5. **Numbers and counts that have drifted** (line counts, test counts, tile
   counts, "~3600-line module"). Re-measure and correct, or make the claim
   qualitative if the exact figure carries nothing.

## Tier 2 — propose, do not apply

Report these with file:line, the proposed replacement, and one line of
reasoning. Wait for approval.

6. **History that no longer guards anything.** The test is not "is this in the
   past tense" — it is **does this explain why the current state resists an
   obvious change?**
   - KEEP: "It used to print a TOTAL; that number was misleading because…"
     — someone will re-add the total otherwise. This is a guardrail.
   - CUT: "the serial warning that used to head this lane" — bookkeeping about
     something already gone. Nothing acts on it.
   When unsure, keep it and say why you were unsure.
7. **Over-explanation.** A paragraph making one point in four sentences.
   Propose the shorter form verbatim so the trade is visible.
8. **Rationale that could move to a shorter home**, e.g. a long README
   passage that a code comment now covers, or vice versa.
9. **Prose that restates what the tool already prints.** The sharpest test
   available for a usage doc, and the one that cut hardest: **run the tool and
   read its output before trimming its documentation.** If the output already
   says it, the doc needs only what the output *cannot* say — the judgement,
   the counterexample that stops the rule being over-applied, and the failure
   that motivated it. A guide row explaining `LOSES X` was 68 words; the tool
   prints `LOSES BONUS_HORSE - replaces the IMPROVEMENT_PASTURE that connects
   it`, so the row was pure restatement and the judgement it should have
   carried was one clause.
10. **A section disproportionate to its siblings.** Compare word counts across
    peers doing the same job — one subcommand at 582 words beside another at
    224 is a structural signal, not a style opinion. The cause is usually
    *form*, not verbosity: every fact given its own bold paragraph pays
    paragraph overhead seven times over. Check whether the document already
    has a denser form for exactly this (a trap table, a trigger table) and use
    it. Do NOT force it: once restatement is gone the rows may be too short to
    earn two-column overhead, and bullets are then the better fit.

## Never cut

- The **reason** behind a decision CLAUDE.md marks "don't relitigate".
- Any **caveat about wrongness**: fog-of-war honesty, provenance limits,
  backfilled or derived sample data, "this reads as a bug but is correct".
- **OMITS-style statements** of what a tool does not do.
- **Citations** in `REFERENCES.md` — the file's value is that its claims are
  checkable.
- Anything recording a **live failure**: a trial that lost a unit, a number
  reported wrongly. These are why the guardrail exists.
- **Counterexamples that bound a rule.** "The connector is listed first" needs
  "a Mine on Gems is −1 hammer" beside it, or the rule reads as a yield
  ranking and gets applied where it does not hold. A rule without its
  exception is not shorter, it is wronger.
- **Literal output strings** the reader will meet on screen — `NOT VISIBLE
  NOW`, `NOTHING BUILDABLE`, `SWITCHED`. Each is a lookup key: when it appears
  and the reader searches the guide for it, a paraphrase does not match. Cut
  only where the output is fully self-explaining *and* carries no trap.

## Procedure

1. `git status` — note which docs the current work already changed.
2. Read every `.md` in scope. Default scope is the whole repo; if the user
   names files, use those.
3. Build the Tier 1 list and the Tier 2 list. **Verify each candidate** —
   Grep for the referenced symbol, read the code, check the number — rather
   than judging from the prose alone.
4. **Before editing a usage doc, list the load-bearing facts in the section**
   — every literal output string, number, counterexample and named failure.
   This is the checklist step 6 needs.
5. Apply Tier 1. Re-read each edited region afterwards to confirm the
   surrounding text still reads correctly.
6. **Grep the edited file for every fact on that list.** Compression drops
   things silently: on the run this was written from, `NOT VISIBLE NOW`
   vanished from a rewritten paragraph and only this check caught it. Restore
   anything missing before reporting. (`grep -F`, and `--` before a pattern
   starting with `-`, or the shell eats it as a flag and reports a false
   loss.)
7. Report: what was applied (grouped by file), then the Tier 2 proposals with
   reasoning, then anything you deliberately kept and why.
8. If any doc states a testable fact you corrected, run the relevant test or
   command to confirm the new version is right. Check markdown links still
   resolve and tables still have their delimiter rows.

## When to stop

A second pass over the same section is often worth it — one run went 582 → 460
→ 352 words, and the second cut was the larger, because the first pass fixed
*form* and only then made the restatement visible. But stop when what is left
is failure records, counterexamples and look-like-a-bug readings. At that point
every remaining sentence changes a choice rather than explaining one, and
further cutting removes decisions rather than words. Say you have reached that
point rather than trimming to hit a number.

Report honestly: if a document is already tight, say so rather than
manufacturing cuts.
