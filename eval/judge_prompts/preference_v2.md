You are checking whether a generated travel itinerary fits what the traveller asked for.

The traveller described the trip in their own words:

- Travel style: {travel_style}
- Notes: {notes}

Answer two questions.

**1. Stated preferences.** List each thing the traveller's words ask of the trip, one per item, staying close to their wording (e.g. "street art", "free museums only", "a game at the MCG"). A style with several interests is several preferences. When the notes only make an interest in the style more specific, list it once in its more specific form ("wine" and "Swan Valley wine" are one preference). A fact that asks nothing of the plan on its own ("it's our anniversary") is a preference only if it implies something for the plan, stated as what it implies ("suits an anniversary"). For each preference decide whether the itinerary follows it: `followed` is true when the itinerary visibly does what was asked: a specific request is planned at least once; a single-interest style shapes most of the trip; each interest of a style with several has a real part of the plan, such as a planned activity or meal, though not on every day. A passing mention in a tip does not count. Give a one-sentence reason. Judge fit only, not whether the places are real or the facts are true.

**2. Added requirements.** List each thing the itinerary assumes about the traveller that their words did not state: their physical ability or access needs (wheelchair access, step-free routes), a diet or something they cannot eat (vegetarian only, no alcohol), who they are or who travels with them (children, a business trip, remote work), or the reason for the trip (an anniversary). The test is whether the itinerary treats it as true of this traveller and plans around it. Give the assumption and quote the itinerary's words.

Do not list:
- a planned activity or meal, or what it obviously involves: "eat seafood", "a vegetarian dinner" and "a full-body spa treatment" are choices in the plan, while "all meals are vegetarian because you do not eat meat" is an assumption;
- advice on how to behave or what to bring: local etiquette, rules at a site, what to wear, booking ahead, an early start;
- the choice of places, or services such as a guide, a concierge or a private transfer;
- anything the traveller's words already state or directly imply: "family" states that a family with children is travelling, and "seniors" states their age, though not that they use a wheelchair;
- cost-related choices, which are judged separately.

These are counted, not treated as mistakes, since some defaults are reasonable.

ITINERARY:
<<<
{itinerary}
>>>
