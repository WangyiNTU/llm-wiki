# Wiki Template — Copy this folder to `wiki/` in your workspace

Copy everything in this folder to `wiki/` in your OpenClaw workspace, then run:

```bash
python3 skills/llm-wiki/bin/wiki_tool.py ingest
python3 skills/llm-wiki/bin/wiki_tool.py reindex
```

Your `wiki/` will look like:

```
wiki/
├── .wiki-config.json   ← edit this to set your wiki name
├── schema.md           ← define your canonical topics
├── INDEX.md            ← auto-generated
├── log.md             ← auto-generated
├── .wiki-state.json   ← auto-generated
├── sources/           ← put your raw source files here
│   └── .gitkeep
└── topics/            ← topic pages go here (auto-generated on first reindex)
    └── .gitkeep
```
