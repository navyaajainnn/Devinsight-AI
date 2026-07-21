"""
Step 2: Summarize a GitHub PR using Gemini.

Usage:
    python summarize_pr.py https://github.com/owner/repo/pull/123
"""

import json
import os
import sys

import google.generativeai as genai
from dotenv import load_dotenv

from fetch_pr_diff import parse_pr_url, fetch_pr_diff

load_dotenv()

genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
model = genai.GenerativeModel("gemini-flash-latest")

PROMPT_TEMPLATE = """You are a senior software engineer reviewing a pull request.

Here is the diff:

{diff}

Respond with ONLY a JSON object (no markdown fences, no extra text) with this exact shape:
{{
  "summary": "a 2-3 sentence plain-English summary of what this PR does",
  "risk_level": "low" | "medium" | "high",
  "key_changes": ["short bullet point", "short bullet point", "..."],
  "files_changed": <number of files touched, as an integer>
}}
"""


def summarize_diff(diff: str) -> dict:
    """Send a diff to Gemini and return the parsed structured summary."""

    max_chars = 15000
    if len(diff) > max_chars:
        diff = diff[:max_chars] + "\n\n... (diff truncated for length)"

    prompt = PROMPT_TEMPLATE.format(diff=diff)

    response = model.generate_content(prompt)

    raw_text = response.text.strip()

    if raw_text.startswith("```"):
        raw_text = raw_text.strip("`")
        raw_text = raw_text.replace("json", "", 1).strip()

    return json.loads(raw_text)


def main():
    if len(sys.argv) != 2:
        print("Usage: python summarize_pr.py <github_pr_url>")
        sys.exit(1)

    pr_url = sys.argv[1]

    try:
        owner, repo, pr_number = parse_pr_url(pr_url)
        print(f"Fetching PR #{pr_number} from {owner}/{repo}...")

        diff = fetch_pr_diff(owner, repo, pr_number)

        print("Sending diff to Gemini for summary...\n")
        summary = summarize_diff(diff)

        print("=" * 50)
        print(f"SUMMARY: {summary['summary']}")
        print(f"RISK LEVEL: {summary['risk_level']}")
        print(f"FILES CHANGED: {summary['files_changed']}")
        print("KEY CHANGES:")
        for change in summary["key_changes"]:
            print(f"  - {change}")
        print("=" * 50)

    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)
    except json.JSONDecodeError:
        print("Error: Gemini didn't return valid JSON. Try again, or check the prompt.")
        sys.exit(1)


if __name__ == "__main__":
    main()