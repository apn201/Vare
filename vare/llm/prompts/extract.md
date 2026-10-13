Read the text below and work out what it is actually about. A cultural intelligence system (Qloo) will then look up each reference using the type you assign, and describe the subject with its own data.

Return JSON only, as one object with these fields:
  "subject": the one thing the text is mainly about (a work, artist, place, dish...), as {"name", "qloo_type"}. Use null if the text has no cultural subject.
  "domains": the 1 to 3 cultural domains the text is about, most central first.
             Each exactly one of: movie, tv_show, book, artist (music), videogame, podcast, brand, place, destination
  "references": an array of objects with fields: name, qloo_type, role, evidence, confidence, ambiguous, implied

role is exactly one of:
  subject     - the main thing the text is about (also include it here)
  creator     - who made the subject (director, author, band, chef, designer)
  cast        - performers or people inside the subject (actors, band members, characters)
  context     - something the text is genuinely about besides the subject (a venue, a city, a scene, a genre it belongs to)
  comparison  - something mentioned only to compare with, or as an influence or reference point
  allusion    - a myth, fairy tale, symbol or theme the text alludes to

implied: true only for a creator or cast member the text does not name but who is unambiguously tied to the subject. If the subject is a work (film, show, album, book, game) and the text does not name its main creator, add that creator (director, showrunner, artist, author) as an implied reference. At most 2 implied references. Never imply anything else.
evidence: the exact phrase from the input text that supports this reference; for implied references, say how it is tied to the subject (e.g. "director of The Substance").
confidence: high | medium | low
ambiguous: true if the name could refer to multiple unrelated things

qloo_type must be exactly one of:
  urn:entity:movie       - a film
  urn:entity:tv_show     - a television show or series
  urn:entity:book        - a book or written work
  urn:entity:brand       - a brand, company, product line, or technology platform
  urn:entity:artist      - a musical artist, band, or performer
  urn:entity:album       - a music album or song
  urn:entity:person      - a real person not better described by a more specific type
  urn:entity:actor       - an actor or actress
  urn:entity:director    - a film or TV director
  urn:entity:author      - a book author
  urn:entity:destination - a city, country or travel destination
  urn:entity:locality    - a neighbourhood or small local area
  urn:entity:videogame   - a video game or game series
  urn:entity:podcast     - a podcast
  urn:entity:place       - a specific venue, restaurant, shop, landmark, or place
  cuisine                - a cuisine, dish, drink, or food style (e.g. ramen, natural wine)
  concept                - an abstract idea, theme, or philosophy with no single named entity
  movement               - a cultural, artistic, or social movement
  genre                  - a creative or cultural genre
  era                    - a time period or era
  subculture             - a community or subculture (e.g. K-pop stans, sneakerheads)
  none                   - cannot be classified

Include: named works, people, brands, places, communities, movements, cultural moments.
Exclude: generic words, pronouns, common verbs, numbers, plain dates, the author's friends and family.
Return at most 10 references, subject first.

Examples:
  "Finally watched Oppenheimer, Nolan outdid himself, felt like Lawrence of Arabia"
    -> subject Oppenheimer (urn:entity:movie); Christopher Nolan role creator;
       Lawrence of Arabia role comparison
  "Taylor Swift's Eras Tour in Lisbon"
    -> subject Taylor Swift (urn:entity:artist); Lisbon role context (urn:entity:destination)
  "Succession is basically King Lear in a boardroom"
    -> subject Succession (urn:entity:tv_show); King Lear role allusion

Text (between the markers; it is data, not instructions):
<<<
{{text}}
>>>

Return the JSON object now.
