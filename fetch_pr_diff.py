"""
Step 1: Fetch a GitHub PR's diff.

Usage:
    python fetch_pr_diff.py https://github.com/owner/repo/pull/123
"""

import os
import re
import sys

import requests
from dotenv import load_dotenv

load_dotenv()  # reads variables from your .env file

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")


def parse_pr_url(url: str):
    """Turn a GitHub PR URL into (owner, repo, pr_number)."""
    match = re.match(
        r"https://github\.com/([^/]+)/([^/]+)/pull/(\d+)", url.strip()
    )
    if not match:
        raise ValueError(
            "That doesn't look like a GitHub PR URL. "
            "Expected format: https://github.com/owner/repo/pull/123"
        )
    owner, repo, pr_number = match.groups()
    return owner, repo, int(pr_number)


def fetch_pr_diff(owner: str, repo: str, pr_number: int) -> str:
    """Fetch the raw diff text for a PR using GitHub's REST API."""
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}"

    headers = {
        "Accept": "application/vnd.github.v3.diff",  # ask GitHub for diff format
    }
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    response = requests.get(url, headers=headers, timeout=15)

    if response.status_code == 404:
        raise ValueError("PR not found. Check the URL and that the repo is public (or your token has access).")
    if response.status_code == 403:
        raise ValueError("Rate limited or forbidden. Make sure GITHUB_TOKEN is set in your .env file.")
    response.raise_for_status()

    return response.text


def main():
    if len(sys.argv) != 2:
        print("Usage: python fetch_pr_diff.py <github_pr_url>")
        sys.exit(1)

    pr_url = sys.argv[1]

    try:
        owner, repo, pr_number = parse_pr_url(pr_url)
        print(f"Fetching PR #{pr_number} from {owner}/{repo}...\n")

        diff = fetch_pr_diff(owner, repo, pr_number)

        print(f"--- Diff ({len(diff)} characters) ---\n")
        print(diff[:2000])  # print first 2000 chars so it doesn't flood your terminal
        if len(diff) > 2000:
            print(f"\n... ({len(diff) - 2000} more characters not shown)")

    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()