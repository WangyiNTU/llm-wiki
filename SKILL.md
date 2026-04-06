---
name: llm-wiki
description: Implement and maintain a markdown-first LLM wiki in OpenClaw. Use when setting up a persistent wiki, ingesting new sources, compiling or refreshing topic pages, linting wiki health, or answering questions from compiled knowledge. Based on Karpathy's LLM wiki pattern, adapted for Codex/OpenClaw without Claude plugins or slash commands.
---

# LLM Wiki

This skill turns `wiki/` into a durable knowledge artifact and keeps the user-facing UX simple:

## Primary Trigger

The default trigger is:

- `run llm-wiki`

Treat that as the top-level OpenClaw-native entrypoint. The user should not need to name subcommands like `ingest`, `status`, `bootstrap-topic`, or `reindex` unless they want to be explicit.

Internally, the skill should choose one of three orchestration modes:

- `sync`:
  inspect wiki health, ingest raw sources, create missing companion markdown for non-md files, surface unmapped/stale material, and decide whether topic work is needed
- `query`:
  answer a user question from the compiled wiki first, then raw sources only when coverage is low or stale
- `update`:
  compile or refresh durable topic pages, then reindex and lint

These modes are internal implementation details. The visible user instruction should still effectively be “run llm-wiki”.

## Mode Selection

When this skill loads, choose the lightest mode that matches the request:

- Use `query` if the user is asking what the wiki knows about a topic or asks a concrete question.
- Use `update` if the user explicitly asks to refresh, compile, file new synthesis back, or update specific topics.
- Otherwise default to `sync`. This is the normal behavior for `run llm-wiki`.

Recommended first step for `sync`:

1. Run `python3 skills/llm-wiki/bin/wiki_tool.py status --json`.
2. If the state is missing or stale, run `python3 skills/llm-wiki/bin/wiki_tool.py ingest --json`.
3. Read `suggested_mode` and `suggested_actions` from the CLI output.
4. Decide whether to stop with a concise health report, bootstrap/update topics, or move into query flow.

The user can also ask follow-up actions in plain language, for example:

- `run llm-wiki`
- `update my personal knowledge base`
- `ingest the latest files into llm-wiki`
- `refresh the wiki after I added papers`
- `ask llm-wiki what it knows about egocentric vision`
- `update the wiki with this new source`

Treat `wiki_tool.py` subcommands as implementation details. The assistant should decide which internal steps to run after loading this skill, and should use the helper's status/suggested-actions output instead of inventing a workflow from scratch.

- Raw sources stay immutable in `wiki/sources/`
- Non-markdown raw files can live there too, using derived companion markdown like `file.pdf.md`
- Topic pages in `wiki/topics/` are LLM-authored synthesis
- `wiki/schema.md`, `wiki/INDEX.md`, `wiki/log.md`, and `wiki/.wiki-state.json` keep the system navigable and persistent

Use the helper CLI for deterministic bookkeeping:

```bash
python3 skills/llm-wiki/bin/wiki_tool.py status --json
python3 skills/llm-wiki/bin/wiki_tool.py ingest --json
python3 skills/llm-wiki/bin/wiki_tool.py bootstrap-topic "Topic Title" --source wiki/sources/path/to/file.md
python3 skills/llm-wiki/bin/wiki_tool.py query "your question"
python3 skills/llm-wiki/bin/wiki_tool.py lint
python3 skills/llm-wiki/bin/wiki_tool.py reindex --event compile --note "updated topic-x and topic-y"
```

The LLM work stays in Codex: reading sources, synthesizing, writing topic pages, and deciding what should be filed back into the wiki.

## Operating Rules

1. Never edit raw source files in place as part of compilation.
2. Treat `wiki/topics/*.md` as generated-but-reviewable artifacts. Regenerate by editing the topic page directly from sources, not by patching summaries blindly.
3. Keep one topic per file. Prefer stable slugs over renames.
4. Every topic page must list its contributing raw sources in `## Sources`.
5. After any wiki edit, run `reindex`. Run `lint` before landing substantial wiki changes.

## Ingest

Use when new markdown sources were added or existing sources changed. This is usually what `run llm-wiki` should start with.

1. Run `python3 skills/llm-wiki/bin/wiki_tool.py ingest --json`.
2. For non-markdown files, ingest may generate lightweight companion markdown files like `file.pdf.md`.
3. Read the summary:
   - `changed_sources`
   - `unmapped_sources`
   - `suggested_mode`
   - `suggested_actions`
   - existing topic coverage
4. Read `wiki/schema.md` before deciding whether to update an existing topic or create a new one.
5. If the sources imply new canonical topics, add them to `wiki/schema.md`.

The helper updates `wiki/.wiki-state.json`. It can create lightweight companion markdown for non-md raw files, track ingest batches, and tell the assistant what the likely next move is, but it does not write durable topic prose for you.

## Compile Or Refresh Topics

Use when sources have changed or a query reveals a durable synthesis worth keeping.

1. Run `ingest`.
2. Read `wiki/schema.md`, `wiki/INDEX.md`, and the relevant raw sources.
3. For a new topic, start with `python3 skills/llm-wiki/bin/wiki_tool.py bootstrap-topic "Topic Title" --source ...`.
4. Then refine or create topic pages in `wiki/topics/` using the template at `skills/llm-wiki/templates/topic-template.md`.
5. Keep coverage honest:
   - `high`: 5+ meaningful sources
   - `medium`: 2-4 sources
   - `low`: 0-1 source or thin evidence
6. Put concrete dates and decisions in the article. Avoid vague summaries.
7. Ensure `## Related Topics` and `## Sources` are current.
8. Run `python3 skills/llm-wiki/bin/wiki_tool.py reindex --event compile --note "..."`.

## Query

After the wiki exists, the user should be able to ask normal questions against this personal knowledge base. The assistant should use the wiki before raw source spelunking.

1. Run `python3 skills/llm-wiki/bin/wiki_tool.py query "question"`.
2. Read the top suggested topic pages first.
3. Fall back to raw sources only when:
   - coverage is low
   - the topic page points to a needed detail
   - the question is clearly newer than the topic update date
4. Answer from the compiled wiki and cite both:
   - the topic page section
   - the raw source path when a claim depends on one document
5. If the answer is broadly reusable, file it back into the most relevant topic or create a new topic page, then `reindex`.

## Lint

Run two layers of lint:

1. Deterministic lint:
   `python3 skills/llm-wiki/bin/wiki_tool.py lint`
2. Semantic lint by Codex:
   - scan for contradictions across related topic pages
   - look for weak coverage claims
   - check whether important new sources are still unmapped
   - check whether topic boundaries are too broad or too fragmented

Fix findings, then rerun `reindex`. Use `lint --write-log` when you want the audit recorded in `wiki/log.md`.

## Topic Contract

Each topic page should have:

- YAML frontmatter with `title`, `slug`, `updated`, `status`
- `# Title`
- `## Summary [coverage: ...]`
- `## Timeline [coverage: ...]`
- `## Current State [coverage: ...]`
- `## Key Decisions [coverage: ...]`
- `## Evidence And Results [coverage: ...]`
- `## Open Questions [coverage: ...]`
- `## Related Topics`
- `## Sources`

## Fit With Karpathy's LLM Wiki Pattern

This skill is intentionally aligned with the gist's core ideas:

- raw sources are immutable inputs
- the wiki is the persistent, compounding artifact
- the schema defines durable structure and workflow
- query answers can be filed back into the wiki
- indexing and logging are first-class

The main OpenClaw adaptation is UX: the user should talk to the agent naturally, for example `run llm-wiki`, while the agent decides which helper commands and edits to execute underneath.

## Auto Mode — Fully Automated Synthesis

The skill can run **fully automatically** on a schedule using OpenClaw's own LLM. No external coding agent needed.

### How It Works

A **cron job** triggers an **isolated OpenClaw agent session** at a schedule. That isolated session:
1. Runs `wiki_tool.py synthesize` to prepare the synthesis task
2. Reads unmapped sources and stale topics
3. Uses the configured LLM (MiniMax, GPT-5, etc.) to do the actual synthesis — read sources, update topic pages
4. Runs `reindex` to update the wiki index
5. Writes a completion note to `wiki/.last-synthesize.txt`

The isolated session uses the **same LLM as the main session** — it is the OpenClaw agent itself, not an external tool.

### Setup: Create the Cron Job

Use the `cron` tool to create an isolated agent-turn job. Example — run synthesis every 6 hours:

```json
{
  "name": "llm-wiki auto-synthesize",
  "schedule": { "kind": "cron", "expr": "0 */6 * * *", "tz": "Asia/Hong_Kong" },
  "sessionTarget": "isolated",
  "payload": {
    "kind": "agentTurn",
    "message": "Run the llm-wiki skill in update mode. Check wiki/sources/ for new papers, map them to topics, update topic pages, then run reindex. Write a one-line summary to wiki/.last-synthesize.txt.",
    "timeoutSeconds": 600
  },
  "delivery": { "mode": "none" }
}
```

Key settings:
- `sessionTarget: "isolated"` — runs in a fresh isolated session (uses the configured default LLM)
- `timeoutSeconds: 600` — give it 10 minutes to finish synthesis
- `delivery.mode: "none"` — no push notification; check `wiki/.last-synthesize.txt` or the wiki index after the job runs
- Trigger immediately to test: `cron run <jobId>`

### Monitoring Auto Synthesis

- **Success**: completion note in `wiki/.last-synthesize.txt`, topic pages updated, index current
- **Failure**: check `wiki/log.md` for the last entries
- **Disabled**: `cron list` to see all jobs; `cron update <jobId> --enabled false` to pause

### One-Shot Auto Synthesis (manual trigger)

To trigger synthesis right now without waiting for cron:

    python3 skills/llm-wiki/bin/wiki_tool.py synthesize --output /tmp/synth-task.txt

This prints what needs doing. To execute the full synthesis loop:

    # In an isolated session or background exec:
    python3 skills/llm-wiki/bin/wiki_tool.py synthesize --output /tmp/synth-task.txt
    # Then: read /tmp/synth-task.txt, do the synthesis work, reindex

The `synthesize` command runs `ingest` first, then emits a task prompt describing unmapped sources, stale topics, and missing canonical topics.

## Notes

- This workflow is intentionally markdown-first and script-light.
- The helper CLI handles indexing, source inventory, structural linting, next-step suggestions, and new-topic scaffolding.
- The LLM handles classification, synthesis, and durable knowledge shaping.
- The wiki should compound over time instead of being rebuilt from scratch for every question.
- Auto mode uses OpenClaw's own LLM — no Claude Code, Codex, or external API keys required for automation.
