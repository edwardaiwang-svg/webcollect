"""Pydantic schemas for the map-step extraction contract + span validation.

The map subagents (run by the corpus-consolidate skill via the Workflow tool)
return JSON matching ShardExtraction. validate_extraction() enforces the "iron
contract": a claim whose evidence quote does not actually appear at the stated
span of the referenced chunk is REJECTED (and re-queued once upstream).
"""
from __future__ import annotations
from pydantic import BaseModel, Field


class Evidence(BaseModel):
    chunk_id: str
    quote: str
    char_start: int
    char_end: int
    stance: int = 1


class ExtractedClaim(BaseModel):
    canonical_text: str
    claim_type: str = "opinion"  # metric|event|forecast|opinion|relationship
    subject: str | None = None
    predicate: str | None = None
    value_raw: str | None = None
    value_num: float | None = None
    value_unit: str | None = None
    polarity: int | None = None
    evidence: list[Evidence] = Field(default_factory=list)


class ShardExtraction(BaseModel):
    claims: list[ExtractedClaim] = Field(default_factory=list)


def validate_extraction(payload: dict, chunk_text_by_id: dict[str, str], fuzzy: int = 90):
    """Validate a shard extraction against the stored chunk texts.

    Returns (accepted: list[ExtractedClaim], rejected: list[dict]).
    A claim is accepted only if it has >=1 evidence row whose quote is found in
    its referenced chunk (exact substring, or fuzzy>=`fuzzy` as a fallback).
    """
    from rapidfuzz import fuzz

    parsed = ShardExtraction.model_validate(payload)
    accepted, rejected = [], []
    for claim in parsed.claims:
        good = []
        for ev in claim.evidence:
            ctext = chunk_text_by_id.get(ev.chunk_id)
            if ctext is None:
                continue
            if ev.quote and ev.quote in ctext:
                good.append(ev)
            elif ev.quote and fuzz.partial_ratio(ev.quote, ctext) >= fuzzy:
                good.append(ev)
        if good:
            claim.evidence = good
            accepted.append(claim)
        else:
            rejected.append({"claim": claim.canonical_text, "reason": "no verifiable evidence span"})
    return accepted, rejected
