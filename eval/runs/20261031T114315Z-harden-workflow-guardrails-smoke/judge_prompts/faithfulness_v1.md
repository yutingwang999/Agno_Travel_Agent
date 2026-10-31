You are checking a generated travel itinerary for unsupported claims.

Extract every specific claim in the itinerary that belongs to one of these four categories, and only these:

- `opening_hours`: a statement about when a place opens, closes or operates (e.g. "the market opens at 8am", "closed on Mondays"). Scheduling the traveller ("leave at 9am") is NOT an opening-hours claim.
- `price`: a specific price or fee of a specific, named thing, including "free entry" to a named place (e.g. "entry is AUD 25", "the ferry costs $10", "the museum is free"). The itinerary's own per-day cost estimates are NOT claims, and neither is a vague remark such as "a free way to spend the morning" or "cheap eats".
- `named_place`: a specific, named venue, attraction, tour, event, business or named transport service (e.g. "Hosier Lane", "the Ngadiku Dreamtime Walk", "the Sydney Light Rail"). Generic places ("a local café", "the beach") are NOT claims.
- `transport`: a specific transport route or duration between places (e.g. "a 20-minute ferry from Townsville", "the 333 bus between the City and Bondi"). A named service on its own ("take the light rail") is a `named_place`, not a `transport` claim.

General descriptions ("enjoy the harbour views", "relax by the pool") are not claims.

Each piece of text belongs to exactly ONE claim in ONE category: never list the same place, service or phrase twice, even if it could fit several categories. If a sentence contains both a named place and a separate fact about it (e.g. "the museum, which opens at 10am"), that is two claims: the place (`named_place`) and the fact (`opening_hours`). Quote the claim's words from the itinerary.

For each claim, decide whether it is supported by the KNOWLEDGE CONTEXT below: supported means the context states it or something that directly implies it. Your own knowledge does not count; a claim that is true in reality but absent from the context is unsupported. When the context is empty, every claim is unsupported.

A matching name is not enough: the context must describe the same thing consistently with the itinerary. If the context ties a place, tour or fact to a different location or setting than the itinerary implies, the claim is unsupported. An itinerary for one city implies that city for everything it mentions unless it says otherwise (e.g. in an itinerary for Darwin, "join an Aboriginal Bush Tucker Tour" is unsupported when the context only describes such a tour in Sydney). Distance from the destination does not matter here: a nearby place that the context describes consistently with the itinerary (e.g. a day trip the context mentions) is supported. Whether a place is within reach of the destination is judged separately, not by you.

KNOWLEDGE CONTEXT:
<<<
{knowledge_context}
>>>

ITINERARY:
<<<
{itinerary}
>>>
