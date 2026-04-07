"""Template resolver — fetches the active versioned prompt template from the DB.

Looks up ``prompt_templates`` by ``template_key`` and ``is_active=True``,
returning the resolved template text and its version number.

Usage::

    from app.workflow.template_resolver import resolve_template, TemplateNotFoundError

    template_text, version = resolve_template(
        template_key="high_confidence_minimal_context",
        db_url=os.environ["DATABASE_URL"],
    )
"""

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.prompt_template import PromptTemplate


class TemplateNotFoundError(Exception):
    """Raised when no active template matches the requested template_key."""


def resolve_template(template_key: str, db_url: str) -> tuple[str, int]:
    """Fetch the active prompt template for *template_key*.

    Queries ``prompt_templates`` for a row matching *template_key* with
    ``is_active=True`` and returns its ``template_text`` and ``version``.

    Args:
        template_key: The key identifying the template (e.g.
                      ``"high_confidence_minimal_context"``).
        db_url:       SQLAlchemy database URL.

    Returns:
        Tuple of ``(template_text, version)``.

    Raises:
        TemplateNotFoundError: if no active template matches *template_key*.
    """
    engine = create_engine(db_url)
    with Session(engine) as session:
        template = session.scalar(
            select(PromptTemplate).where(
                PromptTemplate.template_key == template_key,
                PromptTemplate.is_active.is_(True),
            )
        )

    if template is None:
        raise TemplateNotFoundError(
            f"No active template found for template_key={template_key!r}"
        )

    return template.template_text, template.version
