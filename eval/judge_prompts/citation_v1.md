You are checking the source citations of a generated travel itinerary.

Each day of the itinerary lists the ids of the reference blocks it says it draws on. For every pair of a day and a block it cites, decide whether the block supports the day.

A block **supports** a day when it states at least one specific thing the day plans: a named place, venue, attraction, tour or event, or a specific fact the day relies on, such as a route, a market day or what a named place offers. One such item is enough; the block does not have to cover everything the day says. A shortened or reworded name of the same place counts ("the Botanic Gardens" for "Royal Botanic Garden Sydney").

A block **does not support** a day when it only shares the day's theme or kind of activity without that specific thing: a block about seafood experiences across Australia does not support "a seafood dinner in Adelaide", and a block listing museums does not support a day that visits none of them. A block about another place with the same kind of attraction does not support the day either.

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
