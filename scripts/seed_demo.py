#!/usr/bin/env python3
"""Seed a rich showcase environment with realistic demo data.

Creates a complete demo environment with:
- 1 organization ("JAOT Showcase", Pro plan, 50K credits)
- 3 users (admin, solver, viewer)
- 1 API key for the admin
- 5 activated catalog models
- 8 execution records (5 completed, 2 failed, 1 timeout)
- 5 marketplace reviews
- 1 workspace with 3 members
- 2 builder documents with canvas data
- 1 solve trigger
- Cleanup of leftover test documents ("AI-Generated Model", empty "Untitled Model") across all orgs

Idempotent: safe to run multiple times. Checks for existing data before creating.

Usage:
    python scripts/seed_demo.py
"""

from __future__ import annotations

import hashlib
import secrets
import sys
import uuid
from datetime import timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy.orm import Session  # noqa: E402

from app.models import (  # noqa: E402
    ModelBuilderDocument,
    ModelCatalog,
    ModelExecution,
    ModelReview,
    ModelVersion,
    Organization,
    OrganizationModel,
    SolveTrigger,
    User,
    Workspace,
    WorkspaceMember,
)
from app.services.auth import APIKeyService  # noqa: E402
from app.services.auth.password_service import PasswordService  # noqa: E402
from app.shared.db import SessionLocal  # noqa: E402
from app.shared.utils.datetime_helpers import utcnow  # noqa: E402
from app.shared.utils.id_generator import generate_id  # noqa: E402

DEMO_ORG_NAME = "JAOT Showcase"

DEMO_USERS = [
    {
        "email": "demo@jaot.io",
        "password": "ShowcaseAdmin2026!",
        "name": "Demo Admin",
        "role": "admin",
    },
    {
        "email": "solver@jaot.io",
        "password": "ShowcaseSolver2026!",
        "name": "Maria Garcia",
        "role": "member",
    },
    {
        "email": "viewer@jaot.io",
        "password": "ShowcaseViewer2026!",
        "name": "Jean Dupont",
        "role": "member",
    },
]

# Catalog IDs follow the pattern "official_{template_id}" (see seed_models.py)
DEMO_CATALOG_IDS = [
    "official_knapsack",
    "official_vehicle_routing",
    "official_employee_scheduling",
    "official_production_planning",
    "official_portfolio_optimization",
]

DEMO_REVIEWS = [
    {
        "catalog_index": 0,
        "user_index": 0,
        "rating": 5,
        "title": "Excellent for our supply chain",
        "comment": (
            "We used the knapsack model to optimise cargo loading for 12 trucks. "
            "Solve time was under 200ms and the results were spot-on. "
            "Highly recommended for logistics teams."
        ),
    },
    {
        "catalog_index": 1,
        "user_index": 1,
        "rating": 4,
        "title": "Good routing model, handles complex cases",
        "comment": (
            "Vehicle routing solved our 15-stop delivery problem in under 2 seconds. "
            "Would love to see time-window constraints in a future version."
        ),
    },
    {
        "catalog_index": 2,
        "user_index": 0,
        "rating": 5,
        "title": "Saved us hours of manual scheduling",
        "comment": (
            "Employee scheduling replaced our spreadsheet process completely. "
            "The solver respects availability and minimises overtime costs. Perfect."
        ),
    },
    {
        "catalog_index": 3,
        "user_index": 2,
        "rating": 4,
        "title": "Solid production planner",
        "comment": (
            "Good model, could use more constraint types for multi-stage production. "
            "That said, it correctly maximised profit for our furniture workshop."
        ),
    },
    {
        "catalog_index": 4,
        "user_index": 1,
        "rating": 3,
        "title": "Decent portfolio optimizer",
        "comment": (
            "Works well for basic Markowitz allocation. We needed sector-level caps "
            "which required some manual tweaking of the input data. Still useful."
        ),
    },
]


def _get_or_create_org(db: Session) -> tuple[Organization, bool]:
    """Return the demo org, creating it if necessary."""
    org = db.query(Organization).filter(Organization.name == DEMO_ORG_NAME).first()
    if org:
        return org, False

    org = Organization(
        id=generate_id("org_"),
        name=DEMO_ORG_NAME,
        plan="pro",
        credits_balance=50000,
        credits_subscription=20000,
        credits_purchased=30000,
        monthly_quota=20000,
        rate_limit_per_minute=60,
        rate_limit_per_day=1000,
        is_active=True,
        ai_builder_enabled=True,
        max_private_plugins=20,
    )
    db.add(org)
    db.flush()
    print(f"  Created organization: {org.name} ({org.id})")
    return org, True


def _get_or_create_user(
    db: Session,
    org: Organization,
    email: str,
    password: str,
    name: str,
    role: str,
) -> tuple[User, bool]:
    user = db.query(User).filter(User.email == email).first()
    if user:
        return user, False

    now = utcnow()
    user = User(
        id=generate_id("usr_"),
        email=email,
        name=name,
        organization_id=org.id,
        role=role,
        is_active=True,
        password_hash=PasswordService.hash_password(password),
        email_verified=True,
        email_verified_at=now,
        tos_accepted_at=now,
    )
    db.add(user)
    db.flush()
    print(f"  Created user: {email} ({user.id}) role={role}")
    return user, True


def _ensure_api_key(db: Session, user: User, org: Organization) -> str | None:
    """Create an API key for the demo admin if none exists."""
    from app.models import APIKey

    existing = (
        db.query(APIKey)
        .filter(
            APIKey.user_id == user.id, APIKey.organization_id == org.id, APIKey.is_active.is_(True)
        )
        .first()
    )
    if existing:
        print(f"  API key already exists for {user.email}")
        return None

    _, plaintext = APIKeyService.create_api_key(
        db=db,
        user_id=user.id,
        organization_id=org.id,
        name="Demo Admin Key",
        prefix="ok_live_",
    )
    print(f"  Created API key for {user.email}")
    return plaintext


def _activate_catalog_models(
    db: Session, org: Organization, catalog_ids: list[str]
) -> list[OrganizationModel]:
    """Activate catalog models for the demo org. Returns the org models."""
    org_models: list[OrganizationModel] = []

    for catalog_id in catalog_ids:
        existing = (
            db.query(OrganizationModel)
            .filter(
                OrganizationModel.organization_id == org.id,
                OrganizationModel.catalog_id == catalog_id,
            )
            .first()
        )
        if existing:
            org_models.append(existing)
            continue

        catalog = db.query(ModelCatalog).filter(ModelCatalog.id == catalog_id).first()
        if not catalog:
            print(f"  WARNING: Catalog model {catalog_id} not found, skipping")
            continue

        catalog.total_activations = (catalog.total_activations or 0) + 1

        org_model = OrganizationModel(
            id=str(uuid.uuid4()),
            organization_id=org.id,
            catalog_id=catalog_id,
            is_active=True,
            purchased_at=utcnow(),
            purchase_price_eur=0.0,
        )
        db.add(org_model)
        db.flush()
        org_models.append(org_model)
        print(f"  Activated catalog model: {catalog_id}")

    return org_models


def _ensure_credit_transactions(db: Session, org: Organization, admin_user: User) -> None:
    """Create credit transactions for existing executions (for Usage analytics)."""
    from app.models.credit_transaction import CreditTransaction

    existing_txns = (
        db.query(CreditTransaction)
        .filter(
            CreditTransaction.organization_id == org.id,
            CreditTransaction.transaction_type == "execution_charge",
        )
        .count()
    )
    if existing_txns > 0:
        print(f"  Credit transactions already exist ({existing_txns} found), skipping")
        return

    balance = 50000
    txn_count = 0
    all_execs = (
        db.query(ModelExecution)
        .filter(ModelExecution.organization_id == org.id)
        .order_by(ModelExecution.created_at)
        .all()
    )
    for ex in all_execs:
        if ex.credits_consumed and ex.credits_consumed > 0:
            balance -= ex.credits_consumed
            txn = CreditTransaction(
                id=generate_id("txn_"),
                organization_id=org.id,
                transaction_type="execution_charge",
                credits_amount=-ex.credits_consumed,
                balance_after=balance,
                earned_balance_after=0,
                description=f"Model execution {ex.id}",
                reference_type="execution",
                reference_id=ex.id,
                created_at=ex.created_at,
                created_by=admin_user.id,
            )
            db.add(txn)
            txn_count += 1
    db.flush()
    print(f"  Created {txn_count} credit transactions for analytics")


def _build_execution_records(
    db: Session,
    org: Organization,
    org_models: list[OrganizationModel],
    admin_user: User,
) -> None:
    """Create 8 execution records across the first 3 org models."""
    if len(org_models) < 3:
        print("  WARNING: Not enough activated models for execution records")
        return

    existing_count = (
        db.query(ModelExecution).filter(ModelExecution.organization_id == org.id).count()
    )
    if existing_count >= 8:
        print(f"  Executions already exist ({existing_count} found), skipping creation")
        _ensure_credit_transactions(db, org, admin_user)
        return

    now = utcnow()

    knapsack_model = org_models[0]
    knapsack_executions = [
        {
            "status": "completed",
            "input_data": {
                "capacity": 50,
                "items": [
                    {"name": "laptop", "value": 600, "weight": 10},
                    {"name": "camera", "value": 500, "weight": 5},
                    {"name": "headphones", "value": 150, "weight": 2},
                    {"name": "tablet", "value": 400, "weight": 8},
                ],
            },
            "result_data": {
                "objective_value": 1650.0,
                "status": "optimal",
                "solve_time_seconds": 0.112,
                "variables": {"laptop": 1, "camera": 1, "headphones": 1, "tablet": 1},
                "gap": 0.0,
            },
            "execution_time_ms": 112,
            "objective_value": 1650.0,
            "solver_status": "optimal",
            "credits_consumed": 1,
            "created_at": now - timedelta(days=3, hours=2),
        },
        {
            "status": "completed",
            "input_data": {
                "capacity": 30,
                "items": [
                    {"name": "laptop", "value": 600, "weight": 10},
                    {"name": "camera", "value": 500, "weight": 5},
                    {"name": "book", "value": 30, "weight": 3},
                    {"name": "charger", "value": 50, "weight": 1},
                ],
            },
            "result_data": {
                "objective_value": 1180.0,
                "status": "optimal",
                "solve_time_seconds": 0.098,
                "variables": {"laptop": 1, "camera": 1, "book": 1, "charger": 1},
                "gap": 0.0,
            },
            "execution_time_ms": 98,
            "objective_value": 1180.0,
            "solver_status": "optimal",
            "credits_consumed": 1,
            "created_at": now - timedelta(days=2, hours=5),
        },
        {
            "status": "failed",
            "input_data": {
                "capacity": -10,
                "items": [{"name": "invalid", "value": 0, "weight": 0}],
            },
            "result_data": None,
            "error_message": "Validation error: capacity must be positive",
            "execution_time_ms": 15,
            "objective_value": None,
            "solver_status": None,
            "credits_consumed": 0,
            "created_at": now - timedelta(days=2, hours=1),
        },
    ]

    routing_model = org_models[1]
    routing_executions = [
        {
            "status": "completed",
            "input_data": {
                "depot": {"name": "Warehouse", "x": 0, "y": 0},
                "locations": [
                    {"name": "Restaurant A", "x": 5, "y": 10, "demand": 3},
                    {"name": "Restaurant B", "x": -3, "y": 8, "demand": 2},
                    {"name": "Restaurant C", "x": 7, "y": -2, "demand": 4},
                ],
                "vehicles": [
                    {"name": "Truck 1", "capacity": 10},
                    {"name": "Truck 2", "capacity": 10},
                ],
                "distances": {
                    "Warehouse-Restaurant A": 11.18,
                    "Warehouse-Restaurant B": 8.54,
                    "Warehouse-Restaurant C": 7.28,
                    "Restaurant A-Restaurant B": 8.25,
                    "Restaurant A-Restaurant C": 12.17,
                    "Restaurant B-Restaurant C": 14.14,
                },
            },
            "result_data": {
                "objective_value": 45.32,
                "status": "optimal",
                "solve_time_seconds": 1.876,
                "variables": {
                    "route_truck1": ["Warehouse", "Restaurant A", "Restaurant B", "Warehouse"],
                    "route_truck2": ["Warehouse", "Restaurant C", "Warehouse"],
                },
                "gap": 0.0,
            },
            "execution_time_ms": 1876,
            "objective_value": 45.32,
            "solver_status": "optimal",
            "credits_consumed": 3,
            "created_at": now - timedelta(days=1, hours=8),
        },
        {
            "status": "timeout",
            "input_data": {
                "depot": {"name": "Warehouse", "x": 0, "y": 0},
                "locations": [
                    {"name": f"Location {i}", "x": i * 3, "y": i * 2, "demand": 2}
                    for i in range(1, 51)
                ],
                "vehicles": [{"name": f"Truck {i}", "capacity": 20} for i in range(1, 6)],
                "distances": {},
            },
            "result_data": None,
            "error_message": "Solver time limit exceeded (300s). Best bound gap: 12.4%",
            "execution_time_ms": 300000,
            "objective_value": None,
            "solver_status": "timelimit",
            "credits_consumed": 10,
            "created_at": now - timedelta(days=1, hours=3),
        },
    ]

    scheduling_model = org_models[2]
    scheduling_executions = [
        {
            "status": "completed",
            "input_data": {
                "employees": [
                    {"name": "Alice", "hourly_cost": 25, "max_hours": 40, "min_hours": 8},
                    {"name": "Bob", "hourly_cost": 22, "max_hours": 40, "min_hours": 8},
                    {"name": "Carol", "hourly_cost": 28, "max_hours": 32, "min_hours": 0},
                ],
                "shifts": [
                    {"name": "Monday AM", "duration": 8, "min_staff": 1, "max_staff": 2},
                    {"name": "Monday PM", "duration": 8, "min_staff": 1, "max_staff": 2},
                    {"name": "Tuesday AM", "duration": 8, "min_staff": 1, "max_staff": 2},
                ],
            },
            "result_data": {
                "objective_value": 1200.0,
                "status": "optimal",
                "solve_time_seconds": 0.534,
                "variables": {
                    "Alice_Monday_AM": 1,
                    "Bob_Monday_PM": 1,
                    "Carol_Tuesday_AM": 1,
                    "Alice_Tuesday_AM": 1,
                },
                "gap": 0.0,
            },
            "execution_time_ms": 534,
            "objective_value": 1200.0,
            "solver_status": "optimal",
            "credits_consumed": 2,
            "created_at": now - timedelta(hours=18),
        },
        {
            "status": "completed",
            "input_data": {
                "employees": [
                    {"name": "Alice", "hourly_cost": 25, "max_hours": 40, "min_hours": 16},
                    {"name": "Bob", "hourly_cost": 22, "max_hours": 40, "min_hours": 16},
                    {"name": "Carol", "hourly_cost": 28, "max_hours": 40, "min_hours": 8},
                    {"name": "Dave", "hourly_cost": 20, "max_hours": 24, "min_hours": 8},
                ],
                "shifts": [
                    {"name": "Mon AM", "duration": 8, "min_staff": 2, "max_staff": 3},
                    {"name": "Mon PM", "duration": 8, "min_staff": 1, "max_staff": 2},
                    {"name": "Tue AM", "duration": 8, "min_staff": 2, "max_staff": 3},
                    {"name": "Tue PM", "duration": 8, "min_staff": 1, "max_staff": 2},
                    {"name": "Wed AM", "duration": 8, "min_staff": 2, "max_staff": 3},
                ],
            },
            "result_data": {
                "objective_value": 4720.0,
                "status": "optimal",
                "solve_time_seconds": 4.892,
                "variables": {
                    "Alice_Mon_AM": 1,
                    "Bob_Mon_AM": 1,
                    "Carol_Mon_PM": 1,
                    "Dave_Tue_AM": 1,
                    "Alice_Tue_AM": 1,
                    "Bob_Tue_PM": 1,
                    "Carol_Wed_AM": 1,
                    "Dave_Wed_AM": 1,
                },
                "gap": 0.0,
            },
            "execution_time_ms": 4892,
            "objective_value": 4720.0,
            "solver_status": "optimal",
            "credits_consumed": 5,
            "created_at": now - timedelta(hours=6),
        },
        {
            "status": "failed",
            "input_data": {
                "employees": [],
                "shifts": [
                    {"name": "Monday AM", "duration": 8, "min_staff": 1, "max_staff": 2},
                ],
            },
            "result_data": None,
            "error_message": "Infeasible: no employees available to cover required shifts",
            "execution_time_ms": 42,
            "objective_value": None,
            "solver_status": "infeasible",
            "credits_consumed": 0,
            "created_at": now - timedelta(hours=4),
        },
    ]

    all_executions = [
        (knapsack_model, knapsack_executions),
        (routing_model, routing_executions),
        (scheduling_model, scheduling_executions),
    ]

    created = 0
    for org_model, executions in all_executions:
        for exec_data in executions:
            now_ts = exec_data.pop("created_at", utcnow())
            completed_at = None
            started_at = now_ts
            if exec_data["status"] in ("completed", "failed", "timeout"):
                ms = exec_data.get("execution_time_ms") or 0
                completed_at = now_ts + timedelta(milliseconds=ms)

            execution = ModelExecution(
                id=generate_id("exe_"),
                organization_model_id=org_model.id,
                organization_id=org.id,
                executed_by_user_id=admin_user.id,
                input_data=exec_data["input_data"],
                status=exec_data["status"],
                result_data=exec_data.get("result_data"),
                error_message=exec_data.get("error_message"),
                execution_time_ms=exec_data.get("execution_time_ms"),
                solver_status=exec_data.get("solver_status"),
                objective_value=exec_data.get("objective_value"),
                credits_consumed=exec_data.get("credits_consumed", 0),
                credits_base=1,
                credits_compute=max(0, exec_data.get("credits_consumed", 0) - 1),
                origin="manual",
                created_at=now_ts,
                started_at=started_at,
                completed_at=completed_at,
            )
            db.add(execution)
            created += 1

        org_model.total_executions = (org_model.total_executions or 0) + len(executions)
        total_credits = sum(e.get("credits_consumed", 0) for e in executions)
        org_model.total_credits_used = (org_model.total_credits_used or 0) + total_credits
        org_model.last_executed_at = utcnow()

    db.flush()
    print(f"  Created {created} execution records")
    _ensure_credit_transactions(db, org, admin_user)


def _create_reviews(
    db: Session,
    org: Organization,
    users: list[User],
    catalog_ids: list[str],
) -> None:
    """Create marketplace reviews for the activated models."""
    created = 0
    for review_spec in DEMO_REVIEWS:
        catalog_id = catalog_ids[review_spec["catalog_index"]]
        user = users[review_spec["user_index"]]

        existing = (
            db.query(ModelReview)
            .filter(
                ModelReview.user_id == user.id,
                ModelReview.catalog_id == catalog_id,
            )
            .first()
        )
        if existing:
            continue

        review = ModelReview(
            id=str(uuid.uuid4()),
            catalog_id=catalog_id,
            user_id=user.id,
            organization_id=org.id,
            rating=review_spec["rating"],
            title=review_spec["title"],
            comment=review_spec["comment"],
            is_visible=True,
        )
        db.add(review)
        created += 1

    db.flush()

    for catalog_id in catalog_ids:
        reviews = (
            db.query(ModelReview)
            .filter(ModelReview.catalog_id == catalog_id, ModelReview.is_visible.is_(True))
            .all()
        )
        if reviews:
            avg = sum(r.rating for r in reviews) / len(reviews)
            catalog = db.query(ModelCatalog).filter(ModelCatalog.id == catalog_id).first()
            if catalog:
                catalog.avg_rating = round(avg, 2)

    db.flush()
    print(f"  Created {created} reviews")


def _create_workspace(
    db: Session,
    org: Organization,
    users: list[User],
) -> Workspace:
    """Create the demo workspace with all members."""
    ws_name = "Optimization Pilot"
    existing = (
        db.query(Workspace)
        .filter(Workspace.organization_id == org.id, Workspace.name == ws_name)
        .first()
    )
    if existing:
        print(f"  Workspace '{ws_name}' already exists")
        return existing

    workspace = Workspace(
        id=generate_id("wks_"),
        organization_id=org.id,
        name=ws_name,
        description="Workspace for evaluating JAOT optimization capabilities",
        is_active=True,
        created_by=users[0].id,
    )
    db.add(workspace)
    db.flush()

    workspace_roles = ["admin", "editor", "solver"]
    for i, user in enumerate(users):
        member = WorkspaceMember(
            id=generate_id("wkm_"),
            workspace_id=workspace.id,
            user_id=user.id,
            organization_id=org.id,
            role=workspace_roles[i],
            invited_by=users[0].id,
        )
        db.add(member)

    db.flush()
    print(f"  Created workspace '{ws_name}' with {len(users)} members")
    return workspace


def _create_builder_documents(
    db: Session,
    org: Organization,
    admin_user: User,
) -> list[ModelBuilderDocument]:
    """Create 2 builder documents with pre-built canvas data."""
    docs: list[ModelBuilderDocument] = []

    doc1_name = "Supply Chain Optimizer"
    existing1 = (
        db.query(ModelBuilderDocument)
        .filter(
            ModelBuilderDocument.organization_id == org.id,
            ModelBuilderDocument.name == doc1_name,
        )
        .first()
    )
    if existing1:
        docs.append(existing1)
    else:
        canvas1 = {
            "nodes": [
                {
                    "id": "obj_1",
                    "type": "objective",
                    "position": {"x": 400, "y": 50},
                    "data": {
                        "name": "Minimize Cost",
                        "sense": "minimize",
                        "expression": "5*production_a + 8*production_b + 3*warehouse",
                    },
                },
                {
                    "id": "var_1",
                    "type": "variable",
                    "position": {"x": 100, "y": 200},
                    "data": {
                        "name": "production_a",
                        "lower_bound": 0,
                        "upper_bound": 100,
                        "is_integer": False,
                    },
                },
                {
                    "id": "var_2",
                    "type": "variable",
                    "position": {"x": 400, "y": 200},
                    "data": {
                        "name": "production_b",
                        "lower_bound": 0,
                        "upper_bound": 80,
                        "is_integer": False,
                    },
                },
                {
                    "id": "var_3",
                    "type": "variable",
                    "position": {"x": 700, "y": 200},
                    "data": {
                        "name": "warehouse",
                        "lower_bound": 0,
                        "upper_bound": 200,
                        "is_integer": True,
                    },
                },
                {
                    "id": "con_1",
                    "type": "constraint",
                    "position": {"x": 250, "y": 400},
                    "data": {
                        "name": "Demand Satisfaction",
                        "expression": "production_a + production_b >= 120",
                    },
                },
                {
                    "id": "con_2",
                    "type": "constraint",
                    "position": {"x": 550, "y": 400},
                    "data": {
                        "name": "Warehouse Capacity",
                        "expression": "warehouse <= production_a + production_b",
                    },
                },
            ],
            "edges": [
                {
                    "id": "e1",
                    "source": "var_1",
                    "target": "obj_1",
                    "type": "coefficient",
                    "data": {"coefficient": 5.0},
                },
                {
                    "id": "e2",
                    "source": "var_2",
                    "target": "obj_1",
                    "type": "coefficient",
                    "data": {"coefficient": 8.0},
                },
                {
                    "id": "e3",
                    "source": "var_3",
                    "target": "obj_1",
                    "type": "coefficient",
                    "data": {"coefficient": 3.0},
                },
                {
                    "id": "e4",
                    "source": "var_1",
                    "target": "con_1",
                    "type": "constraint_link",
                    "data": {"coefficient": 1.0},
                },
                {
                    "id": "e5",
                    "source": "var_2",
                    "target": "con_1",
                    "type": "constraint_link",
                    "data": {"coefficient": 1.0},
                },
                {
                    "id": "e6",
                    "source": "var_3",
                    "target": "con_2",
                    "type": "constraint_link",
                    "data": {"coefficient": 1.0},
                },
            ],
            "viewport": {"x": 0, "y": 0, "zoom": 1},
        }

        doc1 = ModelBuilderDocument(
            id=generate_id("bld_"),
            organization_id=org.id,
            created_by=admin_user.id,
            name=doc1_name,
            canvas_json=canvas1,
            model_json=None,
            is_active=True,
        )
        db.add(doc1)
        db.flush()
        docs.append(doc1)
        print(f"  Created builder document: {doc1_name}")

    doc2_name = "Portfolio Rebalancer"
    existing2 = (
        db.query(ModelBuilderDocument)
        .filter(
            ModelBuilderDocument.organization_id == org.id,
            ModelBuilderDocument.name == doc2_name,
        )
        .first()
    )
    if existing2:
        docs.append(existing2)
    else:
        canvas2 = {
            "nodes": [
                {
                    "id": "obj_1",
                    "type": "objective",
                    "position": {"x": 300, "y": 50},
                    "data": {
                        "name": "Maximize Return",
                        "sense": "maximize",
                        "expression": "0.08*stocks + 0.04*bonds",
                    },
                },
                {
                    "id": "var_1",
                    "type": "variable",
                    "position": {"x": 150, "y": 200},
                    "data": {
                        "name": "stocks",
                        "lower_bound": 0,
                        "upper_bound": 1,
                        "is_integer": False,
                    },
                },
                {
                    "id": "var_2",
                    "type": "variable",
                    "position": {"x": 450, "y": 200},
                    "data": {
                        "name": "bonds",
                        "lower_bound": 0,
                        "upper_bound": 1,
                        "is_integer": False,
                    },
                },
                {
                    "id": "con_1",
                    "type": "constraint",
                    "position": {"x": 300, "y": 380},
                    "data": {
                        "name": "Full Allocation",
                        "expression": "stocks + bonds = 1.0",
                    },
                },
            ],
            "edges": [
                {
                    "id": "e1",
                    "source": "var_1",
                    "target": "obj_1",
                    "type": "coefficient",
                    "data": {"coefficient": 0.08},
                },
                {
                    "id": "e2",
                    "source": "var_2",
                    "target": "obj_1",
                    "type": "coefficient",
                    "data": {"coefficient": 0.04},
                },
                {
                    "id": "e3",
                    "source": "var_1",
                    "target": "con_1",
                    "type": "constraint_link",
                    "data": {"coefficient": 1.0},
                },
                {
                    "id": "e4",
                    "source": "var_2",
                    "target": "con_1",
                    "type": "constraint_link",
                    "data": {"coefficient": 1.0},
                },
            ],
            "viewport": {"x": 0, "y": 0, "zoom": 1},
        }

        doc2 = ModelBuilderDocument(
            id=generate_id("bld_"),
            organization_id=org.id,
            created_by=admin_user.id,
            name=doc2_name,
            canvas_json=canvas2,
            model_json=None,
            is_active=True,
        )
        db.add(doc2)
        db.flush()
        docs.append(doc2)
        print(f"  Created builder document: {doc2_name}")

    return docs


def _is_empty_canvas(canvas: dict | None) -> bool:
    """Return True if the canvas has no meaningful content (no nodes)."""
    if not canvas:
        return True
    nodes = canvas.get("nodes")
    if not nodes:
        return True
    return False


def _cleanup_test_builder_documents(db: Session) -> int:
    """Delete leftover test builder documents across ALL orgs.

    Targets:
    - Any document named 'AI-Generated Model' (created by the AI assistant page)
    - Any document named 'Untitled Model' with an empty canvas (no nodes)

    Safe: never deletes user-named documents or documents with real content.
    Idempotent: harmless if nothing matches.
    """
    from sqlalchemy import or_

    candidates = (
        db.query(ModelBuilderDocument)
        .filter(
            or_(
                ModelBuilderDocument.name == "AI-Generated Model",
                ModelBuilderDocument.name == "Untitled Model",
            )
        )
        .all()
    )

    org_stats: dict[str, dict[str, int]] = {}  # org_id -> {reason: count}
    to_delete: list[ModelBuilderDocument] = []

    for doc in candidates:
        reason: str | None = None
        if doc.name == "AI-Generated Model":
            reason = "AI-Generated Model"
        elif doc.name == "Untitled Model" and _is_empty_canvas(doc.canvas_json):
            reason = "Untitled Model (empty)"

        if reason:
            to_delete.append(doc)
            org_id = doc.organization_id
            if org_id not in org_stats:
                org_stats[org_id] = {}
            org_stats[org_id][reason] = org_stats[org_id].get(reason, 0) + 1

    org_names: dict[str, str] = {}
    if org_stats:
        org_ids = list(org_stats.keys())
        orgs = db.query(Organization).filter(Organization.id.in_(org_ids)).all()
        org_names = {o.id: o.name for o in orgs}

    for doc in to_delete:
        db.delete(doc)
    if to_delete:
        db.flush()

    total = len(to_delete)
    if total == 0:
        print("  No leftover test documents found")
    else:
        print(f"  Deleted {total} leftover test document(s):")
        for org_id, reasons in org_stats.items():
            org_label = org_names.get(org_id, org_id)
            for reason, count in reasons.items():
                print(f"    - {org_label}: {count}x {reason}")

    return total


DEMO_TRIGGERS = [
    {
        "name": "Daily Portfolio Rebalance",
        "description": (
            "Runs every market day at 08:00 UTC. Pulls latest asset prices from the "
            "data warehouse and re-optimises the portfolio allocation to stay within "
            "the target risk budget. Results are posted to Slack via the webhook."
        ),
        "doc_index": 0,
        "webhook_url": "https://hooks.slack.com/services/T0XXX/B0XXX/portfolio-alerts",
        "is_enabled": True,
    },
    {
        "name": "Weekly Supply Chain Replan",
        "description": (
            "Triggered every Monday at 06:00 UTC. Reads updated demand forecasts "
            "and supplier lead times, then re-solves the supply chain network to "
            "minimise logistics cost. The optimal plan is pushed to the ERP webhook."
        ),
        "doc_index": 1,
        "webhook_url": "https://erp.example.com/api/webhooks/supply-plan",
        "is_enabled": True,
    },
    {
        "name": "Ad-hoc Stress Test",
        "description": (
            "Manually fired by the ops team to run what-if scenarios on the portfolio "
            "model with extreme market conditions. Disabled by default — enable and "
            "fire via API when needed."
        ),
        "doc_index": 0,
        "webhook_url": "https://monitoring.example.com/webhooks/stress-results",
        "is_enabled": False,
    },
]


def _create_triggers(
    db: Session,
    org: Organization,
    admin_user: User,
    builder_docs: list[ModelBuilderDocument],
) -> None:
    """Create representative triggers linked to builder documents."""
    for spec in DEMO_TRIGGERS:
        if spec["doc_index"] >= len(builder_docs):
            print(f"  WARNING: Not enough builder docs for trigger '{spec['name']}'")
            continue

        existing = (
            db.query(SolveTrigger)
            .filter(
                SolveTrigger.organization_id == org.id,
                SolveTrigger.name == spec["name"],
            )
            .first()
        )
        if existing:
            print(f"  Trigger '{spec['name']}' already exists")
            continue

        document = builder_docs[spec["doc_index"]]

        # Triggers require a pinned version snapshot.
        version = ModelVersion(
            id=generate_id("ver_"),
            document_id=document.id,
            organization_id=org.id,
            canvas_json=document.canvas_json,
            model_json=document.model_json,
            change_summary=f"Version for trigger: {spec['name']}",
            is_named=True,
            version_name="v1.0",
            sequence=1,
        )
        db.add(version)
        db.flush()

        secret_plaintext = secrets.token_hex(32)
        secret_hash = hashlib.sha256(secret_plaintext.encode()).hexdigest()

        trigger = SolveTrigger(
            id=generate_id("trg_"),
            organization_id=org.id,
            created_by=admin_user.id,
            name=spec["name"],
            description=spec["description"],
            document_id=document.id,
            version_id=version.id,
            trigger_secret=secret_hash,
            webhook_url=spec["webhook_url"],
            is_enabled=spec["is_enabled"],
            total_runs=0,
        )
        db.add(trigger)
        db.flush()
        print(
            f"  Created trigger: {spec['name']} ({'enabled' if spec['is_enabled'] else 'disabled'})"
        )


def seed_demo() -> None:
    """Seed all demo data in a single transaction."""
    db: Session = SessionLocal()
    try:
        print("\nJAOT demo seed - showcase environment")
        print("=" * 52)

        print("\n[1/10] Organization")
        org, org_created = _get_or_create_org(db)
        if not org_created:
            print(f"  Organization '{org.name}' already exists ({org.id})")

        print("\n[2/10] Users")
        users: list[User] = []
        for user_spec in DEMO_USERS:
            user, _ = _get_or_create_user(
                db,
                org,
                email=user_spec["email"],
                password=user_spec["password"],
                name=user_spec["name"],
                role=user_spec["role"],
            )
            users.append(user)

        admin_user = users[0]

        print("\n[3/10] API Key")
        api_key_plaintext = _ensure_api_key(db, admin_user, org)

        print("\n[4/10] Catalog Model Activation")
        org_models = _activate_catalog_models(db, org, DEMO_CATALOG_IDS)

        print("\n[5/10] Execution Records")
        _build_execution_records(db, org, org_models, admin_user)

        print("\n[6/10] Marketplace Reviews")
        _create_reviews(db, org, users, DEMO_CATALOG_IDS)

        print("\n[7/10] Workspace")
        _create_workspace(db, org, users)

        print("\n[8/10] Builder Documents")
        builder_docs = _create_builder_documents(db, org, admin_user)

        print("\n[9/10] Cleanup")
        _cleanup_test_builder_documents(db)

        print("\n[10/10] Triggers")
        _create_triggers(db, org, admin_user, builder_docs)

        db.commit()

        print("\n" + "=" * 52)
        print("Demo data seeded successfully!")
        print("=" * 52)
        print(f"\nOrganization: {org.name} ({org.id})")
        print("Admin: demo@jaot.io / ShowcaseAdmin2026!")
        print("Solver: solver@jaot.io / ShowcaseSolver2026!")
        print("Viewer: viewer@jaot.io / ShowcaseViewer2026!")
        if api_key_plaintext:
            print("\nAPI Key (copy now, only shown once):")
            print(f"  {api_key_plaintext}")
        print()

    except Exception as e:
        db.rollback()
        print(f"\nERROR: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_demo()
