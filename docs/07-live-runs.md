# 7. Live runs against a real model

The committed transcripts in `evals/transcripts/` are hand-written. `evalkit live` produces the other kind: it sends each case to a real model, lets the model call the (mock) inventory tools, and records what happened in the same transcript format. Then `run` and `diff` grade it like any other run.

## How to run

Any OpenAI-compatible chat-completions endpoint with tool calling works. The request goes to `<base-url>/chat/completions`. The default is a local [Ollama](https://ollama.com) server, `http://localhost:11434/v1`, which needs no account and costs nothing. The runner still requires `EVALKIT_API_KEY` to be set, and Ollama ignores its value, so any word works there.

### Option A: a local model with Ollama (free, nothing leaves your machine)

Install Ollama from ollama.com, then pull a model that supports tool calling. Small local models are weaker than hosted ones, and the results will show that.

```bash
ollama pull qwen2.5:7b
export EVALKIT_API_KEY="ollama"
export MODEL="qwen2.5:7b"
export TAG="${MODEL//[\/:]/-}"
```

### Option B: a hosted endpoint

Set `--base-url` to the provider's OpenAI-compatible URL, for example `https://api.openai.com/v1`, put the provider's key in `EVALKIT_API_KEY`, and set `MODEL` to a model name the provider offers. A hosted key is a secret: type it only in your own terminal, never in a chat or a file.

### Then run

```bash
python3 -m evalkit live --cases evals/cases/inventory_assistant.jsonl --instructions evals/instructions/v1.md --model "$MODEL" --out "evals/transcripts/live-$TAG-v1.jsonl"

python3 -m evalkit live --cases evals/cases/inventory_assistant.jsonl --instructions evals/instructions/v2.md --model "$MODEL" --out "evals/transcripts/live-$TAG-v2.jsonl"

python3 -m evalkit diff --cases evals/cases/inventory_assistant.jsonl --before "evals/transcripts/live-$TAG-v1.jsonl" --after "evals/transcripts/live-$TAG-v2.jsonl"

unset EVALKIT_API_KEY
```

Add `--base-url` to the two `live` commands for Option B. `TAG` is the model name with `/` and `:` replaced by `-`, used in the file names. A hosted key typed into a terminal stays in your shell history, so run `unset` afterwards and rotate the key if the machine is shared. These commands are written to paste into bash or zsh as they are. A first cheap try: add `--only md1,nm4` and write to `/tmp/try.jsonl`.

Flags: `--base-url`, `--api-key-env` (default `EVALKIT_API_KEY`), `--max-steps` (model calls per case, default 6), `--temperature` (default 0), `--only md1,nm4` (run a subset, useful for a cheap first try), `--timeout` (seconds per request, default 60).

## What is recorded

One JSON object per line:

```json
{"id": "md1", "text": "...final answer...", "tool_calls": [{"name": "inventory_query", "args": {"sku": "TJX1-M-BLK"}}],
 "meta": {"model": "...", "base_url_host": "localhost", "timestamp_utc": "...", "instructions_sha256": "...", "steps": 2, "truncated": false}}
```

- `text` and `tool_calls` are what the graders read. Arguments are recorded exactly as the model sent them, including wrong types.
- `meta` is ignored by grading. `steps` counts model calls; `truncated: true` means the model was still calling tools when `--max-steps` ran out, so the transcript is partial.
- The host is recorded without any path or credentials. The API key is never written to the file, printed, or included in an error message.

## The tools the model gets

`evalkit/mock_backend.py` implements the six tools in memory with fixed data, so a run is repeatable apart from the model. `create_order` and `send_email` are recorded as calls and answered with an "executed in sandbox" result; nothing is sent or ordered. Each case starts with fresh state.

The data is chosen so every case has a correct, reachable answer. For example, `inventory_list` is paginated and not sorted, so the three lowest-stock SKUs are only found by reading page 2. The tests grade a hand-built correct answer for several cases against this data.

## Cost and timing

Each case costs one model call per step, up to `--max-steps`, and a tool-using case needs at least two. A full run is therefore 25 cases times a few calls, per instruction version. I have not measured token counts or wall-clock time for any model; check your provider's pricing and start with `--only` on a handful of cases. A 429 or 5xx response is retried up to three times with a short, capped backoff; any other error stops the run, and the cases already finished stay in the output file.

## Honesty

- The committed `v1.jsonl` and `v2.jsonl` are **illustrations**, written by hand to show a realistic failure and fix. They are not model output and are not evidence about any model. The two files in `evals/instructions/` are real prompts you can run, but those transcripts were not produced from them.
- A live run records whatever the model does, including failures, and it is not cherry-picked. If you publish results, publish the whole file, not the cases that look good. A result that contradicts the story in these docs (for example v2 not beating v1) is a finding, not a bug to be tuned away.
- One run at temperature 0 is not a benchmark. 25 synthetic cases catch regressions in behaviours someone thought of; a hosted model can still vary between runs, and the result says nothing about other prompts, data or models. Repeat runs and compare agreement before drawing a conclusion.
- Nothing in this repository has been run against a real model. The live path is tested only against a local fake server.
