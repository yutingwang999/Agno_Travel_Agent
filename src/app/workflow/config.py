"""Shared workflow configuration constants."""

# Minimum CAG confidence score to skip RAG retrieval.
# Raise to require retrieval more often; lower to rely more on cached answers.
RETRIEVAL_CONFIDENCE_THRESHOLD: float = 0.85

# Upper bound on itinerary cost per budget level, in AUD per person per day,
# EXCLUDING accommodation (itineraries contain no stay). The trip cap is this value
# times the number of days. A level missing from the mapping has no cap (luxury).
# Used by the evaluation harness's budget constraint and, later, by the runtime
# budget rule in harden-workflow-guardrails.
#
# Initial values (2026-10-25), derived from three meals + local transport + tickets:
#
#   AUD per person per day       budget          moderate
#   breakfast / lunch / dinner   10 / 15 / 20    20 / 30 / 50
#   local transport              15              25
#   tickets and activities       0-10            50
#   total                        ~70             ~175
#   cap (with margin)            70              200
#
# Meal prices are one national reference: cost-of-living sources give roughly
# AUD 15-30 for an inexpensive meal and AUD 80-120 for a mid-range dinner for two
# (worldcostofliving.com, radicalstorage.com, hollowayremovals.com.au, admitkard.com).
# The cap marks "clearly over budget", not normal spend. Record any change in
# docs/experiments.md.
DAILY_COST_CAP_AUD_PER_PERSON: dict[str, float] = {
    "budget": 70.0,
    "moderate": 200.0,
}
