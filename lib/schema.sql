-- webcollect structured store (DuckDB). The provenance FK chain is the core:
--   claims <- claim_evidence -> chunks -> documents -> (manifest.jsonl raw blob) + sources
-- FKs are kept as plain columns (no hard constraints) so insert order is flexible;
-- lib/provenance.py walks the chain by join. Every output claim resolves to a
-- verbatim quote + exact char span + source_url + retrieved_at + content_hash.

CREATE TABLE IF NOT EXISTS sources (
  source_id     TEXT PRIMARY KEY,          -- 'reddit:r/stocks', 'fred:UNRATE', 'web:reuters.com'
  kind          TEXT NOT NULL,             -- rss|youtube|reddit|x|web|pdf|api|earnings_call
  display_name  TEXT,
  home_url      TEXT,
  tier          SMALLINT NOT NULL DEFAULT 3,   -- 1 official .. 5 anon social (precedence)
  trust_weight  DOUBLE   NOT NULL DEFAULT 0.5,
  added_at      TIMESTAMP DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS documents (
  doc_id        TEXT PRIMARY KEY,          -- 'doc_'||substr(content_hash,1,16)
  source_id     TEXT,
  retrieval_id  TEXT NOT NULL,             -- -> raw/manifest.jsonl retrieval event
  channel       TEXT,                      -- stats|reddit|x|web
  source_url    TEXT NOT NULL,
  canonical_url TEXT,
  content_hash  TEXT NOT NULL UNIQUE,      -- sha256 of raw blob
  norm_hash     TEXT,                      -- sha256 of normalized text (offsets are vs this)
  blob_path     TEXT NOT NULL,
  media_type    TEXT,
  title         TEXT,
  author        TEXT,
  published_at  TIMESTAMP,
  retrieved_at  TIMESTAMP NOT NULL,
  lang          TEXT,
  token_count   INTEGER,
  char_count    INTEGER,
  source_tier   SMALLINT DEFAULT 3,
  dedup_of      TEXT,                      -- canonical doc_id if near-dup; NULL if canonical
  ingest_status TEXT DEFAULT 'parsed'      -- parsed|chunked|extracted|superseded
);

CREATE TABLE IF NOT EXISTS chunks (
  chunk_id     TEXT PRIMARY KEY,           -- 'doc_xxx#0007'
  doc_id       TEXT NOT NULL,
  ord          INTEGER NOT NULL,
  char_start   INTEGER NOT NULL,           -- offset into normalized doc text
  char_end     INTEGER NOT NULL,
  token_count  INTEGER,
  text         TEXT NOT NULL,              -- == norm_text[char_start:char_end]
  section_path TEXT,
  embed_id     BIGINT                      -- rowid into vectors.sqlite vec_chunks
);

CREATE TABLE IF NOT EXISTS entities (
  entity_id   TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  entity_type TEXT,                        -- company|person|ticker|product|topic
  aliases     TEXT[],
  ticker      TEXT
);

CREATE TABLE IF NOT EXISTS claims (
  claim_id            TEXT PRIMARY KEY,
  canonical_text      TEXT NOT NULL,
  claim_type          TEXT,                -- metric|event|forecast|opinion|relationship
  subject_entity      TEXT,
  predicate           TEXT,
  value_raw           TEXT,
  value_num           DOUBLE,
  value_unit          TEXT,
  polarity            SMALLINT,            -- -1/0/+1
  resolved_status     TEXT DEFAULT 'single',  -- single|corroborated|contested|resolved
  resolved_value      TEXT,
  corroboration_count INTEGER DEFAULT 1,
  first_seen_at       TIMESTAMP,
  last_seen_at        TIMESTAMP
);

-- PROVENANCE join table: every claim links to the exact chunk + verbatim span + doc
CREATE TABLE IF NOT EXISTS claim_evidence (
  evidence_id  TEXT PRIMARY KEY,
  claim_id     TEXT NOT NULL,
  chunk_id     TEXT NOT NULL,
  doc_id       TEXT NOT NULL,
  quote        TEXT NOT NULL,              -- verbatim supporting text
  char_start   INTEGER NOT NULL,           -- absolute offset in normalized doc text
  char_end     INTEGER NOT NULL,
  stance       SMALLINT DEFAULT 1,         -- +1 supports / -1 dissents from resolved_value
  extractor    TEXT,
  extracted_at TIMESTAMP DEFAULT current_timestamp
);

-- statistics time-series (primary-first; revisions append a new vintage row)
CREATE TABLE IF NOT EXISTS stats_series (
  source         TEXT NOT NULL,            -- fred|sec|finnhub|bls|census|worldbank|oecd
  series_id      TEXT NOT NULL,
  period         TEXT NOT NULL,            -- ISO date / quarter label
  vintage        TEXT NOT NULL DEFAULT 'latest',
  value          DOUBLE,
  units          TEXT,
  primary_url    TEXT,
  crosscheck_url TEXT,
  verification   TEXT,                     -- match|within_tolerance|mismatch
  delta          DOUBLE,
  retrieved_at   TIMESTAMP,
  PRIMARY KEY (source, series_id, period, vintage)
);

-- a view exposing contested claims (dissent surfaced for briefs' open-questions)
CREATE OR REPLACE VIEW contested_claims AS
  SELECT * FROM claims WHERE resolved_status = 'contested';
