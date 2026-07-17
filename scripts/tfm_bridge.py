#!/usr/bin/env python3
"""TFM bridge (S6): one MDPDP ModelProject + 17 scenario datasets, plus file dumps.

Creates — through the same service layer the API uses — a ModelProject holding the
MDPDP JModel (Vall-llaura 2017 thesis, eqs. 4.1–4.10; the draft carries the compiled
scenario_00 problem and is auto-committed as v1) and its 17 named datasets:
scenario_00 = the fabricated Table 3 real data (known optimum 90), scenario_01..16 =
synthetic instances at the Table 4 sizes. Optionally dumps every dataset as an
importable ``.json`` file (the studio's Data tab "Import file" understands them).

Run inside the api image (the DB half needs the database):

    docker compose exec api python scripts/tfm_bridge.py --user admin@jaot.io

    # with the datasets folder mounted for the file dump:
    docker run --rm --network jaot_network \
        -v "C:/Users/vall-/Desktop/tfm_models:/dump" \
        -v "$PWD/app:/app/app:ro" -v "$PWD/scripts:/app/scripts:ro" \
        -e DATABASE_URL=postgresql://jaot:jaot@postgres:5432/jaot \
        jaot-api:latest python scripts/tfm_bridge.py \
        --user admin@jaot.io --dump-dir /dump/datasets

``--skip-db`` dumps files only (no database needed). The script refuses to create a
second project with the same name — archive it in the studio or pass
``--project-name`` to create another.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from _seed_common import add_repo_to_path, session_scope  # noqa: E402

add_repo_to_path()

DEFAULT_PROJECT_NAME = "MDPDP — TFM (Vall-llaura 2017)"
PROJECT_DESCRIPTION = (
    "Multi-depot pickup-and-delivery (thesis §2.2, eqs. 4.1–4.10): one JModel, "
    "17 scenario datasets. scenario_00 is the fabricated Table 3 instance with "
    "known optimum 90; scenario_01..16 are synthetic at the Table 4 sizes."
)
COMMIT_SUMMARY = "MDPDP TFM formulation (thesis 4.1-4.10)"


def dump_files(scenarios: list[tuple[str, dict]], dump_dir: Path) -> None:
    """Write every scenario's ``data_json`` as an importable dataset file."""
    dump_dir.mkdir(parents=True, exist_ok=True)
    for name, data_json in scenarios:
        path = dump_dir / f"{name}.dataset.json"
        path.write_text(json.dumps(data_json, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"  wrote {path}")
    readme = dump_dir / "README.txt"
    readme.write_text(
        "TFM MDPDP datasets (S6 bridge)\n"
        "==============================\n\n"
        "Each *.dataset.json fills the MDPDP JModel (thesis eqs. 4.1-4.10) that the\n"
        "bridge creates as a studio model. To use one by hand: open the model in the\n"
        "studio -> Data tab -> New dataset -> Import file -> pick the .json ->\n"
        "save -> Use. scenario_00 solves to the thesis optimum 90.\n"
        "These files are datasets (sets/params), not standalone models: importing\n"
        "them from the model launcher will be rejected on purpose.\n",
        encoding="utf-8",
    )
    print(f"  wrote {readme}")


def seed_database(scenarios: list[tuple[str, dict]], user_email: str, project_name: str) -> None:
    """Create the ModelProject (auto v1) + one dataset per scenario, service-layer."""
    from app.data.tfm_mdpdp import MDPDP_JMODEL, scenario_00_data
    from app.domains.dsl import JModelData, compile_jmodel
    from app.models import ModelProject, User
    from app.services import model_project_service as svc

    with session_scope() as db:
        user = db.query(User).filter(User.email == user_email).first()
        if user is None:
            print(f"ERROR: user {user_email!r} not found — pass --user <email>.")
            sys.exit(1)
        org_id = user.organization_id

        existing = (
            db.query(ModelProject)
            .filter(
                ModelProject.organization_id == org_id,
                ModelProject.name == project_name,
                ModelProject.status == "active",
            )
            .first()
        )
        if existing is not None:
            print(
                f"ERROR: an active project named {project_name!r} already exists "
                f"({existing.id}). Archive it in the studio or pass --project-name."
            )
            sys.exit(1)

        # The draft carries scenario_00 compiled so Analyze/Solve work on first open
        # (the same state the studio reaches after "Use dataset" -> recompile).
        compiled = compile_jmodel(MDPDP_JMODEL, data=JModelData.from_json(scenario_00_data()))
        project = svc.create_seeded(
            db,
            org_id=org_id,
            user_id=user.id,
            name=project_name,
            problem_json=compiled.model_dump(mode="json"),
            dsl_source=MDPDP_JMODEL,
            source_type="import",
            source_ref="scripts/tfm_bridge.py",
            auto_commit_summary=COMMIT_SUMMARY,
        )
        svc.update_meta(db, project, description=PROJECT_DESCRIPTION)

        for name, data_json in scenarios:
            description = (
                "Fabricated Table 3 instance (real data) — thesis optimum 90"
                if name.startswith("scenario_00")
                else "Synthetic instance at a thesis Table 4 size (solve-time comparison)"
            )
            dataset = svc.create_dataset(
                db,
                project,
                user_id=user.id,
                name=name,
                description=description,
                data_json=data_json,
            )
            print(f"  dataset {dataset.id}  {name}")
        db.commit()

        print("----------------------------------------")
        print(f"Project: {project.name} ({project.id})")
        print(f"Org:     {org_id}  ·  created by {user.email}")
        print(f"Open:    /es/studio/{project.id}/build  (JModel lens; datasets in Data tab)")
        print("Try:     Data tab -> scenario_00 -> Use -> Solve  =>  objective 90")
        print("----------------------------------------")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--user", default="admin@jaot.io", help="owner email (default admin@jaot.io)"
    )
    parser.add_argument("--project-name", default=DEFAULT_PROJECT_NAME)
    parser.add_argument("--dump-dir", default=None, help="also write *.dataset.json files here")
    parser.add_argument("--skip-db", action="store_true", help="only dump files, no database")
    args = parser.parse_args()

    if args.skip_db and not args.dump_dir:
        parser.error("--skip-db without --dump-dir would do nothing")

    from app.data.tfm_mdpdp import iter_scenarios

    scenarios = iter_scenarios()
    print(f"Built {len(scenarios)} scenarios (00 = Table 3 real data, 01-16 = Table 4 sizes)")

    if args.dump_dir:
        dump_files(scenarios, Path(args.dump_dir))
    if not args.skip_db:
        seed_database(scenarios, args.user, args.project_name)


if __name__ == "__main__":
    main()
