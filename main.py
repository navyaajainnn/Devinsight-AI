"""
FastAPI backend for DevInsight AI.

Run with:
    uvicorn main:app --reload

Then open http://127.0.0.1:8000 in your browser.
"""

import json

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from fetch_pr_diff import parse_pr_url, fetch_pr_diff
from summarize_pr import summarize_diff

app = FastAPI()


class SummarizeRequest(BaseModel):
    pr_url: str


@app.post("/summarize")
def summarize(request: SummarizeRequest):
    """Fetch a PR's diff and return an AI-generated structured summary."""
    try:
        owner, repo, pr_number = parse_pr_url(request.pr_url)
        diff = fetch_pr_diff(owner, repo, pr_number)
        summary = summarize_diff(diff)
        return summary

    except ValueError as e:
        # bad URL, PR not found, etc - the user's fault, so 400 "Bad Request"
        raise HTTPException(status_code=400, detail=str(e))

    except json.JSONDecodeError:
        # the AI didn't return valid JSON - our fault / a fluke, so 502 "Bad Gateway"
        raise HTTPException(
            status_code=502,
            detail="The AI response couldn't be parsed. Please try again.",
        )


# Serve the frontend files (index.html, etc.) from a folder called "static"
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def serve_frontend():
    return FileResponse("static/index.html")