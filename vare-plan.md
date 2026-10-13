# Väre - plan

Qloo Agentic Hackathon. Deadline Oct 30 2026, 23:45 EDT.
Event: https://qloo.devpost.com/
Build spec: `claude/qloo/VARE_BUILD.md`

## What

**Väre** (Finnish: ripple, the shimmer something casts on its surroundings) is a cultural tag discovery tool that tests one honest question: can Qloo's taste graph surface connections a plain LLM misses?

The tool runs two pipelines on the same text and shows both outputs side by side. Path A is a conventional LLM tag generator. Path B extracts cultural references, resolves them through Qloo, queries Insights for associations, and builds an evidence-grounded tag set.

The user sees both outputs at once and can judge the difference themselves. The tool never claims Path B is better. It shows what it found and where it came from.

## Why Väre

The word fits: a cultural signal is not the thing in the text, it is what the thing ripples out into - adjacent communities, histories, interests. Väre is the ripple, not the stone.

Short, pronounceable in English, unused in the portfolio.

## Prizes

$25,000 total: $15,000 / $6,000 / $4,000. Jason Calacanis personal $25,000 bonus for his favourite. The tool does not have startup shape, so the Calacanis bonus is not the target. The $15,000 is.

## Judging criteria

- Technological implementation: how thoroughly Qloo is used, working non-trivial build
- Design: complete coherent product, not a proof of concept
- Potential impact: credible real audience with a real problem
- Quality of idea: creative non-obvious use of Qloo

Väre scores well on criteria 1 (full pipeline, advanced trace), reasonably on 2 (simple but complete UI), less well on 3 (the audience is content creators, not a massive vertical), and well on 4 (A/B comparison is unusual; most entries will just be "Qloo made my agent tasteful").

## Concept

Core hypothesis: "Can cultural intelligence reveal useful connections that a conventional LLM tag generator does not identify?"

The answer is currently unknown. The product makes it testable.

Four marker levels (borrowed from the Lupa architecture):
- ◆ LLM: conventional generation
- ● Qloo entity/tag resolved: a candidate the API confirmed
- ◆● Qloo Insights: an association from the taste graph
- ■ Evidence: traceable phrase from the input text

Every tag in Path B carries a marker showing which level it came from.

## Plan B

If Qloo-assisted tags do not add value, pivot to topic mode: instead of extra tags, Väre suggests adjacent cultural topics the creator could explore. Same pipeline, different output objective. Topic mode is built alongside tag mode from the beginning.

## First check

Get the Qloo API key from the developer guide. Run the S0 spike before writing any pipeline code. The spike confirms the actual endpoint structure, auth method and response shapes - none of which are verified from the hackathon page alone.

## Architecture overview

```
POST /api/generate
  |
  +-- Path A (asyncio) --> baseline LLM --> TagItem[]
  |
  +-- Path B (asyncio) --> extractor --> resolver --> insights --> selector --> generator --> TagItem[]
  |
  --> Comparison (overlap_count, novelty_count)
  --> Trace (when advanced=True)
```

Stack: Python 3.12, FastAPI, async httpx, pydantic v2, SQLite (trace log, dev only). Frontend: single-page vanilla JS. Hosting: Railway or Fly.io.

## Prior art note

Generic hashtag generators are everywhere. What's unusual here: the A/B comparison built in, the advanced trace that exposes the actual API calls, and the honest benchmark that documents whether the experiment worked. Most Qloo hackathon entries will be "I gave my agent cultural taste." Väre is "I built a tool that tests whether cultural taste adds anything."

## Slices

S0 - Qloo API spike (before anything else)
S1 - Skeleton (repo, health, stub data, UI shell)
S2 - Baseline path working
S3 - Extractor and resolver
S4 - Insights and selector
S5 - Full two-column comparison working
S6 - Advanced mode trace
S7 - Topic mode
S8 - Hosting, benchmark, submission prep
S9 (stretch) - Benchmark evaluation and documented decision

Detail in `VARE_BUILD.md`.
