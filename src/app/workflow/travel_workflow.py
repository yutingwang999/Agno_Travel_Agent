"""Travel Itinerary Planner — Agno Workflow definition.

Registers all 6 steps in order as defined in DESIGN.md section 3 and
git-workflow.md branch 4 (feat/workflow-skeleton).

Workflow steps:
    1. intake              — validate and normalise user input
    2. cag_match           — classify intent via semantic matching
    3. retrieval_decision  — Condition: route to rag_retrieve when confidence < 0.78
    4. rag_retrieve        — retrieve top-k documents (conditional on step 3)
    5. generate            — resolve prompt template and call LLM
    6. validate_output     — validate LLM output; retry once on failure

Each step is a stub in this branch.  Subsequent feature branches fill in
the business logic without changing the surrounding structure.
"""

from agno.workflow import Condition, Step, Workflow

from app.workflow.steps import (
    cag_match_executor,
    generate_executor,
    intake_executor,
    rag_retrieve_executor,
    retrieval_decision_evaluator,
    validate_output_executor,
)

travel_workflow = Workflow(
    name="travel-itinerary-planner",
    description="AI-powered travel itinerary planning using CAG + RAG",
    steps=[
        # Step 1: validate and normalise input
        Step(name="intake", executor=intake_executor),

        # Step 2: classify user intent into itinerary category
        Step(name="cag_match", executor=cag_match_executor),

        # Step 3: conditional routing — run rag_retrieve only when needed
        # evaluator returns True  →  execute steps   (rag_retrieve runs)
        # evaluator returns False →  execute else_steps (empty → skip rag)
        Condition(
            name="retrieval_decision",
            evaluator=retrieval_decision_evaluator,
            steps=[
                Step(name="rag_retrieve", executor=rag_retrieve_executor),
            ],
            else_steps=[],
        ),

        # Step 5: resolve prompt template and call LLM
        Step(name="generate", executor=generate_executor),

        # Step 6: validate LLM output against Pydantic schema
        Step(name="validate_output", executor=validate_output_executor),
    ],
)
