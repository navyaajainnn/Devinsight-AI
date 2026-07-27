"""
Handle incoming GitHub webhooks.

When a PR is opened (or updated), GitHub calls our /webhook/github endpoint.
We verify the request genuinely came from GitHub, run our existing analysis
pipeline, and post the results back as a comment on the PR - fully automatic,
no one has to open the app or click a button.
"""

import hashlib
import hmac
import os

import requests
from dotenv import load_dotenv

from fetch_pr_diff import fetch_pr_diff, PRFetchError
from summarize_pr import summarize_diff, SummarizeError

load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET")

# Only react to these PR actions - ignore things like "closed" or "labeled"
# which don't need a fresh analysis.
RELEVANT_ACTIONS = {"opened", "reopened", "synchronize"}


class WebhookError(Exception):
    """Raised for webhook-level problems (bad config, invalid signature)."""
    pass


def verify_signature(payload_body: bytes, signature_header: str) -> bool:
    """
    GitHub signs every webhook payload using a shared secret only you and
    GitHub know. We recompute that same signature ourselves from the raw
    payload bytes and compare it to what GitHub sent. If they don't match,
    the request either wasn't really from GitHub or was altered in transit.
    """
    if not WEBHOOK_SECRET:
        raise WebhookError("GITHUB_WEBHOOK_SECRET is not set on the server.")

    if not signature_header:
        return False

    expected_signature = "sha256=" + hmac.new(
        WEBHOOK_SECRET.encode("utf-8"),
        payload_body,
        hashlib.sha256,
    ).hexdigest()

    # hmac.compare_digest (instead of a plain ==) avoids leaking timing
    # information that could theoretically help an attacker guess the secret.
    return hmac.compare_digest(expected_signature, signature_header)


def post_pr_comment(owner: str, repo: str, pr_number: int, body: str):
    """Post a comment on a PR. GitHub treats PR comments as issue comments under the hood."""
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{pr_number}/comments"
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"Bearer {GITHUB_TOKEN}",
    }
    response = requests.post(url, headers=headers, json={"body": body}, timeout=15)
    response.raise_for_status()


def format_comment(summary: dict) -> str:
    """Turn a summary dict into a nicely formatted Markdown PR comment."""
    risk_emoji = {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(summary["risk_level"], "⚪")

    lines = [
        "## 🤖 DevInsight AI Review",
        "",
        f"**Risk level:** {risk_emoji} {summary['risk_level']}  ",
        f"**Files changed:** {summary['files_changed']}",
        "",
        summary["summary"],
        "",
        "### Key changes",
    ]
    lines += [f"- {change}" for change in summary["key_changes"]]

    lines.append("")
    lines.append("### Potential issues")
    if summary["issues"]:
        for issue in summary["issues"]:
            lines.append(
                f"- **[{issue['severity'].upper()}]** {issue['description']} "
                f"_(confidence: {issue['confidence']})_"
            )
    else:
        lines.append("No issues found.")

    lines.append("")
    lines.append("_Automated review by DevInsight AI_")

    return "\n".join(lines)


def handle_pull_request_event(payload: dict):
    """
    Process a pull_request webhook event end-to-end: analyze the PR and post
    the result as a comment. Runs in the background - see main.py for why.
    """
    action = payload.get("action")
    if action not in RELEVANT_ACTIONS:
        return

    pr = payload["pull_request"]
    owner = payload["repository"]["owner"]["login"]
    repo = payload["repository"]["name"]
    pr_number = pr["number"]

    try:
        diff = fetch_pr_diff(owner, repo, pr_number)
        summary = summarize_diff(diff)
    except (PRFetchError, SummarizeError) as e:
        # Post the error as a comment too, rather than failing silently -
        # a visible failure is much easier to debug than a missing comment.
        try:
            post_pr_comment(owner, repo, pr_number, f"⚠️ DevInsight AI couldn't analyze this PR: {e}")
        except requests.exceptions.RequestException:
            pass  # if even posting the error fails, there's nothing more we can do
        return

    comment = format_comment(summary)

    try:
        post_pr_comment(owner, repo, pr_number, comment)
    except requests.exceptions.RequestException:
        pass  # comment posting failed (e.g. token permissions) - nothing more to do here