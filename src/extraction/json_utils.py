"""Robust JSON extraction from LLM responses."""
import json
import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _find_balanced(text: str, open_char: str, close_char: str, start: int) -> Optional[str]:
    """Find balanced brackets starting at `start`; return the slice or None."""
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == '\\' and in_string:
            escape = True
            continue
        if ch == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == open_char:
            depth += 1
        elif ch == close_char:
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def _strip_fences(text: str) -> str:
    """Remove markdown code fences and XML wrappers around JSON content."""
    # Strip markdown fences (```json ... ``` or ``` ... ```)
    text = re.sub(r'```(?:json)?\s*', '', text)
    text = re.sub(r'```', '', text)
    # Strip outermost XML/HTML-style tags that some models wrap around JSON,
    # e.g. <entities>[...]</entities> or <response>{...}</response>
    # Repeat in case of nested wrappers.
    for _ in range(5):
        stripped = re.sub(r'^\s*<[^>]+>\s*([\s\S]*?)\s*</[^>]+>\s*$', r'\1', text.strip())
        if stripped == text.strip():
            break
        text = stripped
    return text


def extract_json(response: str, prefer: str = "array") -> Any:
    """
    Extract and parse JSON from an LLM response.

    Tries to find the first JSON array or object by bracket counting rather
    than greedy regex. Falls back to repairing and retrying.

    Args:
        response: Raw LLM response string.
        prefer: "array" to look for [...] first, "object" for {...} first.

    Returns:
        Parsed Python object, or None on failure.
    """
    cleaned = _strip_fences(response).strip()

    # Build search order
    pairs = [('[', ']'), ('{', '}')]
    if prefer == "object":
        pairs = [('{', '}'), ('[', ']')]

    for open_ch, close_ch in pairs:
        start = cleaned.find(open_ch)
        if start == -1:
            continue
        span = _find_balanced(cleaned, open_ch, close_ch, start)
        if span is None:
            # Array/object is truncated — try partial recovery for arrays.
            if open_ch == '[':
                recovered = _recover_partial_array(cleaned, start)
                if recovered is not None:
                    return recovered
            continue
        try:
            return json.loads(span)
        except json.JSONDecodeError:
            # Attempt basic repairs: trailing commas, single quotes
            repaired = re.sub(r',\s*([}\]])', r'\1', span)
            repaired = repaired.replace("'", '"')
            try:
                return json.loads(repaired)
            except json.JSONDecodeError:
                continue

    logger.warning("Could not extract JSON from LLM response. Raw response:\n%s", response[:1000])
    return None


def _recover_partial_array(text: str, array_start: int) -> Optional[Any]:
    """
    When a JSON array is truncated (no closing ]), extract every complete
    {...} object inside it and return them as a list.
    """
    objects = []
    pos = array_start + 1  # skip the opening [
    while pos < len(text):
        # Find the next {
        obj_start = text.find('{', pos)
        if obj_start == -1:
            break
        span = _find_balanced(text, '{', '}', obj_start)
        if span is None:
            break  # This object is also truncated — stop here
        try:
            obj = json.loads(span)
            objects.append(obj)
        except json.JSONDecodeError:
            pass
        pos = obj_start + len(span)

    if objects:
        logger.warning(
            "JSON array was truncated; recovered %d complete object(s). "
            "Consider raising max_new_tokens.", len(objects)
        )
        return objects
    return None
