"""Guidance endpoints for skill level and wizard state persistence."""

from fastapi import APIRouter, HTTPException
from sqlalchemy.orm.attributes import flag_modified

from app.api.deps import CurrentUser, DBSession
from app.models import User
from app.schemas.guidance import GuidanceResponse, GuidanceUpdate, SkillLevel

router = APIRouter()

_DEFAULT_GUIDANCE_STATE = {
    "wizard_step": 0,
    "wizard_dismissed": False,
    "wizard_completed": False,
}


@router.get("/guidance", response_model=GuidanceResponse)
def get_guidance(user: CurrentUser) -> GuidanceResponse:
    """Return current user's guidance preferences and wizard state."""
    state = user.guidance_state or _DEFAULT_GUIDANCE_STATE
    return GuidanceResponse(
        skill_level=SkillLevel(user.skill_level),
        wizard_step=state.get("wizard_step", 0),
        wizard_dismissed=bool(state.get("wizard_dismissed", False)),
        wizard_completed=bool(state.get("wizard_completed", False)),
    )


@router.patch("/guidance", response_model=GuidanceResponse)
def update_guidance(body: GuidanceUpdate, user: CurrentUser, db: DBSession) -> GuidanceResponse:
    """Update guidance preferences and/or wizard state (partial update)."""
    # Re-query user in endpoint session — middleware loads from a separate session,
    # so user object can't be committed/refreshed via the endpoint's db session.
    db_user = db.query(User).filter(User.id == user.id).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")

    if body.skill_level is not None:
        db_user.skill_level = body.skill_level.value

    # Merge wizard state fields into existing JSON
    state = dict(db_user.guidance_state or _DEFAULT_GUIDANCE_STATE)

    if body.wizard_step is not None:
        state["wizard_step"] = body.wizard_step
    if body.wizard_dismissed is not None:
        state["wizard_dismissed"] = body.wizard_dismissed
    if body.wizard_completed is not None:
        state["wizard_completed"] = body.wizard_completed

    db_user.guidance_state = state
    flag_modified(db_user, "guidance_state")

    db.commit()
    db.refresh(db_user)

    return GuidanceResponse(
        skill_level=SkillLevel(db_user.skill_level),
        wizard_step=state.get("wizard_step", 0),
        wizard_dismissed=bool(state.get("wizard_dismissed", False)),
        wizard_completed=bool(state.get("wizard_completed", False)),
    )
