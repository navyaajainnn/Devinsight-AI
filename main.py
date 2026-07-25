"""
FastAPI backend for DevInsight AI.

Run with:
    uvicorn main:app --reload

Then open http://127.0.0.1:8000 in your browser.
"""

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from fetch_pr_diff import parse_pr_url, fetch_pr_diff, PRFetchError
from summarize_pr import summarize_diff, generate_tests, SummarizeError
from duplicate_detector import parse_repo_url, find_duplicates, DuplicateDetectionError

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


# Serve the frontend files (index.html, etc.) from a folder called "static"
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def serve_frontend():
    return FileResponse("static/index.html")