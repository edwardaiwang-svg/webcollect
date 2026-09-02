---
name: corpus-stats
description: Produce a provenance-complete statistical summary (.xlsx + optional chart PDF) from a consolidated webcollect corpus — numbers, trends, and a 1:1 source table. Use for "give me the numbers / stats on X".
allowed-tools: [Bash, Read, Skill]
---

# corpus-stats (D1)

Numbers → spreadsheet with every value traceable. Math is pure DuckDB (no LLM).

## 1. Pull the data (DuckDB)
Primary time-series:
```
duckdb <corpus>/meta/index.duckdb \
  "SELECT source, series_id, period, value, units, primary_url FROM stats_series ORDER BY series_id, period;"
```
Extracted numeric claims with provenance (the join that backs Sheet 2):
```
duckdb <corpus>/meta/index.duckdb "
 SELECT cl.claim_id, cl.subject_entity, cl.predicate, cl.value_num, cl.value_unit,
        cl.resolved_status, cl.resolved_value, cl.corroboration_count,
        d.source_url, d.published_at, d.retrieved_at, d.source_tier, e.quote, d.content_hash
 FROM claims cl JOIN claim_evidence e ON e.claim_id=cl.claim_id
 JOIN documents d ON d.doc_id=e.doc_id
 WHERE cl.claim_type='metric' ORDER BY cl.subject_entity, cl.predicate;"
```
(`<corpus>` = `$CORPUS_ROOT/<corpus_id>`, default `~/corpus/<corpus_id>`.)

## 2. Render with the xlsx skill
Invoke the **xlsx** skill to build a workbook:
- **Summary**: metric, conflict-resolved value, n, week/period delta, trend.
- **Provenance**: the second query above, one row per evidence (claim_id ↔ source_url ↔ content_hash ↔ quote).
- **Conflicts**: rows from `contested_claims` with their dissenting evidence.

Optional chart-pack: render trends to PDF via the **make-pdf** skill.

## Rule
Every Summary cell must reference a claim_id present in the Provenance sheet. Use
`resolved_value` for headline numbers; never emit a number without its source row.
