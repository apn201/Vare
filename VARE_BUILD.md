# Väre - Build Specification

Qloo Agentic Hackathon. Deadline Oct 30 2026, 23:45 EDT.
Event page: https://qloo.devpost.com/
Prizes: $15,000 first, $6,000 second, $4,000 third. Jason Calacanis personal $25,000 bonus for his favourite.

Working name: **Väre**
Tagline: Find the tags hiding between the lines.

---

## 0. Rules governing every line of code

1. **No invented API data.** Every tag in the Qloo-assisted output must trace to an actual Qloo API response. If the API returned nothing, output nothing and say so.
2. **Honest baseline.** Path A uses the same LLM family as Path B. Do not weaken the baseline to flatter the experimental path.
3. **Model proposes, code decides.** LLM extracts candidates; Qloo resolves or rejects them; a deterministic filter applies relevance rules; the final generation prompt gets structured evidence, not speculation.
4. **No credentials in any output.** API keys, bearer tokens, and any header containing auth are stripped from the trace before it reaches the frontend.
5. **Fail loudly.** If any pipeline stage fails - LLM error, Qloo 429, timeout, empty result - represent the failure honestly in the output and the trace. Do not silently fall back to invented tags.
6. **No account required.** The tool is stateless from the user's perspective. No login, no session, no stored text by default.
7. **Every number from real data.** Tag counts, overlap counts, novelty counts: computed from the actual outputs, not hardcoded.
8. **Secrets gate.** Run `tools/check_secrets.py` from the Whyf pattern before any `git push`. CI must also run it.

---

## 1. Stack

- **Backend**: Python 3.12, FastAPI, uvicorn, pydantic v2, httpx (async), SQLite (trace log only)
- **LLM**: OpenAI-compatible endpoint, configurable via env `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`. Default model: `gpt-4o-mini` or any fast chat model. Same model for baseline and extraction stages.
- **Qloo API**: REST, JSON. Base URL `https://hackathon.api.qloo.com` (hackathon endpoint, not production). Auth: `X-Api-Key` header, value from env `QLOO_API_KEY`.
- **Frontend**: Single-page, vanilla JS + CSS. No framework. Served by FastAPI as static files. Must work in Firefox, Chrome, Safari.
- **Hosting**: Railway or Fly.io (one-command deploy, public URL). `railway.json` or `fly.toml` included.
- **Python deps**: `fastapi`, `uvicorn[standard]`, `pydantic`, `httpx`, `python-dotenv`
- **Dev deps**: `pytest`, `respx` (mock httpx), `pytest-asyncio`
- **Node**: not required for the app itself.

Env vars (all required; read from `.env` in dev, from platform secrets in prod):
```
QLOO_API_KEY=
QLOO_BASE_URL=https://hackathon.api.qloo.com
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=
LLM_MODEL=gpt-4o-mini
DEBUG_RETAIN_TRACES=false   # set true in dev to persist traces to SQLite
```

---

## 2. Repo layout

```
vare/
  vare/
    __init__.py
    main.py                  # FastAPI app, mounts static/, includes routers
    config.py                # Settings from env, pydantic BaseSettings
    schema.py                # All pydantic models (request, response, trace)
    pipeline/
      __init__.py
      baseline.py            # Path A: conventional LLM tag generation
      extractor.py           # Stage 1: extract cultural candidates from text
      resolver.py            # Stage 2: resolve candidates against Qloo /search or /tags
      entity_tags.py         # Stage 3: get related entities/tags via /v2/insights
      selector.py            # Stage 4: filter, rank, deduplicate candidates
      generator.py           # Stage 5: final LLM call with structured evidence
      trace.py               # Collect and sanitise per-stage trace records
    qloo/
      __init__.py
      client.py              # Async httpx client, auth header, error handling
      models.py              # Qloo response shapes (verified after S0)
      types.py               # QLOO_ENTITY_TYPES list and TAG_SEARCH_TYPES set
    llm/
      __init__.py
      client.py              # OpenAI-compatible async wrapper (port of virta/nebius_client.py)
      prompts/
        baseline.md          # Baseline tag generation prompt template
        extract.md           # Cultural reference extraction prompt template
        final.md             # Final tag generation with evidence prompt template
        topics.md            # Topic suggestion mode prompt template
    api/
      __init__.py
      generate.py            # POST /api/generate  (tag mode)
      health.py              # GET  /api/health
    static/
      index.html             # Single page, all UI
      style.css
      app.js
    db/
      schema.sql             # Trace log table (optional, dev only)
      db.py                  # SQLite connection, disabled when DEBUG_RETAIN_TRACES=false
  tests/
    conftest.py
    test_baseline.py
    test_extractor.py
    test_resolver.py
    test_entity_tags.py
    test_selector.py
    test_generator.py
    test_api.py              # End-to-end with respx mocks
  tools/
    check_secrets.py         # From Whyf: git history scan, exits 1 on leak
    check_publishable.py     # Working-tree scan
    benchmark.py             # Run benchmark set, print comparison table
  benchmark/
    texts/                   # 8+ .txt files, one input text per file
    results/                 # benchmark.py writes one .json per run here
  scripts/
    qloo_spike.py            # S0: standalone Qloo API probe (run before any pipeline code)
  private/                   # gitignored; .env goes here or in root
  .gitignore
  .env.example
  Makefile
  README.md
  LICENSE                    # MIT
  railway.json               # or fly.toml
  requirements.txt
  requirements-dev.txt
```

`.gitignore` must include: `.env`, `private/`, `benchmark/results/`, `__pycache__/`, `*.pyc`, `*.db`.

---

## 3. Data models (schema.py)

```python
class GenerateRequest(BaseModel):
    text: str                          # max 4000 chars, strip before use
    destination: str = "general"       # general | youtube | linkedin | instagram
    mode: str = "tags"                 # tags | topics
    advanced: bool = False             # whether to include trace in response

class TagItem(BaseModel):
    tag: str
    explanation: str                   # one sentence, evidence-grounded
    source: str                        # "llm" | "qloo_direct" | "qloo_inferred"
    evidence: str | None = None        # phrase from input text or Qloo entity name

class TopicItem(BaseModel):
    topic: str
    connection: str                    # why it connects to the input text
    cultural_basis: str                # what cultural signal supports it

class PathResult(BaseModel):
    tags: list[TagItem] | None = None
    topics: list[TopicItem] | None = None
    count: int
    label: str                         # "Conventional LLM" | "Qloo-assisted"
    error: str | None = None

class Comparison(BaseModel):
    baseline: PathResult
    experimental: PathResult
    overlap_count: int                 # tags in both (tag strings, normalised)
    novelty_count: int                 # in experimental only
    total_latency_ms: int

class TraceStage(BaseModel):
    stage: str
    prompt: str | None = None
    model: str | None = None
    endpoint: str | None = None
    method: str | None = None
    params: dict | None = None         # sanitised, no auth keys
    response_summary: dict | None = None
    raw_items: list | None = None
    selected: list | None = None
    rejected: list | None = None
    latency_ms: int | None = None
    tokens_used: int | None = None
    error: str | None = None

class GenerateResponse(BaseModel):
    request_id: str                    # uuid4
    comparison: Comparison
    trace: list[TraceStage] | None     # None when advanced=False
```

---

## 4. Qloo API integration (qloo/client.py and qloo/types.py)

**Verified from the @qloo/qloo-harness package dry-run output and schema.** These are the actual endpoints, not assumed ones.

### Base URL and auth

```
Base URL (hackathon): https://hackathon.api.qloo.com
Auth header: X-Api-Key: {QLOO_API_KEY}
```

The `QLOO_BASE_URL` env var controls this. Default to `https://hackathon.api.qloo.com`. Do not hardcode production (`https://api.qloo.com`).

### Verified endpoints

**Entity search**: `GET /search`
```
params:
  query: str           # search text
  take: int            # number of results, default 10
  type: str (optional) # entity type URN (see types below)
```
Returns a list of entities. Each entity has at minimum: id (UUID or URN), name, type.

**Entity detail**: `GET /entities`
```
params:
  entity_ids: list[str]  # one or more entity IDs
```

**Insights** (get related entities/tags): `GET /v2/insights`
```
params:
  filter.type: str                     # entity type URN, required
  signal.interests.entities: str       # comma-separated entity IDs
  signal.interests.tags: str           # comma-separated tag URNs
  take: int                            # default 10
```
This is the main call for finding what is culturally related to a resolved entity. The filter type (what kind of entity you want back) does not have to match the signal entity type - Insights crosses domains.

**Tag search**: `GET /tags`
```
params:
  query: str           # search text
  type: str (optional) # tag type filter
  take: int
```
Returns tag objects with URN, name, type.

**Audience compare**: `GET /v2/analysis/compare`
```
params:
  a.signal.interests.entities: str   # group A entity IDs
  b.signal.interests.entities: str   # group B entity IDs
  take: int
```

### Entity types (verified, from `qloo types`)

These are the exact strings Qloo accepts. No others exist.

```
urn:entity:movie
urn:entity:tv_show
urn:entity:book
urn:entity:brand
urn:entity:artist
urn:entity:person
urn:entity:actor
urn:entity:director
urn:entity:author
urn:entity:locality
urn:entity:videogame
urn:entity:podcast
urn:entity:place
```

The extractor LLM is given this exact list and picks one. No translation layer needed - its output goes directly into the API call.

Some types have no entity equivalent in Qloo: movements, subcultures, abstract concepts, genres, eras. These use tag search (`GET /tags`) instead of entity search. The `qloo/types.py` module defines which is which:

```python
# qloo/types.py

QLOO_ENTITY_TYPES = {
    "urn:entity:movie",
    "urn:entity:tv_show",
    "urn:entity:book",
    "urn:entity:brand",
    "urn:entity:artist",
    "urn:entity:person",
    "urn:entity:actor",
    "urn:entity:director",
    "urn:entity:author",
    "urn:entity:locality",
    "urn:entity:videogame",
    "urn:entity:podcast",
    "urn:entity:place",
}

# Types that are abstract or genre-level - use tag search, not entity search
TAG_SEARCH_TYPES = {
    "concept",
    "movement",
    "genre",
    "era",
    "subculture",
    "none",
}
```

### Client requirements

- Async httpx client, `QLOO_BASE_URL` from config, `X-Api-Key` header
- 10-second timeout per request
- Retry once on 429 with 2-second wait; on second 429 return error, stop
- On any non-2xx: return structured error `{status, body}`, never raise
- Log every request as a `TraceStage` with: endpoint path (not full URL), params (auth header stripped), status code, latency, response item count
- Strip from trace params and headers: any key or value containing `key`, `token`, `secret`, `auth`, `api`

### Stub mode

If `QLOO_API_KEY` is not set or is the literal string `stub`, all methods return empty results and log `stub_mode: true` in the trace stage. This allows UI and pipeline work without a live key.

---

## 5. LLM client (llm/client.py)

Port of `virta/nebius_client.py` from Apps\Virta. OpenAI-compatible, async. Handles the reasoning-model case where `message.content` is None and text is in `message.reasoning_content` (configurable field name). Returns `{content: str, model: str, tokens_used: int, latency_ms: int}`.

Prompt templates live in `llm/prompts/*.md`. Load at startup, cache. Use `{{variable}}` substitution. Keep as plain text - no f-strings in templates.

---

## 6. Pipeline stages

### Stage 0 (Path A): Baseline (pipeline/baseline.py)

Input: `text`, `destination`.

Call LLM with `prompts/baseline.md`. Return a JSON array of tag strings, no explanations. Parse strictly; on parse failure log and return error.

Wrap each as `TagItem(tag=t, explanation="", source="llm", evidence=None)`.

`prompts/baseline.md`:
```
You are a tag generator for {{destination}} content.

Generate a concise set of relevant tags for the text below.
- Return JSON only: a flat array of tag strings.
- 8 to 15 tags.
- Prioritise specific terms over generic ones.
- Do not explain your reasoning.
- Do not include hashtag symbols.

Text:
{{text}}
```

---

### Stage 1 (Path B): Cultural reference extraction (pipeline/extractor.py)

Input: `text`.

Call LLM with `prompts/extract.md`. The prompt gives the model the actual Qloo entity type list so it can assign types that map directly to API calls - no translation layer.

Return a JSON array of candidate objects:
- `name`: the cultural reference, concept or entity name
- `qloo_type`: one of the Qloo entity type URNs, or one of the tag-search types (`concept`, `movement`, `genre`, `era`, `subculture`, `none`)
- `evidence`: the phrase from the input text that supports this candidate
- `confidence`: `high | medium | low`
- `ambiguous`: bool

Filter out `confidence: low` candidates unless fewer than 3 total remain.

`prompts/extract.md`:
```
Extract cultural references, named entities and concepts from the text below.
A cultural intelligence system will look up each one in its knowledge graph using the type you assign.

Return JSON only: an array of objects with fields: name, qloo_type, evidence, confidence, ambiguous.

qloo_type must be exactly one of:
  urn:entity:movie       - a film
  urn:entity:tv_show     - a television show or series
  urn:entity:book        - a book or written work
  urn:entity:brand       - a brand, company, product line, or technology platform
  urn:entity:artist      - a musical artist, band, or performer
  urn:entity:person      - a real person not better described by a more specific type
  urn:entity:actor       - an actor or actress
  urn:entity:director    - a film or TV director
  urn:entity:author      - a book author
  urn:entity:locality    - a city, region, or broad geographic area
  urn:entity:videogame   - a video game or game series
  urn:entity:podcast     - a podcast
  urn:entity:place       - a specific venue, landmark, or place
  concept                - an abstract idea, theme, or philosophy with no single named entity
  movement               - a cultural, artistic, or social movement
  genre                  - a creative or cultural genre
  era                    - a time period or era
  subculture             - a community or subculture (e.g. demoscene, vaporwave)
  none                   - cannot be classified

confidence: high | medium | low
evidence: the exact phrase from the input text that supports this candidate
ambiguous: true if the name could refer to multiple unrelated things

Include: named works, technologies, brands, communities, movements, cultural moments.
Exclude: generic words, pronouns, common verbs, numbers, plain dates.

Examples:
  "Amiga"       -> qloo_type: urn:entity:brand   (Commodore Amiga hardware platform)
  "demoscene"   -> qloo_type: subculture
  "Blade Runner"-> qloo_type: urn:entity:movie
  "vaporwave"   -> qloo_type: genre
  "C64"         -> qloo_type: urn:entity:brand

Text:
{{text}}
```

---

### Stage 2 (Path B): Qloo resolution (pipeline/resolver.py)

Input: candidates from extractor.

The `qloo_type` field drives the resolution path directly:

```python
from qloo.types import QLOO_ENTITY_TYPES

for candidate in candidates:
    if candidate.qloo_type in QLOO_ENTITY_TYPES:
        # entity search
        results = await client.search(query=candidate.name, type=candidate.qloo_type, take=3)
        if not results:
            # retry without type filter (catches misclassified types)
            results = await client.search(query=candidate.name, take=3)
    else:
        # tag search for concept, movement, genre, era, subculture, none
        results = await client.tags(query=candidate.name, take=3)
```

If results returned: attach top match as `qloo_id`, `qloo_name`, `qloo_resolved_type`.
If nothing: mark `unresolved: true`.
On error: mark `error: <message>`, continue.

Pass all candidates through. Selector decides what to do with unresolved ones.

---

### Stage 3 (Path B): Entity tags (pipeline/entity_tags.py)

Input: resolved candidates (those with a `qloo_id`).

For each resolved candidate, call `GET /v2/insights` to get culturally related entities:
```
GET /v2/insights
  filter.type=urn:entity:artist    # cycle through multiple filter types
  signal.interests.entities=<qloo_id>
  take=10
```

Try `filter.type` for several entity types to cast a wider net. The response type and the signal entity type do not have to match.

From each response, extract returned items. Attach as `qloo_associations: list[{id, name, type}]` on the candidate.

If Insights returns nothing, the candidate still carries its own name as a potential tag.

Batch candidates: if >5 resolved candidates, make parallel async calls.

---

### Stage 4 (Path B): Candidate selection (pipeline/selector.py)

Input: all candidates (resolved+unresolved) with associations, original text.

Build the candidate pool:
- Each candidate's own name (source: `qloo_direct` if resolved, `llm` if not)
- Each `qloo_association` from Insights results (source: `qloo_inferred`)

Score each pool item:
- `text_relevance`: exact match of name in original text = 2, stem match = 1, none = 0
- `cultural_depth`: came from Qloo Insights = 1, else 0
- `specificity`: named entity or subculture term = 1, generic concept = 0

Sort by `text_relevance * 2 + cultural_depth + specificity` descending. Deduplicate (case-insensitive). Take top 12.

Unresolved candidates enter with `cultural_depth: 0`, source `llm`.

---

### Stage 5 (Path B): Final generation (pipeline/generator.py)

Input: selected candidates with scores and evidence, original text, destination.

Build an evidence block listing each candidate with: tag, evidence phrase, source, any Qloo associations.

Call LLM with `prompts/final.md`. The model writes one explanation per tag using only the provided evidence. Parse strictly. Discard any tag not in the candidate pool (hallucination guard).

`prompts/final.md`:
```
You are writing per-tag explanations for a cultural tag tool.

For each tag below, write one explanation sentence (max 30 words) describing why it relates to the original text. Use only the evidence provided. Do not invent cultural connections not listed in the evidence.

Return JSON only: an array of objects with fields: tag, explanation.

Original text:
{{text}}

Tags with evidence:
{{evidence_block}}
```

---

## 7. Topic mode (pipeline/topics.py)

Reuses extractor + resolver. Instead of entity_tags returning more tags, the Insights associations are framed as adjacent cultural topics.

From the associations, build a signals block: a list of connected domains, communities, movements. Call LLM with `prompts/topics.md`. Return up to 5 topics with: `topic`, `connection`, `cultural_basis`.

`prompts/topics.md`:
```
You are writing cultural topic suggestions for a content creator.

Based on the original text and the cultural signals below, suggest up to 5 adjacent topics the creator could explore. Each topic should be a genuine extension of the content's cultural context - not a generic content strategy suggestion.

For each topic, write:
- topic: the topic name (3-6 words)
- connection: one sentence explaining why it connects to the original text
- cultural_basis: one sentence describing the cultural or historical signal that supports it

Use only the signals provided. Do not invent connections.

Return JSON only: an array of objects with fields: topic, connection, cultural_basis.

Original text:
{{text}}

Cultural signals:
{{signals_block}}
```

---

## 8. API endpoints (api/)

### POST /api/generate

Request body: `GenerateRequest`
Response: `GenerateResponse`

Runs Path A and Path B concurrently with `asyncio.gather`. On both complete: compute overlap and novelty. Attach trace only if `advanced=True`.

If Path A fails: return its error in `baseline.error`, still attempt Path B. If both fail: 200 with errors in both paths. Never 500 the user.

### GET /api/health

Returns `{"status": "ok", "qloo_key_set": bool, "llm_key_set": bool}`.

---

## 9. Frontend (static/)

Design: retro utility. Monospace font (Courier New or similar), off-white background, dark text. No gradients. No animations except a subtle progress bar during generation. Feels like a well-maintained tool from 2003.

### Layout

```
[ Väre ]
Find the tags hiding between the lines.

[ destination: General | YouTube | LinkedIn | Instagram ]

[ large textarea - placeholder text ]

[ ○ Tags  ○ Topics ]          [ Generate and compare ]

[ Advanced mode: OFF ]

---

| Conventional LLM           | Qloo-assisted              |
| Generated tags              | Culturally expanded tags   |
|                             |                            |
| #tag1 #tag2 #tag3 ...       | #tag1 #tag2 #tag3 ...      |
| 12 tags  [ Copy ]           | 14 tags  [ Copy ]          |
|                             |                            |
| Overlap: 8   Novelty: 6              Total time: 3.4s |

---

[ Advanced mode trace - only visible when Advanced mode: ON ]
Stage 0: Baseline LLM    [v]
Stage 1: Reference extraction   [v]
...
```

Tag chips clickable - tooltip shows explanation, evidence, source (`llm` / `qloo_direct` / `qloo_inferred`).

Novelty count shown, no verdict. "Qloo-assisted" is a label, not a claim.

Copy: `#tag1 #tag2 ...` for YouTube/LinkedIn/Instagram, comma-separated for General.

Advanced trace: each stage collapsible, latency badge, prompt/params/response as formatted JSON block. Secrets stripped server-side.

Error states: show actual error message in the affected column. Never hide failures.

---

## 10. Benchmark tool (tools/benchmark.py)

Reads `benchmark/texts/*.txt`. For each, calls `POST /api/generate` against the running server. Saves to `benchmark/results/<timestamp>.json`.

Prints:
```
file                     | overlap | novelty | baseline_n | exp_n | latency
amiga.txt                |   8     |    6    |     12     |   14  |  3.4s
generic_linkedin.txt     |  10     |    2    |     11     |   12  |  2.1s
```

Required texts:
- `amiga.txt` - Amiga + demo scene content
- `generic_linkedin.txt` - generic professional post, no cultural references
- `film.txt` - obscure film post
- `retrocomputing.txt` - retrocomputing or hobby content
- `food.txt` - food/restaurant content
- `fashion.txt` - fashion or subculture content
- `marketing.txt` - corporate marketing copy
- `ambiguous.txt` - text with a deliberate double meaning ("Amiga" = brand or Spanish)

---

## 11. Secrets gate (tools/check_secrets.py)

Port from Apps\Whyf. Scans all git history and working tree. Flags: API key patterns, `private/` paths, committed `.env` files. Exit 1 on any finding.

`Makefile`:
```
make dev        # uvicorn vare.main:app --reload
make test       # pytest tests/
make check      # python tools/check_secrets.py && python tools/check_publishable.py
make benchmark  # python tools/benchmark.py
make deploy     # railway up  (or fly deploy)
```

---

## 12. Slices

### S0 - Qloo API spike (done before writing any pipeline code)

**Goal**: confirm the hackathon key works against the hackathon endpoint. Verify actual response shapes.

**Context**: The harness package was inspected on 2026-10-10. Verified endpoints and params are in section 4. S0 confirms these work with a real key against the hackathon URL.

Script at `scripts/qloo_spike.py`. It:
1. Calls `GET /search?query=Amiga&type=urn:entity:brand&take=5`
2. Calls `GET /tags?query=retrocomputing&take=5`
3. Takes the top entity ID from step 1 and calls `GET /v2/insights?filter.type=urn:entity:artist&signal.interests.entities=<id>&take=5`
4. Calls `GET /entities?entity_ids[]=<id>` for detail
5. Prints full raw JSON for each
6. Prints a pass/fail table

Update `qloo/models.py` with the exact field names from the actual responses.

**Done when**: pass/fail table shows PASS for all, or each FAIL has a fallback noted in section 4.

---

### S1 - Skeleton

**Goal**: repo runs, health check passes, UI loads.

- Repo structure as in section 2
- `config.py` with env vars
- `schema.py` with all models
- `qloo/client.py` stub mode working
- `qloo/types.py` with `QLOO_ENTITY_TYPES` and `TAG_SEARCH_TYPES`
- `llm/client.py` ported from Virta
- `api/health.py` working
- `static/index.html` renders the UI with hardcoded placeholder output
- One smoke test per module
- `.gitignore`, `.env.example`, `LICENSE`, `Makefile`
- `tools/check_secrets.py`, `check_publishable.py`
- `make check` passes, `make test` passes

**Done when**: `make dev` starts, `/api/health` returns 200, page loads.

---

### S2 - Baseline path

**Goal**: Path A produces real LLM tags.

- `pipeline/baseline.py` implemented
- `llm/prompts/baseline.md` written
- `POST /api/generate` returns real baseline tags
- Frontend renders baseline column
- Tag chips show (empty) tooltip on click
- Copy button works
- `tests/test_baseline.py` with respx LLM mock

**Done when**: Amiga text produces a real tag list in the baseline column.

---

### S3 - Extractor and resolver

**Goal**: Stages 1-2 run against real input with real Qloo calls.

- `pipeline/extractor.py` implemented, `prompts/extract.md` written with the full Qloo type list
- `pipeline/resolver.py` implemented - uses `qloo_type` directly, no mapping table
- `qloo/client.py` fully implemented (search, tags endpoints)
- Candidates extracted from Amiga text: "Amiga" -> `urn:entity:brand`, "demoscene" -> `subculture` -> tag search
- `tests/test_extractor.py`, `tests/test_resolver.py`

**Done when**: extractor returns candidates for Amiga text with correct Qloo types; resolver returns at least one Qloo ID (or logs honest empty result).

---

### S4 - Entity tags and selector

**Goal**: Insights queried, candidates scored and selected.

- `pipeline/entity_tags.py` implemented (calls `GET /v2/insights`)
- `pipeline/selector.py` with scoring from section 6
- `tests/test_entity_tags.py`, `tests/test_selector.py`

**Done when**: selector produces a ranked candidate list with traceable scores.

---

### S5 - Full experimental path and comparison

**Goal**: both paths run, both columns visible.

- `pipeline/generator.py` implemented, `prompts/final.md` written
- `POST /api/generate` runs both paths concurrently
- Frontend shows both columns
- Experimental tags show explanation + source in tooltip
- Novelty count displayed
- Copy buttons work for both columns
- `tests/test_generator.py`, `tests/test_api.py`

**Done when**: Amiga text produces a two-column comparison. At least one novel tag in the experimental column, or the tool honestly shows there is none.

---

### S6 - Advanced mode trace

**Goal**: full pipeline trace visible in UI.

- `pipeline/trace.py` collecting `TraceStage` per stage
- Auth headers stripped before trace hits the response
- Frontend Advanced mode toggle
- Each stage: collapsible, latency badge, formatted JSON detail
- `tests/` verify no QLOO_API_KEY or LLM_API_KEY value appears in any trace response

**Done when**: full Amiga run trace is visible, inspectable, secret-free.

---

### S7 - Topic mode

**Goal**: topic suggestions mode works end to end.

- `pipeline/topics.py` implemented, `prompts/topics.md` written
- `POST /api/generate` with `mode: topics` routes correctly
- Frontend mode selector works
- Topic display: name, connection, cultural basis, copy button
- Tests for topic pipeline

**Done when**: Amiga text in topic mode returns at least 3 topic suggestions with traceable cultural basis.

---

### S8 - Benchmark, hosting, submission prep

**Goal**: publicly reachable, submission ready.

- `tools/benchmark.py` written
- `benchmark/texts/` has all 8 texts
- Benchmark run against live URL
- Railway or Fly.io deployment running at a public URL
- `README.md`: what it does, how to run locally, env vars, what advanced trace shows
- `LICENSE` MIT present
- `make check` passes on clean clone
- Devpost submission fields ready

**Done when**: `curl https://<demo-url>/api/health` returns 200.

---

### S9 (stretch) - Benchmark evaluation gate

Document one of three decisions in `README.md`:
- Tags mode consistently adds value
- Tags mode adds value only for niche/subculture texts
- Pivot to topic mode (tags equivalent, topics add more)

The decision must reflect actual benchmark output.

---

## 13. Definition of done

- Same input processed by both paths
- Path A is a real, unweakened LLM generator
- Path B uses real Qloo API data (not stub)
- Both outputs visible simultaneously
- Each experimental tag has traceable evidence
- Advanced mode shows actual prompts, sanitised API params, responses
- No secrets in trace
- Users can copy tags
- Failures and empty results shown honestly
- Benchmark results documented
- `make check` passes on clean clone
- Public demo URL responds 200

---

## 14. Submission checklist

- [ ] Devpost form submitted
- [ ] Demo URL field: public URL where judges use the tool end-to-end
- [ ] Code repo: public GitHub/GitLab/Bitbucket, MIT license visible in About
- [ ] Description: what it does, what makes it Qloo-powered
- [ ] Tools used: FastAPI, Qloo API (hackathon endpoint), OpenAI-compatible LLM, etc.
- [ ] Demo video: under 3 minutes, shows both columns, shows advanced trace, shows a failure case honestly

---

## 15. Hackathon narrative (for the Devpost description)

A conventional LLM already knows how to generate hashtags.

Väre tests whether cultural intelligence reveals connections that ordinary text analysis misses. The tool runs both approaches on the same text and shows you both outputs at once, with traceable evidence behind every tag in the experimental column.

It uses Qloo's taste graph to find cultural relationships beyond what the text explicitly says. If the text mentions an Amiga, does the Qloo graph connect Amiga to the demoscene? If it does, that connection is surfaced. If it does not, no connection is claimed.

Advanced mode shows the full pipeline: the exact prompts, the Qloo API calls, what was resolved and what was rejected, what the scoring algorithm decided and why.

The tool does not promise better reach or engagement. It is an experiment with an honest benchmark. Either the cultural intelligence adds something useful, or it does not - and the tool is built to tell you which.
