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

# Prompt-injection patterns checked against every free-text request field before
# the workflow starts (harden-workflow-guardrails, design decision 6). Regular
# expressions, matched case-insensitively anywhere in the field. A basic line of
# defence that makes the evaluation's injection entries measurable, not a complete
# filter; extend the list rather than special-casing one input.
PROMPT_INJECTION_PATTERNS: list[str] = [
    # "ignore all previous instructions", "disregard the rules above"
    r"\b(?:ignore|disregard|forget|override)\b.{0,40}\b(?:instructions?|prompts?|rules|directions|guidelines)\b",
    r"\bsystem\s*prompt\b",
    r"\byou\s+are\s+now\b",
    # chat-template role markers: <|im_start|>, <|system|>
    r"<\|[^|>]{0,30}\|>",
    # markdown role headers: "### system", "## assistant:"
    r"#{2,}\s*(?:system|assistant|developer)\b",
    # Chinese: "忽略之前的所有指令", "无视规则", "系统提示词", "你现在是"
    r"(?:忽略|无视|無視|忘记|忘記).{0,15}(?:指令|指示|提示|规则|規則)",
    r"(?:系统|系統)\s*提示",
    r"你(?:现在|現在)是",
]
