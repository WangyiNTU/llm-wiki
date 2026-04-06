# LLM Wiki — OpenClaw Skill

![Hero](./01_hero.png)

A markdown-first, LLM-powered wiki for personal knowledge management. Built on [Karpathy's LLM Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f), adapted for OpenClaw.

Raw source files go in → LLM synthesizes → durable topic pages come out. The wiki compounds over time rather than being rebuilt from scratch for every question.

> ⚠️ **Note:** The `skills/llm-wiki/` folder contains the skill code. Your personal wiki lives in `workspace/wiki/` and is **never published**. The `wiki-template/` subfolder inside this skill is the starter template for new users — copy it to start a fresh wiki.

---

## Publishing to ClawhHub

This skill is published on [ClawhHub](https://clawhub.ai). To install from ClawhHub:

```bash
openclaw skills install llm-wiki
```

To publish your own updated version of this skill to ClawhHub:

```bash
# Login first
openclaw clawhub login

# Publish the skill
openclaw clawhub skill publish ./skills/llm-wiki/
```

Requirements for publishing:
- Skill folder must have `SKILL.md` at the root ✓
- `bin/wiki_tool.py` must be executable or callable via `python3` ✓
- No private data in the skill folder (your `workspace/wiki/` is excluded) ✓
- A clean `wiki-template/` folder for new user onboarding ✓

---

## Installation in OpenClaw

### Option A: ClawhHub (recommended)

```bash
openclaw skills install llm-wiki
```

### Option B: Manual

Copy or clone this `llm-wiki/` skill folder into your OpenClaw skills directory:

```
openclaw-workspace/
└── skills/
    └── llm-wiki/
        ├── SKILL.md
        ├── README.md
        ├── bin/
        │   └── wiki_tool.py
        └── templates/
            └── topic-template.md
```

---

## Setup

### 1. Configure wiki sources

Edit `wiki/.wiki-config.json` (create it if it doesn't exist):

```json
{
  "name": "My Research Wiki",
  "state_file": "wiki/.wiki-state.json",
  "index_file": "wiki/INDEX.md",
  "log_file": "wiki/log.md",
  "schema_file": "wiki/schema.md",
  "topics_dir": "wiki/topics",
  "mode": "recommended",
  "sources": [
    {
      "path": "wiki/sources",
      "include": ["**/*.md", "**/*.pdf"],
      "exclude": ["**/*.pdf.md"]
    }
  ]
}
```

### 2. Define your canonical topics

Edit `wiki/schema.md` to define the topics that matter for your use case. The schema is the durable contract — it defines what topics exist and what each one covers.

```markdown
## Canonical Topics

- `egocentric-vision` — First-person vision, embodied perception, datasets.
- `autonomous-driving` — Occupancy prediction, object detection, scene understanding.
- `multimedia-forensics` — File fragment classification, media recovery, forensics.
...
```

### 3. Add raw source files

Drop files into `wiki/sources/`. The ingest step will scan them and generate companion markdown for non-markdown files (e.g., `.pdf` → `.pdf.md`).

```
wiki/
├── sources/
│   ├── Papers/
│   │   └── my-paper.pdf      ← source file (immutable)
│   └── Notes/
│       └── meeting-notes.md
├── topics/
│   └── egocentric-vision.md  ← LLM-authored synthesis
├── schema.md
├── INDEX.md
└── log.md
```

---

## Usage

### In OpenClaw Chat

The natural-language trigger is `run llm-wiki`:

```
run llm-wiki
update my wiki with the latest papers
refresh the wiki after adding new sources
ask the wiki what it knows about autonomous driving
```

OpenClaw decides whether to run `sync` (health check + ingest), `query` (answer from wiki), or `update` (compile topics) based on your request.

### Via the CLI Helper

All commands run from the workspace root (`openclaw-workspace/`):

#### Ingest new sources

```bash
python3 skills/llm-wiki/bin/wiki_tool.py ingest
python3 skills/llm-wiki/bin/wiki_tool.py ingest --json   # machine-readable output
```

Scans `wiki/sources/`, generates companion markdown for non-md files (PDFs), updates state. Run this whenever you add new files.

#### Check wiki health

```bash
python3 skills/llm-wiki/bin/wiki_tool.py status
python3 skills/llm-wiki/bin/wiki_tool.py status --json
```

Shows source count, topic count, unmapped sources, stale topics, and suggested next actions.

#### Query the wiki

```bash
python3 skills/llm-wiki/bin/wiki_tool.py query "what papers do I have on crowd counting"
```

Returns scored topic pages and raw sources relevant to your question.

#### Bootstrap a new topic

```bash
python3 skills/llm-wiki/bin/wiki_tool.py bootstrap-topic "Egocentric Vision" --slug egocentric-vision --source wiki/sources/papers/egocentric-survey.pdf.md
python3 skills/llm-wiki/bin/wiki_tool.py bootstrap-topic "My Topic" --slug my-topic --reindex
```

Creates a scaffolded topic page from a template, optionally reindexing afterward.

#### Lint the wiki

```bash
python3 skills/llm-wiki/bin/wiki_tool.py lint
python3 skills/llm-wiki/bin/wiki_tool.py lint --write-log
```

Checks for: stale topics (sources newer than topic), orphan source references, unmapped sources, missing schema topics/files.

#### Reindex

```bash
python3 skills/llm-wiki/bin/wiki_tool.py reindex --event compile --note "updated autonomous-driving topic"
```

Updates `INDEX.md` and `wiki-state.json` after any topic edits.

#### Prepare synthesis task (for auto mode)

```bash
python3 skills/llm-wiki/bin/wiki_tool.py synthesize --output /tmp/synth-task.txt
```

Runs ingest first, then emits a structured task prompt listing unmapped sources, stale topics, and missing topics. Used by the auto-synthesis cron job.

---

## Auto Mode — Fully Automated Synthesis

The wiki can run synthesis **fully automatically** using OpenClaw's own LLM. No external coding agents, no manual triggers.

### How It Works

1. A **cron job** fires every N hours (configurable)
2. It triggers an **isolated OpenClaw agent session**
3. The isolated session reads `llm-wiki` SKILL.md, decides what needs work
4. It reads unmapped source files, updates topic pages, runs `reindex`
5. Writes a completion note to `wiki/.last-synthesize.txt`

### Setup the Cron Job

```bash
# In OpenClaw chat, run:
/new
```

Then create the job via the cron tool:

```json
{
  "name": "llm-wiki auto-synthesize",
  "schedule": { "kind": "cron", "expr": "0 */6 * * *", "tz": "Asia/Hong_Kong" },
  "sessionTarget": "isolated",
  "payload": {
    "kind": "agentTurn",
    "message": "Run the llm-wiki skill in update mode. Check wiki/sources/ for new papers, map them to topics, update topic pages, then run reindex. Write a one-line summary to wiki/.last-synthesize.txt. If wiki is healthy (no unmapped sources, no stale topics), just write 'OK' to wiki/.last-synthesize.txt.",
    "timeoutSeconds": 600
  },
  "delivery": { "mode": "none" }
}
```

- **Every 6 hours** is a good default. Adjust the cron expression as needed.
- `sessionTarget: "isolated"` ensures the synthesis runs in a fresh session using OpenClaw's configured LLM.
- Results land in `wiki/.last-synthesize.txt` — check it after each run.

### Trigger Immediately

```bash
cron run <job-id>
```

### Pause / Resume

```bash
cron list                              # see all jobs and their IDs
cron update <job-id> --enabled false  # pause
cron update <job-id> --enabled true   # resume
```

---

## File Structure

```
skills/llm-wiki/
├── SKILL.md              ← OpenClaw skill definition + usage guide
├── README.md             ← This file
├── bin/
│   └── wiki_tool.py      ← CLI helper (ingest, query, lint, bootstrap, synthesize)
└── templates/
    └── topic-template.md ← Topic page scaffold

wiki/                     ← Your wiki (user-managed)
├── sources/             ← Raw immutable source files
│   └── Papers/
│       └── *.pdf
├── topics/              ← LLM-authored topic pages
│   ├── egocentric-vision.md
│   └── autonomous-driving.md
├── .wiki-config.json    ← Wiki configuration
├── .wiki-state.json     ← Auto-generated state (do not edit)
├── INDEX.md             ← Auto-generated index
├── log.md               ← Activity log
└── schema.md            ← Topic definitions
```

---

## Key Design Principles

- **Sources are immutable** — never edit raw sources; if a source changes materially, update the raw file and re-ingest
- **Topics are durable synthesis** — written by an LLM from sources, not raw notes
- **Schema is the contract** — canonical topics are defined in `schema.md` and should be stable
- **Wiki compounds** — each query/answer can be filed back into the wiki as new synthesis; the wiki grows richer over time
- **LLM does synthesis; `wiki_tool.py` does bookkeeping** — the helper handles state tracking, indexing, and lint; the LLM handles reading, reasoning, and writing

---

## Requirements

- Python 3.8+
- `poppler-utils` (for PDF text extraction: `pdftotext`) — install via `apt install poppler-utils` if not present
- OpenClaw with at least one configured LLM provider (for synthesis)
