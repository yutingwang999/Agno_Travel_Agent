You are checking the source citations of a generated travel itinerary.

Each day of the itinerary lists the ids of the reference blocks it says it draws on. For every pair of a day and a block it cites, decide whether the block supports the day.

A block **supports** a day when it states at least one specific thing the day plans: a named place, venue, attraction, tour or event, or a specific fact the day relies on, such as a route, a market day or what a named place offers. One such item is enough; the block does not have to cover everything the day says. A shortened or reworded name of the same place counts ("the Botanic Gardens" for "Royal Botanic Garden Sydney").

This includes a named place the day goes to and what that place offers which the day does there, even when the day names a more specific spot or words the activity differently:

- the block names a river, beach, island, lane or park the day visits or looks at (a block mentioning views over a river supports an evening enjoying that river's views);
- the block says a named town or island offers an activity, and the day does that activity there (a block saying a beach town has surfing lessons supports a morning surfing at one of that town's beaches; a block listing wildlife encounters on an island supports a day watching that wildlife on the island);
- the block lists where a named place has a kind of attraction, and the day goes looking for that attraction there without naming the spot (a block naming a city's street-art lanes supports a self-guided street-art walk in that city).

The trip's destination name on its own does not count: a block that only says the city has many restaurants does not support a day of restaurants there. What the destination offers does count when the block states it specifically, as in the examples above.

A block **does not support** a day when it only shares the day's theme or kind of activity without tying it to the place the day goes: a block about seafood experiences across Australia does not support "a seafood dinner in Adelaide", and a block listing museums does not support a day that visits none of them. A block about another place does not support the day either, even with a similar name or the same kind of attraction: a block about a building does not support a visit to a different building nearby, and a guided bushwalk with a theme does not support a spa treatment with the same theme.

Decide only from the block's text, never from what you know about the place, and do not judge whether the rest of the day is accurate.

For each pair give the day number, the block id, `supported`, the `item`: the words of the day's plan that the block states (empty when not supported), and a one-sentence reason. Return one check for every pair listed below and no others.

REFERENCE BLOCKS:
<<<
{blocks}
>>>

DAYS AND THE BLOCKS THEY CITE:
<<<
{days}
>>>
