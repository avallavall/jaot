"""AI discovery routes: llms.txt and llms-full.txt.

Serves curated Markdown content at well-known URLs so AI agents and LLMs
can discover JAOT's capabilities, authentication requirements, and API
usage without visiting external documentation.

Routes are excluded from the OpenAPI schema to avoid polluting the MCP
tool list.
"""

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse, RedirectResponse

from app.config import settings

router = APIRouter()


# NOTE: frontend/public/llms.txt is the SERVED source of truth (D-09). LLMS_TXT here is retained
# only for llms-full.txt parity/tests; keep in sync manually.
LLMS_TXT = """\
# JAOT

> Optimization as a Service platform. Solve linear programming (LP) and mixed-integer programming (MIP) problems via API or MCP.

## Docs
- [API Reference](/docs/api/reference): Complete REST API documentation
- [Authentication](/docs/api/authentication): API key and JWT auth guide

## MCP
- [MCP Endpoint](/mcp): Model Context Protocol server with 17 optimization tools
- Tools: solve_problem, validate_problem, solve_multi_objective, list_available_solvers, list_templates, get_template, solve_with_template, import_preview, import_and_solve, list_catalog_models, get_catalog_model, get_catalog_model_schema, activate_catalog_model, execute_model, get_execution, get_execution_insights, get_credit_balance

## API
- Base URL: /api/v2
- [Solve](/api/v2/solve): POST — Solve any optimization problem (JSON definition)
- [Templates](/api/v2/solve/templates): GET — List available problem templates
- [Catalog](/api/v2/models/catalog): GET — Browse marketplace models
- [Credits](/api/v2/credits/balance): GET — Check credit balance
"""

# llms-full.txt — comprehensive inlined documentation

LLMS_FULL_TXT = """\
# JAOT — Full Documentation

> Complete reference for AI agents using JAOT's optimization platform.

## Overview

JAOT is an Optimization as a Service platform. It solves linear programming (LP) and mixed-integer programming (MIP) problems via a REST API or Model Context Protocol (MCP). Users define optimization problems as JSON (variables, constraints, objective) and receive solutions with optimal variable values, objective value, and solver statistics. JAOT also hosts a marketplace of pre-built optimization models that can be activated and executed without writing any formulation code.

## Authentication

JAOT uses API key authentication for all protected endpoints. Keys follow the format `ok_live_<40-hex-chars>`.

### Getting an API Key

Sign up to receive your key:

```bash
curl -X POST https://jaot.io/api/v2/auth/signup \\
  -H "Content-Type: application/json" \\
  -d '{"email": "you@example.com", "name": "You", "organization_name": "Acme", "plan": "free"}'
```

The response includes an `api_key` field shown only once. Store it securely.

### Using the Key

Include the key as a Bearer token in every request to protected endpoints:

```
Authorization: Bearer ok_live_a1b2c3d4e5f6789012345678901234567890abcdef
```

### Public Endpoints (No Key Required)

| Method | Path | Description |
|--------|------|-------------|
| GET | /api/v2/health | Health check |
| GET | /api/v2/solve/templates | List problem templates |
| GET | /api/v2/models/catalog | Browse marketplace |
| GET | /api/v2/credits/rates | Exchange rates |
| GET | /api/v2/credits/calculator | Estimate credits for a problem |
| POST | /api/v2/auth/signup | Create account |
| POST | /api/v2/auth/login | Validate key |

### Error Responses

| Code | Meaning |
|------|---------|
| 401 | Missing, invalid, or expired API key |
| 402 | Insufficient credits |
| 403 | Admin endpoint accessed by non-admin |
| 429 | Rate limited |

### Key Management

```bash
POST /api/v2/keys
Authorization: Bearer <existing_key>
{"name": "CI key", "expires_days": 90}

# List keys (prefix only, never the full key)
GET /api/v2/keys

# Revoke a key
DELETE /api/v2/keys/{key_id}
```

## API Reference

Base URL: `/api/v2`

### Solve — POST /api/v2/solve

Solve an optimization problem synchronously. Requires authentication.

**Request:**
```json
{
  "name": "production_planning",
  "objective": {
    "sense": "maximize",
    "expression": "50*widgets + 40*gadgets"
  },
  "variables": [
    {"name": "widgets", "type": "integer", "lower_bound": 0, "upper_bound": 100},
    {"name": "gadgets", "type": "integer", "lower_bound": 0, "upper_bound": 80}
  ],
  "constraints": [
    {"name": "machine_hours", "expression": "2*widgets + 3*gadgets <= 240"},
    {"name": "labor_hours", "expression": "4*widgets + 2*gadgets <= 200"}
  ],
  "options": {
    "time_limit_seconds": 30,
    "gap_tolerance": 0.0001
  }
}
```

**Response:**
```json
{
  "status": "optimal",
  "objective_value": 3500.0,
  "variables": [
    {"name": "widgets", "value": 30, "type": "integer"},
    {"name": "gadgets", "value": 60, "type": "integer"}
  ],
  "solution": {"widgets": 30, "gadgets": 60},
  "solve_time_seconds": 0.045,
  "credits_used": 2,
  "credits_remaining": 93
}
```

Solver status values: `optimal`, `feasible`, `infeasible`, `unbounded`, `time_limit`, `error`.

### Validate — POST /api/v2/solve/validate

Check a problem without solving. No credits charged.

**Response (valid):**
```json
{
  "valid": true,
  "estimated_credits": 3,
  "num_variables": 5,
  "num_constraints": 8
}
```

**Response (invalid):**
```json
{
  "valid": false,
  "errors": ["Objective references undefined variables: {'unknown_var'}"]
}
```

### Templates — GET /api/v2/solve/templates

List available problem templates (public, no auth).

```json
{
  "templates": [
    {
      "id": "knapsack",
      "display_name": "Knapsack Problem",
      "description": "Select items to maximize value within a weight limit",
      "category": "combinatorial"
    }
  ]
}
```

### Template Detail — GET /api/v2/solve/templates/{template_id}

Get a template's input schema and example input.

### Solve with Template — POST /api/v2/solve/templates/{template_id}/solve

Solve using a template with user-friendly input (no raw LP formulation needed).

```json
{
  "capacity": 50,
  "items": [
    {"name": "laptop", "value": 600, "weight": 10},
    {"name": "camera", "value": 500, "weight": 5}
  ]
}
```

### Catalog — GET /api/v2/models/catalog

Browse the marketplace of pre-built optimization models (public, no auth).

Query parameters: `category`, `search`, `page`, `page_size`.

### Catalog Detail — GET /api/v2/models/catalog/{catalog_id}

Get details of a specific marketplace model.

### Catalog Schema — GET /api/v2/models/catalog/{catalog_id}/schema

Get the input schema and example input for a marketplace model.

### Activate Model — POST /api/v2/models/catalog/{catalog_id}/activate

Activate a marketplace model for your organization. Requires auth.

### Execute Model — POST /api/v2/models/{model_id}/execute

Execute an activated model with input data. Requires auth.

```json
{
  "input_data": {
    "capacity": 50,
    "items": [{"name": "laptop", "value": 600, "weight": 10}]
  }
}
```

### Get Execution — GET /api/v2/models/executions/all

List execution results. Requires auth. Query: `page`, `page_size`, `status`.

### Credits Balance — GET /api/v2/credits/balance

Get current credit balance. Requires auth.

```json
{
  "credits_balance": 950,
  "credits_earned": 200,
  "currency": "EUR",
  "local_balance": 95.0
}
```

## MCP Usage

JAOT exposes a Model Context Protocol server at `/mcp` using HTTP+SSE transport.

### Connecting

Point your MCP client to:
```
https://jaot.io/mcp
```

The MCP endpoint is public (no auth to connect). Individual tools that require authentication will return an error with instructions if called without a Bearer API key.

### Available Tools (17)

| Tool | Auth | Description |
|------|------|-------------|
| solve_problem | Yes | Solve an optimization problem (optional solver choice or auto routing) |
| validate_problem | Yes | Validate without solving (no credits) |
| solve_multi_objective | Yes | Solve a multi-objective problem (Pareto front) |
| list_available_solvers | Yes | List available solvers and their credit multipliers |
| list_templates | No | List available problem templates |
| get_template | No | Get template details and input schema |
| solve_with_template | Yes | Solve using a template (optional solver choice) |
| import_preview | Yes | Preview how a CSV file is parsed into a problem |
| import_and_solve | Yes | Import data from a CSV and solve in one step |
| list_catalog_models | No | Browse marketplace models |
| get_catalog_model | No | Get model details |
| get_catalog_model_schema | No | Get model input schema |
| activate_catalog_model | Yes | Activate a marketplace model |
| execute_model | Yes | Execute an activated model |
| get_execution | Yes | Get execution results |
| get_execution_insights | Yes | Get auto-insights (gap, time, quality) for an execution |
| get_credit_balance | Yes | Check credit balance |

### Example Workflow: Template Path

1. `list_templates` — browse available templates
2. `get_template("knapsack")` — see input schema and example
3. `solve_with_template("knapsack", {"capacity": 50, "items": [...]})` — solve

### Example Workflow: Marketplace Path

1. `list_catalog_models` — browse marketplace
2. `get_catalog_model("mdl_abc")` — check details
3. `get_catalog_model_schema("mdl_abc")` — see required inputs
4. `activate_catalog_model("mdl_abc")` — activate for your org
5. `execute_model("orgmdl_xyz", {"input_data": {...}})` — run it
6. `get_execution` — check results

## Optimization Concepts

### Linear Programming (LP)

Linear programming finds the optimal value of a linear objective function subject to linear constraints. A problem consists of:

- **Decision variables**: quantities to determine (e.g., units to produce). Each has a name, type, and optional bounds.
- **Objective function**: a linear expression to minimize or maximize (e.g., `50*x + 40*y`).
- **Constraints**: linear inequalities or equalities that solutions must satisfy (e.g., `2*x + 3*y <= 240`). Each has a left-hand expression, a sense (`<=`, `>=`, `=`), and a right-hand-side value.

Variable types: `continuous` (any real value within bounds), `integer` (whole numbers only), `binary` (0 or 1 — used for yes/no decisions).

### Mixed-Integer Programming (MIP)

MIP extends LP by allowing integer and binary variables alongside continuous ones. This enables modeling of discrete decisions: selecting items (binary), assigning resources (integer), routing (binary arcs). MIP problems are generally harder to solve than pure LP because the solver must explore a branch-and-bound tree.

### Solver Status Values

| Status | Meaning |
|--------|---------|
| optimal | Globally optimal solution found |
| feasible | A solution exists but optimality not proven (e.g., time limit reached) |
| infeasible | No solution satisfies all constraints |
| unbounded | Objective can improve without limit |
| time_limit | Solver stopped at time limit; best solution (if any) returned |

## Problem JSON Schema

The `OptimizationProblem` schema defines how to structure a problem for the `/api/v2/solve` endpoint:

```json
{
  "name": "my_problem",
  "variables": [
    {
      "name": "x",
      "type": "continuous",
      "lower_bound": 0,
      "upper_bound": 100
    },
    {
      "name": "y",
      "type": "integer",
      "lower_bound": 0
    },
    {
      "name": "use_option",
      "type": "binary"
    }
  ],
  "constraints": [
    {
      "name": "budget",
      "expression": "10*x + 20*y <= 500"
    },
    {
      "name": "minimum",
      "expression": "x + y >= 10"
    }
  ],
  "objective": {
    "sense": "maximize",
    "expression": "5*x + 8*y"
  },
  "options": {
    "time_limit_seconds": 60,
    "gap_tolerance": 0.01
  }
}
```

### Field Reference

**variables[]:**
- `name` (string, required): variable identifier, used in expressions
- `type` (enum, required): `continuous`, `integer`, or `binary`
- `lower_bound` (number, optional): minimum value (default 0 for continuous/integer, 0 for binary)
- `upper_bound` (number, optional): maximum value (default infinity for continuous/integer, 1 for binary)

**constraints[]:**
- `name` (string, optional): human-readable label
- `expression` (string, required): linear inequality/equality using variable names (e.g., `2*x + 3*y <= 100`)
- Supported operators in expression: `<=`, `>=`, `=`

**objective:**
- `sense` (enum, required): `minimize` or `maximize`
- `expression` (string, required): linear expression using variable names

**options:**
- `time_limit_seconds` (number, optional): solver time limit in seconds (default 30)
- `gap_tolerance` (number, optional): acceptable optimality gap (default 0.0001, meaning 0.01%)
"""


@router.get(
    "/.well-known/llms.txt",
    response_class=RedirectResponse,
    include_in_schema=False,
)
async def get_llms_txt() -> RedirectResponse:
    """Permanently redirect to the canonical /llms.txt served at the site root.

    Single source of truth for the AI-discovery index (Phase 13.3, D-09): the
    curated llms.txt lives at the root path, so this well-known location 301s
    there to keep crawlers converging on one document instead of two divergent
    copies. ``LLMS_TXT`` is retained for ``llms-full.txt`` parity and tests.
    """
    return RedirectResponse(url=f"{settings.FRONTEND_URL.rstrip('/')}/llms.txt", status_code=301)


@router.get(
    "/.well-known/llms-full.txt",
    response_class=PlainTextResponse,
    include_in_schema=False,
)
async def get_llms_full_txt() -> PlainTextResponse:
    """Serve comprehensive llms-full.txt documentation for AI agents."""
    return PlainTextResponse(content=LLMS_FULL_TXT, media_type="text/plain; charset=utf-8")
