"""A deliberately small Gemini client used only for intent routing.

Cost discipline, in order of how much it saves:

  1. The local matcher in intents.py answers most messages for free; this client
     is only reached when the message is genuinely ambiguous.
  2. The prompt carries only the actions available to the CURRENT role, one line
     each - not the whole catalogue, not the schema, not the conversation.
  3. At most two prior turns are sent, and only their action names.
  4. Structured output is requested, so the reply is a short JSON object rather
     than prose. `maxOutputTokens` caps it hard.
  5. Identical normalised messages are served from a small cache.

A typical call is roughly 250-400 input tokens and under 60 output tokens.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Sequence

import httpx

from .intents import Action

DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-lite-latest")
API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"

# Output is capped hard: the model returns an action name, a couple of short
# parameters, and one sentence. It never returns data.
MAX_OUTPUT_TOKENS = int(os.environ.get("AEGIS_ASSISTANT_MAX_OUTPUT_TOKENS", "120"))
REQUEST_TIMEOUT = float(os.environ.get("AEGIS_ASSISTANT_TIMEOUT", "12"))


class AssistantUnavailable(RuntimeError):
    """Raised when routing through the model is impossible or not configured."""


def api_key() -> Optional[str]:
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")


def configured() -> bool:
    return bool(api_key())


def _system_prompt(actions: Sequence[Action], role: str) -> str:
    lines = [f"- {a.name}: {a.summary}" for a in actions]
    for a in actions:
        for key, desc in a.params.items():
            lines.append(f"    {a.name}.{key} = {desc}")
    catalogue = "\n".join(lines)
    return (
        "You route a clinical-safety console. Choose ONE action for the user's "
        "message and fill its parameters.\n"
        f"The user's role is: {role}.\n\n"
        f"Actions:\n{catalogue}\n\n"
        "Rules:\n"
        "- Never invent patient data, numbers, metrics or results. The console "
        "computes those itself.\n"
        "- 'reply' is one short sentence confirming what you are about to do. "
        "Never state a finding in it.\n"
        "- If nothing fits, use action 'none' and ask a brief clarifying question "
        "in 'reply'.\n"
    )


RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string"},
        "params": {
            "type": "object",
            "properties": {
                "family": {"type": "string"},
                "provenance": {"type": "string"},
                "patient": {"type": "string"},
                "filter": {"type": "string"},
                "role": {"type": "string"},
                "view": {"type": "string"},
                "topic": {"type": "string"},
            },
        },
        "reply": {"type": "string"},
    },
    "required": ["action", "reply"],
}


def route(message: str, role: str, actions: Sequence[Action],
          history: Optional[List[str]] = None,
          model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    """Ask the model to pick one action. Raises AssistantUnavailable on failure."""
    key = api_key()
    if not key:
        raise AssistantUnavailable(
            "No Gemini API key. Set GEMINI_API_KEY in the environment.")

    # Only the last couple of action names go back, never full transcripts.
    context = ""
    if history:
        context = "Recent actions: " + ", ".join(history[-2:]) + "\n"

    payload = {
        "systemInstruction": {"parts": [{"text": _system_prompt(actions, role)}]},
        "contents": [{"role": "user", "parts": [{"text": context + message.strip()[:400]}]}],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": MAX_OUTPUT_TOKENS,
            "responseMimeType": "application/json",
            "responseSchema": RESPONSE_SCHEMA,
        },
    }

    url = f"{API_ROOT}/{model}:generateContent"
    try:
        response = httpx.post(url, params={"key": key}, json=payload,
                              timeout=REQUEST_TIMEOUT)
    except httpx.HTTPError as exc:
        raise AssistantUnavailable(f"could not reach Gemini: {exc}") from exc

    if response.status_code == 404:
        raise AssistantUnavailable(
            f"model '{model}' not available for this key; set GEMINI_MODEL to one "
            "your key can use")
    if response.status_code in (401, 403):
        raise AssistantUnavailable("Gemini rejected the API key")
    if response.status_code == 429:
        raise AssistantUnavailable("Gemini rate limit reached; try again shortly")
    if response.status_code >= 400:
        raise AssistantUnavailable(
            f"Gemini returned {response.status_code}: {response.text[:160]}")

    body = response.json()
    usage = body.get("usageMetadata") or {}
    try:
        text = body["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as exc:
        raise AssistantUnavailable("Gemini returned no usable candidate") from exc

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        # Structured output should make this unreachable, but a truncated
        # response must degrade to a clarifying question rather than a crash.
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            raise AssistantUnavailable("Gemini returned unparseable output")
        parsed = json.loads(match.group(0))

    return {
        "action": parsed.get("action", "none"),
        "params": parsed.get("params") or {},
        "reply": parsed.get("reply", ""),
        "source": "model",
        "tokens": {
            "input": usage.get("promptTokenCount", 0),
            "output": usage.get("candidatesTokenCount", 0),
            "total": usage.get("totalTokenCount", 0),
        },
    }


__all__ = ["route", "configured", "api_key", "AssistantUnavailable",
           "DEFAULT_MODEL", "MAX_OUTPUT_TOKENS"]
