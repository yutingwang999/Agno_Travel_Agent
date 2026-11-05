You are checking whether a generated travel itinerary fits what the traveller asked for.

The traveller described the trip in their own words:

- Travel style: {travel_style}
- Notes: {notes}

Answer two questions.

**1. Stated preferences.** List each thing the traveller's words ask of the trip, one per item, staying close to their wording (e.g. "street art", "free museums only", "a game at the MCG"). A style with several interests is several preferences. When the notes only make an interest in the style more specific, list it once in its more specific form ("wine" and "Swan Valley wine" are one preference). A fact that asks nothing of the plan on its own ("it's our anniversary") is a preference only if it implies something for the plan, stated as what it implies ("suits an anniversary"). For each preference decide whether the itinerary follows it: `followed` is true when the itinerary visibly does what was asked: a specific request is planned at least once; a single-interest style shapes most of the trip; each interest of a style with several has a real part of the plan, such as a planned activity or meal, though not on every day. A passing mention in a tip does not count. Give a one-sentence reason. Judge fit only, not whether the places are real or the facts are true.

**2. Added requirements.** List each requirement the itinerary imposes or assumes about the traveller that their words did not state: for example wheelchair access or step-free routes for "seniors, slow pace", or vegetarian-only meals when no diet was mentioned. Give the requirement and quote the itinerary's words. Do not list ordinary planning advice (booking ahead, wearing sunscreen, an early start), the choice of places itself, what a planned activity obviously involves (being able to swim for a swim, walking for a walk), or cost-related choices, which are judged separately. These are counted, not treated as mistakes, since some defaults are reasonable.

ITINERARY:
<<<
{itinerary}
>>>
