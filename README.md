# DevInsight AI

An AI-powered code review assistant that analyzes GitHub Pull Requests and repositories — combining LLM-based analysis with real static analysis (via tree-sitter) to summarize PRs, catch bugs, generate tests, detect duplicate code, and map out architecture. Can run automatically on every new PR via a GitHub webhook.

<img src="images\main_page.png" style="width: 100%"/>

## What it does

Paste a public GitHub PR or repo URL, and DevInsight AI will:

- **Summarize & flag risk** — plain-English PR summary, risk level, and concrete bug findings (not style nitpicks), with confidence scores
- **Generate tests** — detects the PR's language automatically and writes real, runnable tests (pytest, Jest, JUnit, and more)
- **Find duplicate logic** — parses the whole repo with tree-sitter and flags near-duplicate functions across files and languages, using deterministic text similarity (no AI cost)
- **Map architecture** — extracts real imports and symbols via tree-sitter, then synthesizes a plain-English overview and a rendered Mermaid diagram grounded in those facts
- **Auto-review PRs** — connect a GitHub webhook and DevInsight AI comments on every new PR automatically, no manual step required


<img src="images\summarise.png" style="width: 100%"/>
<img src="images\duplication.png" style="width: 100%"/>
<img src="images\architecture.png" style="width: 100%"/>
<img src="images\arch_diag.png" style="width: 100%"/>

## Tech Stack

- **Backend:** Python, FastAPI
- **Frontend:** HTML, CSS, vanilla JavaScript, Mermaid.js
- **AI:** Google Gemini API
- **Static analysis:** tree-sitter (Python, JavaScript, JSX, TypeScript, TSX)
- **Integration:** GitHub REST API, GitHub Webhooks (HMAC-SHA256 verified)
- **Deployment:** Render

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
GITHUB_WEBHOOK_SECRET=your_webhook_secret_here
```

`GITHUB_WEBHOOK_SECRET` is only needed if you're setting up automatic PR reviews (see below) — the app runs fine without it for manual use.

### 5. Run the app

```
uvicorn main:app --reload
```

### 6. Open your browser

Go to `http://127.0.0.1:8000`

## Setting up automatic PR reviews (optional)

To have DevInsight AI comment automatically on every new PR:

1. Generate a random secret: `python -c "import secrets; print(secrets.token_hex(32))"`
2. Add it as `GITHUB_WEBHOOK_SECRET` in your `.env` and in your deployment platform's environment variables
3. Make sure your `GITHUB_TOKEN` has **Pull requests: Read and write** permission (needed to post comments, not just read diffs)
4. On the target repo: Settings → Webhooks → Add webhook
   - Payload URL: `https://your-deployed-url/webhook/github`
   - Content type: `application/json`
   - Secret: the same value from step 1
   - Events: only **Pull requests**
5. Open a PR on that repo — DevInsight AI should comment within seconds

## Project structure

```
devinsight-ai/
├── static/
│   └── index.html            # Frontend UI (landing page + interactive tool)
├── fetch_pr_diff.py           # Fetches PR diffs from GitHub's API
├── summarize_pr.py             # Summary, risk scoring, bug detection, test generation (Gemini)
├── duplicate_detector.py        # Tree-sitter parsing + difflib similarity for duplicate detection
├── architecture_analyzer.py      # Tree-sitter fact extraction + AI-synthesized architecture diagrams
├── webhook_handler.py             # GitHub webhook signature verification + auto-comment posting
├── main.py                         # FastAPI backend and all routes
├── requirements.txt
└── .gitignore
```

## Current Status

All core features are live and working:

- ✅ PR summarization with risk scoring and bug detection
- ✅ Language-aware automated test generation
- ✅ Multi-language duplicate logic detection (Python, JS, JSX, TS, TSX)
- ✅ Architecture analysis with rendered Mermaid diagrams
- ✅ Automatic PR review via GitHub webhook
- ✅ Deployed live on Render with a custom UI

**Possible future directions:**
- API documentation generation
- Technical debt scoring across a full repo
- Support for additional languages (Java, Go, Ruby)
