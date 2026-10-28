"""
Seed script for the travel agent database.

Inserts:
  - 3 itinerary_categories  (family, budget, adventure)
  - prompt_templates          (every version in TEMPLATE_DEFINITIONS; the version in
                               ACTIVE_TEMPLATE_VERSIONS is the only active one per key)
  - 13 source documents into the Agno Knowledge base (travel_docs table via PgVector)

Idempotent — safe to run multiple times; existing rows are skipped, not duplicated.

Usage:
    python scripts/seed.py
"""

import os
import sys
import time

# ---------------------------------------------------------------------------
# Bootstrap path so src.app.* imports resolve correctly
# ---------------------------------------------------------------------------
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT_DIR, ".env"))

from google import genai  # noqa: E402
from google.genai import types  # noqa: E402
from sqlalchemy import create_engine, make_url, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.models.itinerary_category import ItineraryCategory  # noqa: E402
from app.workflow.knowledge_base import build_knowledge, knowledge_table_name  # noqa: E402
from app.workflow.template_versions import apply_template_versions, check_active_versions  # noqa: E402

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DATABASE_URL = os.environ["DATABASE_URL"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "gemini-embedding-001")

_genai_client = genai.Client(api_key=GEMINI_API_KEY)


def compute_embedding(text: str) -> list[float]:
    """Return a 768-dimensional embedding vector for *text* using the Gemini API."""
    result = _genai_client.models.embed_content(
        model=f"models/{EMBEDDING_MODEL}",
        contents=text,
        config=types.EmbedContentConfig(
            task_type="SEMANTIC_SIMILARITY",
            output_dimensionality=768,
        ),
    )
    return result.embeddings[0].values


# ---------------------------------------------------------------------------
# Seed definitions
# ---------------------------------------------------------------------------

ITINERARY_CATEGORIES = [
    {
        "category_key": "family",
        "description": "Family trips with child-friendly activities, safe pacing, and practical convenience.",
        "tone": "friendly and family-oriented",
        "constraints": "Keep activities safe, easy to manage, and suitable for children. Avoid extreme sports, late-night venues, and strenuous hikes.",
    },
    {
        "category_key": "budget",
        "description": "Cost-conscious travel focused on value, free attractions, and affordable transport and stays.",
        "tone": "practical and cost-conscious",
        "constraints": "Prioritise low-cost activities, budget accommodation, public transport, and free or cheap attractions.",
    },
    {
        "category_key": "adventure",
        "description": "Active travel for travellers seeking outdoor challenge, movement, and physical engagement.",
        "tone": "exciting and energetic",
        "constraints": "Suit physically active adults. Include demanding outdoor activities, safety basics, and necessary gear or hire options.",
    },
    {
        "category_key": "romantic",
        "description": "Couples travel built around privacy, scenery, and intimate experiences.",
        "tone": "romantic and intimate",
        "constraints": "Emphasise couple-friendly stays, private dining, scenic spots, and low-crowd experiences.",
    },
    {
        "category_key": "luxury",
        "description": "High-end travel with premium accommodation, dining, and exclusive experiences.",
        "tone": "sophisticated and indulgent",
        "constraints": "Recommend five-star stays, private transfers, fine dining, and exclusive access. Cost is secondary.",
    },
    {
        "category_key": "solo",
        "description": "Independent travel for one person, with flexibility, safety, and social optionality.",
        "tone": "independent and empowering",
        "constraints": "Prioritise safety, solo-friendly accommodation, and activities that work well alone.",
    },
    {
        "category_key": "eco",
        "description": "Sustainable travel that reduces environmental impact and supports local operators.",
        "tone": "mindful and nature-conscious",
        "constraints": "Prefer low-impact transport, eco-certified stays, conservation experiences, and local ownership.",
    },
    {
        "category_key": "culinary",
        "description": "Food and wine travel centred on dining, markets, tastings, and regional produce.",
        "tone": "passionate and flavour-driven",
        "constraints": "Focus on food markets, cooking classes, restaurant trails, wine regions, and local specialties.",
    },
    {
        "category_key": "cultural",
        "description": "Heritage, arts, museums, and culturally rich experiences.",
        "tone": "curious and immersive",
        "constraints": "Prioritise museums, galleries, heritage sites, performing arts, and Indigenous cultural experiences.",
    },
    {
        "category_key": "wellness",
        "description": "Restorative travel focused on relaxation, recovery, and wellbeing.",
        "tone": "calming and restorative",
        "constraints": "Recommend spa stays, thermal pools, yoga, quiet settings, and low-intensity experiences.",
    },
    {
        "category_key": "beach",
        "description": "Coastal travel built around beaches, swimming, and relaxed seaside time.",
        "tone": "relaxed and sun-soaked",
        "constraints": "Prioritise beach access, water activities, coastal walks, and waterfront dining.",
    },
    {
        "category_key": "city",
        "description": "Urban travel focused on neighbourhoods, transport, dining, and city culture.",
        "tone": "vibrant and exploratory",
        "constraints": "Focus on city neighbourhoods, public transport, urban dining, laneways, and local culture.",
    },
    {
        "category_key": "road-trip",
        "description": "Self-drive travel along scenic routes with long-distance movement between stops.",
        "tone": "free-spirited and adventurous",
        "constraints": "Plan around driving distances, fuel stops, rest breaks, and roadside attractions.",
    },
    {
        "category_key": "wildlife",
        "description": "Travel centred on observing animals in ethical and natural settings.",
        "tone": "enthusiastic and respectful",
        "constraints": "Recommend ethical wildlife encounters, national parks, sanctuaries, and seasonal sightings.",
    },
    {
        "category_key": "photography",
        "description": "Travel designed around visually strong locations and photo opportunities.",
        "tone": "artistic and visually driven",
        "constraints": "Prioritise golden-hour spots, iconic viewpoints, permits, and photogenic landscapes.",
    },
    {
        "category_key": "backpacker",
        "description": "Ultra-budget travel for shoestring itineraries, hostels, and simple logistics.",
        "tone": "adventurous and frugal",
        "constraints": "Focus on hostels, free camping, low-cost transport, and free or cheap attractions.",
    },
    {
        "category_key": "group-friends",
        "description": "Social travel for groups of friends seeking shared activities and group-friendly stays.",
        "tone": "social and high-energy",
        "constraints": "Recommend group accommodation, shared experiences, nightlife, and activities for 4-10 people.",
    },
    {
        "category_key": "senior",
        "description": "Comfortable travel for older travellers with relaxed pacing and accessibility in mind.",
        "tone": "relaxed and comfortable",
        "constraints": "Prefer gentle activities, step-free stays, accessible transport, and unhurried sightseeing.",
    },
    {
        "category_key": "honeymoon",
        "description": "Romantic once-in-a-lifetime travel for newlyweds and special celebrations.",
        "tone": "luxurious and deeply romantic",
        "constraints": "Focus on secluded resorts, special dining, spa experiences, and memorable premium touches.",
    },
    {
        "category_key": "bleisure",
        "description": "Business trip plus leisure time, balancing work needs with short quality experiences.",
        "tone": "efficient and rewarding",
        "constraints": "Optimise around work schedules, business hotels, airport proximity, and compact sightseeing.",
    },
    {
        "category_key": "weekend",
        "description": "Short getaway travel for 2-3 day escapes with minimal planning.",
        "tone": "spontaneous and refreshing",
        "constraints": "Keep trips close to home base, easy to book, and suitable for a short stay.",
    },
    {
        "category_key": "festival",
        "description": "Event-led travel built around festivals, dates, tickets, and venue logistics.",
        "tone": "enthusiastic and community-driven",
        "constraints": "Plan around event dates, ticketing, accommodation near venues, and transport to sites.",
    },
    {
        "category_key": "indigenous",
        "description": "Travel focused on First Nations experiences, culture, and Indigenous-led activities.",
        "tone": "respectful and deeply cultural",
        "constraints": "Recommend Indigenous-owned or Indigenous-led experiences. Treat cultural knowledge with care and respect.",
    },
    {
        "category_key": "outback",
        "description": "Remote inland travel with long distances, harsh conditions, and self-sufficiency.",
        "tone": "rugged and awe-inspiring",
        "constraints": "Plan for remote conditions, extra water, spare tyres, satellite comms, and fuel distances.",
    },
    {
        "category_key": "island-hopping",
        "description": "Travel across multiple islands using ferries, short flights, and island-based stays.",
        "tone": "breezy and exploratory",
        "constraints": "Plan around ferry or flight schedules, light packing, and seasonal weather risks.",
    },
    {
        "category_key": "alpine",
        "description": "Mountain and snow-country travel with alpine scenery and seasonal access.",
        "tone": "crisp and exhilarating",
        "constraints": "Focus on ski fields, alpine walks, safety, equipment, and seasonality.",
    },
    {
        "category_key": "water-sports",
        "description": "Travel built around water-based activity across coastal and lake destinations.",
        "tone": "energetic and ocean-focused",
        "constraints": "Include equipment hire, safety briefings, instructor support, and conditions by discipline.",
    },
    {
        "category_key": "camping",
        "description": "Outdoor travel focused on campsites, wilderness stays, and self-sufficient nights.",
        "tone": "earthy and self-sufficient",
        "constraints": "Recommend campgrounds, permits, fire rules, leave-no-trace practice, and tent-based stays.",
    },
    {
        "category_key": "glamping",
        "description": "Premium nature stays combining outdoor settings with hotel-like comfort.",
        "tone": "indulgent and nature-immersive",
        "constraints": "Recommend eco-glamping, ensuite comfort, and premium nature access. Exclude basic tent camping.",
    },
    {
        "category_key": "volunteer",
        "description": "Travel that combines exploration with volunteering or service work.",
        "tone": "purposeful and community-minded",
        "constraints": "Recommend accredited volunteer organisations, preparation requirements, and ethical impact.",
    },
    {
        "category_key": "educational",
        "description": "Learning-oriented travel for workshops, field studies, and interpretive experiences.",
        "tone": "curious and intellectually engaging",
        "constraints": "Focus on guided learning, science centres, workshops, and trips with educational value.",
    },
    {
        "category_key": "art",
        "description": "Creative travel centred on galleries, street art, studios, and arts events.",
        "tone": "creative and culturally rich",
        "constraints": "Centre on art venues, public art, artist studios, festivals, and exhibition planning.",
    },
    {
        "category_key": "music",
        "description": "Travel around live music, concerts, music venues, and music festivals.",
        "tone": "passionate and energetic",
        "constraints": "Plan around venue schedules, ticketing, and accommodation near events.",
    },
    {
        "category_key": "sports-active",
        "description": "Sports participation travel for people training, competing, or joining events.",
        "tone": "competitive and motivating",
        "constraints": "Focus on participation, registration deadlines, training routes, gear, and event logistics.",
    },
    {
        "category_key": "fishing",
        "description": "Travel focused on fishing experiences, waters, seasons, and operators.",
        "tone": "relaxed and patient",
        "constraints": "Recommend licensed operators, permits, seasonal catch windows, and bag-limit awareness.",
    },
    {
        "category_key": "cycling",
        "description": "Travel centred on bike routes, rail trails, and cycling-friendly stays.",
        "tone": "active and scenery-focused",
        "constraints": "Recommend routes with distance and elevation, bike hire, transfer support, and safe riding.",
    },
    {
        "category_key": "walking-hiking",
        "description": "Travel focused on walking tracks, multi-day hikes, and trail-based exploration.",
        "tone": "grounded and meditative",
        "constraints": "Recommend graded trails, water sources, hut or campsite planning, and pack guidance.",
    },
    {
        "category_key": "sailing",
        "description": "Travel built around sailing, charter boats, and coastal or offshore water time.",
        "tone": "nautical and free",
        "constraints": "Recommend charters, weather windows, marina logistics, and license requirements.",
    },
    {
        "category_key": "skiing",
        "description": "Snow-sport travel to ski fields and alpine resorts.",
        "tone": "thrilling and alpine",
        "constraints": "Focus on ski schools, lift passes, hire gear, snow season, and road conditions.",
    },
    {
        "category_key": "scuba-diving",
        "description": "Dive travel for reefs, wrecks, liveaboards, and underwater experiences.",
        "tone": "awe-struck and underwater",
        "constraints": "Recommend certified operators, dive difficulty, marine park rules, and reef protection.",
    },
    {
        "category_key": "rock-climbing",
        "description": "Travel focused on climbing crags, bouldering, and guided ascents.",
        "tone": "bold and technical",
        "constraints": "Recommend guide services, suitable grades, gear hire, access rules, and seasonal closures.",
    },
    {
        "category_key": "kayaking",
        "description": "Travel centred on kayaking routes across rivers, bays, and sheltered water.",
        "tone": "serene and adventurous",
        "constraints": "Include kayak type, guided versus self-guided options, tides, and safety equipment.",
    },
    {
        "category_key": "stargazing",
        "description": "Travel for dark-sky viewing, astronomy, and night-sky experiences.",
        "tone": "wonder-filled and contemplative",
        "constraints": "Recommend dark-sky locations, best months, celestial events, and telescope access.",
    },
    {
        "category_key": "foodie-budget",
        "description": "Budget-friendly food travel focused on street food, markets, and cheap eats.",
        "tone": "enthusiastic and money-savvy",
        "constraints": "Target affordable meals, food trucks, markets, demos, and low-cost dining options.",
    },
    {
        "category_key": "wine",
        "description": "Travel through wine regions with tastings, cellar doors, and vineyard stays.",
        "tone": "refined and leisurely",
        "constraints": "Recommend cellar doors, winery dining, accommodation, and responsible tasting options.",
    },
    {
        "category_key": "craft-beer",
        "description": "Travel for craft beer venues, brewery trails, and taproom visits.",
        "tone": "casual and convivial",
        "constraints": "Recommend breweries, tasting paddles, food pairings, and responsible drinking reminders.",
    },
    {
        "category_key": "spa-retreat",
        "description": "Wellness travel centred on spa stays, thermal bathing, and recovery.",
        "tone": "serene and indulgent",
        "constraints": "Focus on spa packages, thermal experiences, overnight retreats, and advance booking.",
    },
    {
        "category_key": "meditation-wellness",
        "description": "Quiet retreat travel focused on mindfulness, meditation, and inner reset.",
        "tone": "peaceful and introspective",
        "constraints": "Recommend silent retreats, meditation centres, digital detox, and quiet natural settings.",
    },
    {
        "category_key": "surf",
        "description": "Surf travel for breaks, lessons, camps, and wave conditions.",
        "tone": "stoked and ocean-obsessed",
        "constraints": "Recommend surf breaks by level, lesson options, board hire, and rip-current safety.",
    },
    {
        "category_key": "luxury-family",
        "description": "High-end family travel combining premium stays with child-friendly experiences.",
        "tone": "premium and family-centred",
        "constraints": "Combine luxury accommodation with family suites, kids' clubs, private guides, and premium activities.",
    },
]

# ---- Prompt templates -------------------------------------------------------
# Variables available in both templates:
#   {destination}, {trip_length}, {budget}, {matched_category},
#   {tone}, {constraints}, {retrieved_context}
# ---------------------------------------------------------------------------

HIGH_CONFIDENCE_TEMPLATE = """\
You are an expert Australian travel planner specialising in {matched_category} travel.

Plan a {trip_length}-day itinerary to {destination} for a traveller with a {budget} budget.

Travel style: {matched_category}
Tone: {tone}
Planning constraints: {constraints}

Return ONLY a valid JSON object with this exact structure — no prose, no markdown fences:
{{
  "destination": string,
  "trip_length_days": integer,
  "budget_level": string,
  "travel_style": string,
  "daily_itinerary": [
    {{
      "day": integer,
      "morning": string,
      "afternoon": string,
      "evening": string,
      "estimated_cost_aud": number
    }}
  ],
  "total_estimated_cost_aud": number,
  "key_tips": [string]
}}
"""

LOW_CONFIDENCE_TEMPLATE = """\
You are an expert Australian travel planner.

Plan a {trip_length}-day itinerary to {destination} for a traveller with a {budget} budget.

Travel style: {matched_category}
Tone: {tone}
Planning constraints: {constraints}

Use the following reference information to enrich your plan with accurate, specific details:
---
{retrieved_context}
---

Return ONLY a valid JSON object with this exact structure — no prose, no markdown fences:
{{
  "destination": string,
  "trip_length_days": integer,
  "budget_level": string,
  "travel_style": string,
  "daily_itinerary": [
    {{
      "day": integer,
      "morning": string,
      "afternoon": string,
      "evening": string,
      "estimated_cost_aud": number
    }}
  ],
  "total_estimated_cost_aud": number,
  "key_tips": [string]
}}
"""

CORRECTION_TEMPLATE = """\
The following JSON output from a travel planner AI does not match the required schema.

Validation errors:
{validation_errors}

Invalid output:
{raw_llm_output}

Return ONLY a corrected valid JSON object with this exact structure — no prose, no markdown fences:
{{
  "destination": string,
  "trip_length_days": integer,
  "budget_level": string,
  "travel_style": string,
  "daily_itinerary": [
    {{
      "day": integer,
      "morning": string,
      "afternoon": string,
      "evening": string,
      "estimated_cost_aud": number
    }}
  ],
  "total_estimated_cost_aud": number,
  "key_tips": [string]
}}
"""

# Every version ever defined, append-only: a new wording is a new entry, so
# earlier results stay reproducible with ?template_version=N.
TEMPLATE_DEFINITIONS = [
    {
        "template_key": "high_confidence_minimal_context",
        "version": 1,
        "template_text": HIGH_CONFIDENCE_TEMPLATE,
    },
    {
        "template_key": "low_confidence_with_retrieval",
        "version": 1,
        "template_text": LOW_CONFIDENCE_TEMPLATE,
    },
    {
        "template_key": "validate_output_correction",
        "version": 1,
        "template_text": CORRECTION_TEMPLATE,
    },
]

# The version of each key that requests use by default. Seed makes exactly this
# version active; change the number to upgrade or roll back.
ACTIVE_TEMPLATE_VERSIONS = {
    "high_confidence_minimal_context": 1,
    "low_confidence_with_retrieval": 1,
    "validate_output_correction": 1,
}

# ---- Source documents -------------------------------------------------------
# ---------------------------------------------------------------------------

SOURCE_DOCUMENTS = []  # corpus kept private


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

def seed_itinerary_categories(session: Session) -> None:
    print("Seeding itinerary_categories...")
    for data in ITINERARY_CATEGORIES:
        existing = session.scalar(
            select(ItineraryCategory).where(
                ItineraryCategory.category_key == data["category_key"]
            )
        )
        if existing:
            print(f"  [skip] category_key={data['category_key']} already exists")
            continue

        embed_text = (
            f"{data['category_key']} {data['description']} "
            f"{data['tone']} {data['constraints']}"
        )
        print(f"  [embed] computing vector for category_key={data['category_key']}")
        embedding = compute_embedding(embed_text)

        category = ItineraryCategory(
            category_key=data["category_key"],
            description=data["description"],
            tone=data["tone"],
            constraints=data["constraints"],
            embedding_vector=embedding,
        )
        session.add(category)
        print(f"  [insert] category_key={data['category_key']}")

    session.commit()


def seed_prompt_templates(session: Session) -> None:
    print("Seeding prompt_templates...")
    log = apply_template_versions(session, TEMPLATE_DEFINITIONS, ACTIVE_TEMPLATE_VERSIONS)
    for line in log or ["[skip] every defined version exists and the declared versions are active"]:
        print(f"  {line}")


def _travel_docs_has_embedding_column(db_url: str, table_name: str) -> bool:
    """Return True if the ai.<table_name> table has an 'embedding' column."""
    from sqlalchemy import inspect as sa_inspect

    engine = create_engine(db_url)
    insp = sa_inspect(engine)
    if not insp.has_table(table_name, schema="ai"):
        return False
    columns = {col["name"] for col in insp.get_columns(table_name, schema="ai")}
    return "embedding" in columns


def seed_source_documents() -> None:
    """Insert source documents into the Agno Knowledge base (travel_docs table).

    Uses Agno's Knowledge.insert() with skip_if_exists=True for idempotency.
    Agno's PgVector creates and manages the travel_docs table automatically.
    Destination and category metadata are stored in the document's meta_data
    field so they are retrievable after search.

    If the travel_docs table already exists but is missing the 'embedding' column
    (which can happen when the table was created by an older version of Agno or a
    partial seed run), the table is dropped so that PgVector can recreate it with
    the correct schema including the vector column.
    """
    table_name = knowledge_table_name()
    print(f"Seeding knowledge base ({table_name})...")
    knowledge = build_knowledge(
        db_url=DATABASE_URL,
        api_key=GEMINI_API_KEY,
        embedding_model=EMBEDDING_MODEL,
        table_name=table_name,
    )

    if not _travel_docs_has_embedding_column(DATABASE_URL, table_name):
        print(
            f"  [warn] {table_name} table is missing the 'embedding' column — "
            "dropping and recreating so PgVector can add it."
        )
        knowledge.vector_db.drop()

    # Ensure the table exists with the correct schema (including the embedding
    # column) before any inserts. This is a no-op when the table already has
    # the correct schema, and is required after a drop to recreate it.
    knowledge.vector_db.create()

    for data in SOURCE_DOCUMENTS:
        print(f"  [insert] title={data['title']!r}")
        knowledge.insert(
            name=data["title"],
            text_content=data["chunk_text"],
            metadata={"destination": data["destination"], **data["metadata_json"]},
            skip_if_exists=True,
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    # Fail on a bad declaration before connecting or writing anything.
    check_active_versions(TEMPLATE_DEFINITIONS, ACTIVE_TEMPLATE_VERSIONS)
    print(f"Connecting to database: {make_url(DATABASE_URL).render_as_string(hide_password=True)}")
    engine = create_engine(DATABASE_URL)

    with Session(engine) as session:
        seed_itinerary_categories(session)
        seed_prompt_templates(session)

    seed_source_documents()

    print("Seed complete.")


if __name__ == "__main__":
    main()
