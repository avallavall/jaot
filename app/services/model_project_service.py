"""ModelProject service — create, draft, commit, restore, diff, list, archive.

All functions take a SQLAlchemy Session and have no FastAPI context (same pattern
as ``version_service.py``). Every query filters ``organization_id`` for tenancy.
"""

import hashlib
import json
import logging
from typing import Any

from sqlalchemy import desc, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.model_project import (
    ModelProject,
    ModelProjectDataset,
    ModelProjectListing,
    ModelProjectVersion,
)
from app.schemas.model import PublishModelRequest
from app.schemas.model_project import DiffEntry, VersionDiff
from app.shared.constants.listing_status import (
    AUTHOR_TOGGLEABLE,
    STATUS_PUBLISHED,
    STATUS_UNPUBLISHED,
)
from app.shared.utils.datetime_helpers import utcnow

logger = logging.getLogger(__name__)


class ProjectConflictError(Exception):
    """Optimistic-concurrency or dirty-draft conflict — routes map this to 409."""


def content_hash(model_json: dict[str, Any] | None) -> str:
    """Stable sha256 of a canonical model_json (order-independent)."""
    canonical = json.dumps(model_json or {}, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def draft_is_untouched(project: ModelProject) -> bool:
    """Is the draft still exactly what the project was seeded with?

    A generator-backed fork holds a model rendered once, at fork time, and the
    solve path re-renders from the card. When the card is corrected the two stop
    agreeing: the studio shows one model and the API solves another, for the
    same project id, with no warning on either side.

    While this returns True the draft is a cache of the card and may be
    refreshed. Once it returns False the user has edited the model by hand, and
    their version is what every path must use — the draft PUT has never refused
    an edit to a generator-backed project, so those edits exist and were being
    thrown away by the solve path.

    A project seeded before ``seed_content_hash`` existed has NULL there and so
    reads as edited. That is deliberate: we cannot tell whether it was edited,
    and keeping a model the user may have written beats overwriting it.
    """
    return (
        project.seed_content_hash is not None
        and project.draft_content_hash == project.seed_content_hash
    )


def refresh_seeded_draft(db: Session, project: ModelProject, model_json: dict[str, Any]) -> bool:
    """Bring an untouched generator-backed draft back in step with its card.

    Returns True when the draft moved. Does nothing when the user has edited it.
    """
    if not draft_is_untouched(project):
        return False
    fresh = content_hash(model_json)
    if fresh == project.draft_content_hash:
        return False
    project.draft_model_json = model_json
    project.draft_content_hash = fresh
    project.seed_content_hash = fresh
    project.draft_updated_at = utcnow()
    project.draft_lock_version = (project.draft_lock_version or 0) + 1
    db.flush()
    return True


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
        seed_content_hash=content_hash(problem_json),
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
        if status == "archived":
            withdraw_listing_on_archive(db, project)
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
    # Serialize concurrent writers at the row before comparing: a plain
    # read-then-compare lets two clients presenting the same If-Match both
    # pass (neither sees the other's uncommitted bump) and the second write
    # silently overwrites the first. FOR UPDATE makes the loser re-read the
    # winner's bumped version and take the 409.
    db.refresh(project, with_for_update=True)
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


class ProjectNotPublishableError(Exception):
    """A project that may not be published — routes map this to 400.

    Two different reasons reach here, and they ask the author for two different
    things: commit *anything*, or commit a change *of your own*. The interface
    turned both into "commit first, then come back", which is a lie to somebody
    who already committed. ``code`` is what lets a screen tell them apart; it is
    the same stable-identifier convention as :class:`CodedHTTPException`.
    """

    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.code = code


#: No commit at all — the listing pins a committed version, never the draft.
PUBLISH_NEEDS_COMMIT = "projects.publish_needs_commit"
#: Adopted from the marketplace and still identical to what was adopted.
PUBLISH_NEEDS_OWN_CHANGE = "projects.publish_needs_own_change"


def publish_listing(
    db: Session,
    project: ModelProject,
    *,
    author_org_id: str,
    req: PublishModelRequest,
) -> ModelProjectListing:
    """Publish a project to the marketplace: upsert its listing facet + pin the HEAD version.

    Publishing pins the committed HEAD version (``current_version_id``), never the
    dirty draft (P1.5 §2.1), so a project must have at least one commit — otherwise
    :class:`ProjectNotPublishableError`. Re-publishing updates the same 1:1 listing and
    re-pins the current HEAD. The model CONTENT stays on the project/version; the listing
    holds only presentation (no generator facet — a published project runs from its
    versioned problem).
    """
    if project.current_version_id is None:
        raise ProjectNotPublishableError(
            "Commit a version before publishing.", PUBLISH_NEEDS_COMMIT
        )
    # Owner decision 2026-07-17: an ADOPTED model (marketplace fork) may only be
    # republished after the adopter commits their own change — derivative works
    # are welcome, 1:1 authorship clones are not. The adoption seed auto-commits
    # v1, and commit_version dedups no-change commits, so committed_count > 1
    # really means "modified".
    if project.source_type == "marketplace" and (project.committed_count or 0) <= 1:
        raise ProjectNotPublishableError(
            "This model was adopted from the marketplace. Commit a change of your "
            "own before publishing it as your listing.",
            PUBLISH_NEEDS_OWN_CHANGE,
        )

    now = utcnow()
    listing = (
        db.query(ModelProjectListing)
        .filter(ModelProjectListing.model_project_id == project.id)
        .first()
    )
    if listing is None:
        listing = ModelProjectListing(model_project_id=project.id, published_at=now)
        db.add(listing)

    listing.name = req.display_name.lower().replace(" ", "_")
    listing.display_name = req.display_name
    listing.description = req.description
    listing.short_description = req.short_description
    listing.category = req.category
    listing.tags = req.tags
    listing.is_public = req.is_public
    listing.status = STATUS_PUBLISHED
    listing.is_official = False
    listing.author_organization_id = author_org_id
    listing.pinned_version_id = project.current_version_id
    listing.section_overview = req.section_overview
    listing.section_features = req.section_features
    listing.section_how_it_works = req.section_how_it_works
    listing.section_example_io = req.section_example_io
    listing.section_changelog = req.section_changelog
    if listing.published_at is None:
        listing.published_at = now
    db.flush()
    return listing


class ListingNotFoundError(Exception):
    """Withdrawing/restoring a project that was never published — routes map this to 404."""


class ListingStateError(Exception):
    """The listing is not in a state this transition applies to — routes map this to 409."""


def set_listing_published(
    db: Session,
    project: ModelProject,
    *,
    published: bool,
) -> ModelProjectListing:
    """Withdraw a listing from the marketplace, or put it back. Reversible either way.

    Owner decision 2026-07-31: withdrawing keeps the listing row and every rollup
    on it (adoptions, executions, average rating), so restoring is one click and
    the history survives. Every catalog surface — list, detail and input schema —
    filters ``status == "published"``, so a withdrawn listing is simply absent
    from all three.

    Forks already made are unaffected: adoption COPIES the model into the
    adopter's own project (``create_from_marketplace``), and ``source_ref`` is
    plain provenance text with no FK, so nothing dereferences the listing
    afterwards.

    Only ``published <-> unpublished`` is a legal round trip. Restoring is NOT a
    way into ``published`` from anywhere else: a ``draft`` listing has never
    passed :func:`publish_listing`'s checks (committed version, the adopted-model
    rule, pinning HEAD) and has no ``pinned_version_id``, so promoting it would
    put a listing on the marketplace that 404s the moment somebody adopts it; a
    ``deprecated`` one is a template the seeder retired on purpose. Both must go
    through publish, which is why this raises instead of quietly widening.

    Idempotent in both directions: repeating a transition already applied is a
    no-op, not an error, so a double-clicked button is harmless.
    """
    listing = (
        db.query(ModelProjectListing)
        .filter(ModelProjectListing.model_project_id == project.id)
        .first()
    )
    if listing is None:
        raise ListingNotFoundError("This project has never been published to the marketplace.")

    target = STATUS_PUBLISHED if published else STATUS_UNPUBLISHED
    if listing.status not in AUTHOR_TOGGLEABLE:
        raise ListingStateError(
            f"A listing in state '{listing.status}' cannot be {target} from here; publish it."
        )

    listing.status = target
    db.flush()
    return listing


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


def withdraw_listing_on_archive(db: Session, project: ModelProject) -> ModelProjectListing | None:
    """Take a published listing off the marketplace because its project was archived.

    An archived project refuses every write, so its listing could never be
    updated again, and the author had put the model away. Until this existed the
    listing stayed on the marketplace: a visitor searched, opened the detail page
    and copied the model of somebody who thought it was gone. Archiving is the
    only way to a permanent delete, so the window was not an edge case.

    Only a ``published`` listing is touched. A ``draft`` or ``deprecated`` one is
    already absent from every catalog surface, and moving it would be the widening
    :func:`set_listing_published` refuses. Restoring the project does NOT put the
    listing back: the author publishes again, one click, with the rollups intact.
    """
    listing = (
        db.query(ModelProjectListing)
        .filter(
            ModelProjectListing.model_project_id == project.id,
            ModelProjectListing.status == STATUS_PUBLISHED,
        )
        .first()
    )
    if listing is None:
        return None
    listing.status = STATUS_UNPUBLISHED
    db.flush()
    return listing


def archive_project(db: Session, project: ModelProject) -> ModelProject:
    """Soft-delete a project (status=archived) and withdraw its listing."""
    project.status = "archived"
    project.archived_at = utcnow()
    withdraw_listing_on_archive(db, project)
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
#: TFM's largest — 243 vehicles × 199 orders over three sparse tuple arc sets —
#: serializes to ~5.8 MB) while keeping a single row well under the 50 MB
#: request-body cap.
MAX_DATASET_JSON_BYTES = 16_000_000


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
    try:
        db.flush()
    except IntegrityError as exc:
        # A concurrent creator won the unique index (ix_mpd_project_name) — the
        # pre-check can't see an uncommitted rival row; surface the same 409
        raise ProjectConflictError(f"a dataset named {name!r} already exists") from exc
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
    try:
        db.flush()
    except IntegrityError as exc:
        raise ProjectConflictError(f"a dataset named {dataset.name!r} already exists") from exc
    db.refresh(dataset)
    return dataset


def delete_dataset(db: Session, dataset: ModelProjectDataset) -> None:
    """Delete a dataset (datasets are working data — no soft-delete tier)."""
    db.delete(dataset)
    db.flush()
