#!/usr/bin/env python3
"""
Generate a lightweight context graph and index for this repository.
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path

# Allow overriding the target repo via CONTEXT_REPO_ROOT so one canonical generator can service many repos.
REPO_ROOT = Path(os.environ.get("CONTEXT_REPO_ROOT") or Path(__file__).resolve().parents[2]).resolve()
REPO_NAME = REPO_ROOT.name
# Store context artifacts under .spectra/context to keep the repo root clean.
CONTEXT_DIR = REPO_ROOT / ".spectra" / "context"
GRAPH_PATH = CONTEXT_DIR / "context.graph.yaml"
INDEX_PATH = CONTEXT_DIR / "index.md"

TEXT_EXTS = {".md", ".yaml", ".yml", ".json", ".py", ".ps1", ".psm1", ".sh", ".sql", ".txt"}


def iso_mtime(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).isoformat()
    except FileNotFoundError:
        return datetime.now().isoformat()


def read_first_meaningful_line(path: Path) -> str:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("<!--"):
                continue
            return stripped.lstrip("#").strip()
    except Exception:
        return ""
    return ""


def summarize_journal(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="ignore")
    for line in text.splitlines()[1:10]:
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped
    return "Journal entry"


def find_workflow_name(path: Path) -> str:
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines()[:30]:
        match = re.match(r"\s*name\s*:\s*(.+)", line)
        if match:
            return match.group(1).strip()
    return path.name


def find_secret_refs(root: Path):
    patterns = ("credentialRef", "vault:")
    matches = []
    for ext in TEXT_EXTS:
        for file in root.rglob(f"*{ext}"):
            try:
                text = file.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if any(pat in text for pat in patterns):
                try:
                    matches.append(file.relative_to(root).as_posix())
                except ValueError:
                    matches.append(file.as_posix())
    return sorted(set(matches))


def classify_doc(path: Path) -> str:
    parts = {p.lower() for p in path.parts}
    if "decisions" in parts:
        return "decision"
    if "playbooks" in parts:
        return "playbook"
    if "chronicles" in parts:
        return "chronicle"
    if "journal" in parts:
        return "journal"
    if "docs" in parts:
        return "doc"
    return "doc"


def collect_docs(root: Path):
    # Targeted patterns to keep signal high.
    patterns = [
        "*.md",  # top-level docs like copilot instructions
        "docs/**/*.md",
        "playbooks/**/*.md",
        "decisions/**/*.md",
        "chronicles/**/*.md",
        "history/**/*.md",
        "context/*.md",
    ]
    docs = []
    for pattern in patterns:
        for path in root.glob(pattern):
            # Skip generated indices to avoid recursion.
            if path.name == "index.md" and "context" in path.parts:
                continue
            if path.is_dir():
                continue
            docs.append(path)
    return sorted(set(docs))


def ensure_files():
    CONTEXT_DIR.mkdir(parents=True, exist_ok=True)


def add_node(nodes, node):
    nodes.append(node)


def generate_graph():
    ensure_files()
    nodes = []
    now = datetime.now().isoformat()

    readme = REPO_ROOT / "README.md"
    if readme.exists():
        add_node(nodes, {
            "id": f"{REPO_NAME}:readme",
            "title": "Repository README",
            "type": "doc",
            "path": "README.md",
            "summary": read_first_meaningful_line(readme) or "Repository overview",
            "owner": f"{REPO_NAME} team",
            "freshness": iso_mtime(readme),
            "tags": ["overview"],
        })

    workflows_dir = REPO_ROOT / ".github" / "workflows"
    if workflows_dir.exists():
        for wf in sorted(workflows_dir.glob("*.y*ml")):
            add_node(nodes, {
                "id": f"{REPO_NAME}:workflow:{wf.stem}",
                "title": f"Workflow: {find_workflow_name(wf)}",
                "type": "workflow",
                "path": wf.relative_to(REPO_ROOT).as_posix(),
                "summary": "GitHub Actions workflow",
                "owner": f"{REPO_NAME} team",
                "freshness": iso_mtime(wf),
                "tags": ["workflow", "ci"],
            })

    for pattern, ntype, tag in [
        ("*.contract.yaml", "contract", "contract"),
        ("*.plan.yaml", "plan", "plan"),
        ("spectra.manifest.json", "manifest", "manifest"),
    ]:
        for file in REPO_ROOT.rglob(pattern):
            rel = file.relative_to(REPO_ROOT).as_posix()
            add_node(nodes, {
                "id": f"{REPO_NAME}:{ntype}:{file.stem}",
                "title": f"{ntype.capitalize()}: {file.name}",
                "type": ntype,
                "path": rel,
                "summary": f"{ntype.capitalize()} file",
                "owner": f"{REPO_NAME} team",
                "freshness": iso_mtime(file),
                "tags": [tag],
            })

    journal_dir = REPO_ROOT / "journal"
    if journal_dir.exists():
        journal_files = sorted(journal_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)[:5]
        for jf in journal_files:
            add_node(nodes, {
                "id": f"{REPO_NAME}:journal:{jf.stem}",
                "title": f"Journal: {jf.stem}",
                "type": "journal",
                "path": jf.relative_to(REPO_ROOT).as_posix(),
                "summary": summarize_journal(jf),
                "owner": f"{REPO_NAME} team",
                "freshness": iso_mtime(jf),
                "tags": ["journal"],
            })

    # Broader doc coverage (docs, playbooks, decisions, chronicles, history, top-level md)
    for doc in collect_docs(REPO_ROOT):
        doc_type = classify_doc(doc)
        rel = doc.relative_to(REPO_ROOT).as_posix()
        add_node(nodes, {
            "id": f"{REPO_NAME}:{doc_type}:{doc.stem}",
            "title": f"{doc_type.capitalize()}: {doc.name}",
            "type": doc_type,
            "path": rel,
            "summary": read_first_meaningful_line(doc) or f"{doc_type.capitalize()} file",
            "owner": f"{REPO_NAME} team",
            "freshness": iso_mtime(doc),
            "tags": [doc_type],
        })

    secret_refs = find_secret_refs(REPO_ROOT)
    if secret_refs:
        summary = ", ".join(secret_refs[:5])
        if len(secret_refs) > 5:
            summary += " ..."
        add_node(nodes, {
            "id": f"{REPO_NAME}:secrets-refs",
            "title": "Secret references",
            "type": "secrets-refs",
            "path": "",
            "summary": f"Files referencing credentialRef/vault: {summary}",
            "owner": f"{REPO_NAME} team",
            "freshness": now,
            "tags": ["secrets", "static-scan"],
        })

    graph = {
        "meta": {
            "repo": REPO_NAME,
            "generatedAt": now,
            "generatedBy": "context-generator v0.1",
        },
        "nodes": nodes,
    }
    return graph


def format_scalar(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    text = str(value)
    if re.search(r"[:#-]|^\s|\s$", text):
        escaped = text.replace('"', '\"')
        return f'"{escaped}"'
    return text


def dump_yaml(data, indent=0):
    lines = []
    space = " " * indent
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                lines.append(f"{space}{key}:")
                lines.extend(dump_yaml(value, indent + 2))
            else:
                lines.append(f"{space}{key}: {format_scalar(value)}")
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, (dict, list)):
                lines.append(f"{space}-")
                lines.extend(dump_yaml(item, indent + 2))
            else:
                lines.append(f"{space}- {format_scalar(item)}")
    else:
        lines.append(f"{space}{format_scalar(data)}")
    return lines


def write_graph(graph):
    lines = dump_yaml(graph)
    GRAPH_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_index(graph):
    lines = [
        f"# Context Index — {REPO_NAME}",
        "",
        f"Generated: {graph['meta']['generatedAt']}",
        "",
        "## Key items",
    ]
    for node in sorted(graph["nodes"], key=lambda n: (n.get("type", ""), n.get("title", ""))):
        loc = node.get("path", "")
        freshness = node.get("freshness", "")[:10]
        lines.append(f"- {node.get('title', '(untitled)')} (`{node.get('type', '')}`) — {node.get('summary', '').strip()} ({loc or 'n/a'}, updated {freshness})")
    lines.extend([
        "",
        "## How to regenerate",
        "- Run `python scripts/context/generate_context.py` from the repo root.",
    ])
    INDEX_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    graph = generate_graph()
    write_graph(graph)
    write_index(graph)
    print(f"Generated {GRAPH_PATH} and {INDEX_PATH} for {REPO_NAME}")


if __name__ == "__main__":
    main()
