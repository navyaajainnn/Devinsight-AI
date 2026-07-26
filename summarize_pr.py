"""
Summarize a GitHub PR diff and detect potential bugs, using Gemini.
Hardened with error handling for rate limits, timeouts, and malformed responses.
"""

import json
import os
import re
from collections import Counter

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
            request_options={"timeout": 60},
        )
    except ResourceExhausted:
        raise SummarizeError(
            "Gemini's rate limit was hit. Please wait a minute and try again."
        )
    except GoogleAPICallError as e:
        if "deadline" in str(e).lower():
            raise SummarizeError(
                "The AI took too long to respond (this PR's diff may be large). Please try again."
            )
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


TEST_PROMPT_TEMPLATE = """You are a senior software engineer writing unit tests.

Here is a PR diff:

{diff}

The code in this diff is written in {language}. Write tests using {framework},
covering the main behavior of functions/methods that were added or modified,
including at least one reasonable edge case per function.

Respond with ONLY a JSON object (no markdown fences, no extra text) with this exact shape:
{{
  "language": "{language}",
  "test_code": "the full test code as a single string, with real newlines, written in {language} using {framework}",
  "functions_covered": ["function_name_1", "function_name_2", "..."],
  "notes": "1-2 sentences on any assumptions made or things a human should double-check"
}}

Rules:
- If the diff doesn't contain enough context to write meaningful tests (e.g. it's
  config, docs, or CSS changes only), return "test_code": "" and explain why in "notes".
- Write realistic, runnable test code, not pseudocode.
- Do not invent functions or behavior that isn't actually in the diff.
"""

TEST_REQUIRED_KEYS = {"language", "test_code", "functions_covered", "notes"}

# Maps a file extension found in the diff to (language name, test framework to use).
EXTENSION_TO_LANGUAGE = {
    ".py": ("Python", "pytest"),
    ".js": ("JavaScript", "Jest"),
    ".jsx": ("JavaScript (React)", "Jest with React Testing Library"),
    ".ts": ("TypeScript", "Jest"),
    ".tsx": ("TypeScript (React)", "Jest with React Testing Library"),
    ".java": ("Java", "JUnit 5"),
    ".go": ("Go", "Go's built-in testing package"),
    ".rb": ("Ruby", "RSpec"),
    ".php": ("PHP", "PHPUnit"),
    ".cs": ("C#", "xUnit"),
}

# Matches the file path on a "diff --git a/path/to/file.ext b/..." line, and
# captures just the extension (e.g. ".py") from it.
DIFF_GIT_LINE = re.compile(r"^diff --git a/.+?(\.\w+) b/", re.MULTILINE)


def detect_primary_language(diff: str) -> tuple:
    """
    Look at every changed file's extension in the diff and return the
    (language, framework) for whichever extension appears most often.
    Falls back to a generic instruction if nothing recognizable is found.
    """
    extensions = DIFF_GIT_LINE.findall(diff)

    if not extensions:
        return ("an appropriate language for this code", "an appropriate testing framework")

    most_common_ext, _ = Counter(extensions).most_common(1)[0]

    return EXTENSION_TO_LANGUAGE.get(
        most_common_ext,
        ("an appropriate language for this code", "an appropriate testing framework"),
    )


def generate_tests(diff: str) -> dict:
    """Send a diff to Gemini and return generated test code in the appropriate language."""

    truncated = len(diff) > MAX_DIFF_CHARS
    if truncated:
        diff = diff[:MAX_DIFF_CHARS] + "\n\n... (diff truncated for length)"

    language, framework = detect_primary_language(diff)

    prompt = TEST_PROMPT_TEMPLATE.format(diff=diff, language=language, framework=framework)

    try:
        response = model.generate_content(
            prompt,
            generation_config={"temperature": 0.2},
            request_options={"timeout": 60},
        )
    except ResourceExhausted:
        raise SummarizeError(
            "Gemini's rate limit was hit. Please wait a minute and try again."
        )
    except GoogleAPICallError as e:
        if "deadline" in str(e).lower():
            raise SummarizeError(
                "The AI took too long to respond (this PR's diff may be large). Please try again."
            )
        raise SummarizeError(f"The AI service returned an error: {e.message}")

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

    missing_keys = TEST_REQUIRED_KEYS - result.keys()
    if missing_keys:
        raise SummarizeError(
            f"The AI's response was missing expected fields: {', '.join(missing_keys)}. Please try again."
        )

    result["diff_truncated"] = truncated
    return result