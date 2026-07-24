"""
Fetch a GitHub PR's diff, with proper error handling.
"""

import os
import re

import requests
from dotenv import load_dotenv

load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")


class PRFetchError(Exception):
    """Raised when we can't fetch a PR diff, with a user-friendly message."""
    pass


def parse_pr_url(url: str):
    match = re.match(
        r"https://github\.com/([^/]+)/([^/]+)/pull/(\d+)", url.strip()
    )
    if not match:
        raise PRFetchError(
            "That doesn't look like a GitHub PR URL. "
            "Expected format: https://github.com/owner/repo/pull/123"
        )
    owner, repo, pr_number = match.groups()
    return owner, repo, int(pr_number)


def fetch_pr_diff(owner: str, repo: str, pr_number: int) -> str:
    """Fetch the raw diff text for a PR using GitHub's REST API."""
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}"

    headers = {"Accept": "application/vnd.github.v3.diff"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    try:
        response = requests.get(url, headers=headers, timeout=15)
    except requests.exceptions.Timeout:
        raise PRFetchError("GitHub took too long to respond. Please try again.")
    except requests.exceptions.ConnectionError:
        raise PRFetchError("Couldn't reach GitHub. Check your internet connection and try again.")

    if response.status_code == 404:
        raise PRFetchError(
            "PR not found. Check the URL, and make sure the repo is public "
            "(or that your GITHUB_TOKEN has access to it)."
        )

    if response.status_code == 403:
        # GitHub distinguishes rate limiting from other forbidden errors via this header.
        remaining = response.headers.get("X-RateLimit-Remaining")
        if remaining == "0":
            reset_hint = " Add a GITHUB_TOKEN if you haven't, or wait for your rate limit to reset."
            raise PRFetchError(f"GitHub rate limit exceeded.{reset_hint}")
        raise PRFetchError("Access forbidden. Your token may not have permission to view this repo.")

    if response.status_code == 401:
        raise PRFetchError("GitHub rejected the token. Check that GITHUB_TOKEN in your .env is valid.")

    response.raise_for_status()  # catches any other unexpected status code

    diff = response.text

    if not diff.strip():
        raise PRFetchError(
            "This PR has an empty diff (e.g. a merge commit or permissions-only change). "
            "Nothing to analyze."
        )

    return diff