# Väre

Find the tags hiding between the lines.

Väre runs two tag generators on the same text and shows both outputs side by side:

- **Conventional LLM**: one prompt, one model, a list of tags.
- **Qloo-assisted**: the same model reads what the post is *about* (its subject, and the role of every reference). [Qloo](https://www.qloo.com/) resolves the references and describes the subject with its own data: its profile tags, and what its taste graph associates with it. Deterministic code shortlists. The model then picks the tags that fit this post and explains each one, but it cannot add any.

In short, Qloo knows the work and the LLM knows the post.

**The product is a culture-aware tagging service for agents** (MCP, see [Use it from an agent](#use-it-from-an-agent)): give it a post, get back tags grounded in Qloo, each with its evidence. The web page is its test bench: it runs the same Väre pipeline next to a conventional LLM tagger so you can judge what Qloo adds.

Väre does not claim the second column is better. It shows where every tag came from, and the benchmark says how often it adds anything.

Built for the Qloo hackathon (deadline 30 Oct 2026).

## Use it from an agent

Väre is an MCP server with four read-only tools:

| tool | what it does | LLM? |
|---|---|---|
| `create_tags(text, destination)` | the Väre run: 8-14 tags grounded in Qloo, each with source and evidence, plus a ready-to-paste string (hashtags or comma-separated) | yes |
| `suggest_topics(text, destination)` | up to 5 adjacent cultural topics, each resting on a named Qloo signal | yes |
| `qloo_profile(name, entity_type)` | how Qloo describes a film, show, book, artist or place: subgenres, themes, styles, cast | no, Qloo only |
| `qloo_related(name, entity_type, related_type)` | what Qloo's taste graph connects it to: similar films, artists its fans like, associated tags | no, Qloo only |

Remote (streamable HTTP), e.g. Claude Code:

```bash
claude mcp add --transport http vare https://helppox.com/vare/mcp
```

Local (stdio), e.g. Claude Desktop's `claude_desktop_config.json`:

```json
{ "mcpServers": { "vare": { "command": "/path/to/.venv/bin/python", "args": ["-m", "vare.mcp_server"], "cwd": "/path/to/vare" } } }
```

`scripts/mcp_smoke.py <url>` connects like an agent, lists the tools and calls each one.

The public endpoint has no login (judges must be able to use it freely), so it is rate-limited per visitor: 10 runs per 10 minutes and 60 per day, 30 Qloo lookups per 10 minutes, 400 runs per day in total. Over the limit, the web API answers 429 and MCP a JSON-RPC error saying when to retry. Väre also stops calling Qloo when fewer than 300 monthly calls remain, so the key lasts through judging. All of these are settings in `.env`.

## What each tag carries

| marker | source | meaning |
|---|---|---|
| ◆ | `llm` | from the language model only (Qloo had no match) |
| ● | `qloo_direct` | named in the text (or its unnamed creator), confirmed as a Qloo entity or tag |
| ■ | `qloo_profile` | Qloo's own tag on the subject (`GET /entities`): its subgenres, styles, themes |
| ◆● | `qloo_inferred` | Qloo Insights associates it with a reference the post is about |

Click a tag for its explanation and evidence. Tags in the Qloo column that the conventional column missed are marked `*`.

## Pipeline

```
A0  baseline   LLM -> tags
B1  read       LLM -> subject, domains, references with a role:
               subject | creator | cast | context | comparison | allusion
               (+ at most 2 implied creators/cast, e.g. the unnamed director)
B2  resolve    GET /search?types=…  |  GET /v2/tags?filter.query=…
               comparisons and allusions are not looked up
B3  enrich     GET /entities?entity_ids=<subject>          -> Qloo profile tags + cast
               GET /v2/insights?filter.type=urn:tag&filter.parents.types=<domain>
                    &signal.interests.entities|tags=<id>     -> associated tags
B4  shortlist  score = text_relevance*2 + cultural_depth + specificity + about_subject
               (deterministic, no LLM; every rejection recorded with its reason)
B5  choose     LLM picks 8-14 from the shortlist and explains each; cannot add tags;
               code keeps the subject
```

Example: *"Finally watched The Substance… the director clearly has seen Kubrick movies… references to Icarus, Cinderella, Limitless…"*

- Conventional LLM, given the same brief (tag what the post is about, leave out comparisons and allusions): the substance, coralie fargeat, demi moore, body horror, satire, movie review, film discussion, cinema…
- Qloo-assisted: The Substance, Coralie Fargeat, Body horror, Psychological horror, Dark comedy, Satire, Celebrity culture, Female autonomy, Raw…
- Kubrick, Icarus, Cinderella and Limitless are recognised as comparisons and allusions, not the subject. The director is not named in the post; the LLM proposed her and Qloo confirmed her.

Rules the code enforces:

- Every Qloo-sourced tag is a real API response item. If Qloo returns nothing, the column says so.
- The model proposes, code decides: name matching, type compatibility, roles, domain scoping, profile filtering, scoring and the hallucination guard are deterministic and visible in the trace.
- Path A uses the same model, endpoint and settings as Path B, and the same brief: tag what the post is about, leave out what it only compares to or alludes to, 8-14 tags. The difference between the columns is Qloo, not the instructions.
- Failures are shown in the affected column, never replaced with invented tags.
- Keys never reach the browser: credential-like params are dropped, and every string in the response is scrubbed of the actual key values.

Topic mode reuses B1-B3, adds cross-domain entity hops (a film -> artists and books), and asks the model for adjacent topics grounded in those signals. Its baseline is the same topic prompt without the signals.

## Advanced mode

Turn it on to see every stage: the exact prompts, model, tokens, each Qloo request with sanitised params, items returned, cache hits, what was selected and what was rejected with the reason.

## Run locally

```bash
python -m venv .venv && .venv/Scripts/activate   # or source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env                             # fill in the keys
make dev                                         # http://localhost:8000
make test
make check                                       # secrets gate, run before any push
make spike                                       # S0: live Qloo smoke test
make benchmark                                   # needs the server running
```

Deployment: `deploy/DEPLOY.md` (uvicorn under systemd behind an Apache reverse proxy).

Environment (see `.env.example`):

| var | |
|---|---|
| `QLOO_API_KEY` | hackathon key; `stub` or empty runs without Qloo and says so |
| `QLOO_BASE_URL` | `https://hackathon.api.qloo.com` |
| `LLM_API_KEY` | any OpenAI-compatible endpoint; an OpenRouter `sk-or-` key selects OpenRouter automatically |
| `LLM_BASE_URL`, `LLM_MODEL` | default with OpenRouter: `deepseek/deepseek-v4.1-flash` |
| `LLM_REASONING` | `off` (default on OpenRouter), `low`, `medium`, `high` |
| `QLOO_CACHE_PATH` | private SQLite cache of Qloo responses, default `var/qloo_cache.db` |
| `DEBUG_RETAIN_TRACES` | `true` stores traces in `var/traces.db`; off by default, nothing stored |

## Verified Qloo API facts (S0, 2026-10-13)

Differences from the original build spec, all confirmed against the live hackathon API:

- Tag search is `GET /v2/tags?filter.query=`; `GET /tags` is 404.
- Entity search filters with `types=`; the video game type is `urn:entity:videogame`.
- `filter.type=urn:tag` on Insights returns associated tags. Without `filter.parents.types` a film comes back with "Three Star" and "American Express"; with it, "soundtrack", "Neo-Noir".
- Rate limit is 5 requests/second and 10,000/month (`x-*-ratelimit-*` headers). The client paces at 4/s, retries a 429 once, and caches responses privately.
- Some Insights calls take more than 10 s cold, so the Qloo timeout is 15 s.

- `GET /entities` returns Qloo's own profile tags for an entity (a film has ~300: subgenres, styles, themes, and hundreds of plot keywords) plus its references (cast). Väre keeps only the descriptive kinds, with per-kind quotas.
- New releases can have no Insights tag associations at all (The Substance returns none); the profile still describes them.
- Cuisine associations are slow (13-16 s per call) and tag-to-tag returns spelling variants ("Of Ramen"), so food references keep their Qloo-confirmed names and are not expanded.

## Other deviations from the spec

- An extra extractor type `cuisine`, so food references may resolve to dish and venue tags.
- The extractor also names the text's subject, domains and each reference's role. Code uses the domains to pick the right tag among same-name variants and to scope Insights, and the roles to keep comparisons and allusions out.
- A new source, `qloo_profile`, and a final stage that chooses from a shortlist instead of explaining a fixed list.
- The product is an MCP server (`vare/mcp_server.py`, `/mcp` and stdio): the rules require an agentic tool, an agent framework, or Qloo inside an existing agent. It returns only Väre's tags; the conventional-LLM comparison is a web test-bench feature.
- The baseline prompt carries the same constraints as the Qloo path (subject first, no comparisons or allusions), so the comparison is fair.
- Hosting: any public URL satisfies the rules; Väre runs behind Apache instead of Railway or Fly.
- Ties in the selector go to tags several references agree on, then genres over styles over keywords, then Qloo's order.
- Every LLM stage retries once if the reply has no JSON (both paths alike, recorded in the trace).
- Reasoning is off by default on OpenRouter: with thinking on, extraction took ~70 s for the same output.

## Benchmark

`benchmark/texts/` has eight texts: film, music, TV, food, fashion, an ambiguous title (*Heat* during a heatwave), corporate marketing, and a LinkedIn post with no cultural content. Results are written to `benchmark/results/` (gitignored; they contain Qloo data, which the hackathon terms do not allow publishing).

Run of 2026-10-13, tags mode, local, both columns given the same brief. "Qloo-sourced" counts profile + Insights tags in the Qloo column.

| file | overlap | novelty | conventional | Qloo column | Qloo-sourced | example Qloo tags |
|---|---|---|---|---|---|---|
| substance | 3 | 9 | 12 | 12 | 10 | Body horror, Psychological horror, Dystopian |
| film (Dune) | 5 | 9 | 12 | 14 | 9 | Space opera, Sound design, Immersive |
| ambiguous (Heat) | 4 | 9 | 12 | 13 | 10 | Neo noir, Heist, Cinematography |
| tv (The Bear) | 4 | 10 | 12 | 14 | 8 | Culinary drama, Workplace drama, Dark comedy |
| music (Billie Eilish) | 4 | 9 | 12 | 13 | 8 | Dark Pop, Alternative Pop, Electropop |
| fashion | 0 | 12 | 12 | 12 | 8 | Haute Couture, Modern Luxury |
| food | 3 | 3 | 12 | 6 | 0 | names only (Ramen, Izakaya, Natural Wine) |
| marketing | 0 | 0 | 12 | 0 | 0 | no cultural references found |
| generic_linkedin | 0 | 0 | 12 | 0 | 0 | no cultural references found |

With the same brief, the conventional LLM already finds the obvious genre tags (body horror, neo-noir). Where the post is about a work or an artist, the Qloo column adds what a fan or a recommender would use and the post never said: subgenres, styles and themes ("Culinary drama", "Space opera", "Dark Pop"), each traceable to Qloo. Where there is no cultural subject it adds nothing and says so. The conventional column is better at post-level tags ("film review", "concert review") that Qloo does not model.

## License

MIT
