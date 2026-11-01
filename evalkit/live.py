"""Run the case set against a real model through an OpenAI-compatible chat-completions endpoint.

The model gets the instructions as a system prompt and the mock tools from `mock_backend`. Whatever it
does is recorded in the transcript format `load_responses` already reads, so `evalkit run` and
`evalkit diff` grade it like any other run. Standard library only. The API key is read from an
environment variable, sent only in the Authorization header, and scrubbed from every error message.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional
from urllib.parse import urlparse

from .case import Case
from .mock_backend import TOOL_SCHEMAS, MockBackend

DEFAULT_BASE_URL = "https://models.github.ai/inference"
DEFAULT_KEY_ENV = "EVALKIT_API_KEY"
MAX_RETRIES = 3
MAX_BACKOFF_SECONDS = 4.0
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")

Sleeper = Callable[[float], None]


class LiveError(RuntimeError):
    """A failure talking to the model endpoint. Messages never contain the API key."""


def _scrub(text: str, secret: str) -> str:
    return text.replace(secret, "***") if secret else text


def _backoff(attempt: int, retry_after: Optional[str]) -> float:
    delay = 0.5 * (2 ** attempt)
    if retry_after and retry_after.strip().isdigit():
        delay = max(delay, float(retry_after))
    return min(delay, MAX_BACKOFF_SECONDS)


def _check_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise LiveError("--base-url must be an http(s) URL such as https://models.github.ai/inference")
    if parsed.scheme == "http" and parsed.hostname not in LOOPBACK_HOSTS:
        raise LiveError("refusing to send an API key over plain http to a non-local host; use https")
    return base_url.rstrip("/") + "/chat/completions"


def chat_completion(
    url: str,
    api_key: str,
    payload: Dict[str, Any],
    timeout: float = 60.0,
    sleep: Sleeper = time.sleep,
) -> Dict[str, Any]:
    """POST one chat-completions request. Retries 429 and 5xx up to MAX_RETRIES times."""
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    for attempt in range(MAX_RETRIES + 1):
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as reply:
                return json.loads(reply.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            retryable = error.code == 429 or error.code >= 500
            if retryable and attempt < MAX_RETRIES:
                sleep(_backoff(attempt, error.headers.get("Retry-After")))
                continue
            detail = _scrub(error.read().decode("utf-8", "replace")[:300], api_key)
            raise LiveError(f"HTTP {error.code} from the model endpoint: {detail}") from None
        except (urllib.error.URLError, OSError) as error:
            raise LiveError(f"could not reach the model endpoint: {_scrub(str(error), api_key)}") from None
        except ValueError:
            raise LiveError("the model endpoint returned a body that is not JSON") from None
    raise LiveError("unreachable")  # pragma: no cover


def _parse_args(raw: Any) -> Any:
    """Tool arguments as a dict, or None when the model sent something that is not a JSON object."""
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def run_case(
    case: Case,
    *,
    instructions: str,
    model: str,
    url: str,
    api_key: str,
    max_steps: int = 6,
    temperature: float = 0.0,
    timeout: float = 60.0,
    sleep: Sleeper = time.sleep,
) -> Dict[str, Any]:
    """Drive one case to a final answer or to max_steps model calls. Returns the row and its loop stats."""
    backend = MockBackend()
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": instructions},
        {"role": "user", "content": case.prompt},
    ]
    recorded: List[Dict[str, Any]] = []
    text, steps, truncated = "", 0, True
    while steps < max_steps:
        payload = {"model": model, "messages": messages, "tools": TOOL_SCHEMAS, "temperature": temperature}
        reply = chat_completion(url, api_key, payload, timeout, sleep)
        steps += 1
        try:
            message = reply["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            raise LiveError("unexpected response shape: no choices[0].message") from None
        calls = message.get("tool_calls") or []
        if not calls:
            text, truncated = message.get("content") or "", False
            break
        text = message.get("content") or text  # keep any commentary the model wrote alongside tool calls
        messages.append({"role": "assistant", "content": message.get("content"), "tool_calls": calls})
        for call in calls:
            function = call.get("function", {})
            name, args = function.get("name", ""), _parse_args(function.get("arguments"))
            recorded.append({"name": name, "args": args or {}})
            result = backend.call(name, args) if args is not None else {"error": "arguments were not a JSON object"}
            messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": json.dumps(result)})
    return {"id": case.id, "text": text, "tool_calls": recorded, "steps": steps, "truncated": truncated}


def run_live(
    cases: Iterable[Case],
    *,
    instructions: str,
    model: str,
    base_url: str,
    api_key: str,
    max_steps: int = 6,
    temperature: float = 0.0,
    timeout: float = 60.0,
    sleep: Sleeper = time.sleep,
    on_row: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> List[Dict[str, Any]]:
    """Run every case and return transcript rows. `on_row` fires after each case so callers can save progress."""
    url = _check_url(base_url)
    host = urlparse(base_url).hostname
    digest = hashlib.sha256(instructions.encode("utf-8")).hexdigest()
    rows = []
    for case in cases:
        row = run_case(
            case,
            instructions=instructions,
            model=model,
            url=url,
            api_key=api_key,
            max_steps=max_steps,
            temperature=temperature,
            timeout=timeout,
            sleep=sleep,
        )
        row["meta"] = {
            "model": model,
            "base_url_host": host,
            "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "instructions_sha256": digest,
            "steps": row.pop("steps"),
            "truncated": row.pop("truncated"),
        }
        rows.append(row)
        if on_row:
            on_row(row)
    return rows
