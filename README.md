# JAOT — Just Another Optimization Tool

**A self-hostable optimization platform.** Describe a problem in natural
language or JSON, get the optimal solution back — no solver expertise required.
Build models with an AI assistant, share them in a marketplace, expose them to
AI agents over MCP, or just hit the REST API.

---

## What it is

JAOT wraps industrial MIP/LP solvers (SCIP, HiGHS) behind a multi-tenant API,
a visual builder, and an LLM formulation assistant. It is **a platform, not a
library and not a hosted SaaS** — you run it yourself with `docker compose up`.

- **Solver-agnostic core** — an `OptimizationProblem` schema that stays
  independent of the solver. Ships SCIP (via PySCIPOpt) and HiGHS (via highspy);
  an optional Hexaly adapter is bring-your-own-license.
- **LLM formulation assistant** — turn a natural-language description into a
  runnable model, grounded in a RAG index over the template library
  (Qdrant + local sentence-transformers; no data leaves your box except the
  Claude calls you opt into).
- **Solution explainer + sensitivity** — don't just solve, *understand*. Every
  solve reports shadow prices, binding constraints, and variable reduced costs
  (exact for LP, approximate for MIP), and a one-click AI explanation translates
  the result into plain language grounded strictly in your actual numbers.
- **Model marketplace** — a free, collaborative gallery: publish your models
  and activate community ones. No prices or commissions.
- **MCP server** — exposes solver tools to AI agents (Claude, etc.) via the
  Model Context Protocol.
- **102 templates + 27 problem generators** — knapsack, vehicle routing,
  scheduling, production planning, portfolio, a full MDPDP-TW formulation, and
  more.
- **Credits ledger, multi-tenant auth, admin panel, i18n (en/es/ca/fr/de),
  and a Prometheus/Grafana/Alertmanager monitoring stack** — included.

Monetization is **off by default** (`MONETIZATION_ENABLED=false`): the
marketplace is free and collaborative. A self-hosted deployment can enable the
paid marketplace by flipping the flag and bringing its own Stripe keys — that
billing code is complete but **has never been exercised against live Stripe**,
so test before you charge real money.

---

## Quickstart

```bash
git clone https://github.com/avallavall/jaot.git && cd jaot
cp .env.example .env   # includes first-run admin credentials — change the password
docker compose up -d   # migrates, seeds the catalog, creates your admin on first boot
```

Open http://localhost:3000 and log in with your `SEED_ADMIN_*` credentials — or
mint an API key and solve over HTTP:

```bash
docker compose exec api python scripts/ensure_admin_api_key.py   # prints your API key

curl -X POST http://localhost:8001/api/v2/solve \
  -H "Authorization: Bearer <your-api-key>" \
  -H "Content-Type: application/json" \
  -d '{"name":"test","variables":[{"name":"x","type":"continuous","lower_bound":0,"upper_bound":10}],"objective":{"sense":"maximize","expression":"3*x"},"constraints":[{"name":"c1","expression":"x <= 5"}]}'
```

Returns `{"status":"optimal","objective_value":15.0,...}`. Full setup guide →
[docs/getting-started/QUICKSTART.md](docs/getting-started/QUICKSTART.md).

---

## Architecture

```
┌──────────────────────────────────────────────┐
│  Next.js 16 frontend  (5 locales)             │
└───────────────┬──────────────────────────────┘
                │ REST + SSE + WebSocket
┌───────────────▼──────────────────────────────┐
│  FastAPI (Python 3.12)                        │
│  auth · solve · LLM/RAG · credits ·           │
│  marketplace · triggers · MCP server          │
└──┬─────────┬──────────┬──────────┬────────────┘
   │         │          │          │
┌──▼──┐ ┌────▼────┐ ┌──▼──┐ ┌─────▼─────┐ ┌────────────┐
│ Pg  │ │RabbitMQ │ │Redis│ │  Qdrant   │ │ Anthropic  │
│ 18  │ │+ Celery │ │     │ │ (RAG)     │ │ Claude API │
└─────┘ │ workers │ └─────┘ └───────────┘ └────────────┘
        │ SCIP /  │
        │ HiGHS / │
        │ Hexaly  │
        └─────────┘
```

A **modular monolith**: the solver is the first extracted bounded context
(`app/domains/solver/`), behind a `SolverAdapter` protocol enforced by
import-linter contracts. Adding a solver means writing one adapter — see
[docs/ARCHITECTURE/OVERVIEW.md](docs/ARCHITECTURE/OVERVIEW.md).

---

## Documentation

| Doc | Description |
|---|---|
| [Quickstart](docs/getting-started/QUICKSTART.md) | From zero to first solve |
| [Architecture](docs/ARCHITECTURE/OVERVIEW.md) | System design, components, data model |
| [Contributing](CONTRIBUTING.md) | Dev setup and conventions |
| [Testing & Quality](docs/TESTING.md) | Test strategy, coverage, mutation scores |
| [Disaster Recovery](deploy/DISASTER-RECOVERY.md) | Incident response runbook |
| [MDPDP Spec](docs/specifications/MDPDP_TW_T_FORMULATION.md) | A worked mathematical formulation |

---

## Built with

JAOT stands on the **[SCIP Optimization Suite](https://www.scipopt.org/)**
(Zuse Institute Berlin) and **[HiGHS](https://highs.dev/)** — full attributions
in [THIRD_PARTY_LICENSES](THIRD_PARTY_LICENSES).

Built solo and AI-accelerated. What you can verify rather than take on faith:
tests run against real PostgreSQL (no mocked DB), domain boundaries are enforced
by import-linter contracts, and every change is gated by lint, tests, and
security scans (`bandit`, `pip-audit`, `npm audit`). Details, coverage, and
mutation-test scores in [Testing & Quality](docs/TESTING.md).

**Maintained best-effort** — monthly issue triage, quarterly dependency/CVE
pass. Issues and focused PRs welcome; see [CONTRIBUTING.md](CONTRIBUTING.md) and
[SECURITY.md](SECURITY.md).

---

## Citing the solvers

JAOT is powered by **SCIP 10** (via PySCIPOpt) and **HiGHS**. As the SCIP team
[requests](https://www.scipopt.org/index.php#cite), any work that uses SCIP
should acknowledge and cite it. If JAOT helps your research or product, please
cite the underlying solvers:

```bibtex
@misc{scip10,
  title        = {The {SCIP} Optimization Suite 10.0},
  author       = {Christopher Hojny and Mathieu Besançon and Ksenia Bestuzheva and Sander Borst and João Dionísio and Johannes Ehls and Leon Eifler and Mohammed Ghannam and Ambros Gleixner and Adrian Göß and Alexander Hoen and Jacob von Holly-Ponientzietz and Rolf van der Hulst and Dominik Kamp and Thorsten Koch and Kevin Kofler and Jurgen Lentz and Marco Lübbecke and Stephen J. Maher and Paul Matti Meinhold and Gioni Mexi and Til Mohr and Erik Mühmer and Krunal Kishor Patel and Marc E. Pfetsch and Sebastian Pokutta and Chantal Reinartz Groba and Felipe Serrano and Yuji Shinano and Mark Turner and Stefan Vigerske and Matthias Walter and Dieter Weninger and Liding Xu},
  year         = {2025},
  howpublished = {Optimization Online preprint, arXiv:2511.18580},
  url          = {https://arxiv.org/abs/2511.18580}
}

@article{achterberg2009scip,
  title   = {{SCIP}: solving constraint integer programs},
  author  = {Achterberg, Tobias},
  journal = {Mathematical Programming Computation},
  volume  = {1},
  number  = {1},
  pages   = {1--41},
  year    = {2009},
  doi     = {10.1007/s12532-008-0001-1}
}

@article{huangfu2018highs,
  title   = {Parallelizing the dual revised simplex method},
  author  = {Huangfu, Qi and Hall, J. A. Julian},
  journal = {Mathematical Programming Computation},
  volume  = {10},
  number  = {1},
  pages   = {119--142},
  year    = {2018},
  doi     = {10.1007/s12532-017-0130-5}
}
```

---

## License

[Apache License 2.0](LICENSE) — see also [NOTICE](NOTICE). Third-party license
attributions are in [THIRD_PARTY_LICENSES](THIRD_PARTY_LICENSES).
