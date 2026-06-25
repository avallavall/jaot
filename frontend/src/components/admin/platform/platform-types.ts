// Types for the admin platform-analytics dashboard. Mirror the Pydantic response
// models in app/api/v2/routes/admin/analytics.py. Consumed via direct fetch
// (same pattern as components/admin/analytics), not the generated api.ts client.

export interface EntityCounts {
  total: number;
  active: number;
  new: number;
}

export interface ExecutionStats {
  total: number;
  per_user: number;
  per_org: number;
  success_rate: number;
  avg_solve_time_ms: number | null;
  median_solve_time_ms: number | null;
  by_status: Record<string, number>;
  by_origin: Record<string, number>;
  by_solver: Record<string, number>;
}

export interface BuilderSolves {
  total: number;
  success_rate: number;
  avg_solve_time_ms: number | null;
}

export interface CategoryStat {
  category: string;
  executions: number;
  avg_solve_time_ms: number | null;
  success_rate: number;
}

export interface DailyPoint {
  date: string;
  executions: number;
}

export interface PlatformOverview {
  days: number;
  users: EntityCounts;
  orgs: EntityCounts;
  avg_users_per_org: number;
  plan_distribution: Record<string, number>;
  executions: ExecutionStats;
  builder_solves: BuilderSolves;
  by_category: CategoryStat[];
  daily: DailyPoint[];
}

export interface Percentiles {
  p50: number | null;
  p95: number | null;
  p99: number | null;
}

export interface AutomationStats {
  total_triggers: number;
  active_triggers: number;
  total_runs: number;
  cron_success_rate: number;
  webhook_delivery_rate: number;
  schedules_failing: number;
}

export interface LowSuccessModel {
  id: string;
  display_name: string;
  category: string;
  success_rate: number;
  total_executions: number;
}

export interface Reliability {
  days: number;
  total_executions: number;
  percentiles_ms: Percentiles;
  timeout_rate: number;
  failure_rate: number;
  failures_by_solver_status: Record<string, number>;
  avg_queue_time_s: number | null;
  async_count: number;
  sync_count: number;
  automation: AutomationStats;
  low_success_models: LowSuccessModel[];
}

export interface AiUsage {
  days: number;
  conversations: number;
  messages: number;
  orgs_using_ai: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_cost_eur: number;
  avg_cost_per_conversation: number;
  messages_per_conversation: number;
  accepted_conversations: number;
  acceptance_rate: number;
  thumbs_up: number;
  thumbs_down: number;
  thumbs_ratio: number;
}

export interface PeriodOption {
  labelKey: string;
  days: number;
}
