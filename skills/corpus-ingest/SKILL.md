---
name: corpus-ingest
description: Acquire web sources (stats APIs, articles, Reddit, X best-effort) into a webcollect corpus's content-addressed raw store with full provenance. Use when collecting/gathering data, building a corpus, or pulling stats/anecdotes from the web.
allowed-tools: [Bash, Read, WebSearch, WebFetch, Skill]
---

# corpus-ingest

Pull sources into a webcollect corpus. Every fetch is hashed, blob-stored, logged
in `raw/manifest.jsonl`, and registered as a `documents` row — so every later claim
traces back to origin. Exact duplicates (same content_hash) are skipped automatically.

Run from the repo: `~/test/webcollect` with its venv: `.venv/bin/python cli.py ...`

## 0. Pick / create the corpus
```
.venv/bin/python cli.py init <corpus_id>          # English default (bge-small)
.venv/bin/python cli.py init <corpus_id> --zh     # multilingual (e5-small) for ZH content
```

## 1. Statistics — primary-first (free; API keys live in `.env`)
Prefer primaries from `config/metric_map.yaml`. Cross-check aggregators against them.
```
.venv/bin/python cli.py ingest-stats <corpus> --fred UNRATE --fred CPIAUCSL --finnhub NVDA
```
- FRED (macro), SEC EDGAR XBRL (filings), Finnhub (markets). Values land in `stats_series`
  (tier-1); the raw API JSON is stored as a provenance doc.
- For SEC/Census/BLS/World Bank/OECD beyond the CLI, fetch via WebFetch/curl then
  `ingest-file ... --tier 1`.

## 2. Articles / web pages (the cross-check + general web)
```
.venv/bin/python cli.py ingest-url <corpus> "https://www.reuters.com/..." --tier 2
```
For JS-heavy or blocked pages, fetch with WebFetch / curl (or any scraper you trust), save the
text, then:
```
.venv/bin/python cli.py ingest-file <corpus> /path/to/text --tier 2 --source-url "<original url>"
```
YouTube/podcasts: use **youtube-transcript** / **digest-source-fetch**, then `ingest-file`.

## 3. Reddit — the main anecdote channel (official OAuth API)
Needs `REDDIT_*` in `.env` (CLIENT_ID already registered; add SECRET/USERNAME/PASSWORD).
```
.venv/bin/python cli.py ingest-reddit <corpus> stocks --limit 100 --sort new
.venv/bin/python cli.py ingest-reddit <corpus> stocks --query "NVDA earnings" --comment-expand 1
```
Each post (title + body + flattened comment tree) is one tier-5 document. Seeds in
`config/subreddits.yaml`. ToS: personal research only; no redistribution/LLM-training.

## 4. X / Twitter — best-effort, tier-4 (no API)
- Hydrate a *specific cited tweet* by id: WebFetch `https://cdn.syndication.twimg.com/tweet-result?id=<ID>&token=x`, then `ingest-file --tier 4`.
- A small watchlist of accounts: use the **claude-in-chrome** MCP on J's logged-in session, save text, `ingest-file --tier 4`.
- Never make X a dependency; anecdote analysis degrades to Reddit-only.

## Next
After ingesting, run **corpus-consolidate** to chunk, embed, dedup, and extract claims.
