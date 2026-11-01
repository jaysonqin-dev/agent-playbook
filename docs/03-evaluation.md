# 3. Evaluation

You cannot tell whether an instruction change helped by reading a few answers. You need a fixed set of cases, graders that do not drift, and a way to compare two runs.

## The harness in this repo

```
evals/cases/inventory_assistant.jsonl   25 cases for a fictional inventory assistant
evals/transcripts/v1.jsonl, v2.jsonl    two recorded runs (hand-written, see the note below)
evalkit/                                cases, graders, runner, report, CLI
```

```bash
python3 -m evalkit run  --cases evals/cases/inventory_assistant.jsonl --responses evals/transcripts/v1.jsonl
python3 -m evalkit diff --cases evals/cases/inventory_assistant.jsonl --before evals/transcripts/v1.jsonl --after evals/transcripts/v2.jsonl
```

The transcripts are **hand-written** to illustrate a realistic failure and a realistic fix. They are not output from a real model. The harness can also grade a live agent: `python3 -m evalkit live` records a real model's answers (see [Live runs](07-live-runs.md)), and `run_cases(cases, callable)` takes a function from a case to a response.

## What it grades, and why deterministically

Graders: `contains`, `not_contains`, `regex`, `number_close`, `tool_called` (with argument subset), `tool_not_called`, `tool_order`, `max_words`, `json_fields`.

They are deterministic on purpose. A model-based judge adds its own variance to the thing you are measuring. Use one only for what these graders cannot express, and calibrate it against the deterministic ones first.

What is worth grading in an agent:

- **Numbers.** The answer says 100, not 70. Metric-definition mistakes show up here.
- **Tool use.** The right tool, with the right arguments, in the right order, and not called when it should not be (an out-of-scope question must not trigger a data query; a write must not happen before approval).
- **Format.** JSON fields, length limits, a numbered list when asked.
- **Refusals.** Unsupported or invalid requests are declined clearly.

## Reading a run

```
v1 -> v2
  pass rate 72% -> 92%
  regressed: tr4
  fixed: md1, tr3, ap1, fm3, sr2, nm1
  still_failing: nm4
```

The pass rate went up and a regression is hiding inside it: the "always check the data first" instruction fixed several cases and made the agent query data for an out-of-scope question (`tr4`). Read `regressed` first. `--fail-on-regression` makes that a hard gate.

## Cases worth adding after every incident

Each real failure becomes a case before it becomes a rule. The case proves the fix works now and keeps working after the next edit.

## Limits

- 25 cases is a smoke test, not a benchmark. It catches regressions in behaviors you thought of.
- Recorded runs measure one sample. A live model varies run to run: run each case several times and report agreement, which this repo does not do yet.
- Passing the set says nothing about cases that are not in it.
