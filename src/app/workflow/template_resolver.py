"""Template resolver — fetches the active versioned prompt template from the DB.

Looks up ``prompt_templates`` by ``template_key``, returning the resolved
template text and its version number.

By default the active version (``is_active=True``) is returned.  Pass an
explicit ``version`` to request a specific version instead — useful for
reproducing past workflow runs or A/B testing.

Usage::

    from app.workflow.template_resolver import resolve_template, TemplateNotFoundError

    # Active version (default)
    template_text, version = resolve_template(
        template_key="high_confidence_minimal_context",
        db_url=os.environ["DATABASE_URL"],
    )

    # Specific version override
    template_text, version = resolve_template(
        template_key="high_confidence_minimal_context",
        db_url=os.environ["DATABASE_URL"],
        version=2,
    )
"""

from typing import Optional

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.prompt_template import PromptTemplate


class TemplateNotFoundError(Exception):
    """Raised when no matching template exists for the requested key/version."""


def resolve_template(
    template_key: str,
    db_url: str,
    version: Optional[int] = None,
) -> tuple[str, int]:
    """Fetch a prompt template for *template_key*.

    When *version* is ``None`` (default), returns the active template
    (``is_active=True``).  When *version* is supplied, returns that specific
    version regardless of its active flag — allowing callers to reproduce past
    workflow runs.

    Args:
        template_key: The key identifying the template (e.g.
                      ``"high_confidence_minimal_context"``).
        db_url:       SQLAlchemy database URL.
        version:      Specific version to fetch.  ``None`` fetches the active
                      version.

    Returns:
        Tuple of ``(template_text, version)``.

    Raises:
        TemplateNotFoundError: if no matching template exists.
    """
    engine = create_engine(db_url)
    with Session(engine) as session:
        if version is not None:
            template = session.scalar(
                select(PromptTemplate).where(
                    PromptTemplate.template_key == template_key,
                    PromptTemplate.version == version,
                )
            )
            not_found_msg = (
                f"No template found for template_key={template_key!r} version={version}"
            )
        else:
            template = session.scalar(
                select(PromptTemplate).where(
                    PromptTemplate.template_key == template_key,
                    PromptTemplate.is_active.is_(True),
                )
            )
            not_found_msg = (
                f"No active template found for template_key={template_key!r}"
            )

    if template is None:
        raise TemplateNotFoundError(not_found_msg)

    return template.template_text, template.version
