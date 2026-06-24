# Use Case: Core Solve Flow — Model Execution

> The flagship flow: user submits a problem, credits are deducted, Celery solves in parallel, the solution is returned.

## Diagram

```mermaid
sequenceDiagram
    participant User as User
    participant Frontend as Frontend (/solve)
    participant API as POST /api/v2/solve
    participant PSS as PlatformSettingsService
    participant Orchestrator as SolveOrchestrator
    participant Credits as CreditsService
    participant DB as PostgreSQL
    participant RabbitMQ as Celery Queue
    participant Worker as celery_worker (SCIP|HiGHS)
    participant Solver as SolverAdapter
    
    User->>Frontend: Enter problem JSON
    Frontend->>API: POST /solve {variables, constraints, objective, options}
    API->>API: validate_problem() → check refs are valid
    API->>PSS: get("solve_maintenance_gate")
    PSS-->>API: false (platform active)
    alt maintenance_gate == true
        API->>Frontend: 503 "Maintenance mode"
    end
    
    API->>API: _enforce_tier_caps(org.plan) → check max_variables
    alt tier limit exceeded
        API->>Frontend: 403 "Variable limit exceeded. Upgrade to Pro."
    end
    
    API->>API: _enforce_tier_caps() → check daily solve quota
    alt daily_solves exceeded
        API->>Frontend: 403 "Daily quota exceeded"
    end
    
    API->>Orchestrator: SolveOrchestrator.solve_async(org, problem)
    Orchestrator->>API: compute_credits(vars, constraints, time_limit)
    API-->>Orchestrator: credits_needed = 15
    
    Orchestrator->>Credits: deduct(org_id, 15, ref_type="execution", ref_id="exe_...")
    alt insufficient_credits
        Credits-->>Orchestrator: InsufficientCreditsError
        Orchestrator->>Frontend: 402 "Insufficient credits"
    end
    Credits->>DB: INSERT CreditTransaction(type=EXECUTION, credits_amount=-15, org_id)
    
    Orchestrator->>DB: CREATE ModelExecution(id='exe_...', org_id, status='pending', ...)
    Orchestrator->>API: execution_id = 'exe_org_...'
    API->>Frontend: 202 {task_id, execution_id, credits_consumed=15, estimated_time_s=30}
    
    Frontend->>Frontend: Store execution_id
    Frontend->>Frontend: Start polling: GET /solve/async/{execution_id}
    
    Orchestrator->>Orchestrator: extract_problem_details() → num_vars, num_constraints
    Orchestrator->>Orchestrator: determine_solver_name(problem) → "scip" | "highs"
    Orchestrator->>Orchestrator: resolve_queue(solver_name) → "solve_scip"
    Orchestrator->>RabbitMQ: apply_async(queue='solve_scip', ...)
    RabbitMQ-->>Orchestrator: task_id enqueued
    Orchestrator->>DB: UPDATE ModelExecution SET status='running', task_id, solver_name
    Orchestrator->>Frontend: (background task enqueued)
    
    RabbitMQ->>Worker: Dequeue task
    Worker->>Worker: _assert_queue_match(solver_name, queue) → reject if mismatch
    Worker->>Solver: SolverAdapter.solve(problem_dict)
    
    alt Solver = SCIP
        Solver->>Solver: SCIPAdapter.solve() → call pyscipopt
    else Solver = HiGHS
        Solver->>Solver: HighsAdapter.solve() → call highspy
    end
    
    alt Solve succeeds
        Solver-->>Worker: solution {objective_value, variables_dict, status='optimal'}
    else Time limit
        Solver-->>Worker: {status='time_limit', best_objective, gap}
    else Infeasible
        Solver-->>Worker: {status='infeasible'}
    else Solver error
        Solver-->>Worker: SolverUnavailableError
        Worker->>DB: UPDATE ModelExecution SET status='failed'
        Worker->>Credits: refund(org_id, 15, ref_id)
        Worker->>Frontend: (polling detects failure)
    end
    
    Worker->>DB: UPDATE ModelExecution(status='completed', result_data={...}, execution_time_ms=1234, objective_value=42.5)
    Worker->>DB: INSERT UsageRecord(org_id, problem_type='mip', credits_used=15, execution_time_ms=1234)
    Worker->>API: (callback via celery-result)
    
    Frontend->>Frontend: Poll GET /solve/async/{execution_id}
    API->>DB: SELECT * FROM ModelExecution WHERE id=execution_id AND org_id=?
    DB-->>API: {status='completed', result_data, ...}
    API->>Frontend: 200 {status, objective_value, variables, execution_time_ms}
    
    Frontend->>Frontend: Display solution chart
    Frontend->>Frontend: Update credits_balance = 85 (100 - 15)
```

## Critical Points

### Pre-Solve Validation
1. **`validate_problem()`**: checks variable refs in objective/constraints
2. **`_enforce_tier_caps()`**: validates plan limits (max_variables, max_solves/day)
3. **Maintenance mode**: `solve_maintenance_gate` = true → 503 for everyone

### Pre-Pay + Refund Pattern
1. **Deduct before executing**: `CreditsService.deduct(...)` → CreditTransaction(EXECUTION)
2. **On failure**: `CreditsService.refund(...)` → CreditTransaction(REFUND) with the same reference_id
3. **Idempotency**: Unique constraint prevents double-refund

### Queue Routing per Solver
1. **`resolve_queue(solver_name)`**: maps "scip" → "solve_scip"
2. **Worker `_assert_queue_match()`**: rejects if a task arrives on the wrong queue
3. **Reason**: scalability. SCIP requires more resources than HiGHS

### Timing
- Frontend receives 202 immediately (does not wait for the solve)
- Polling every 2-5 seconds typically
- Client-side timeout: ~5 min
- Solver timeout: via `options.time_limit_seconds` (clamped per plan)

## Relevant Files

- `app/api/v2/solve.py:POST /solve` — main entry point
- `app/api/v2/deps/solve_maintenance_gate.py` — dependency for the gate check
- `app/services/solve_orchestrator.py:SolveOrchestrator` — orchestration
- `app/services/credits_service.py:CreditsService.deduct/refund()` — transactional
- `app/domains/solver/adapters/base.py` — SolverAdapter, DEFAULT_SOLVER_NAME
- `app/domains/solver/adapters/scip_adapter.py` — SCIPAdapter.solve()
- `app/domains/solver/adapters/highs_adapter.py` — HighsAdapter.solve()
- `app/domains/solver/queue_routing.py:resolve_queue()` — queue selection
- `app/tasks/solve_tasks.py` — Celery task (async execution)
- `app/models/optimization_model.py:ModelExecution` — execution record
