"""Prompt template versions: which versions exist and which one is active.

``scripts/seed.py`` keeps two separate declarations:

- the template definitions — every ``(template_key, version)`` with its text,
  append-only, so earlier results stay reproducible with ``template_version``;
- the active versions — one version per key, the one requests use by default.

Upgrading is "append a definition and change its number in the map"; rolling
back is "change the number back".  The database's partial unique index
(migration 0006) guarantees at most one active row per key.

Public API:
    check_active_versions(definitions, active_versions) -> None
    apply_template_versions(session, definitions, active_versions) -> list[str]
"""

from collections.abc import Mapping, Sequence

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.prompt_template import PromptTemplate


def check_active_versions(
    definitions: Sequence[Mapping], active_versions: Mapping[str, int]
) -> None:
    """Raise ValueError unless every defined key has exactly one declared, defined version.

    Args:
        definitions:     Template definitions with ``template_key``, ``version``
                         and ``template_text``.
        active_versions: Mapping of template key to the version to activate.
    """
    defined = {(d["template_key"], d["version"]) for d in definitions}
    defined_keys = {key for key, _ in defined}
    problems: list[str] = []
    for key in sorted(defined_keys - active_versions.keys()):
        problems.append(f"no active version declared for {key!r}")
    for key, version in sorted(active_versions.items()):
        if (key, version) not in defined:
            problems.append(f"declared active version {key!r} v{version} is not defined")
    if problems:
        raise ValueError("Invalid ACTIVE_TEMPLATE_VERSIONS: " + "; ".join(problems))


def apply_template_versions(
    session: Session,
    definitions: Sequence[Mapping],
    active_versions: Mapping[str, int],
) -> list[str]:
    """Insert missing template versions and make the declared version of each key active.

    Checks the declaration before writing anything, then inserts, deactivates
    and activates in one transaction.  Rows of keys that are not defined are
    left untouched.

    Args:
        session:         Open SQLAlchemy session; committed on success.
        definitions:     Template definitions (see :func:`check_active_versions`).
        active_versions: Mapping of template key to the version to activate.

    Returns:
        One log line per insert and per activation change.
    """
    check_active_versions(definitions, active_versions)
    log: list[str] = []

    existing = {
        (row.template_key, row.version)
        for row in session.scalars(select(PromptTemplate)).all()
    }
    for data in definitions:
        key, version = data["template_key"], data["version"]
        if (key, version) in existing:
            continue
        session.add(
            PromptTemplate(
                template_key=key,
                version=version,
                template_text=data["template_text"],
                is_active=False,
            )
        )
        log.append(f"[insert] template_key={key} version={version}")
    session.flush()

    for key, version in sorted(active_versions.items()):
        current = session.scalars(
            select(PromptTemplate.version).where(
                PromptTemplate.template_key == key, PromptTemplate.is_active
            )
        ).all()
        if current == [version]:
            continue
        # Deactivate first and flush, so the single-active index never sees two rows.
        session.execute(
            update(PromptTemplate)
            .where(PromptTemplate.template_key == key, PromptTemplate.is_active)
            .values(is_active=False)
        )
        session.flush()
        session.execute(
            update(PromptTemplate)
            .where(PromptTemplate.template_key == key, PromptTemplate.version == version)
            .values(is_active=True)
        )
        log.append(f"[activate] template_key={key} version={version} (was {current or 'none'})")

    session.commit()
    return log
