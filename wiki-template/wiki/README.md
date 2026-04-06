# Wiki Template

Copy this `wiki/` folder to your OpenClaw workspace root. After copying:

```bash
# 1. Edit wiki name (optional)
#    Open wiki/.wiki-config.json and change "name"

# 2. Define your canonical topics
#    Edit wiki/schema.md — add your own topics

# 3. Add source files
#    Drop files into wiki/sources/ (PDFs, markdown, etc.)

# 4. Run first ingest
python3 skills/llm-wiki/bin/wiki_tool.py ingest

# 5. Bootstrap initial topics (optional)
python3 skills/llm-wiki/bin/wiki_tool.py bootstrap-topic "My Topic" --slug my-topic

# 6. Reindex
python3 skills/llm-wiki/bin/wiki_tool.py reindex --event bootstrap --note "first setup"
```

After setup, your wiki layout will be:

```
workspace/
├── skills/
│   └── llm-wiki/          ← the skill (already installed)
└── wiki/                   ← your wiki (from this template)
    ├── .wiki-config.json   ← your wiki config
    ├── schema.md           ← your topic definitions
    ├── sources/            ← your raw source files
    ├── topics/             ← topic pages written by the LLM
    ├── INDEX.md            ← auto-generated
    ├── log.md              ← activity log
    └── .wiki-state.json    ← auto-generated state
```
