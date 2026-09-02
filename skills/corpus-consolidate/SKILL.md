---
name: corpus-consolidate
description: Turn a raw webcollect corpus into a queryable, deduplicated, conflict-resolved claim store with full provenance — chunk + embed + dedup, then map-reduce claim extraction via the Workflow tool. Use after corpus-ingest, or when asked to consolidate/process collected data.
allowed-tools: [Bash, Read, Write, Workflow, Task]
---

# corpus-consolidate

Raw documents → chunks + embeddings → extracted, span-verified, conflict-resolved
claims. Deterministic steps run via the CLI ($0); the claim extraction is a
map-reduce over the **Workflow tool** on the Max subscription ($0 marginal).

Run from `~/test/webcollect` with `.venv/bin/python cli.py ...`.

## 1. Deterministic prep (no LLM)
```
.venv/bin/python cli.py chunk-embed <corpus>     # chunk every 'parsed' doc, embed -> sqlite-vec
.venv/bin/python cli.py build-fts <corpus>        # BM25 keyword index (DuckDB FTS)
```

## 2. Plan the shards
```
.venv/bin/python cli.py shards <corpus> --shard-tokens 100000   # -> JSON: [{shard, chunk_ids[]}]
```
Each shard ≈ 100k tokens of chunks (comfortable Opus read-every-line headroom).

## 3. MAP — extract claims per shard (Workflow fan-out)
For each shard, read its chunks' text from DuckDB
(`SELECT chunk_id, text FROM chunks WHERE chunk_id IN (...)`) and run a subagent that
returns JSON matching `lib/schemas.py:ShardExtraction`:
```json
{"claims":[{"canonical_text":"...","claim_type":"metric|event|forecast|opinion|relationship",
  "subject":"NVDA","predicate":"revenue_q1","value_raw":"$26B","value_num":2.6e10,"value_unit":"USD",
  "polarity":1,"evidence":[{"chunk_id":"doc_x#0003","quote":"<verbatim>","char_start":N,"char_end":M,"stance":1}]}]}
```
**Iron contract:** every evidence `quote` MUST be verbatim from its `chunk_id`. Load each
shard's JSON — unverifiable spans are auto-rejected:
```
.venv/bin/python cli.py load-extraction <corpus> <a_doc_id_in_shard> shard_<i>.json
```
Use the Workflow tool to fan shards out in parallel (one map agent per shard; for
high-value corpora run 2–4 lens-diverse miners per shard: metrics / events / opinions).

## 4. REDUCE — resolve conflicts (deterministic)
```
.venv/bin/python cli.py resolve-conflicts <corpus>
```
Groups claims by (subject, predicate); winner by tier precedence + recency +
corroboration. **Dissent is preserved** as stance−1 evidence and surfaced via the
`contested_claims` view (feeds brief open-questions).

## 5. Verify
Spot-check provenance: `.venv/bin/python cli.py prov <corpus> <claim_id>` → must print a
verbatim quote + source_url + content_hash. Then run **corpus-query** / the output skills.
