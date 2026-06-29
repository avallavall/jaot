"""MCP server integration for JAOT Optimization Platform.

Exposes 26 curated optimization tools via the Model Context Protocol (MCP),
enabling AI agents (Claude, GPT, etc.) to discover and use JAOT's
optimization capabilities: multi-solver solving, multi-objective (Pareto),
templates, standard-format import/export (MPS/LP/CIP/JSON), the model
marketplace, execution insights, credits, and first-class **model projects**
(create, version with commit messages, analyze stats/health, and solve).
"""

from fastapi import FastAPI
from fastapi_mcp import FastApiMCP


def setup_mcp(app: FastAPI) -> FastApiMCP:
    """Initialize and mount MCP server exposing curated optimization tools."""
    mcp = FastApiMCP(
        app,
        name="JAOT Optimization Platform",
        description=(
            "Solve linear (LP) and mixed-integer (MIP) optimization problems with "
            "a choice of solvers (SCIP, HiGHS, Hexaly) or automatic routing, "
            "including multi-objective (Pareto) solves. Import and export models in "
            "standard formats (MPS/LP/CIP/JSON). Browse and run a marketplace of "
            "pre-built models, and inspect result insights. Create, version "
            "(git-style commits), analyze (stats + health score) and solve "
            "first-class model projects. "
            "Authenticate with a Bearer API key."
        ),
        include_operations=[
            # Solve
            "solve_problem",
            "validate_problem",
            "solve_multi_objective",
            "list_available_solvers",
            # Templates
            "list_templates",
            "get_template",
            "solve_with_template",
            # File I/O — standard formats (MPS/LP/CIP/JSON)
            "import_preview",
            "import_and_solve",
            "export_model",
            "export_execution",
            # Marketplace
            "list_catalog_models",
            "get_catalog_model",
            "get_catalog_model_schema",
            "activate_catalog_model",
            # Execution, analysis & credits
            "execute_model",
            "get_execution",
            "get_execution_insights",
            "get_credit_balance",
            # Model projects — create, version, analyze & solve a first-class model
            "create_model_project",
            "get_model_project",
            "list_model_projects",
            "commit_model_version",
            "list_project_versions",
            "get_model_stats",
            "solve_model_project",
        ],
        describe_all_responses=True,
        describe_full_response_schema=True,
    )
    mcp.mount_http(mount_path="/mcp")
    return mcp
