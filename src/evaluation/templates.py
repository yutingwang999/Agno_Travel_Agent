"""Generation prompt templates of a run: which versions it used, and a copy of each.

A run directory gets ``generation_prompts/<template key>_v<version>.txt`` beside
``judge_prompts/``: the text of every prompt template version the run used,
read from the evaluation database.  With the request and the step events stored
per entry in ``results.jsonl`` they reproduce every prompt sent to the
generation model.

The generation templates come from the generate events (``generation_templates``
in the summary).  validate_output does not report which correction template it
used, so the run records the version active when it started
(``correction_template``).

Public API::

    from evaluation.templates import templates_used, read_template_texts, write_generation_prompts
"""

from pathlib import Path

from sqlalchemy import create_engine, text

CORRECTION_TEMPLATE_KEY = "validate_output_correction"
PROMPTS_DIRNAME = "generation_prompts"


def templates_used(conditions: dict) -> list[tuple[str, int]]:
    """Return the (key, version) pairs a run used, from its summary's ``conditions``."""
    pairs = [(t["key"], t["version"]) for t in conditions.get("generation_templates", [])]
    correction = conditions.get("correction_template")
    if correction:
        pairs.append((correction["key"], correction["version"]))
    return sorted(set(pairs))


def active_version(db_url: str, template_key: str) -> int | None:
    """Return the active version of *template_key*, or None when none is active."""
    engine = create_engine(db_url)
    try:
        with engine.connect() as conn:
            return conn.execute(
                text("SELECT version FROM prompt_templates WHERE template_key = :key AND is_active"),
                {"key": template_key},
            ).scalar()
    finally:
        engine.dispose()


def read_template_texts(db_url: str, templates: list[tuple[str, int]]) -> dict[tuple[str, int], str]:
    """Return the text of each (key, version); raise LookupError if one is missing."""
    engine = create_engine(db_url)
    texts: dict[tuple[str, int], str] = {}
    try:
        with engine.connect() as conn:
            for key, version in templates:
                found = conn.execute(
                    text("SELECT template_text FROM prompt_templates "
                         "WHERE template_key = :key AND version = :version"),
                    {"key": key, "version": version},
                ).scalar()
                if found is None:
                    raise LookupError(f"prompt template {key!r} v{version} is not in the database")
                texts[(key, version)] = found
    finally:
        engine.dispose()
    return texts


def write_generation_prompts(run_dir: Path, texts: dict[tuple[str, int], str]) -> list[Path]:
    """Write one file per template version; never overwrite an existing file."""
    target = run_dir / PROMPTS_DIRNAME
    target.mkdir(parents=True, exist_ok=True)
    paths = [target / f"{key}_v{version}.txt" for key, version in texts]
    existing = [p for p in paths if p.exists()]
    if existing:
        raise FileExistsError(f"already written: {', '.join(p.name for p in existing)}")
    for path, template_text in zip(paths, texts.values()):
        path.write_text(template_text, encoding="utf-8", newline="\n")
    return paths
