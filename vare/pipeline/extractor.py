"""Stage 1: the LLM reads the text: what it is about (subject), its domains,
and every cultural reference typed for a Qloo lookup and given a role.

The roles let code keep comparisons and allusions ("felt like Kubrick",
"a Cinderella story") out of the tags. Implied references (the director of a
named film) are allowed but capped, and only count once Qloo confirms them."""

from __future__ import annotations

from ..llm.client import LLMClient, render
from ..qloo.types import ALL_EXTRACTOR_TYPES, DOMAIN_TYPES
from ..schema import ROLES, Candidate
from . import llm_json_stage, normalise
from .trace import Trace

MAX_CANDIDATES = 10
MAX_IMPLIED = 2


def parse_candidates(parsed: object) -> tuple[list[Candidate], list[dict]]:
    """Validate the extractor's JSON. Returns (kept, rejected-with-reason)."""
    kept: list[Candidate] = []
    rejected: list[dict] = []
    if not isinstance(parsed, list):
        return kept, [{"item": parsed, "reason": "not a JSON array"}]
    seen: set[str] = set()
    for item in parsed:
        if not isinstance(item, dict) or not str(item.get("name") or "").strip():
            rejected.append({"item": item, "reason": "missing name"})
            continue
        name = str(item["name"]).strip()
        qtype = str(item.get("qloo_type") or "none").strip()
        if qtype not in ALL_EXTRACTOR_TYPES:
            rejected.append({"item": name, "reason": f"unknown qloo_type {qtype!r}, treated as none"})
            qtype = "none"
        conf = str(item.get("confidence") or "medium").lower()
        if conf not in ("high", "medium", "low"):
            conf = "medium"
        role = str(item.get("role") or "context").lower()
        if role not in ROLES:
            rejected.append({"item": name, "reason": f"unknown role {role!r}, treated as context"})
            role = "context"
        implied = bool(item.get("implied", False))
        if implied and role not in ("creator", "cast"):
            rejected.append({"item": name, "reason": f"implied {role} not allowed (only creator or cast)"})
            continue
        if implied and sum(c.implied for c in kept) >= MAX_IMPLIED:
            rejected.append({"item": name, "reason": f"more than {MAX_IMPLIED} implied references"})
            continue
        key = normalise(name)
        if not key or key in seen:
            continue
        seen.add(key)
        kept.append(Candidate(
            name=name,
            qloo_type=qtype,
            evidence=str(item.get("evidence") or "").strip(),
            confidence=conf,  # type: ignore[arg-type]
            ambiguous=bool(item.get("ambiguous", False)),
            role=role,  # type: ignore[arg-type]
            implied=implied,
        ))
    # exactly one subject: the first one named; any others become context
    subjects = [c for c in kept if c.role == "subject"]
    for c in subjects[1:]:
        c.role = "context"
    return kept, rejected


def apply_subject(parsed: object, cands: list[Candidate]) -> list[Candidate]:
    """Make sure the declared subject is a candidate with role subject, first."""
    subj = parsed.get("subject") if isinstance(parsed, dict) else None
    if isinstance(subj, dict) and str(subj.get("name") or "").strip():
        key = normalise(str(subj["name"]))
        match = next((c for c in cands if normalise(c.name) == key), None)
        if match is None:
            qtype = str(subj.get("qloo_type") or "none")
            match = Candidate(name=str(subj["name"]).strip(), qloo_type=qtype if qtype in ALL_EXTRACTOR_TYPES else "none",
                              evidence=str(subj["name"]).strip(), confidence="high")
            cands = [match] + cands
        for c in cands:
            if c.role == "subject" and c is not match:
                c.role = "context"
        match.role = "subject"
    subject = [c for c in cands if c.role == "subject"]
    return subject + [c for c in cands if c.role != "subject"]


def parse_domains(parsed: object) -> tuple[list[str], list[dict]]:
    """The text's main domains, mapped to Qloo entity URNs. Unknown values are
    rejected, not guessed."""
    if not isinstance(parsed, dict):
        return [], []
    out, rejected = [], []
    for d in parsed.get("domains") or []:
        urn = DOMAIN_TYPES.get(str(d).strip().lower().removeprefix("urn:entity:"))
        if urn is None:
            rejected.append({"item": d, "reason": "unknown domain"})
        elif urn not in out:
            out.append(urn)
    return out[:3], rejected


def drop_low_confidence(cands: list[Candidate]) -> tuple[list[Candidate], list[Candidate]]:
    """Spec: drop `low` unless fewer than 3 would remain."""
    strong = [c for c in cands if c.confidence != "low"]
    if len(strong) < 3:
        return cands, []
    return strong, [c for c in cands if c.confidence == "low"]


async def run(llm: LLMClient, text: str, trace: Trace) -> tuple[list[Candidate], list[str], str | None]:
    """Returns (candidates, domains, error)."""
    prompt = render("extract", text=text)
    parsed, stage = await llm_json_stage(llm, trace, "B1 extract: cultural references", prompt)
    if stage.error:
        return [], [], stage.error
    domains, rejected = parse_domains(parsed)
    refs = parsed.get("references") if isinstance(parsed, dict) else parsed
    cands, rej = parse_candidates(refs)
    rejected += rej
    cands = apply_subject(parsed, cands)
    cands, low = drop_low_confidence(cands)
    rejected += [{"item": c.name, "reason": "low confidence"} for c in low]
    if len(cands) > MAX_CANDIDATES:
        rejected += [{"item": c.name, "reason": f"over the {MAX_CANDIDATES}-candidate limit"} for c in cands[MAX_CANDIDATES:]]
        cands = cands[:MAX_CANDIDATES]
    stage.response_summary = {**(stage.response_summary or {}), "domains": domains}
    stage.selected = [{"name": c.name, "role": c.role, "qloo_type": c.qloo_type, "confidence": c.confidence,
                       "implied": c.implied, "ambiguous": c.ambiguous, "evidence": c.evidence} for c in cands]
    stage.rejected = rejected or None
    return cands, domains, None
