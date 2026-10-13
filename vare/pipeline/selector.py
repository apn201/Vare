"""Stage 4: deterministic shortlist. No LLM here.

Pool:
- each reference's own name: qloo_direct when Qloo confirmed it, llm when not
- the subject's Qloo profile tags (qloo_profile)
- Insights tag associations (qloo_inferred)

Out before scoring, each with its reason:
- comparisons and allusions ("felt like Kubrick", "a Cinderella story")
- implied references Qloo could not confirm

Score = text_relevance * 2 + cultural_depth + specificity + about_subject
  text_relevance  2 exact phrase in text, 1 stem match, 0 none
  cultural_depth  1 if the tag came from Qloo data about another reference
  specificity     1 named entity / specific tag type, 0 generic
  about_subject   1 if it is the subject or Qloo data about the subject

Ties: more references agreeing (support), then tag kind (genre > style >
theme > keyword), then Qloo's own order. Near-duplicates dropped, caps per
source, MAX_SHORTLIST kept. The subject is always on the shortlist.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from ..qloo.types import QLOO_ENTITY_TYPES, is_generic_tag_type
from ..schema import SIDE_ROLES, Candidate, PoolItem, TraceStage
from . import normalise
from .trace import Trace

MAX_SHORTLIST = 20
MAX_PROFILE = 14
PER_ORIGIN = 3
MIN_INFERRED_SCORE = 2
DUP_RATIO = 0.88
SPECIFIC_LLM_TYPES = QLOO_ENTITY_TYPES | {"subculture", "movement", "genre", "cuisine"}
QLOO_DERIVED = ("qloo_profile", "qloo_inferred")


def _words(s: str) -> list[str]:
    return re.findall(r"[0-9a-zÀ-ɏ]+", s.lower())


def text_relevance(tag: str, text: str, exclude: str | None = None) -> int:
    """`exclude` removes the source reference's own phrase first, so a derived
    tag cannot score a text match off the name it came from
    ("Dystopian Futures" must not match "Future" in "Future Crew")."""
    if exclude:
        text = re.sub(re.escape(exclude), " ", text, flags=re.I)
    low = text.lower()
    phrase = tag.lower().strip()
    if phrase and re.search(r"(?<![0-9a-z])" + re.escape(phrase) + r"(?![0-9a-z])", low):
        return 2
    if normalise(tag) and normalise(tag) in normalise(text) and len(normalise(tag)) >= 5:
        return 2   # "demo scene" vs "demoscene"
    text_words = _words(text)
    for w in _words(tag):
        if len(w) < 4:
            continue
        stem = w[:5]
        if any(tw.startswith(stem) for tw in text_words if len(tw) >= 4):
            return 1
    return 0


def is_dup(a: str, b: str) -> bool:
    """Same tag in other clothes: spelling variants ("demoszene"), spacing
    ("demo scene"), or one wrapping the other ("demoscene music")."""
    na, nb = normalise(a), normalise(b)
    if na == nb or SequenceMatcher(None, na, nb).ratio() >= DUP_RATIO:
        return True
    short, long_ = sorted((na, nb), key=len)
    return len(short) >= 5 and short in long_


def prefilter(cands: list[Candidate]) -> tuple[list[Candidate], list[dict]]:
    kept, rejected = [], []
    for c in cands:
        if c.role in SIDE_ROLES:
            rejected.append({"tag": c.name, "source": "llm", "reason": f"{c.role}: mentioned, not what the text is about"})
        elif c.implied and not c.resolved:
            rejected.append({"tag": c.name, "source": "llm", "reason": "implied by the LLM, not confirmed by Qloo"})
        else:
            kept.append(c)
    return kept, rejected


def build_pool(cands: list[Candidate], text: str) -> list[PoolItem]:
    pool: list[PoolItem] = []
    derived: list[PoolItem] = []
    for c in cands:
        about_subject = c.role == "subject"
        if c.resolved:
            spec = 1 if c.qloo_kind == "entity" or not is_generic_tag_type(c.qloo_resolved_type) else 0
            evidence = (f"not named in the text: {c.evidence}; confirmed in Qloo" if c.implied else c.evidence) or None
            item = PoolItem(tag=c.qloo_name or c.name, source="qloo_direct", evidence=evidence, origin=c.name,
                            role=c.role, qloo_id=c.qloo_id, qloo_type=c.qloo_resolved_type, specificity=spec)
        else:
            spec = 1 if c.qloo_type in SPECIFIC_LLM_TYPES else 0
            item = PoolItem(tag=c.name, source="llm", evidence=c.evidence or None, origin=c.name,
                            role=c.role, specificity=spec)
        item.text_relevance = max(text_relevance(item.tag, text), text_relevance(c.name, text))
        item.about_subject = int(about_subject)
        pool.append(item)
        origin = c.qloo_name or c.name
        for a in sorted(c.qloo_associations, key=lambda a: a.kind != "profile"):
            if a.kind == "entity":
                continue
            profile = a.kind == "profile"
            derived.append(PoolItem(
                tag=a.name, source="qloo_profile" if profile else "qloo_inferred", origin=origin, role=c.role,
                evidence=(f"Qloo profile of {origin}" if profile else f"Qloo Insights: associated with {origin}"),
                qloo_id=a.id, qloo_type=a.type, affinity=a.affinity, rank=a.rank,
                text_relevance=text_relevance(a.name, text, exclude=c.evidence or c.name), cultural_depth=1,
                specificity=0 if is_generic_tag_type(a.type) else 1, about_subject=int(about_subject),
            ))
    pool += merge_support(derived)
    for p in pool:
        p.score = p.text_relevance * 2 + p.cultural_depth + p.specificity + p.about_subject
    return pool


def merge_support(items: list[PoolItem]) -> list[PoolItem]:
    """The same Qloo tag reached from several references, or from both the
    profile and Insights, is one tag with more support (Billie Eilish and
    Lorde both -> "indie pop"). The first source seen (profile) is kept."""
    out: list[PoolItem] = []
    by_key: dict[str, PoolItem] = {}
    for p in items:
        key = normalise(p.tag)
        first = by_key.get(key)
        if first is None:
            by_key[key] = p
            out.append(p)
            continue
        if p.origin in first.origin.split(" + ") and p.source == first.source:
            continue
        first.support += 1
        if p.origin not in first.origin.split(" + "):
            first.origin += " + " + p.origin
        first.evidence += f"; also {p.evidence[0].lower()}{p.evidence[1:]}"
        first.rank = min(first.rank, p.rank)
        first.text_relevance = max(first.text_relevance, p.text_relevance)
        first.about_subject = max(first.about_subject, p.about_subject)
    return out


TYPE_PRIORITY = (("urn:tag:subgenre:", 0), ("urn:tag:genre:", 0), ("urn:tag:style:", 1), ("urn:tag:music:", 1),
                 ("urn:tag:theme:", 2), ("urn:tag:keyword:", 3))


def type_priority(t: str | None) -> int:
    return next((v for prefix, v in TYPE_PRIORITY if t and t.startswith(prefix)), 4)


def select(pool: list[PoolItem]) -> tuple[list[PoolItem], list[dict]]:
    # ties: more references agreeing, then tag kind, then Qloo's own order.
    # Not affinity: in practice most associations come back at 1.00.
    # Profile tags arrive already balanced across kinds (entity_tags quotas),
    # so their own rank is kept rather than re-sorted by kind here.
    order = sorted(enumerate(pool), key=lambda x: (
        -x[1].score, -x[1].support,
        0 if x[1].source == "qloo_profile" else type_priority(x[1].qloo_type),
        x[1].rank, x[0]))
    subject = next((p for p in pool if p.role == "subject" and p.source in ("qloo_direct", "llm")), None)
    kept: list[PoolItem] = [subject] if subject else []
    rejected: list[dict] = []
    per_origin: dict[str, int] = {}
    profile_n = 0
    for _, p in order:
        if p is subject:
            continue
        why = None
        dup = next((k for k in kept if is_dup(k.tag, p.tag)), None)
        if dup is not None and dup.source in QLOO_DERIVED and p.source in QLOO_DERIVED \
                and normalise(dup.tag) in normalise(p.tag) and len(p.tag) > len(dup.tag):
            # two Qloo tags, one wrapping the other: keep the specific one
            # ("Science Fiction" over "Fiction"), carrying the support over
            p.support = max(p.support, dup.support)
            kept[kept.index(dup)] = p
            rejected.append({"tag": dup.tag, "source": dup.source, "score": dup.score,
                             "reason": f"less specific than '{p.tag}'"})
            continue
        if dup is not None:
            why = f"near-duplicate of '{dup.tag}'"
        elif p.source in QLOO_DERIVED and p.score < MIN_INFERRED_SCORE:
            why = f"score {p.score} below {MIN_INFERRED_SCORE} (generic tag type, not in text)"
        elif p.source == "qloo_profile" and profile_n >= MAX_PROFILE:
            why = f"already {MAX_PROFILE} profile tags"
        elif p.source == "qloo_inferred" and p.support == 1 and per_origin.get(p.origin, 0) >= PER_ORIGIN:
            why = f"already {PER_ORIGIN} inferred tags from '{p.origin}'"
        elif len(kept) >= MAX_SHORTLIST:
            why = f"outside top {MAX_SHORTLIST}"
        if why:
            rejected.append({"tag": p.tag, "source": p.source, "score": p.score, "reason": why})
            continue
        kept.append(p)
        if p.source == "qloo_profile":
            profile_n += 1
        elif p.source == "qloo_inferred":
            per_origin[p.origin] = per_origin.get(p.origin, 0) + 1
    return kept, rejected


def _row(p: PoolItem) -> dict:
    return {"tag": p.tag, "source": p.source, "role": p.role, "score": p.score, "text_relevance": p.text_relevance,
            "cultural_depth": p.cultural_depth, "specificity": p.specificity, "about_subject": p.about_subject,
            "support": p.support, "origin": p.origin, "qloo_type": p.qloo_type}


def run(cands: list[Candidate], text: str, trace: Trace) -> list[PoolItem]:
    cands, early = prefilter(cands)
    pool = build_pool(cands, text)
    kept, rejected = select(pool)
    rejected = early + rejected
    trace.add(TraceStage(
        stage="B4 select: deterministic shortlist",
        params={"formula": "text_relevance*2 + cultural_depth + specificity + about_subject",
                "tie_break": "support (references agreeing), tag kind (genre > style > theme > keyword), Qloo rank",
                "max_shortlist": MAX_SHORTLIST, "max_profile": MAX_PROFILE,
                "per_origin": PER_ORIGIN, "min_derived_score": MIN_INFERRED_SCORE},
        response_summary={"pool": len(pool), "shortlisted": len(kept), "rejected": len(rejected)},
        selected=[_row(p) for p in kept] or None,
        rejected=rejected or None,
    ))
    return kept
