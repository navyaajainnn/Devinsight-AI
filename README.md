# DevInsight AI

An AI-powered assistant that analyzes GitHub Pull Requests and generates concise, structured summaries using an LLM — built as a hands-on project to learn full-stack development and practical LLM integration.

## What it does

Paste a public GitHub PR URL, and DevInsight AI will:
- Fetch the PR's diff directly from GitHub
- Send it to an LLM with a structured prompt
- Return a clean summary: what changed, risk level, key changes, and files touched

## Tech Stack

- **Backend:** Python, FastAPI
- **Frontend:** HTML, CSS, vanilla JavaScript
- **AI:** Google Gemini API
- **Integration:** GitHub REST API

## Running locally

### 1. Clone the repository

```
git clone https://github.com/navyaajainnn/Devinsight-AI.git
cd Devinsight-AI
```

### 2. Create and activate a virtual environment

Windows:
```
python -m venv venv
venv\Scripts\activate
```

Mac/Linux:
```
python -m venv venv
source venv/bin/activate
```

### 3. Install dependencies

```
pip install -r requirements.txt
```

### 4. Add your API keys

Create a `.env` file in the project root with:

```
GITHUB_TOKEN=your_github_token_here
GOOGLE_API_KEY=your_google_api_key_here
```

### 5. Run the app

```
uvicorn main:app --reload
```

### 6. Open your browser

Go to `http://127.0.0.1:8000`

## Project structure

```
devinsight-ai/
├── static/
│   └── index.html       # Frontend UI
├── fetch_pr_diff.py      # Fetches PR diffs from GitHub's API
├── summarize_pr.py        # Sends diffs to Gemini, parses structured response
├── main.py                 # FastAPI backend and routes
├── requirements.txt
└── .gitignore
```

## Current Status

Actively in development — this is Phase 1 of a larger project.

**Working now:**
- PR fetching via GitHub API
- AI-generated PR summaries (summary, risk level, key changes, files changed)
- Simple web interface


"this is a test change for webhook"
**Planned next:**
- Bug/issue detection in diffs
- Duplicate logic detection
- Unit test generation
- Architecture explanation and sequence diagrams
