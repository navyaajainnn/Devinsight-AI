"""
FastAPI backend for DevInsight AI.

Run with:
    uvicorn main:app --reload

Then open http://127.0.0.1:8000 in your browser.
"""

import json

from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from fetch_pr_diff import parse_pr_url, fetch_pr_diff, PRFetchError
from summarize_pr import summarize_diff, generate_tests, SummarizeError
from duplicate_detector import parse_repo_url, find_duplicates, DuplicateDetectionError
from architecture_analyzer import analyze_architecture, ArchitectureError
from webhook_handler import verify_signature, handle_pull_request_event, WebhookError

app = FastAPI()


class SummarizeRequest(BaseModel):
    pr_url: str


def _fetch_diff_or_raise(pr_url: str) -> str:
    """Shared helper: parse the URL and fetch the diff, converting errors to HTTPException."""
    try:
        owner, repo, pr_number = parse_pr_url(pr_url)
        return fetch_pr_diff(owner, repo, pr_number)
    except PRFetchError as e:
        message = str(e)
        if "rate limit" in message.lower():
            raise HTTPException(status_code=429, detail=message)
        if "too long to respond" in message.lower():
            raise HTTPException(status_code=504, detail=message)
        raise HTTPException(status_code=400, detail=message)


@app.post("/summarize")
def summarize(request: SummarizeRequest):
    """Fetch a PR's diff and return an AI-generated structured summary."""
    diff = _fetch_diff_or_raise(request.pr_url)

    try:
        summary = summarize_diff(diff)
    except SummarizeError as e:
        message = str(e)
        if "rate limit" in message.lower():
            raise HTTPException(status_code=429, detail=message)
        raise HTTPException(status_code=502, detail=message)

    return summary


@app.post("/generate-tests")
def generate_tests_endpoint(request: SummarizeRequest):
    """Fetch a PR's diff and return AI-generated pytest test code for it."""
    diff = _fetch_diff_or_raise(request.pr_url)

    try:
        tests = generate_tests(diff)
    except SummarizeError as e:
        message = str(e)
        if "rate limit" in message.lower():
            raise HTTPException(status_code=429, detail=message)
        raise HTTPException(status_code=502, detail=message)

    return tests


@app.post("/detect-duplicates")
def detect_duplicates_endpoint(request: SummarizeRequest):
    """
    Scan a repo's Python files for near-duplicate functions.
    Accepts a repo URL or a PR URL in the same field (only owner/repo is used).
    """
    try:
        owner, repo = parse_repo_url(request.pr_url)
        result = find_duplicates(owner, repo)
    except DuplicateDetectionError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return result


@app.post("/architecture")
def architecture_endpoint(request: SummarizeRequest):
    """
    Analyze a repo's architecture: extracts real imports/symbols via tree-sitter,
    then asks the AI to synthesize an overview and a Mermaid diagram from those facts.
    """
    try:
        owner, repo = parse_repo_url(request.pr_url)
        result = analyze_architecture(owner, repo)
    except ArchitectureError as e:
        message = str(e)
        if "rate limit" in message.lower():
            raise HTTPException(status_code=429, detail=message)
        raise HTTPException(status_code=400, detail=message)

    return result


@app.post("/webhook/github")
async def github_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    GitHub calls this endpoint automatically when a PR is opened/updated.
    We verify it's genuinely from GitHub, then hand off the actual analysis
    to a background task so we can respond immediately - GitHub expects a
    fast response and will consider the delivery failed (and retry) if we
    take too long, and our AI analysis can easily take longer than that.
    """
    payload_body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")

    try:
        valid = verify_signature(payload_body, signature)
    except WebhookError as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not valid:
        raise HTTPException(status_code=401, detail="Invalid webhook signature.")

    event_type = request.headers.get("X-GitHub-Event")
    payload = json.loads(payload_body)

    if event_type == "pull_request":
        background_tasks.add_task(handle_pull_request_event, payload)

    return {"status": "received"}


# Serve the frontend files (index.html, etc.) from a folder called "static"
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def serve_frontend():
    return FileResponse("static/index.html")