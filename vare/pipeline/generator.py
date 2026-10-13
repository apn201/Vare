"""Stage 5: the LLM chooses from the shortlist and explains each choice.

Qloo supplies the vocabulary, the LLM knows the post. The model picks the
8-14 shortlisted tags that fit this particular text and writes one
evidence-bound sentence for each. It cannot add a tag: anything not on the
shortlist is discarded and recorded (hallucination guard). The tag string,
source and evidence always come from the shortlist, never from the model, and
the subject is always kept.
"""

from __future__ import annotations

from ..llm.client import LLMClient, render
from ..schema import PathResult, PoolItem, TagItem
from . import llm_json_stage, normalise
from .trace import Trace

LABEL = "Qloo-assisted"
MAX_FINAL = 14


def evidence_block(selected: list[PoolItem]) -> str:
    lines = []
    for p in selected:
        role = f" [{p.role}]" if p.role and p.source in ("qloo_direct", "llm") else ""
        kind = (p.qloo_type or "").replace("urn:tag:", "").replace("urn:entity:", "")
        if p.source == "qloo_direct":
            how = f"{p.evidence or p.origin}; confirmed in Qloo as {kind}"
        elif p.source == "qloo_profile":
            how = f"{p.evidence} ({kind})"
        elif p.source == "qloo_inferred":
            how = f"{p.evidence} ({kind})"
        else:
            how = f"found in text as \"{p.evidence or p.origin}\"; not found in Qloo"
        lines.append(f"- {p.tag}{role}: {how}")
    return "\n".join(lines)


async def run(llm: LLMClient, text: str, destination: str, selected: list[PoolItem], trace: Trace) -> PathResult:
    if not selected:
        return PathResult(tags=[], count=0, label=LABEL,
                          error="No cultural references survived extraction and Qloo resolution, so there is nothing to show.")
    prompt = render("final", text=text, destination=destination, evidence_block=evidence_block(selected))
    parsed, stage = await llm_json_stage(llm, trace, "B5 generate: choose and explain", prompt)
    if stage.error:
        return PathResult(tags=[], count=0, label=LABEL, error=stage.error)
    if not isinstance(parsed, list):
        stage.error = "expected a JSON array"
        return PathResult(tags=[], count=0, label=LABEL, error=f"generator: {stage.error}")

    by_key = {normalise(p.tag): p for p in selected}
    out: list[TagItem] = []
    discarded, seen = [], set()
    for item in parsed:
        if not isinstance(item, dict):
            continue
        key = normalise(str(item.get("tag") or ""))
        p = by_key.get(key)
        if p is None:
            discarded.append({"tag": item.get("tag"), "reason": "not on the shortlist (hallucination guard)"})
            continue
        if key in seen:
            continue
        if len(out) >= MAX_FINAL:
            discarded.append({"tag": p.tag, "reason": f"over {MAX_FINAL} tags"})
            continue
        seen.add(key)
        out.append(TagItem(tag=p.tag, explanation=str(item.get("explanation") or "").strip()[:300],
                           source=p.source, evidence=p.evidence))

    # code decides: the subject stays even if the model dropped it
    subject = next((p for p in selected if p.role == "subject" and p.source in ("qloo_direct", "llm")), None)
    if subject is not None and normalise(subject.tag) not in seen:
        seen.add(normalise(subject.tag))
        out.insert(0, TagItem(tag=subject.tag, source=subject.source, evidence=subject.evidence,
                              explanation="The main subject of the text" +
                              (", confirmed in Qloo." if subject.source == "qloo_direct" else ".")))

    omitted = [{"tag": p.tag, "reason": "not chosen for this post"} for k, p in by_key.items() if k not in seen]
    stage.selected = [t.tag for t in out]
    stage.rejected = (discarded + omitted) or None
    return PathResult(tags=out, count=len(out), label=LABEL)
