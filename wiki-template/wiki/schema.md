# Schema — Your Canonical Topics

*Edit this file to define the topics that matter for your wiki. These topics are the durable contract — they should be stable over time.*

## Canonical Topics

- `topic-one` — Description of what this topic covers.
- `topic-two` — Description of what this topic covers.
- `topic-three` — Description of what this topic covers.

## Source Rules

- Raw source files live in `wiki/sources/` and stay immutable during compilation.
- Prefer one source file per imported artifact or note.
- When a source changes materially, update the raw file and rerun `ingest`; do not patch topic prose alone.

## Topic Page Contract

Every topic page should:

- use YAML frontmatter with `title`, `slug`, `updated`, and `status`
- include coverage tags on the main synthesis sections
- end with `## Related Topics` and `## Sources`
- link raw sources with normal markdown links relative to `wiki/topics/`
- make dates concrete in `YYYY-MM-DD` form

## Coverage Guidance

- `high`: 5+ meaningful sources or repeated corroboration
- `medium`: 2–4 sources with decent synthesis
- `low`: 0–1 source, sparse evidence, or clearly provisional synthesis

Coverage tags are epistemic labels, not polish labels. Keep them honest.

## Query Filing Rules

- File new synthesis back into the wiki when it is likely to answer the same future question again.
- Expand an existing topic page when the answer fits its scope.
- Create a new topic page only when the synthesis represents a stable topic, not a one-off answer.

## Evolution Log

- **YYYY-MM-DD:** Initial setup — define your first canonical topics here.
