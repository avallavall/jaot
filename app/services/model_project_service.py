"""ModelProject service — create, draft, commit, restore, diff, list, archive.

All functions take a SQLAlchemy Session and have no FastAPI context (same pattern
as ``version_service.py``). Every query filters ``organization_id`` for tenancy.
"""

import hashlib
import json
import logging
from typing import Any

from sqlalchemy import desc, or_
from sqlalchemy.orm import Session

from app.models.model_project import ModelProject, ModelProjectDataset, ModelProjectVersion
from app.schemas.model_project import DiffEntry, VersionDiff
from app.shared.utils.datetime_helpers import utcnow

logger = logging.getLogger(__name__)


class ProjectConflictError(Exception):
    """Optimistic-concurrency or dirty-draft conflict — routes map this to 409."""


def content_hash(model_json: dict[str, Any] | None) -> str:
    """Stable sha256 of a canonical model_json (order-independent)."""
    canonical = json.dumps(model_json or {}, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


# --------------------------------------------------------------------------- #
# Create
# --------------------------------------------------------------------------- #
def create_blank(
    db: Session,
    *,
    org_id: str,
    user_id: str | None,
    name: str = "Untitled Project",
    description: str | None = None,
    workspace_id: str | None = None,
) -> ModelProject:
    """Create an empty project (no draft content, no versions; first commit = v1)."""
    project = ModelProject(
        organization_id=org_id,
        created_by=user_id,
        name=name,
        description=description,
        workspace_id=workspace_id,
        status="active",
        source_type="blank",
    )
    db.add(project)
    db.flush()
    db.refresh(project)
    logger.info("Created blank ModelProject %s for org %s", project.id, org_id)
    return project


def create_seeded(
    db: Session,
    *,
    org_id: str,
    user_id: str | None,
    name: str,
    problem_json: dict[str, Any] | None,
    canvas_json: dict[str, Any] | None = None,
    dsl_source: str | None = None,
    source_type: str,
    source_ref: str | None = None,
    auto_commit_summary: str | None = None,
) -> ModelProject:
    """Create a project seeded from another source (builder doc / template / import).

    The seed is written to the draft. When ``auto_commit_summary`` is set the
    draft is immediately committed as v1 so the project is born with history.
    """
    now = utcnow()
    project = ModelProject(
        organization_id=org_id,
        created_by=user_id,
        name=name,
        status="active",
        source_type=source_type,
        source_ref=source_ref,
        draft_model_json=problem_json,
        draft_canvas_json=canvas_json,
        draft_dsl_source=dsl_source,
        draft_content_hash=content_hash(problem_json),
        draft_updated_at=now,
    )
    db.add(project)
    db.flush()
    if auto_commit_summary:
        commit_version(db, project, user_id=user_id, summary=auto_commit_summary)
    db.refresh(project)
    logger.info(
        "Created seeded ModelProject %s (source=%s) for org %s", project.id, source_type, org_id
    )
    return project


# --------------------------------------------------------------------------- #
# Read / list
# --------------------------------------------------------------------------- #
def get_project_or_404(db: Session, project_id: str, org_id: str) -> ModelProject | None:
    """Fetch a project owned by the org (any status), or None."""
    return (
        db.query(ModelProject)
        .filter(ModelProject.id == project_id, ModelProject.organization_id == org_id)
        .first()
    )


def list_projects(
    db: Session,
    *,
    org_id: str,
    status: str | None = "active",
    workspace_id: str | None = None,
    q: str | None = None,
    created_by: str | None = None,
    skip: int = 0,
    limit: int = 50,
) -> list[ModelProject]:
    """List the org's projects, newest-updated first.

    The list is org-scoped (collaborative). Pass ``created_by`` to narrow it to a
    single user's models (the "Mine" filter).
    """
    query = db.query(ModelProject).filter(ModelProject.organization_id == org_id)
    if status:
        query = query.filter(ModelProject.status == status)
    if workspace_id:
        query = query.filter(ModelProject.workspace_id == workspace_id)
    if created_by:
        query = query.filter(ModelProject.created_by == created_by)
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(ModelProject.name.ilike(like), ModelProject.description.ilike(like))
        )
    return query.order_by(desc(ModelProject.updated_at)).offset(skip).limit(limit).all()


# --------------------------------------------------------------------------- #
# Mutate metadata / draft
# --------------------------------------------------------------------------- #
def update_meta(
    db: Session,
    project: ModelProject,
    *,
    name: str | None = None,
    description: str | None = None,
    status: str | None = None,
) -> ModelProject:
    """Patch project metadata. Sets archived_at when status flips to archived."""
    if name is not None:
        project.name = name
    if description is not None:
        project.description = description
    if status is not None and status != project.status:
        project.status = status
        project.archived_at = utcnow() if status == "archived" else None
    db.flush()
    db.refresh(project)
    return project


def update_draft(
    db: Session,
    project: ModelProject,
    *,
    model_json: dict[str, Any] | None = None,
    canvas_json: dict[str, Any] | None = None,
    dsl_source: str | None = None,
    expected_lock: int | None,
) -> ModelProject:
    """Replace the mutable HEAD draft with optimistic concurrency.

    ``expected_lock`` must equal the current ``draft_lock_version`` (the
    ``If-Match`` value); a mismatch means another tab/client wrote first and
    raises :class:`ProjectConflictError` (→ 409).
    """
    if expected_lock is not None and expected_lock != project.draft_lock_version:
        raise ProjectConflictError(
            f"stale draft: expected lock {expected_lock}, have {project.draft_lock_version}"
        )
    if model_json is not None:
        project.draft_model_json = model_json
        project.draft_content_hash = content_hash(model_json)
    if canvas_json is not None:
        project.draft_canvas_json = canvas_json
    if dsl_source is not None:
        project.draft_dsl_source = dsl_source
    project.draft_lock_version += 1
    project.draft_updated_at = utcnow()
    db.flush()
    db.refresh(project)
    return project


# --------------------------------------------------------------------------- #
# Versions
# --------------------------------------------------------------------------- #
def _latest_version(db: Session, project_id: str) -> ModelProjectVersion | None:
    return (
        db.query(ModelProjectVersion)
        .filter(ModelProjectVersion.model_project_id == project_id)
        .order_by(desc(ModelProjectVersion.sequence))
        .first()
    )


def commit_version(
    db: Session,
    project: ModelProject,
    *,
    user_id: str | None,
    summary: str,
    body: str | None = None,
    canvas_json: dict[str, Any] | None = None,
    dsl_source: str | None = None,
) -> ModelProjectVersion:
    """Snapshot the current draft as an immutable, message-bearing version.

    Serializes ``sequence`` allocation under a ``FOR UPDATE`` lock on the project
    row (same lock-order discipline as the credit/withdrawal flows). A blank
    summary is rejected by the caller's schema; here we treat an unchanged model
    (same ``content_hash`` as the current HEAD) as a **no-op** that returns the
    existing version without creating a row.
    """
    clean_summary = (summary or "").strip()
    if not clean_summary:
        raise ValueError("commit summary must not be empty")

    # Lock the project row up front to serialize sequence + current_version_id.
    locked = db.query(ModelProject).filter(ModelProject.id == project.id).with_for_update().one()

    model_json = locked.draft_model_json or {}
    new_hash = content_hash(model_json)

    # No-op dedup: a commit that doesn't change the model returns the current HEAD.
    if locked.current_version_id:
        current = (
            db.query(ModelProjectVersion)
            .filter(ModelProjectVersion.id == locked.current_version_id)
            .first()
        )
        if current is not None and current.content_hash == new_hash:
            return current

    latest = _latest_version(db, locked.id)
    next_seq = (latest.sequence if latest else 0) + 1

    # Freeze structural stats + problem class onto the immutable version (P1b).
    from app.services.model_stats_service import compute_from_json  # noqa: PLC0415

    stats = compute_from_json(model_json)

    version = ModelProjectVersion(
        model_project_id=locked.id,
        organization_id=locked.organization_id,
        sequence=next_seq,
        parent_version_id=locked.current_version_id,
        model_json=model_json,
        canvas_json=canvas_json if canvas_json is not None else locked.draft_canvas_json,
        dsl_source=dsl_source if dsl_source is not None else locked.draft_dsl_source,
        content_hash=new_hash,
        commit_summary=clean_summary[:500],
        commit_body=body.strip() if body else None,
        created_by=user_id,
        stats_json=stats.model_dump(mode="json"),
        problem_class=stats.problem_class,
    )
    db.add(version)
    db.flush()

    locked.current_version_id = version.id
    locked.committed_count = (locked.committed_count or 0) + 1
    db.flush()
    db.refresh(version)
    logger.info("Committed version %s (seq=%d) of project %s", version.id, next_seq, locked.id)
    return version


def list_versions(
    db: Session, project_id: str, org_id: str, *, skip: int = 0, limit: int = 50
) -> list[ModelProjectVersion]:
    """List a project's versions, newest first (org-scoped)."""
    return (
        db.query(ModelProjectVersion)
        .filter(
            ModelProjectVersion.model_project_id == project_id,
            ModelProjectVersion.organization_id == org_id,
        )
        .order_by(desc(ModelProjectVersion.sequence))
        .offset(skip)
        .limit(limit)
        .all()
    )


def get_version_or_404(
    db: Session, project_id: str, version_id: str, org_id: str
) -> ModelProjectVersion | None:
    """Fetch a single version with project + org ownership validation."""
    return (
        db.query(ModelProjectVersion)
        .filter(
            ModelProjectVersion.id == version_id,
            ModelProjectVersion.model_project_id == project_id,
            ModelProjectVersion.organization_id == org_id,
        )
        .first()
    )


def checkout_into_draft(
    db: Session,
    project: ModelProject,
    version: ModelProjectVersion,
    *,
    discard_draft: bool = False,
) -> ModelProject:
    """Copy a committed version's snapshot into the mutable draft.

    History is never mutated. If the draft has uncommitted changes (its hash
    differs from the current HEAD version) and ``discard_draft`` is False, a
    :class:`ProjectConflictError` is raised (→ 409) so the caller can confirm.
    """
    current_hash = None
    if project.current_version_id:
        current = (
            db.query(ModelProjectVersion)
            .filter(ModelProjectVersion.id == project.current_version_id)
            .first()
        )
        current_hash = current.content_hash if current else None

    draft_dirty = project.draft_content_hash is not None and project.draft_content_hash != (
        current_hash or content_hash(None)
    )
    if draft_dirty and not discard_draft:
        raise ProjectConflictError(
            "draft has uncommitted changes; pass discard_draft=true to overwrite"
        )

    project.draft_model_json = version.model_json
    project.draft_canvas_json = version.canvas_json
    project.draft_dsl_source = version.dsl_source
    project.draft_content_hash = version.content_hash
    project.draft_lock_version += 1
    project.draft_updated_at = utcnow()
    db.flush()
    db.refresh(project)
    logger.info("Checked out version %s into draft of project %s", version.id, project.id)
    return project


def diff_versions(a: ModelProjectVersion, b: ModelProjectVersion) -> VersionDiff:
    """Pure-python structural diff between two version snapshots' model_json."""
    am = a.model_json or {}
    bm = b.model_json or {}
    entries: list[DiffEntry] = []

    def _by_name(items: Any) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for it in items or []:
            if isinstance(it, dict) and it.get("name"):
                out[str(it["name"])] = it
        return out

    for kind, key in (("variable", "variables"), ("constraint", "constraints")):
        old = _by_name(am.get(key))
        new = _by_name(bm.get(key))
        for name in new.keys() - old.keys():
            entries.append(DiffEntry(kind=kind, change="added", name=name))
        for name in old.keys() - new.keys():
            entries.append(DiffEntry(kind=kind, change="removed", name=name))
        for name in old.keys() & new.keys():
            if old[name] != new[name]:
                entries.append(DiffEntry(kind=kind, change="modified", name=name))

    obj_changed = (am.get("objective") or {}) != (bm.get("objective") or {})
    if obj_changed:
        entries.append(DiffEntry(kind="objective", change="modified", name="objective"))

    return VersionDiff(
        from_version_id=a.id,
        to_version_id=b.id,
        entries=entries,
        objective_changed=obj_changed,
    )


def archive_project(db: Session, project: ModelProject) -> ModelProject:
    """Soft-delete a project (status=archived)."""
    project.status = "archived"
    project.archived_at = utcnow()
    db.flush()
    db.refresh(project)
    return project


def hard_delete_project(db: Session, project: ModelProject) -> None:
    """Permanently delete a project and its versions (irreversible).

    The ``versions`` relationship cascades (``all, delete-orphan`` + DB-level
    ``ondelete=CASCADE``), so the committed history is removed with it (and so are
    its datasets). Past ``ModelExecution`` rows keep their ``model_project_id`` as
    a historical tag (no FK), so the executions audit trail is preserved. The AI
    Assistant conversations, by contrast, are unlinked (``model_project_id``
    cleared) so the project-scoped conversation filter never returns rows dangling
    off a dead id.
    """
    from app.models.llm_conversation import LLMConversation  # noqa: PLC0415

    db.query(LLMConversation).filter(LLMConversation.model_project_id == project.id).update(
        {"model_project_id": None}, synchronize_session=False
    )
    db.delete(project)
    db.flush()


# --------------------------------------------------------------------------- #
# Datasets (named data bundles / scenarios, §8)
# --------------------------------------------------------------------------- #

#: Upper bound on a dataset's serialized size. Generous for real scenarios (the
#: TFM's largest is well under 1 MB of values) while keeping a single row from
#: approaching the request-body cap.
MAX_DATASET_JSON_BYTES = 5_000_000


def validate_dataset_json(data_json: dict[str, Any]) -> None:
    """Validate a dataset's ``data_json`` (size + JModelData shape).

    Raises :class:`~app.domains.dsl.JModelError` — routes map it to a 422 with the
    message. Validating here (not in the Pydantic schema) keeps ``app.schemas``
    from importing ``app.domains`` (the compiler imports ``app.schemas`` — a cycle).
    """
    from app.domains.dsl import JModelData, JModelError  # noqa: PLC0415

    serialized = json.dumps(data_json, separators=(",", ":"), default=str)
    if len(serialized) > MAX_DATASET_JSON_BYTES:
        raise JModelError(
            f"dataset is too large ({len(serialized):,} bytes — max {MAX_DATASET_JSON_BYTES:,})"
        )
    JModelData.from_json(data_json)


def list_datasets(db: Session, project: ModelProject) -> list[ModelProjectDataset]:
    """The project's datasets, oldest first (stable scenario order)."""
    return (
        db.query(ModelProjectDataset)
        .filter(
            ModelProjectDataset.model_project_id == project.id,
            ModelProjectDataset.organization_id == project.organization_id,
        )
        .order_by(ModelProjectDataset.created_at, ModelProjectDataset.id)
        .all()
    )


def get_dataset_or_404(
    db: Session, dataset_id: str, org_id: str, project_id: str | None = None
) -> ModelProjectDataset | None:
    """Fetch an org-owned dataset (optionally pinned to a project), or None."""
    query = db.query(ModelProjectDataset).filter(
        ModelProjectDataset.id == dataset_id,
        ModelProjectDataset.organization_id == org_id,
    )
    if project_id is not None:
        query = query.filter(ModelProjectDataset.model_project_id == project_id)
    return query.first()


def _dataset_name_taken(
    db: Session, project: ModelProject, name: str, exclude_id: str | None = None
) -> bool:
    query = db.query(ModelProjectDataset.id).filter(
        ModelProjectDataset.model_project_id == project.id,
        ModelProjectDataset.name == name,
    )
    if exclude_id is not None:
        query = query.filter(ModelProjectDataset.id != exclude_id)
    return db.query(query.exists()).scalar() or False


def create_dataset(
    db: Session,
    project: ModelProject,
    *,
    user_id: str | None,
    name: str,
    description: str | None,
    data_json: dict[str, Any],
) -> ModelProjectDataset:
    """Create a named dataset for the project.

    Raises :class:`~app.domains.dsl.JModelError` on an invalid ``data_json`` and
    :class:`ProjectConflictError` on a duplicate name (a unique index backs this).
    """
    validate_dataset_json(data_json)
    if _dataset_name_taken(db, project, name):
        raise ProjectConflictError(f"a dataset named {name!r} already exists")
    dataset = ModelProjectDataset(
        model_project_id=project.id,
        organization_id=project.organization_id,
        created_by=user_id,
        name=name,
        description=description,
        data_json=data_json,
    )
    db.add(dataset)
    db.flush()
    db.refresh(dataset)
    logger.info("Created dataset %s (%r) for project %s", dataset.id, name, project.id)
    return dataset


def update_dataset(
    db: Session,
    dataset: ModelProjectDataset,
    *,
    name: str | None = None,
    description: str | None = None,
    data_json: dict[str, Any] | None = None,
) -> ModelProjectDataset:
    """Update a dataset's name/description/values (only the fields provided)."""
    if data_json is not None:
        validate_dataset_json(data_json)
        dataset.data_json = data_json
    if name is not None and name != dataset.name:
        if _dataset_name_taken(db, dataset.project, name, exclude_id=dataset.id):
            raise ProjectConflictError(f"a dataset named {name!r} already exists")
        dataset.name = name
    if description is not None:
        dataset.description = description
    dataset.updated_at = utcnow()
    db.flush()
    db.refresh(dataset)
    return dataset


def delete_dataset(db: Session, dataset: ModelProjectDataset) -> None:
    """Delete a dataset (datasets are working data — no soft-delete tier)."""
    db.delete(dataset)
    db.flush()
