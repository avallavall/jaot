# Security Policy

## Reporting a vulnerability

Please **do not open a public issue** for security vulnerabilities.

Use GitHub's private vulnerability reporting on this repository
(**Security → Report a vulnerability**). You'll get an acknowledgement within
7 days; fixes are released best-effort with priority over regular maintenance.

## Scope

Reports are welcome for anything in this repository: the FastAPI backend, the
Next.js frontend, the MCP server, deployment manifests under `deploy/`, and
the monitoring stack configuration.

Especially interesting areas:

- Authentication / authorization (API keys, JWT, org-scoped data isolation)
- The credits ledger and marketplace payout logic
- Solver input parsing (uploaded model files, LLM-generated formulations)
- The LLM assistant boundary (prompt-injection hardening lives in
  `app/services/llm/prompt_templates.py` and is contract-tested)

## Supported versions

The latest `main` branch and the most recent release. The project is
maintained best-effort (monthly triage, quarterly CVE pass via `pip-audit`
and `npm audit` in CI).
