"""rebuild-rag step b: retrieval is restricted to the destination and the Australia-wide documents."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from agno.filters import IN
from agno.workflow.types import StepInput, StepOutput

from app.workflow.retrieval_service import _search_knowledge, destination_in_knowledge_base
from app.workflow.steps.rag_retrieve import rag_retrieve_executor


def _knowledge():
    document = SimpleNamespace(meta_data={"destination": "sydney"}, name="Testville", content="Made up.")
    knowledge = MagicMock()
    knowledge.search.return_value = [document]
    return knowledge


def test_search_is_restricted_to_the_destination_and_australia():
    knowledge = _knowledge()

    _search_knowledge(knowledge, "query", 5, "sydney")

    expression = knowledge.search.call_args.kwargs["filters"][0]
    assert isinstance(expression, IN)
    assert expression.key == "destination"
    assert expression.values == ["sydney", "australia"]


def test_search_without_a_destination_is_not_filtered():
    knowledge = _knowledge()

    _search_knowledge(knowledge, "query", 5)

    assert knowledge.search.call_args.kwargs["filters"] is None


def test_destination_check_reports_false_when_the_database_fails():
    """conftest refuses database connections in unit tests; the step must still complete."""
    assert destination_in_knowledge_base("sydney", "postgresql://test:test@localhost/test") is False


def _step_input(destination: str) -> StepInput:
    intake = json.dumps({"step": "intake", "data": {"destination": destination, "travel_style": "family"}})
    return StepInput(
        additional_data={"session_id": "sid"},
        previous_step_outputs={"intake": StepOutput(step_name="intake", content=intake)},
    )


@pytest.mark.parametrize(("in_knowledge_base", "matched"), [(True, True), (False, False)])
def test_step_passes_the_destination_and_reports_whether_it_matched(monkeypatch, in_knowledge_base, matched):
    """Spec scenarios "Known city" and "City not in the knowledge base"."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost/test")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    retrieve = MagicMock(return_value=[])
    monkeypatch.setattr("app.workflow.steps.rag_retrieve.retrieve_documents", retrieve)
    monkeypatch.setattr(
        "app.workflow.steps.rag_retrieve.destination_in_knowledge_base", lambda destination, db_url: in_knowledge_base
    )

    event = json.loads(rag_retrieve_executor(_step_input("sydney")).content)

    assert retrieve.call_args.kwargs["destination"] == "sydney"
    assert event["data"]["destination_matched"] is matched
