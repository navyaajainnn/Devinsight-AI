"""
Analyze a repo's architecture.

Uses tree-sitter to extract REAL facts from each file (its imports, and its
top-level functions/classes) - this part is fully deterministic, no AI involved.
Only the final synthesis step (turning those facts into a plain-English
overview and a Mermaid diagram) uses the AI - and it's grounded in the
extracted facts, not guessing from file names alone.
"""

import json
import os

import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted, GoogleAPICallError
from dotenv import load_dotenv

# Reuse the GitHub-fetching and language-detection machinery already built
# for duplicate detection, instead of duplicating it.
from duplicate_detector import (
    _get_default_branch,
    _list_source_files,
    _fetch_file_content,
    LANGUAGE_CONFIGS,
    DuplicateDetectionError,
)

load_dotenv()

genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
model = genai.GenerativeModel("gemini-flash-latest")

MAX_FILES_FOR_ARCHITECTURE = 20  # keep the prompt a reasonable size

IMPORT_NODE_TYPES = {"import_statement", "import_from_statement"}
SYMBOL_NODE_TYPES = {"function_definition", "class_definition", "function_declaration", "class_declaration"}


class ArchitectureError(Exception):
    """Raised when we can't complete architecture analysis, with a user-friendly message."""
    pass


def _extract_structure(file_path: str, source_code: str, extension: str) -> dict:
    """Walk a file's syntax tree and pull out just its imports and top-level symbol names."""
    config = LANGUAGE_CONFIGS[extension]
    parser = config["parser"]

    tree = parser.parse(bytes(source_code, "utf8"))
    imports = []
    symbols = []

    def walk(node):
        if node.type in IMPORT_NODE_TYPES:
            # Grab the whole import line as raw text - simple and language-agnostic.
            line = node.text.decode("utf8").replace("\n", " ").strip()
            imports.append(line)
        elif node.type in SYMBOL_NODE_TYPES:
            name_node = node.child_by_field_name("name")
            if name_node:
                symbols.append(name_node.text.decode("utf8"))
        for child in node.children:
            walk(child)

    walk(tree.root_node)
    return {"file": file_path, "imports": imports, "symbols": symbols}


def _build_structure_summary(owner: str, repo: str, branch: str) -> list:
    """Fetch and analyze up to MAX_FILES_FOR_ARCHITECTURE source files in the repo."""
    source_files = _list_source_files(owner, repo, branch)[:MAX_FILES_FOR_ARCHITECTURE]

    if not source_files:
        supported_exts = ", ".join(LANGUAGE_CONFIGS.keys())
        raise ArchitectureError(
            f"No supported source files found in this repo. Supported: {supported_exts}"
        )

    structures = []
    for path in source_files:
        extension = "." + path.rsplit(".", 1)[-1]
        content = _fetch_file_content(owner, repo, path, branch)
        if content:
            structures.append(_extract_structure(path, content, extension))

    return structures


ARCHITECTURE_PROMPT_TEMPLATE = """You are a senior software architect. Below is a factual,
machine-extracted structural summary of a repository: each file's actual imports and the
actual top-level functions/classes it defines. This data is accurate - do not invent
files, imports, or symbols that aren't listed.

{structure_text}

Based ONLY on the facts above, respond with ONLY a JSON object (no markdown fences, no
extra text) with this exact shape:
{{
  "overview": "a 3-5 sentence plain-English explanation of how this codebase is organized and how the pieces relate",
  "components": [
    {{"name": "file or module name", "role": "one sentence on what this file/component is responsible for"}}
  ],
  "mermaid_diagram": "a Mermaid flowchart (graph TD syntax) showing the main files/modules as nodes and their import relationships as arrows, using short valid Mermaid node IDs"
}}

Rules:
- Base the diagram ONLY on the actual import relationships shown above.
- Keep the diagram to the most important 6-12 files/modules - skip trivial ones if there are many.
- Use simple, valid Mermaid syntax: graph TD, node IDs without spaces or special characters, labels in square brackets.
"""


def analyze_architecture(owner: str, repo: str) -> dict:
    """Produce a plain-English architecture overview and a Mermaid diagram for a repo."""
    try:
        branch = _get_default_branch(owner, repo)
    except DuplicateDetectionError as e:
        # Reuse the same "repo not found" style error from duplicate_detector.
        raise ArchitectureError(str(e))

    structures = _build_structure_summary(owner, repo, branch)

    # Turn the extracted facts into compact, readable text for the prompt.
    lines = []
    for s in structures:
        lines.append(f"FILE: {s['file']}")
        if s["imports"]:
            lines.append("  imports:")
            for imp in s["imports"]:
                lines.append(f"    {imp}")
        if s["symbols"]:
            lines.append(f"  defines: {', '.join(s['symbols'])}")
        lines.append("")

    structure_text = "\n".join(lines)

    prompt = ARCHITECTURE_PROMPT_TEMPLATE.format(structure_text=structure_text)

    try:
        response = model.generate_content(
            prompt,
            generation_config={"temperature": 0.2},
            request_options={"timeout": 30},
        )
    except ResourceExhausted:
        raise ArchitectureError("Gemini's rate limit was hit. Please wait a minute and try again.")
    except GoogleAPICallError as e:
        raise ArchitectureError(f"The AI service returned an error: {e.message}")

    try:
        raw_text = response.text.strip()
    except (ValueError, AttributeError):
        raise ArchitectureError("The AI didn't return a usable response. Try a different repo.")

    if raw_text.startswith("```"):
        raw_text = raw_text.strip("`")
        raw_text = raw_text.replace("json", "", 1).strip()

    try:
        result = json.loads(raw_text)
    except json.JSONDecodeError:
        raise ArchitectureError("The AI's response wasn't valid JSON. Please try again.")

    required_keys = {"overview", "components", "mermaid_diagram"}
    missing = required_keys - result.keys()
    if missing:
        raise ArchitectureError(f"The AI's response was missing fields: {', '.join(missing)}. Please try again.")

    result["files_analyzed"] = len(structures)
    return result