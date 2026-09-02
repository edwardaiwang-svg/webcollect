# webcollect

A portable, **provenance-first** web data-collection & consolidation pipeline,
packaged as six Claude Code skills. Collect statistics and qualitative anecdotes at
volume, consolidate millions of tokens into a queryable claim store, and emit
decision-ready deliverables where **every number and quote traces back to its source**.

Runs **$0**: all LLM work happens inside Claude Code (Workflow tool + subagents);
embeddings are local (sentence-transformers); statistics come from free primary APIs.

## Prerequisites
- macOS or Linux with `git`, [`uv`](https://docs.astral.sh/uv/), and `jq` on PATH (`install.sh` exits if any is missing)
- Homebrew (used to install `duckdb`)
- [Claude Code](https://claude.com/claude-code) — the skills are invoked from it

## Quick start
```bash
git clone https://github.com/edwardaiwang-svg/webcollect.git
cd webcollect
./install.sh          # uv venv + deps, duckdb, .env from env.example, symlink skills, merge MCP stub, selftest
```
`install.sh` ends by running `python lib/db.py --selftest` — it must print `SELFTEST PASS ✅`
(15 checks: provenance chain, fabricated-quote rejection, dedup, hybrid search, …).
Then fill in `.env` (all keys optional; Reddit needs a free OAuth "script" app).

**What `install.sh` writes outside the repo** (backups are taken first): symlinks under
`~/.claude/skills/`, an MCP-server merge into `~/.claude.json`, and — only with the
`--with-permissions` flag — read-only permission entries in `~/.claude/settings.local.json`.
The first selftest downloads a small sentence-transformers model from Hugging Face.

## Pipeline (skills)
1. **corpus-ingest** — stats (FRED / SEC EDGAR / Finnhub), articles, Reddit, X best-effort → raw store.
2. **corpus-consolidate** — chunk + embed + dedup, then map-reduce claim extraction (Workflow).
3. **corpus-query** — hybrid dense + BM25 retrieval (+ optional local rerank) with provenance.
4. **corpus-stats / corpus-anecdotes / corpus-brief** — xlsx / clustered anecdotes / decision brief.

## CLI (the deterministic glue)
```
.venv/bin/python cli.py init <corpus>
.venv/bin/python cli.py ingest-stats <corpus> --fred UNRATE
.venv/bin/python cli.py ingest-reddit <corpus> stocks --limit 100
.venv/bin/python cli.py ingest-url <corpus> "https://..." --tier 2
.venv/bin/python cli.py ingest-file <corpus> /path/to/text --tier 2 --source-url "<original url>"
.venv/bin/python cli.py chunk-embed <corpus> && .venv/bin/python cli.py build-fts <corpus>
.venv/bin/python cli.py query <corpus> "your question" --k 10 --rerank
.venv/bin/python cli.py prov <corpus> <claim_id>
```
Also: `shards`, `load-extraction`, `resolve-conflicts` — see `.venv/bin/python cli.py --help`.

## Architecture
- **Raw store** — content-addressed blobs (`raw/blobs/<sha256>`) + append-only `raw/manifest.jsonl`.
- **Structured** — DuckDB (`meta/index.duckdb`): sources → documents → chunks → claims → claim_evidence (the provenance FK chain) + stats_series.
- **Vector** — sqlite-vec (`meta/vectors.sqlite`); `embed_id` joins back to chunks.
- Corpora live under `$CORPUS_ROOT` (default `~/corpus/`), **machine-local and gitignored**.

## Design rule
No claim ships without a resolvable footnote: the loader rejects any extracted quote that does
not appear verbatim in the stored source text, and confidence is derived from source tiers.

## License
MIT — see `LICENSE`. The pipeline only fetches and consolidates; respect each source's terms.
