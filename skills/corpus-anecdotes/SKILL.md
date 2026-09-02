---
name: corpus-anecdotes
description: Cluster qualitative user anecdotes (Reddit/X/forum chunks) from a webcollect corpus into themes with sentiment and verbatim representative quotes (each linked to source). Use for "what are people saying about X".
allowed-tools: [Bash, Read, Workflow, Skill]
---

# corpus-anecdotes (D2)

Social-tier passages → themed clusters → sentiment + representative quotes with links.

## 1. Retrieve social passages on the topic
```
cd ~/test/webcollect
.venv/bin/python cli.py query <corpus> "<topic>" --k 80 --tier-max 5
```
(Or pull all social chunks: `duckdb <corpus>/meta/index.duckdb "SELECT c.chunk_id,c.text,d.source_url FROM chunks c JOIN documents d ON d.doc_id=c.doc_id WHERE d.channel IN ('reddit','x')"`.)

## 2. Cluster (sklearn over local embeddings)
Concrete inline approach — embed the retrieved texts and KMeans them:
```python
from sentence_transformers import SentenceTransformer
from sklearn.cluster import KMeans
import numpy as np
m = SentenceTransformer("BAAI/bge-small-en-v1.5")
X = m.encode(texts, normalize_embeddings=True)
k = min(8, max(2, len(texts)//10))
labels = KMeans(n_clusters=k, n_init=10, random_state=0).fit_predict(X)
```
(For variable cluster counts use HDBSCAN; KMeans is the simple default.)

## 3. Label + sentiment (Workflow fan-out)
One subagent per cluster: name the theme, assign sentiment (−1/0/+1), and pick 2–3
**verbatim** quotes that exist in the cluster's chunks. Run clusters in parallel via the
Workflow tool ($0). Reject any quote not found verbatim in a chunk.

## 4. Render
Build a markdown report (one section per cluster: theme · size · mean sentiment · quotes),
each quote as `[“…verbatim…”](source_url) (retrieved <date>, <content_hash>)`. Convert to
PDF via the **make-pdf** skill. Optional: an **xlsx** dump of every post with its cluster + sentiment.

X content is tier-4 best-effort; if absent, this runs Reddit-only.
