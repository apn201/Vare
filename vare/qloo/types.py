"""Qloo type vocabulary, verified against the hackathon API on 2026-10-13.

The spec listed `urn:entity:video_game` and a `/tags` endpoint; the live API
rejects both. These sets are what the API actually accepts.
"""

# Accepted by GET /search `types=` (from the API's own 400 message).
QLOO_ENTITY_TYPES = {
    "urn:entity:actor",
    "urn:entity:album",
    "urn:entity:artist",
    "urn:entity:author",
    "urn:entity:book",
    "urn:entity:brand",
    "urn:entity:destination",
    "urn:entity:director",
    "urn:entity:locality",
    "urn:entity:movie",
    "urn:entity:person",
    "urn:entity:place",
    "urn:entity:podcast",
    "urn:entity:tv_show",
    "urn:entity:videogame",
}

# Accepted by GET /v2/insights `filter.type=` (each probed live, 200 OK).
INSIGHTS_FILTER_TYPES = {
    "urn:entity:artist",
    "urn:entity:book",
    "urn:entity:brand",
    "urn:entity:destination",
    "urn:entity:movie",
    "urn:entity:person",
    "urn:entity:place",
    "urn:entity:podcast",
    "urn:entity:tv_show",
    "urn:entity:videogame",
    "urn:tag",
}

# Abstract or genre-level references: no single entity, resolve via /v2/tags.
TAG_SEARCH_TYPES = {
    "cuisine",
    "concept",
    "movement",
    "genre",
    "era",
    "subculture",
    "none",
}

ALL_EXTRACTOR_TYPES = QLOO_ENTITY_TYPES | TAG_SEARCH_TYPES

# Domain words the extractor may use for the text as a whole -> entity URN.
DOMAIN_TYPES = {
    "movie": "urn:entity:movie", "film": "urn:entity:movie",
    "tv_show": "urn:entity:tv_show", "tv": "urn:entity:tv_show",
    "book": "urn:entity:book",
    "artist": "urn:entity:artist", "music": "urn:entity:artist",
    "videogame": "urn:entity:videogame", "video_game": "urn:entity:videogame",
    "podcast": "urn:entity:podcast",
    "brand": "urn:entity:brand",
    "place": "urn:entity:place", "food": "urn:entity:place",
    "destination": "urn:entity:destination", "travel": "urn:entity:destination",
}

# Candidate types for which venue, dish and ambience tags are the right answer.
VENUE_TYPES = {"cuisine", "urn:entity:place", "urn:entity:destination", "urn:entity:locality"}

# Tag subtypes that describe venues, moods or audience labels rather than
# culture. They show up in Insights results (e.g. "Accessible", "Cold") and are
# real Qloo data, but they are not specific enough to be useful as tags.
GENERIC_TAG_SUBTYPES = (
    "urn:tag:content:",
    "urn:tag:character:",
    "urn:tag:decor:",
    "urn:tag:ambience:",
    "urn:tag:specialty_dish:",
    "urn:tag:audience:",
    "urn:tag:offerings:",
    "urn:tag:amenity:",
    "urn:tag:genre:locality",
    "urn:tag:category:place",
    "urn:tag:menu_highlight:",
    "urn:tag:nearby_attraction:",
    "urn:tag:good_for:",
    "urn:tag:accessibility:",
    "urn:tag:price_level:",
    "urn:tag:streaming_service:",
    "urn:tag:credit_card:",
    "urn:tag:hotel_rating:",
    "urn:tag:cost_description:",
    "urn:tag:inclusivity:",
    "urn:tag:host:",
    "urn:tag:genre:place",
    "urn:tag:genre:person",
)

# filter.parents.types for tag Insights: without it, a film's associated tags
# come back as "Three Star", "American Express" (venue tags from the same
# audience). With it, Qloo returns tags that describe that kind of entity.
TAG_PARENT_FOR_ENTITY = {
    "urn:entity:movie": "urn:entity:movie",
    "urn:entity:tv_show": "urn:entity:tv_show",
    "urn:entity:book": "urn:entity:book",
    "urn:entity:author": "urn:entity:book",
    "urn:entity:artist": "urn:entity:artist",
    "urn:entity:album": "urn:entity:artist",
    "urn:entity:actor": "urn:entity:movie",
    "urn:entity:director": "urn:entity:movie",
    "urn:entity:person": "urn:entity:movie",
    "urn:entity:videogame": "urn:entity:videogame",
    "urn:entity:podcast": "urn:entity:podcast",
    "urn:entity:brand": "urn:entity:brand",
    "urn:entity:place": "urn:entity:place",
    "urn:entity:destination": "urn:entity:destination",
    "urn:entity:locality": "urn:entity:place",
}

# Cross-domain hops for topic mode: which kinds of entity to ask Insights for,
# given the kind of entity we start from. Two per source keeps the call budget
# (5 req/s, 10k/month) sane.
CROSS_DOMAIN = {
    "urn:entity:movie": ["urn:entity:artist", "urn:entity:book"],
    "urn:entity:tv_show": ["urn:entity:movie", "urn:entity:podcast"],
    "urn:entity:book": ["urn:entity:movie", "urn:entity:podcast"],
    "urn:entity:artist": ["urn:entity:movie", "urn:entity:brand"],
    "urn:entity:album": ["urn:entity:artist", "urn:entity:movie"],
    "urn:entity:brand": ["urn:entity:videogame", "urn:entity:podcast"],
    "urn:entity:videogame": ["urn:entity:artist", "urn:entity:movie"],
    "urn:entity:podcast": ["urn:entity:book", "urn:entity:tv_show"],
    "urn:entity:place": ["urn:entity:destination", "urn:entity:brand"],
    "urn:entity:destination": ["urn:entity:place", "urn:entity:movie"],
    "urn:entity:locality": ["urn:entity:place", "urn:entity:movie"],
}
DEFAULT_CROSS_DOMAIN = ["urn:entity:artist", "urn:entity:movie"]


def is_generic_tag_type(subtype: str | None) -> bool:
    return bool(subtype) and subtype.startswith(GENERIC_TAG_SUBTYPES)
