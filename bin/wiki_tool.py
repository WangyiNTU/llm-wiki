#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import hashlib
import json
import mimetypes
import re
import subprocess
import sys
from pathlib import Path
from string import Template
from typing import Any


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text())


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def sha256_text(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def is_markdown_path(path: Path) -> bool:
    return path.suffix.lower() in {".md", ".markdown"}


def companion_markdown_path(path: Path) -> Path:
    return Path(f"{path.as_posix()}.md")


def tokenize(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]{3,}", text.lower())}


def slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "new-topic"


def humanize_slug(slug: str) -> str:
    return slug.replace("-", " ").strip().title() or "New Topic"


def iso_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    raw = text[4:end]
    body = text[end + 5 :]
    data: dict[str, str] = {}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip().strip('"')
    return data, body


def parse_heading_section(body: str, heading: str) -> str:
    match = re.search(rf"^## {re.escape(heading)}\s*$", body, flags=re.MULTILINE)
    if not match:
        return ""
    start = match.end()
    next_heading = re.search(r"^##\s+", body[start:], flags=re.MULTILINE)
    return body[start : start + next_heading.start()] if next_heading else body[start:]


def parse_sources_section(topic_file: Path, body: str) -> list[str]:
    section = parse_heading_section(body, "Sources")
    if not section:
        return []
    paths: list[str] = []
    for line in section.splitlines():
        line = line.strip()
        if not line.startswith("- "):
            continue
        target = None
        link = re.search(r"\[[^\]]+\]\(([^)]+)\)", line)
        if link:
            target = link.group(1).strip()
        elif "`" in line:
            ticks = re.findall(r"`([^`]+)`", line)
            if ticks:
                target = ticks[0].strip()
        else:
            target = line[2:].strip()
        if not target:
            continue
        resolved = (topic_file.parent / target).resolve()
        try:
            rel = resolved.relative_to(topic_file.parent.parent)
            paths.append(rel.as_posix())
        except ValueError:
            paths.append(target)
    return sorted(set(paths))


def parse_related_topics(body: str) -> list[str]:
    section = parse_heading_section(body, "Related Topics")
    if not section:
        return []
    related = []
    for path in re.findall(r"\(([^)]+\.md)\)", section):
        related.append(Path(path).stem)
    for slug in re.findall(r"`([a-z0-9-]+)`", section):
        related.append(slug)
    return sorted(set(related))


def resolve_wiki_root(start: Path, explicit: str | None) -> Path:
    if explicit:
        candidate = Path(explicit)
        return candidate.resolve() if candidate.is_absolute() else (start / candidate).resolve()
    for path in [start, *start.parents]:
        candidate = path / "wiki"
        if (candidate / ".wiki-config.json").exists():
            return candidate.resolve()
    raise SystemExit("Could not locate wiki root. Pass --wiki-root.")


class Wiki:
    def __init__(self, wiki_root: Path):
        self.wiki_root = wiki_root
        self.repo_root = wiki_root.parent
        self.config_path = wiki_root / ".wiki-config.json"
        self.config = read_json(self.config_path, {})
        if not self.config:
            raise SystemExit(f"Missing config: {self.config_path}")
        self.state_path = self.repo_root / self.config.get("state_file", "wiki/.wiki-state.json")
        self.index_path = self.repo_root / self.config.get("index_file", "wiki/INDEX.md")
        self.log_path = self.repo_root / self.config.get("log_file", "wiki/log.md")
        self.schema_path = self.repo_root / self.config.get("schema_file", "wiki/schema.md")
        self.topics_dir = self.repo_root / self.config.get("topics_dir", "wiki/topics")
        self.sources = self.config.get("sources", [])

    def source_files(self) -> list[Path]:
        files: list[Path] = []
        for entry in self.sources:
            root = self.repo_root / entry["path"]
            include = entry.get("include", ["**/*.md"])
            exclude = entry.get("exclude", [])
            if not root.exists():
                continue
            for pattern in include:
                for path in root.glob(pattern):
                    if not path.is_file():
                        continue
                    rel = path.relative_to(self.repo_root).as_posix()
                    if any(fnmatch.fnmatch(rel, ex) or fnmatch.fnmatch(path.name, ex) for ex in exclude):
                        continue
                    files.append(path)
        return sorted(set(files))

    def raw_source_candidates(self) -> list[Path]:
        files: list[Path] = []
        for entry in self.sources:
            root = self.repo_root / entry["path"]
            exclude = entry.get("exclude", [])
            if not root.exists():
                continue
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                rel = path.relative_to(self.repo_root).as_posix()
                if any(fnmatch.fnmatch(rel, ex) or fnmatch.fnmatch(path.name, ex) for ex in exclude):
                    continue
                files.append(path)
        return sorted(set(files))

    def topic_files(self) -> list[Path]:
        if not self.topics_dir.exists():
            return []
        return sorted(
            path for path in self.topics_dir.glob("*.md") if path.is_file() and path.name != "README.md"
        )

    def read_topics(self) -> list[dict[str, Any]]:
        topics: list[dict[str, Any]] = []
        for topic_file in self.topic_files():
            text = topic_file.read_text()
            frontmatter, body = parse_frontmatter(text)
            topics.append(
                {
                    "path": topic_file.relative_to(self.repo_root).as_posix(),
                    "title": frontmatter.get("title") or topic_file.stem.replace("-", " ").title(),
                    "slug": frontmatter.get("slug") or topic_file.stem,
                    "updated": frontmatter.get("updated", ""),
                    "status": frontmatter.get("status", "active"),
                    "sources": parse_sources_section(topic_file, body),
                    "related_topics": parse_related_topics(body),
                }
            )
        return topics

    def schema_topics(self) -> list[str]:
        if not self.schema_path.exists():
            return []
        text = self.schema_path.read_text()
        section = parse_heading_section(text, "Canonical Topics")
        return sorted(set(re.findall(r"^- `([a-z0-9-]+)`", section, flags=re.MULTILINE)))

    def topic_path(self, slug: str) -> Path:
        return self.topics_dir / f"{slug}.md"

    def topic_template_text(self) -> str:
        template_path = self.repo_root / "skills/llm-wiki/templates/topic-template.md"
        if template_path.exists():
            return template_path.read_text()
        raise SystemExit(f"Missing topic template: {template_path}")

    def compute_snapshot(self) -> dict[str, Any]:
        sources = []
        derived_sources = []
        for source in self.source_files():
            rel = source.relative_to(self.repo_root).as_posix()
            sources.append(
                {
                    "path": rel,
                    "sha256": sha256_text(source),
                    "mtime": dt.datetime.fromtimestamp(source.stat().st_mtime, dt.timezone.utc)
                    .replace(microsecond=0)
                    .isoformat(),
                }
            )
        for raw in self.raw_source_candidates():
            if is_markdown_path(raw):
                continue
            rel = raw.relative_to(self.repo_root).as_posix()
            derived = companion_markdown_path(raw)
            derived_rel = derived.relative_to(self.repo_root).as_posix() if derived.exists() else None
            derived_sources.append(
                {
                    "raw_path": rel,
                    "derived_path": derived_rel,
                    "kind": mimetypes.guess_type(raw.name)[0] or raw.suffix.lower().lstrip('.') or 'binary',
                }
            )
        topics = self.read_topics()
        mapped_sources = {src for topic in topics for src in topic["sources"]}
        return {
            "version": 2,
            "wiki_root": self.wiki_root.relative_to(self.repo_root).as_posix(),
            "generated_at": now_iso(),
            "sources": sources,
            "derived_sources": derived_sources,
            "topics": topics,
            "unmapped_sources": sorted(entry["path"] for entry in sources if entry["path"] not in mapped_sources),
        }

    def update_state(self, state: dict[str, Any], preserve_reindex: bool = True) -> dict[str, Any]:
        previous = read_json(self.state_path, {})
        previous_sources = {entry["path"]: entry["sha256"] for entry in previous.get("sources", [])}
        current_paths = {entry["path"] for entry in state["sources"]}
        previous_paths = set(previous_sources)
        state["new_sources"] = sorted(current_paths - previous_paths)
        state["changed_sources"] = sorted(
            entry["path"]
            for entry in state["sources"]
            if entry["path"] in previous_paths and previous_sources.get(entry["path"]) != entry["sha256"]
        )
        state["deleted_sources"] = sorted(previous_paths - current_paths)
        state["last_ingest"] = now_iso()
        state["last_batch"] = {
            "timestamp": state["last_ingest"],
            "new_sources": state["new_sources"],
            "changed_sources": state["changed_sources"],
            "deleted_sources": state["deleted_sources"],
        }
        history = list(previous.get("batch_history", []))
        if state["new_sources"] or state["changed_sources"] or state["deleted_sources"]:
            history.append(state["last_batch"])
        state["batch_history"] = history[-20:]
        if preserve_reindex and previous.get("last_reindex"):
            state["last_reindex"] = previous["last_reindex"]
        write_json(self.state_path, state)
        return state

    def append_log(self, event: str, note: str | None) -> None:
        header = "# Wiki Activity Log\n"
        existing = self.log_path.read_text() if self.log_path.exists() else header
        if not existing.startswith("# Wiki Activity Log"):
            existing = header + "\n" + existing.lstrip()
        block = [f"## {now_iso()}", f"- Event: `{event}`"]
        if note:
            block.append(f"- Note: {note}")
        self.log_path.write_text(existing.rstrip() + "\n\n" + "\n".join(block) + "\n")

    def render_index(self, state: dict[str, Any]) -> str:
        topics = state["topics"]
        lines = [
            f"# {self.config.get('name', 'LLM Wiki')}",
            "",
            f"Last indexed: {state['generated_at']}",
            f"Mode: `{self.config.get('mode', 'staging')}`",
            f"Topics: {len(topics)} | Sources: {len(state['sources'])} | Unmapped sources: {len(state['unmapped_sources'])}",
            "",
            "## How To Use",
            "",
            "- Start with the most relevant topic page in `wiki/topics/`.",
            "- Trust `high` coverage sections first, then `medium`, then raw sources.",
            "- Use `python3 skills/llm-wiki/bin/wiki_tool.py query \"...\"` to shortlist relevant topics.",
            "- Add new raw material to `wiki/sources/` and keep those files immutable.",
            "",
            "## Topics",
            "",
        ]
        if topics:
            lines.extend(
                [
                    "| Topic | Updated | Sources | Status |",
                    "| --- | --- | ---: | --- |",
                ]
            )
            for topic in topics:
                lines.append(
                    f"| [{topic['title']}](./topics/{topic['slug']}.md) | {topic['updated'] or '-'} | {len(topic['sources'])} | {topic['status']} |"
                )
        else:
            lines.append("*No topics yet. Ingest sources, then create the first topic pages.*")
        lines.extend(["", "## Unmapped Sources", ""])
        if state["unmapped_sources"]:
            for path in state["unmapped_sources"]:
                lines.append(f"- [{path}](./{Path(path).relative_to('wiki').as_posix()})")
        else:
            lines.append("*None.*")
        lines.extend(
            [
                "",
                "## Files",
                "",
                "- [Schema](./schema.md)",
                "- [Log](./log.md)",
                "- [State](./.wiki-state.json)",
            ]
        )
        return "\n".join(lines) + "\n"


def build_suggested_actions(wiki: Wiki, state: dict[str, Any], lint: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    lint = lint or lint_report(wiki)
    actions: list[dict[str, Any]] = []
    last_ingest = iso_date(state.get("last_ingest"))
    last_reindex = iso_date(state.get("last_reindex"))

    if not state.get("sources"):
        actions.append(
            {
                "kind": "sync",
                "priority": "high",
                "reason": "No raw sources are indexed yet.",
                "command": None,
            }
        )
        return actions

    if state.get("new_sources") or state.get("changed_sources") or state.get("deleted_sources"):
        actions.append(
            {
                "kind": "update",
                "priority": "high",
                "reason": "Recent source changes need topic review and possible synthesis updates.",
                "command": "python3 skills/llm-wiki/bin/wiki_tool.py ingest --json",
            }
        )

    if lint.get("schema_missing_files"):
        actions.append(
            {
                "kind": "update",
                "priority": "high",
                "reason": f"Canonical schema topics do not have topic files yet: {', '.join(lint['schema_missing_files'][:5])}",
                "command": "python3 skills/llm-wiki/bin/wiki_tool.py bootstrap-topic \"Topic Title\" --source wiki/sources/...",
            }
        )

    if lint.get("stale_topics"):
        stale = ", ".join(item["topic"] for item in lint["stale_topics"][:5])
        actions.append(
            {
                "kind": "update",
                "priority": "high",
                "reason": f"Some topic pages are older than their sources: {stale}",
                "command": "python3 skills/llm-wiki/bin/wiki_tool.py reindex --event compile --note \"refresh updated topics\"",
            }
        )

    if state.get("unmapped_sources"):
        unmapped = ", ".join(state["unmapped_sources"][:3])
        actions.append(
            {
                "kind": "update",
                "priority": "medium",
                "reason": f"Unmapped sources should be folded into existing topics or new stable topics: {unmapped}",
                "command": None,
            }
        )

    if lint.get("orphan_sources") or lint.get("topics_without_sources"):
        actions.append(
            {
                "kind": "update",
                "priority": "medium",
                "reason": "Some topic pages have broken or missing source attribution.",
                "command": None,
            }
        )

    if last_ingest and (not last_reindex or last_reindex < last_ingest):
        actions.append(
            {
                "kind": "sync",
                "priority": "medium",
                "reason": "State was ingested more recently than the index; reindex after any topic edits.",
                "command": "python3 skills/llm-wiki/bin/wiki_tool.py reindex --event compile --note \"refresh index\"",
            }
        )

    if not actions:
        actions.append(
            {
                "kind": "query",
                "priority": "low",
                "reason": "Wiki state looks healthy; answer questions from compiled topics first.",
                "command": "python3 skills/llm-wiki/bin/wiki_tool.py query \"your question\"",
            }
        )
    return actions


def summarize_status(wiki: Wiki, state: dict[str, Any], lint: dict[str, Any] | None = None) -> dict[str, Any]:
    lint = lint or lint_report(wiki)
    actions = build_suggested_actions(wiki, state, lint)
    return {
        "wiki": wiki.wiki_root.relative_to(wiki.repo_root).as_posix(),
        "mode": wiki.config.get("mode", "staging"),
        "source_count": len(state.get("sources", [])),
        "topic_count": len(state.get("topics", [])),
        "unmapped_sources": len(state.get("unmapped_sources", [])),
        "stale_topics": len(lint.get("stale_topics", [])),
        "schema_missing_files": len(lint.get("schema_missing_files", [])),
        "last_ingest": state.get("last_ingest"),
        "last_reindex": state.get("last_reindex"),
        "last_batch": state.get("last_batch"),
        "recent_batches": state.get("batch_history", [])[-5:],
        "suggested_mode": actions[0]["kind"] if actions else "query",
        "suggested_actions": actions,
    }


def cmd_status(wiki: Wiki, args: argparse.Namespace) -> int:
    state = read_json(wiki.state_path, {}) or wiki.compute_snapshot()
    summary = summarize_status(wiki, state)
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"wiki: {summary['wiki']}")
        print(f"mode: {summary['mode']}")
        print(f"source_count: {summary['source_count']}")
        print(f"topic_count: {summary['topic_count']}")
        print(f"unmapped_sources: {summary['unmapped_sources']}")
        print(f"stale_topics: {summary['stale_topics']}")
        print(f"schema_missing_files: {summary['schema_missing_files']}")
        print(f"last_ingest: {summary['last_ingest']}")
        print(f"last_reindex: {summary['last_reindex']}")
        print(f"suggested_mode: {summary['suggested_mode']}")
        print("\nsuggested_actions:")
        for action in summary["suggested_actions"]:
            command = f" | command: {action['command']}" if action.get("command") else ""
            print(f"  - [{action['priority']}] {action['kind']}: {action['reason']}{command}")
    return 0
def lint_report(wiki: Wiki) -> dict[str, Any]:
    state = wiki.compute_snapshot()
    topics = state["topics"]
    source_paths = {entry["path"] for entry in state["sources"]}
    schema_topics = set(wiki.schema_topics())
    topic_slugs = {topic["slug"] for topic in topics}
    stale_topics = []
    orphan_sources = []
    topics_without_sources = []
    topics_without_related_links = []
    for topic in topics:
        newest_source = None
        if not topic["sources"]:
            topics_without_sources.append(topic["slug"])
        for source in topic["sources"]:
            if source not in source_paths:
                orphan_sources.append({"topic": topic["slug"], "source": source})
                continue
            source_file = wiki.repo_root / source
            source_date = dt.datetime.fromtimestamp(source_file.stat().st_mtime, dt.timezone.utc).date().isoformat()
            newest_source = max(newest_source or source_date, source_date)
        if topic["updated"] and newest_source and newest_source > topic["updated"]:
            stale_topics.append(
                {
                    "topic": topic["slug"],
                    "topic_updated": topic["updated"],
                    "newest_source": newest_source,
                }
            )
        if len(topic["sources"]) >= 3 and not topic["related_topics"]:
            topics_without_related_links.append(topic["slug"])
    return {
        "generated_at": now_iso(),
        "source_count": len(state["sources"]),
        "topic_count": len(topics),
        "stale_topics": stale_topics,
        "orphan_sources": orphan_sources,
        "unmapped_sources": state["unmapped_sources"],
        "topics_without_sources": topics_without_sources,
        "topics_without_related_links": topics_without_related_links,
        "schema_missing_topics": sorted(topic_slugs - schema_topics),
        "schema_missing_files": sorted(schema_topics - topic_slugs),
    }


def cmd_lint(wiki: Wiki, args: argparse.Namespace) -> int:
    report = lint_report(wiki)
    if args.write_log:
        counts = (
            f"stale={len(report['stale_topics'])}, "
            f"orphans={len(report['orphan_sources'])}, "
            f"unmapped={len(report['unmapped_sources'])}, "
            f"schema_missing_topics={len(report['schema_missing_topics'])}, "
            f"schema_missing_files={len(report['schema_missing_files'])}"
        )
        note = counts if not args.note else f"{counts}; {args.note}"
        wiki.append_log("lint", note)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Sources: {report['source_count']}")
        print(f"Topics: {report['topic_count']}")
        print(f"Stale topics: {len(report['stale_topics'])}")
        print(f"Orphan source refs: {len(report['orphan_sources'])}")
        print(f"Unmapped sources: {len(report['unmapped_sources'])}")
        print(f"Schema missing topics: {len(report['schema_missing_topics'])}")
        print(f"Schema missing files: {len(report['schema_missing_files'])}")
        for key in [
            "stale_topics",
            "orphan_sources",
            "unmapped_sources",
            "topics_without_sources",
            "topics_without_related_links",
            "schema_missing_topics",
            "schema_missing_files",
        ]:
            items = report[key]
            if not items:
                continue
            print(f"\n{key}:")
            for item in items[:20]:
                print(f"  - {item}")
    return 0


def cmd_reindex(wiki: Wiki, args: argparse.Namespace) -> int:
    previous = read_json(wiki.state_path, {})
    state = wiki.compute_snapshot()
    state["changed_sources"] = previous.get("changed_sources", [])
    state["deleted_sources"] = previous.get("deleted_sources", [])
    state["last_ingest"] = previous.get("last_ingest")
    state["last_reindex"] = now_iso()
    write_json(wiki.state_path, state)
    wiki.index_path.write_text(wiki.render_index(state))
    if args.event:
        wiki.append_log(args.event, args.note)
    print(f"Reindexed {len(state['topics'])} topics and {len(state['sources'])} sources.")
    return 0


def source_heading_hint(source_file: Path) -> str:
    try:
        text = source_file.read_text()
    except Exception:
        return source_file.stem.replace("-", " ")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
    return source_file.stem.replace("-", " ")


def infer_related_topics(wiki: Wiki, slug: str, title: str, source_paths: list[str], limit: int = 5) -> list[dict[str, str]]:
    state = read_json(wiki.state_path, {}) or wiki.compute_snapshot()
    source_set = set(source_paths)
    query_tokens = tokenize(f"{slug} {title}")
    related: list[tuple[int, dict[str, Any]]] = []
    for topic in state.get("topics", []):
        if topic["slug"] == slug:
            continue
        shared_sources = len(source_set & set(topic.get("sources", [])))
        token_overlap = len(query_tokens & tokenize(f"{topic.get('slug', '')} {topic.get('title', '')}"))
        score = shared_sources * 10 + token_overlap
        if score > 0:
            related.append((score, topic))
    related.sort(key=lambda item: (-item[0], item[1]["slug"]))
    return [
        {"title": topic.get("title") or humanize_slug(topic["slug"]), "slug": topic["slug"]}
        for score, topic in related[:limit]
    ]


def build_source_bullets(source_paths: list[str]) -> str:
    if not source_paths:
        return "- [Source label](../sources/path/to/source.md)"
    lines = []
    for path in source_paths:
        label = source_heading_hint(Path(path)) if Path(path).is_absolute() else Path(path).stem.replace("-", " ").title()
        rel_path = path if path.startswith("../") else f"../{Path(path).relative_to('wiki').as_posix()}"
        lines.append(f"- [{label}]({rel_path})")
    return "\n".join(lines)


def derive_markdown_for_file(path: Path) -> str | None:
    suffix = path.suffix.lower()
    title = path.stem
    rel_name = path.name

    if suffix in {'.txt', '.text'}:
        try:
            content = path.read_text()
        except Exception:
            return None
        return f"# {title}\n\nDerived from: `{rel_name}`\n\n## Extracted Text\n\n```text\n{content[:20000]}\n```\n"

    if suffix == '.pdf':
        extracted = None
        try:
            proc = subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True, text=True, timeout=60)
            if proc.returncode == 0 and proc.stdout.strip():
                extracted = proc.stdout
        except Exception:
            extracted = None
        if extracted:
            return (
                f"# {title}\n\nDerived from: `{rel_name}`\n\n"
                f"> This markdown companion was auto-generated from the PDF for wiki ingestion.\n\n"
                f"## Extracted Text\n\n```text\n{extracted[:40000]}\n```\n"
            )
        return (
            f"# {title}\n\nDerived from: `{rel_name}`\n\n"
            f"> Placeholder companion for a PDF source. Use an existing OpenClaw PDF skill to replace this with a richer extraction later.\n\n"
            f"## Notes\n\n- Original PDF is present.\n- Local text extraction was unavailable or failed.\n"
        )

    return (
        f"# {title}\n\nDerived from: `{rel_name}`\n\n"
        f"> Auto-generated metadata companion for a non-markdown source.\n\n"
        f"## Notes\n\n- Original file type: `{suffix or 'unknown'}`\n- Replace this with a richer conversion if an OpenClaw skill exists for this file type.\n"
    )


def ensure_companion_markdown(raw_path: Path) -> Path | None:
    companion = companion_markdown_path(raw_path)
    if companion.exists():
        return companion
    derived = derive_markdown_for_file(raw_path)
    if not derived:
        return None
    companion.write_text(derived)
    return companion


def bootstrap_topic_text(wiki: Wiki, slug: str, title: str, source_paths: list[str], note: str | None) -> str:
    template = Template(wiki.topic_template_text())
    related = infer_related_topics(wiki, slug, title, source_paths)
    related_block = "\n".join(
        f"- [{item['title']}](./{item['slug']}.md)" for item in related
    ) or "- [Neighbor Topic](./neighbor-topic.md)"
    source_block = build_source_bullets(source_paths)
    summary = "Two or three tight paragraphs. Write this as a durable briefing, not meeting notes."
    if note:
        summary += f"\n\nBootstrap note: {note}"
    if source_paths:
        hints = []
        for raw_path in source_paths[:5]:
            src = wiki.repo_root / raw_path
            hints.append(source_heading_hint(src) if src.exists() else Path(raw_path).stem.replace('-', ' '))
        summary += "\n\nInitial source hints: " + "; ".join(hints)
    return template.safe_substitute(
        title=title,
        slug=slug,
        updated=dt.datetime.now(dt.timezone.utc).date().isoformat(),
        status="draft",
        summary=summary,
        timeline_bullets="- **YYYY-MM-DD:** Concrete event, decision, or result.",
        current_state="What is true now, what changed recently, and what a reader should know before opening raw sources.",
        key_decisions="- **YYYY-MM-DD:** Decision and rationale.",
        evidence_and_results="- Metric, experiment, benchmark, or observation tied to a source.",
        open_questions="- What remains uncertain or worth investigating next.",
        related_topics=related_block,
        sources=source_block,
    )


def cmd_bootstrap_topic(wiki: Wiki, args: argparse.Namespace) -> int:
    slug = slugify(args.slug or args.title)
    title = args.title or humanize_slug(slug)
    topic_path = wiki.topic_path(slug)
    if topic_path.exists() and not args.force:
        raise SystemExit(f"Topic already exists: {topic_path}. Use --force to overwrite.")

    source_paths: list[str] = []
    for item in args.source or []:
        raw = Path(item)
        resolved = raw if raw.is_absolute() else (wiki.repo_root / raw)
        if resolved.exists():
            try:
                rel = resolved.relative_to(wiki.repo_root).as_posix()
            except ValueError:
                rel = item
            source_paths.append(rel)
        else:
            source_paths.append(item)
    source_paths = sorted(dict.fromkeys(source_paths))

    topic_path.parent.mkdir(parents=True, exist_ok=True)
    topic_path.write_text(bootstrap_topic_text(wiki, slug, title, source_paths, args.note))

    if args.reindex:
        cmd_reindex(
            wiki,
            argparse.Namespace(event="bootstrap-topic", note=args.note or f"bootstrapped {slug}")
        )
    else:
        print(f"Bootstrapped topic: {topic_path.relative_to(wiki.repo_root)}")
    return 0


def cmd_ingest(wiki: Wiki, args: argparse.Namespace) -> int:
    generated = []
    if not args.no_derive:
        for raw in wiki.raw_source_candidates():
            if is_markdown_path(raw) or raw.name.endswith('.md'):
                continue
            created = ensure_companion_markdown(raw)
            if created:
                generated.append(created.relative_to(wiki.repo_root).as_posix())
    state = wiki.compute_snapshot()
    state = wiki.update_state(state)
    payload = {
        "sources": len(state["sources"]),
        "topics": len(state["topics"]),
        "new_sources": state.get("new_sources", []),
        "changed_sources": state["changed_sources"],
        "deleted_sources": state["deleted_sources"],
        "unmapped_sources": state["unmapped_sources"],
        "generated_companions": generated,
        "derived_sources": state.get("derived_sources", []),
        "last_batch": state.get("last_batch", {}),
    }
    summary = summarize_status(wiki, state)
    payload.update({"suggested_mode": summary["suggested_mode"], "suggested_actions": summary["suggested_actions"]})
    if args.write_log:
        note = args.note or (
            f"new={len(payload['new_sources'])}, changed={len(payload['changed_sources'])}, deleted={len(payload['deleted_sources'])}"
        )
        wiki.append_log("ingest", note)
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Sources scanned: {payload['sources']}")
        print(f"Topics found: {payload['topics']}")
        print(f"New sources: {len(payload['new_sources'])}")
        print(f"Changed sources: {len(payload['changed_sources'])}")
        print(f"Deleted sources: {len(payload['deleted_sources'])}")
        print(f"Generated companions: {len(payload['generated_companions'])}")
        print(f"Unmapped sources: {len(payload['unmapped_sources'])}")
        print(f"Suggested mode: {payload['suggested_mode']}")
        for group_name in ["new_sources", "changed_sources", "deleted_sources", "generated_companions"]:
            items = payload[group_name]
            if items:
                print(f"\n{group_name}:")
                for path in items[:20]:
                    print(f"  - {path}")
        if payload["unmapped_sources"]:
            print("\nunmapped_sources:")
            for path in payload["unmapped_sources"][:20]:
                print(f"  - {path}")
        print("\nsuggested_actions:")
        for action in payload["suggested_actions"]:
            command = f" | command: {action['command']}" if action.get("command") else ""
            print(f"  - [{action['priority']}] {action['kind']}: {action['reason']}{command}")
    return 0


def synthesize_prompt(wiki: Wiki, state: dict[str, Any], args: argparse.Namespace) -> str:
    """Build a full synthesis prompt for the LLM, writing to task file."""
    parts: list[str] = []
    parts.append(f"# LLM Wiki — Auto-Synthesis Task\n")
    parts.append(f"Generated: {now_iso()}\n")
    parts.append(f"Wiki root: {wiki.wiki_root}\n")
    parts.append(f"Repo root: {wiki.repo_root}\n")
    parts.append("---\n")

    # 1. Wiki health summary
    parts.append("## Wiki State\n")
    parts.append(f"- Total sources: {len(state.get('sources', []))}")
    parts.append(f"- Total topics: {len(state.get('topics', []))}")
    parts.append(f"- Unmapped sources: {len(state.get('unmapped_sources', []))}")
    parts.append(f"- New/Changed sources: {len(state.get('new_sources', [])) + len(state.get('changed_sources', []))}\n")

    # 2. Schema topics
    schema_topics = wiki.schema_topics()
    topics = wiki.read_topics()
    topic_slugs = {t['slug'] for t in topics}
    missing_topics = sorted(set(schema_topics) - topic_slugs)
    parts.append("## Canonical Schema Topics\n")
    for slug in schema_topics:
        status = "[MISSING]" if slug in missing_topics else "[exists]"
        topic = next((t for t in topics if t['slug'] == slug), None)
        if topic:
            parts.append(f"- `{slug}` {status} — {len(topic['sources'])} sources")
        else:
            parts.append(f"- `{slug}` {status}")
    parts.append("")

    # 3. Unmapped sources (prioritized)
    unmapped = state.get('unmapped_sources', [])
    if unmapped:
        parts.append(f"## Unmapped Sources ({len(unmapped)})\n")
        parts.append("These sources are not yet linked from any topic page. Map each to the most relevant canonical topic and update the topic's `## Sources` section + add synthesis content.\n")
        for path in unmapped[:15]:
            src_file = wiki.repo_root / path
            hint = source_heading_hint(src_file) if src_file.exists() else Path(path).stem
            parts.append(f"- `{path}` — hint: {hint}")
        parts.append("")

    # 4. Stale topics (sources newer than topic)
    lint = lint_report(wiki)
    stale = lint.get('stale_topics', [])
    if stale:
        parts.append(f"## Stale Topics ({len(stale)})\n")
        parts.append("These topic pages have newer sources that may need synthesis refresh. Review and update if needed.\n")
        for item in stale[:10]:
            parts.append(f"- `{item['topic']}` — topic updated: {item['topic_updated']}, newest source: {item['newest_source']}")
        parts.append("")

    # 5. Missing canonical topics
    if missing_topics:
        parts.append(f"## Missing Canonical Topics ({len(missing_topics)})\n")
        parts.append("These schema topics have no topic file yet. Bootstrap them using the schema description.\n")
        for slug in missing_topics[:10]:
            parts.append(f"- `{slug}`")
        parts.append("")

    # 6. Instructions
    parts.append("---\n")
    parts.append("## Instructions\n")
    parts.append("1. Read `wiki/schema.md` to understand the canonical topic structure.\n")
    parts.append("2. For each unmapped source, read the source file, decide which topic(s) it belongs to, and update the topic page's `## Sources` section.\n")
    parts.append("3. If the topic page is sparse, add synthesis content to `## Summary`, `## Current State`, `## Evidence And Results` sections.\n")
    parts.append("4. If a new canonical topic is missing, bootstrap it: `python3 skills/llm-wiki/bin/wiki_tool.py bootstrap-topic \"Topic Title\" --slug <slug>`\n")
    parts.append("5. After all edits: `python3 skills/llm-wiki/bin/wiki_tool.py reindex --event auto-synthesize --note \"<brief summary>\"`\n")
    parts.append("6. Write a brief completion note to `wiki/.last-synthesize.txt` describing what was done.\n")

    return "\n".join(parts)


def cmd_synthesize(wiki: Wiki, args: argparse.Namespace) -> int:
    """Prepare synthesis task: run ingest, emit prompt, write task file."""
    # Always ingest first to pick up new/changed sources
    ingest_args = argparse.Namespace(json=True, write_log=False, note=None, no_derive=False)
    cmd_ingest(wiki, ingest_args)

    state = read_json(wiki.state_path, {}) or wiki.compute_snapshot()

    # Decide what needs work
    unmapped = state.get('unmapped_sources', [])
    lint = lint_report(wiki)
    stale = lint.get('stale_topics', [])
    missing = sorted(set(wiki.schema_topics()) - {t['slug'] for t in wiki.read_topics()})

    if not unmapped and not stale and not missing:
        msg = "Wiki is healthy — no synthesis needed."
        if args.output:
            Path(args.output).write_text(msg + "\n")
            print(f"Task file written: {args.output}")
            print(msg)
        else:
            print(msg)
        return 0

    prompt = synthesize_prompt(wiki, state, args)

    if args.output:
        Path(args.output).write_text(prompt)
        print(f"Synthesis task written to: {args.output}")
        print(f"Unmapped: {len(unmapped)}, Stale: {len(stale)}, Missing topics: {len(missing)}")
    else:
        print(prompt)
    return 0


def cmd_query(wiki: Wiki, args: argparse.Namespace) -> int:
    state = read_json(wiki.state_path, {}) or wiki.compute_snapshot()
    query_tokens = tokenize(args.question)
    scored_topics = []
    for topic in state.get("topics", []):
        topic_file = wiki.repo_root / topic["path"]
        text = topic_file.read_text() if topic_file.exists() else topic["title"]
        score = len(query_tokens & tokenize(f"{topic['title']} {topic['slug']} {text[:4000]}"))
        if score:
            scored_topics.append((score, topic))
    scored_topics.sort(key=lambda item: (-item[0], item[1]["slug"]))

    scored_sources = []
    for source in state.get("sources", []):
        source_file = wiki.repo_root / source["path"]
        text = source_file.read_text() if source_file.exists() else source["path"]
        score = len(query_tokens & tokenize(f"{source['path']} {text[:3000]}"))
        if score:
            scored_sources.append((score, source["path"]))
    scored_sources.sort(key=lambda item: (-item[0], item[1]))

    payload = {
        "question": args.question,
        "topics": [
            {"score": score, "slug": topic["slug"], "path": topic["path"], "title": topic["title"]}
            for score, topic in scored_topics[: args.limit]
        ],
        "sources": [{"score": score, "path": path} for score, path in scored_sources[: args.limit]],
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Question: {args.question}")
        print("\nSuggested topics:")
        if payload["topics"]:
            for item in payload["topics"]:
                print(f"- score={item['score']} {item['path']}")
        else:
            print("- none")
        print("\nSuggested raw sources:")
        if payload["sources"]:
            for item in payload["sources"]:
                print(f"- score={item['score']} {item['path']}")
        else:
            print("- none")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OpenClaw-native helper for markdown LLM wikis.")
    parser.add_argument("--wiki-root", help="Path to the wiki root. Defaults to auto-detecting ./wiki.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name in ["status", "ingest", "lint"]:
        sub = subparsers.add_parser(name)
        sub.add_argument("--json", action="store_true")
        if name in {"ingest", "lint"}:
            sub.add_argument("--write-log", action="store_true")
            sub.add_argument("--note")
        if name == "ingest":
            sub.add_argument("--no-derive", action="store_true")

    reindex = subparsers.add_parser("reindex")
    reindex.add_argument("--event")
    reindex.add_argument("--note")

    bootstrap = subparsers.add_parser("bootstrap-topic")
    bootstrap.add_argument("title", nargs="?")
    bootstrap.add_argument("--slug")
    bootstrap.add_argument("--source", action="append", default=[])
    bootstrap.add_argument("--note")
    bootstrap.add_argument("--force", action="store_true")
    bootstrap.add_argument("--reindex", action="store_true")

    query = subparsers.add_parser("query")
    query.add_argument("question")
    query.add_argument("--limit", type=int, default=5)
    query.add_argument("--json", action="store_true")

    synth = subparsers.add_parser("synthesize")
    synth.add_argument("--output", "-o", help="Write synthesis task prompt to this file instead of stdout.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    wiki_root = resolve_wiki_root(Path.cwd(), args.wiki_root)
    wiki = Wiki(wiki_root)
    if args.command == "status":
        return cmd_status(wiki, args)
    if args.command == "ingest":
        return cmd_ingest(wiki, args)
    if args.command == "lint":
        return cmd_lint(wiki, args)
    if args.command == "reindex":
        return cmd_reindex(wiki, args)
    if args.command == "bootstrap-topic":
        return cmd_bootstrap_topic(wiki, args)
    if args.command == "query":
        return cmd_query(wiki, args)
    if args.command == "synthesize":
        return cmd_synthesize(wiki, args)
    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
