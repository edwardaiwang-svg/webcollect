---
name: corpus-brief
description: Produce a decision-ready brief (.docx/PDF) from a consolidated webcollect corpus — TL;DR recommendation, corroborated key facts, trends, sentiment, conflicts/open-questions, confidence — with numbered footnotes back to every source. Use for "give me a brief / decision memo on X".
allowed-tools: [Bash, Read, Workflow, Skill]
---

# corpus-brief (D3)

The top-of-funnel deliverable. Synthesizes the consolidated corpus into a structured,
fully-cited brief and runs it through an adversarial review loop before finalizing.

## 1. Assemble inputs (reuse the other stages)
- Key facts: top conflict-resolved claims —
  `duckdb <corpus>/meta/index.duckdb "SELECT subject_entity,predicate,resolved_value,corroboration_count,resolved_status FROM claims WHERE resolved_status IN ('resolved','corroborated','contested') ORDER BY corroboration_count DESC LIMIT 50;"`
- Trends: from **corpus-stats** queries. Sentiment: from **corpus-anecdotes**.
- Open questions: `SELECT canonical_text FROM contested_claims;`
- Supporting passages: `.venv/bin/python cli.py query <corpus> "<decision question>" --k 20 --rerank`

## 2. Synthesize (Workflow, Opus, $0)
Fixed structure: **TL;DR recommendation → Key facts (each with corroboration_count) →
Trends → Sentiment → Conflicts & open-questions → Confidence rating** (from tier mix +
corroboration coverage). Every fact gets a footnote marker `[n]`.

## 3. Adversarial review loop (generalize digest-build Step 2.6)
Fan out lens-diverse reviewers via the Workflow tool — decision-readiness, bear case,
attribution integrity (every `[n]` resolves via `cli.py prov`), number/recency integrity —
then one revision pass. Block on any unresolved citation.

## 4. Render
Footnotes endnote each `[n]` with source_url, author, published_at, retrieved_at, tier,
verbatim quote; append a Sources table (every document + content_hash). Output via the
**docx** skill, or a PDF via the **pdf** skill.

## Rule
No claim ships without a resolvable footnote. Confidence must reflect source tiers, not vibes.
