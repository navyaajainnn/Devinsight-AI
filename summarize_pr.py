"""
Summarize a GitHub PR diff and detect potential bugs, using Gemini.
Hardened with error handling for rate limits, timeouts, and malformed responses.
"""

import json
import os

import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted, GoogleAPICallError
from dotenv import load_dotenv

load_dotenv()

genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
model = genai.GenerativeModel("gemini-flash-latest")

MAX_DIFF_CHARS = 15000

REQUIRED_KEYS = {"summary", "risk_level", "key_changes", "files_changed", "issues"}

PROMPT_TEMPLATE = """You are a senior software engineer reviewing a pull request.

Here is the diff:

{diff}

Respond with ONLY a JSON object (no markdown fences, no extra text) with this exact shape:
{{
  "summary": "a 2-3 sentence plain-English summary of what this PR does",
  "risk_level": "low" | "medium" | "high",
  "key_changes": ["short bullet point", "short bullet point", "..."],
  "files_changed": <number of files touched, as an integer>,
  "issues": [
    {{
      "severity": "low" | "medium" | "high",
      "description": "a specific, concrete bug or risk you found, one sentence",
      "confidence": "low" | "medium" | "high"
    }}
  ]
}}

Rules for the "issues" list:
- ONLY include real functional bugs, edge cases, or risks.
- Do NOT include style, naming, formatting, or personal-preference comments.
- If you find no real issues, return an empty list: "issues": []
"""


class SummarizeError(Exception):
    """Raised when we can't produce a summary, with a user-friendly message."""
    pass


def summarize_diff(diff: str) -> dict:
    """Send a diff to Gemini and return the parsed structured summary + bug findings."""

    truncated = len(diff) > MAX_DIFF_CHARS
    if truncated:
        diff = diff[:MAX_DIFF_CHARS] + "\n\n... (diff truncated for length)"

    prompt = PROMPT_TEMPLATE.format(diff=diff)

    try:
        response = model.generate_content(
            prompt,
            generation_config={"temperature": 0.2},
            request_options={"timeout": 30},
        )
    except ResourceExhausted:
        raise SummarizeError(
            "Gemini's rate limit was hit. Please wait a minute and try again."
        )
    except GoogleAPICallError as e:
        raise SummarizeError(f"The AI service returned an error: {e.message}")

    # response.text raises if the model's response was blocked by safety filters
    # or otherwise came back empty - handle that explicitly instead of crashing.
    try:
        raw_text = response.text.strip()
    except (ValueError, AttributeError):
        raise SummarizeError(
            "The AI didn't return a usable response (it may have been blocked). Try a different PR."
        )

    if raw_text.startswith("```"):
        raw_text = raw_text.strip("`")
        raw_text = raw_text.replace("json", "", 1).strip()

    try:
        result = json.loads(raw_text)
    except json.JSONDecodeError:
        raise SummarizeError("The AI's response wasn't valid JSON. Please try again.")

    missing_keys = REQUIRED_KEYS - result.keys()
    if missing_keys:
        raise SummarizeError(
            f"The AI's response was missing expected fields: {', '.join(missing_keys)}. Please try again."
        )

    result["diff_truncated"] = truncated
    return result