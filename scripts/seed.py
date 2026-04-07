"""
Seed script for the travel agent database.

Inserts:
  - 3 itinerary_categories  (family, budget, adventure)
  - 2 prompt_templates       (high_confidence_minimal_context, low_confidence_with_retrieval)
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
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.models.itinerary_category import ItineraryCategory  # noqa: E402
from app.models.prompt_template import PromptTemplate  # noqa: E402
from app.workflow.knowledge_base import build_knowledge  # noqa: E402

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
        "description": (
            "Family travel focused on kid-friendly destinations, activities suitable for "
            "children of all ages, and group experiences that adults and children enjoy together. "
            "Includes wildlife parks, theme parks, beaches, and gentle outdoor activities."
        ),
        "tone": "friendly and family-oriented",
        "constraints": (
            "Activities must be suitable for children of all ages. "
            "Avoid extreme sports, late-night venues, and physically demanding hikes. "
            "Prioritise safety, convenience, and family amenities."
        ),
    },
    {
        "category_key": "budget",
        "description": (
            "Budget-conscious travel that maximises experience while minimising cost. "
            "Focuses on free attractions, affordable accommodation, public transport, "
            "local markets, and low-cost dining options across Australia."
        ),
        "tone": "practical and cost-conscious",
        "constraints": (
            "Prioritise free or low-cost activities. "
            "Recommend budget accommodation (hostels, camping, budget hotels). "
            "Favour public transport over car hire. "
            "Highlight free beaches, parks, markets, and cultural institutions."
        ),
    },
    {
        "category_key": "adventure",
        "description": (
            "Adventure and active travel for physically fit adults seeking outdoor challenges. "
            "Includes surfing, hiking, diving, rock climbing, off-road driving, wildlife "
            "encounters, and multi-day wilderness expeditions across Australia."
        ),
        "tone": "exciting and energetic",
        "constraints": (
            "Activities may be physically demanding. "
            "Suitable for active adults without major physical limitations. "
            "Include appropriate safety briefings and equipment hire in recommendations."
        ),
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

PROMPT_TEMPLATES = [
    {
        "template_key": "high_confidence_minimal_context",
        "version": 1,
        "template_text": HIGH_CONFIDENCE_TEMPLATE,
        "is_active": True,
    },
    {
        "template_key": "low_confidence_with_retrieval",
        "version": 1,
        "template_text": LOW_CONFIDENCE_TEMPLATE,
        "is_active": True,
    },
]

# ---- Source documents -------------------------------------------------------
# Content derived from australia.com pages (factual, no marketing language).
# ---------------------------------------------------------------------------

SOURCE_DOCUMENTS = [
    {
        "destination": "Sydney",
        "title": "Guide to Sydney",
        "chunk_text": (
            "Sydney is located in New South Wales on traditional lands of the Gadigal people "
            "(Eora Nation). Key landmarks include Sydney Harbour Bridge and Opera House. "
            "Multiple beaches including Bondi offer year-round swimming. Airport (SYD) is 9 km "
            "from the city centre with direct train access. Four distinct seasons: warm months "
            "November-February, cooler March-August. Aboriginal cultural experiences available "
            "year-round."
        ),
        "metadata_json": {"source": "australia.com", "category": "destination"},
    },
    {
        "destination": "Melbourne",
        "title": "Guide to Melbourne",
        "chunk_text": (
            "Melbourne sits on traditional lands of the Wurundjeri people of the Kulin Nation. "
            "Known for fine dining, coffee culture, laneways, sports events, art galleries, and "
            "heritage walks. Two airports serve the city. Weather is highly variable — four "
            "seasons in one day possible. Best visited spring/summer (November-February). "
            "Nearby: Great Ocean Road, Yarra Valley, Dandenong Ranges, Mornington Peninsula."
        ),
        "metadata_json": {"source": "australia.com", "category": "destination"},
    },
    {
        "destination": "Gold Coast",
        "title": "Guide to the Gold Coast",
        "chunk_text": (
            "Gold Coast is in Queensland, accessible via Gold Coast Airport (30 km away) or "
            "Brisbane Airport (80 km). Main attractions include Surfers Paradise beach, theme "
            "parks (Warner Bros. Movie World, Dreamworld, Sea World), and subtropical hinterland "
            "with rainforest walks and waterfalls. Approximately 300 sunny days annually. "
            "Public transit includes the G:link tram. High season November-January."
        ),
        "metadata_json": {"source": "australia.com", "category": "destination"},
    },
    {
        "destination": "Brisbane",
        "title": "Guide to Brisbane",
        "chunk_text": (
            "Brisbane is Queensland's capital on traditional lands of the Turrbal and Yuggera "
            "peoples. Main attractions include South Bank cultural precinct, Story Bridge, "
            "Brisbane River activities, Botanic Gardens, and Wheel of Brisbane. Nearby islands: "
            "Moreton Island, North Stradbroke Island, K'gari (Fraser Island). Average 261 "
            "sunshine days per year. Mild winters June-August; peak season November-February. "
            "Airport 17 km from city centre."
        ),
        "metadata_json": {"source": "australia.com", "category": "destination"},
    },
    {
        "destination": "Australia",
        "title": "Australia's Sporting Experiences",
        "chunk_text": (
            "Key sporting events and venues across Australia: Hamilton Island Race Week (August, "
            "world's largest offshore keelboat regatta); Sydney to Hobart Yacht Race (26 December, "
            "1,170 km); Birdsville Races (September, Simpson Desert QLD, since 1882); Tiwi Islands "
            "Grand Final (Australian Rules Football, 2.5 hours by ferry from Darwin); Melbourne "
            "Cricket Ground (100,000+ seat capacity); Adelaide Oval RoofClimb; Bells Beach Rip Curl "
            "Pro World Surfing Championships; Barnbougle Dunes and Lost Farm golf courses in "
            "Tasmania (ranked top 100 worldwide)."
        ),
        "metadata_json": {"source": "australia.com", "category": "adventure", "activity": "sport"},
    },
    {
        "destination": "Australia",
        "title": "Best Places to See Wild Koalas",
        "chunk_text": (
            "Eight prime koala viewing locations: Kangaroo Island SA (30-min flight from Adelaide, "
            "Flinders Chase National Park); Raymond Island VIC (250 koalas, 4 hours from Melbourne); "
            "Great Ocean Road VIC (Kennett River and Cape Otway, 1 hour from Melbourne); Port "
            "Stephens NSW (2.5 hours north of Sydney, Tilligerry Habitat Reserve); Magnetic Island "
            "QLD (largest northern population, 20-min ferry from Townsville); Noosa National Park "
            "QLD (2 hours from Brisbane); Yanchep National Park WA (1 hour from Perth); Tidbinbilla "
            "Nature Reserve ACT (outside Canberra)."
        ),
        "metadata_json": {"source": "australia.com", "category": "wildlife"},
    },
    {
        "destination": "Australia",
        "title": "Australia's Seasonal Nature Experiences",
        "chunk_text": (
            "Staircase to the Moon: March-October, Broome WA, full-moon tidal phenomenon. "
            "Fagus colour change: late April-May, Tasmania crater mountains. "
            "Bioluminescent plankton: September-February, Jervis Bay NSW (3 hours from Sydney). "
            "Lavender fields: December-February, Tasmania (largest in the Southern Hemisphere). "
            "Wildflower bloom: September-November nationwide — Maree SA, Grampians VIC, WA "
            "(12,000+ species). Jacaranda season: October-November, Sydney, Brisbane, Melbourne, "
            "Perth, Adelaide; Grafton Jacaranda Festival. Aurora Australis: May-August, Tasmania "
            "(Bruny Island, Cradle Mountain-Lake St Clair, Bathurst Harbour)."
        ),
        "metadata_json": {"source": "australia.com", "category": "nature"},
    },
    {
        "destination": "Australia",
        "title": "Family Adventure Travel in Australia",
        "chunk_text": (
            "Family activities by region: Great Ocean Road 3-day lodge walk (12+ years, VIC); "
            "surfing lessons for all ages at Bondi, Manly, and Byron Bay (NSW); Whitsunday Islands "
            "sailing and Great Barrier Reef access (QLD); Aboriginal cultural kayaking and bush food "
            "tours at Shark Bay WA; Canberra Segway tours, GoBoat, wildlife spotting — koalas, "
            "platypuses, kangaroos, emus (ACT); Kangaroo Island sandboarding, quad biking, seal and "
            "dolphin swimming (SA); Cradle Mountain chairlift walks with wombats, wallabies, and "
            "Tasmanian devils (TAS)."
        ),
        "metadata_json": {"source": "australia.com", "category": "family"},
    },
    {
        "destination": "Australia",
        "title": "Girls Getaway Destinations in Australia",
        "chunk_text": (
            "Top getaway destinations: Perth WA — Swan Valley wine tasting (30 min), kayaking Swan "
            "River, emerging food scene. Mornington Peninsula VIC — Alba Thermal hot springs, wine "
            "region, beer and spirits trail. Uluru NT — dot painting classes, Indigenous-guided "
            "tours, Wintjiri Wiru drone light show (10,000+ drones). Sydney NSW — Paddington "
            "boutiques, Art Gallery of NSW (Sydney Modern), fine dining at Nour and Arthur. "
            "Kangaroo Island SA — seal and dolphin swimming, koala encounters, local oysters, "
            "crayfish, honey, gin. Esperance WA — yoga, photography workshops, Indigenous culture. "
            "Blue Mountains NSW — waterfall hiking, wildlife tours."
        ),
        "metadata_json": {"source": "australia.com", "category": "culture"},
    },
    {
        "destination": "Australia",
        "title": "Australia's Best Street Art",
        "chunk_text": (
            "Street art hubs by city: Canberra — designated free spaces in city centre, NewActon, "
            "Braddon. Sydney — Surry Hills, Newtown, Enmore. Darwin — Austin Lane (largest murals), "
            "annual Street Art Festival, Shadforth Lane. Brisbane — Fortitude Valley, annual Street "
            "Art Festival. Adelaide — Peel Street, Anster Street, Wonderwalls Port Adelaide. Perth — "
            "Grand Lane, Light Locker Art Space, Fremantle, Subiaco. Hobart — Bidencopes Lane "
            "(Vibrance, Dark Mofo festivals). Melbourne — regarded as one of the world's street art "
            "capitals: Hosier Lane, Rutledge Lane, Centre Place; Silo Art Trail through Grampians."
        ),
        "metadata_json": {"source": "australia.com", "category": "culture", "activity": "street-art"},
    },
    {
        "destination": "Australia",
        "title": "Australia's Historical and Cultural Experiences",
        "chunk_text": (
            "Iconic structures: Sydney Opera House and Harbour Bridge (NSW); Parliament House (ACT). "
            "Aboriginal/Indigenous sites: Uluru-Kata Tjuta National Park (500 million years of "
            "history); Kakadu National Park (NT); Waringarri Aboriginal Arts Centre, Kununurra WA; "
            "Budj Bim Cultural Landscape SW Victoria. Convict heritage: Port Arthur Historic Site "
            "(Tasmania, best-preserved convict settlement); Fremantle Prison WA; Hyde Park Barracks "
            "Sydney NSW. Art institutions: National Gallery of Victoria (Melbourne); National Gallery "
            "of Australia (Canberra); MONA (Hobart). Rock art sites nearly 30,000 years old. "
            "Australia has 20 UNESCO World Heritage locations."
        ),
        "metadata_json": {"source": "australia.com", "category": "culture", "activity": "history"},
    },
    {
        "destination": "Australia",
        "title": "Guided Indigenous Walking Tours",
        "chunk_text": (
            "Regional Indigenous walking tours: wukalina Walk (Bay of Fires/Mt William TAS); "
            "Ngadiku Dreamtime Walk (Daintree Rainforest, 2 hours north of Cairns QLD); Yura Malka "
            "Cultural Walk (Ikara-Flinders Ranges/Sacred Canyon SA); Borrgoron Coast to Creek "
            "(Cygnet Bay, Dampier Peninsula, 2 hours north of Broome WA); Nitmiluk Tours (Cutta "
            "Cutta Caves, 30 min south of Katherine NT); Worn Gundidj at Tower Hill (Great Ocean "
            "Road VIC); Aboriginal Bush Tucker Tour (Royal Botanic Gardens Sydney NSW). Experiences "
            "include: traditional knowledge, rock art, plant identification, medicinal uses, wildlife "
            "encounters, foraging, cave exploration, storytelling. Duration ranges from one-hour "
            "city tours to four-day wilderness walks."
        ),
        "metadata_json": {"source": "australia.com", "category": "culture", "activity": "indigenous"},
    },
    {
        "destination": "Australia",
        "title": "Australia's Best Seafood Experiences",
        "chunk_text": (
            "Regional seafood by location: Tasmania — Bruny Island abalone, sea urchin, Freycinet "
            "oysters; Bicheno and St Helens fish and chips. NSW — Sydney Fish Market cooking "
            "classes; Batemans Bay oyster kayaking; Port Stephens picnics. Queensland — Daintree "
            "Rainforest (2.5 hours from Cairns) mud crab spearfishing with Indigenous guides. "
            "South Australia — Port Lincoln and Coffin Bay oyster shucking (Pacific and Angasi "
            "varieties). Western Australia — Rottnest Island (1 hour from Perth) western rock "
            "lobster trapping and five-course banquets. Northern Territory — Arnhem Land (1 hour "
            "from Darwin) barramundi fishing March-November, mud crab dinners. Victoria — St Kilda "
            "Melbourne award-winning seafood restaurants."
        ),
        "metadata_json": {"source": "australia.com", "category": "food", "activity": "seafood"},
    },
]


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
    for data in PROMPT_TEMPLATES:
        existing = session.scalar(
            select(PromptTemplate).where(
                PromptTemplate.template_key == data["template_key"],
                PromptTemplate.version == data["version"],
            )
        )
        if existing:
            print(
                f"  [skip] template_key={data['template_key']} "
                f"version={data['version']} already exists"
            )
            continue

        template = PromptTemplate(
            template_key=data["template_key"],
            version=data["version"],
            template_text=data["template_text"],
            is_active=data["is_active"],
        )
        session.add(template)
        print(f"  [insert] template_key={data['template_key']} version={data['version']}")

    session.commit()


def seed_source_documents() -> None:
    """Insert source documents into the Agno Knowledge base (travel_docs table).

    Uses Agno's Knowledge.insert() with skip_if_exists=True for idempotency.
    Agno's PgVector creates and manages the travel_docs table automatically.
    Destination and category metadata are stored in the document's meta_data
    field so they are retrievable after search.
    """
    print("Seeding knowledge base (travel_docs)...")
    knowledge = build_knowledge(
        db_url=DATABASE_URL,
        api_key=GEMINI_API_KEY,
        embedding_model=EMBEDDING_MODEL,
    )

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
    print(f"Connecting to database: {DATABASE_URL}")
    engine = create_engine(DATABASE_URL)

    with Session(engine) as session:
        seed_itinerary_categories(session)
        seed_prompt_templates(session)

    seed_source_documents()

    print("Seed complete.")


if __name__ == "__main__":
    main()
