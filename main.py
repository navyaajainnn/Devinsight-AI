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
from summarize_pr import summarize_diff, SummarizeError

app = FastAPI()


class SummarizeRequest(BaseModel):
    pr_url: str


@app.post("/summarize")
def summarize(request: SummarizeRequest):
    """Fetch a PR's diff and return an AI-generated structured summary."""
    try:
        owner, repo, pr_number = parse_pr_url(request.pr_url)
        diff = fetch_pr_diff(owner, repo, pr_number)

    except PRFetchError as e:
        message = str(e)
        # Rate limit and "took too long" errors are transient - 429/504 signal that
        # to the frontend, vs. 400 for things that are the user's own input mistake.
        if "rate limit" in message.lower():
            raise HTTPException(status_code=429, detail=message)
        if "too long to respond" in message.lower():
            raise HTTPException(status_code=504, detail=message)
        raise HTTPException(status_code=400, detail=message)

    try:
        summary = summarize_diff(diff)

    except SummarizeError as e:
        message = str(e)
        if "rate limit" in message.lower():
            raise HTTPException(status_code=429, detail=message)
        raise HTTPException(status_code=502, detail=message)

    return summary


# Serve the frontend files (index.html, etc.) from a folder called "static"
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def serve_frontend():
    return FileResponse("static/index.html")