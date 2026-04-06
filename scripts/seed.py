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

import google.generativeai as genai  # noqa: E402
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

genai.configure(api_key=GEMINI_API_KEY)


def compute_embedding(text: str) -> list[float]:
    """Return a 768-dimensional embedding vector for *text* using the Gemini API."""
    result = genai.embed_content(
        model=f"models/{EMBEDDING_MODEL}",
        content=text,
        task_type="SEMANTIC_SIMILARITY",
        output_dimensionality=768,
    )
    return result["embedding"]


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
