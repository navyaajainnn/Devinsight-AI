"""
Detect duplicated / near-duplicate function logic across a repo's source files.

Supports Python, JavaScript, JSX, TypeScript, and TSX. Uses tree-sitter to parse
each file into functions, and Python's built-in difflib to compare them.
"""

import base64
import difflib
import os
import re
from collections import defaultdict
from itertools import combinations

import requests
import tree_sitter_javascript as tsjs
import tree_sitter_python as tspython
import tree_sitter_typescript as tsts
from tree_sitter import Language, Parser
from dotenv import load_dotenv

load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

MAX_FILES = 25               # cap files scanned, to stay fast and within GitHub's rate limits
MIN_FUNCTION_LINES = 3       # skip trivial one-liners, too noisy to be useful
SIMILARITY_THRESHOLD = 0.75  # 0.0-1.0 - lower catches more renamed-variable duplicates, but more false positives
BUCKET_SIZE = 5              # group functions into buckets of ~5 lines - only compare within/near the same bucket


class DuplicateDetectionError(Exception):
    """Raised when we can't complete duplicate detection, with a user-friendly message."""
    pass


# --- Language setup ---------------------------------------------------------
# Each entry says: which tree-sitter grammar to use for this file extension,
# which syntax-tree node types count as "a function" in that language, and
# which "group" it belongs to for comparison purposes (so e.g. a JS function
# can be compared against a TS function, but never against a Python one).

_PY_LANG = Language(tspython.language())
_JS_LANG = Language(tsjs.language())
_TS_LANG = Language(tsts.language_typescript())
_TSX_LANG = Language(tsts.language_tsx())

_JS_TS_FUNCTION_TYPES = {"function_declaration", "method_definition", "arrow_function"}

LANGUAGE_CONFIGS = {
    ".py":  {"parser": Parser(_PY_LANG),  "function_types": {"function_definition"}, "group": "python"},
    ".js":  {"parser": Parser(_JS_LANG),  "function_types": _JS_TS_FUNCTION_TYPES,   "group": "js_ts"},
    ".jsx": {"parser": Parser(_JS_LANG),  "function_types": _JS_TS_FUNCTION_TYPES,   "group": "js_ts"},
    ".ts":  {"parser": Parser(_TS_LANG),  "function_types": _JS_TS_FUNCTION_TYPES,   "group": "js_ts"},
    ".tsx": {"parser": Parser(_TSX_LANG), "function_types": _JS_TS_FUNCTION_TYPES,   "group": "js_ts"},
}


def parse_repo_url(url: str):
    """Extract (owner, repo) from either a plain repo URL or a PR URL."""
    match = re.match(r"https://github\.com/([^/]+)/([^/]+)", url.strip())
    if not match:
        raise DuplicateDetectionError("That doesn't look like a valid GitHub URL.")
    owner, repo = match.groups()
    repo = repo.rstrip("/")
    if repo.endswith(".git"):
        repo = repo[:-4]
    return owner, repo


def _github_headers():
    headers = {"Accept": "application/vnd.github.v3+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return headers


def _get_default_branch(owner: str, repo: str) -> str:
    url = f"https://api.github.com/repos/{owner}/{repo}"
    response = requests.get(url, headers=_github_headers(), timeout=15)
    if response.status_code == 404:
        raise DuplicateDetectionError("Repo not found. Check the URL and that it's public.")
    response.raise_for_status()
    return response.json()["default_branch"]


def _list_source_files(owner: str, repo: str, branch: str) -> list:
    """List every file whose extension we support, using GitHub's recursive tree API."""
    url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
    response = requests.get(url, headers=_github_headers(), timeout=15)
    response.raise_for_status()
    tree = response.json().get("tree", [])

    supported = []
    for item in tree:
        if item["type"] != "blob":
            continue
        for ext in LANGUAGE_CONFIGS:
            if item["path"].endswith(ext):
                supported.append(item["path"])
                break

    return supported[:MAX_FILES]


def _fetch_file_content(owner: str, repo: str, path: str, branch: str) -> str:
    """Fetch one file's text content. Returns empty string if it can't be fetched."""
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}?ref={branch}"
    response = requests.get(url, headers=_github_headers(), timeout=15)
    if response.status_code != 200:
        return ""
    data = response.json()
    if data.get("encoding") != "base64":
        return ""
    return base64.b64decode(data["content"]).decode("utf-8", errors="ignore")


def _get_function_name(node, parent) -> str:
    """
    Get a function's name. Most function types have a "name" field directly.
    Arrow functions (const foo = () => {...}) don't - the name actually
    belongs to the variable they were assigned to, so we look at the parent.
    """
    name_node = node.child_by_field_name("name")
    if name_node:
        return name_node.text.decode("utf8")

    if node.type == "arrow_function" and parent is not None and parent.type == "variable_declarator":
        parent_name_node = parent.child_by_field_name("name")
        if parent_name_node:
            return parent_name_node.text.decode("utf8")

    return "<anonymous>"


def _extract_functions(file_path: str, source_code: str, extension: str) -> list:
    """Use tree-sitter to walk a file's syntax tree and pull out every function."""
    config = LANGUAGE_CONFIGS[extension]
    parser = config["parser"]
    function_types = config["function_types"]
    group = config["group"]

    tree = parser.parse(bytes(source_code, "utf8"))
    functions = []

    def walk(node, parent=None):
        if node.type in function_types:
            name = _get_function_name(node, parent)
            body_text = node.text.decode("utf8")
            line_count = body_text.count("\n") + 1
            if line_count >= MIN_FUNCTION_LINES:
                functions.append({
                    "file": file_path,
                    "name": name,
                    "code": body_text,
                    "start_line": node.start_point[0] + 1,
                    "group": group,
                })
        for child in node.children:
            walk(child, node)

    walk(tree.root_node)
    return functions


def find_duplicates(owner: str, repo: str) -> dict:
    """Fetch a repo's source files, extract every function, and find near-duplicate pairs."""
    branch = _get_default_branch(owner, repo)
    source_files = _list_source_files(owner, repo, branch)

    if not source_files:
        supported_exts = ", ".join(LANGUAGE_CONFIGS.keys())
        raise DuplicateDetectionError(
            f"No supported source files found in this repo. Supported: {supported_exts}"
        )

    all_functions = []
    for path in source_files:
        extension = "." + path.rsplit(".", 1)[-1]
        content = _fetch_file_content(owner, repo, path, branch)
        if content:
            all_functions.extend(_extract_functions(path, content, extension))

    # Group functions by (language group, size bucket) - we only ever compare
    # functions within the same language family AND roughly the same size.
    # This keeps comparisons fast and avoids nonsensical cross-language matches.
    buckets = defaultdict(list)
    for func in all_functions:
        line_count = func["code"].count("\n") + 1
        size_bucket = line_count // BUCKET_SIZE
        buckets[(func["group"], size_bucket)].append(func)

    duplicates = []
    seen_pairs = set()

    for (group, size_bucket), funcs_in_bucket in buckets.items():
        neighboring = buckets.get((group, size_bucket + 1), [])
        candidates = funcs_in_bucket + neighboring

        for func_a, func_b in combinations(candidates, 2):
            id_a = (func_a["file"], func_a["name"], func_a["start_line"])
            id_b = (func_b["file"], func_b["name"], func_b["start_line"])
            pair_id = frozenset([id_a, id_b])

            if pair_id in seen_pairs:
                continue
            seen_pairs.add(pair_id)

            if func_a["file"] == func_b["file"] and func_a["name"] == func_b["name"]:
                continue

            similarity = difflib.SequenceMatcher(None, func_a["code"], func_b["code"]).ratio()

            if similarity >= SIMILARITY_THRESHOLD:
                duplicates.append({
                    "function_a": {"file": func_a["file"], "name": func_a["name"], "line": func_a["start_line"]},
                    "function_b": {"file": func_b["file"], "name": func_b["name"], "line": func_b["start_line"]},
                    "similarity": round(similarity, 2),
                })

    duplicates.sort(key=lambda d: d["similarity"], reverse=True)

    return {
        "files_scanned": len(source_files),
        "functions_analyzed": len(all_functions),
        "duplicates": duplicates,
    }