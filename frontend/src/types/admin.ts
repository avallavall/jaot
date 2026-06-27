// Admin-only types for the platform admin panel. These mirror the read-only
// aggregate returned by `GET /api/v2/admin/organizations/{id}/overview`.

export interface AdminOrgDetail {
  id: string;
  name: string;
  plan: string;
  credits_balance: number;
  credits_subscription: number;
  credits_purchased: number;
  credits_earned: number;
  credits_used_month: number;
  monthly_quota: number;
  rate_limit_per_minute: number;
  rate_limit_per_day: number;
  ai_builder_enabled: boolean;
  byok_configured: boolean;
  max_private_plugins: number;
  is_active: boolean;
  is_verified: boolean;
  is_public_profile: boolean;
  slug: string | null;
  billing_email: string | null;
  currency: string;
  website_url: string | null;
  created_at: string;
  owner_user_id: string | null;
}

export interface AdminOrgOwner {
  id: string;
  name: string;
  email: string | null;
}

export interface AdminOrgCounts {
  users: number;
  active_users: number;
  api_keys: number;
  active_api_keys: number;
  models: number;
  executions: number;
}

export interface AdminOrgExecutionStats {
  total: number;
  completed: number;
  failed: number;
  running: number;
  credits_consumed_total: number;
}

export interface AdminOrgUser {
  id: string;
  organization_id: string;
  name: string;
  email: string | null;
  is_admin: boolean;
  can_build_plugins: boolean;
  is_active: boolean;
  created_at: string;
}

export interface AdminOrgApiKey {
  id: string;
  organization_id: string;
  user_id: string;
  name: string;
  description: string | null;
  key_prefix: string;
  is_active: boolean;
  created_at: string;
  last_used_at: string | null;
}

export interface AdminOrgModel {
  id: string;
  display_name: string;
  catalog_id: string | null;
  source: "marketplace" | "custom";
  is_active: boolean;
  total_executions: number;
  total_credits_used: number;
  last_executed_at: string | null;
  created_at: string;
}

export interface AdminOrgExecution {
  id: string;
  status: string;
  solver_name: string | null;
  credits_consumed: number;
  execution_time_ms: number | null;
  objective_value: number | null;
  model_display_name: string | null;
  executed_by_user_id: string | null;
  created_at: string;
}

export interface AdminOrgTransaction {
  id: string;
  transaction_type: string;
  credits_amount: number;
  balance_after: number;
  description: string;
  created_at: string;
}

export interface AdminOrganizationOverview {
  organization: AdminOrgDetail;
  owner: AdminOrgOwner | null;
  counts: AdminOrgCounts;
  execution_stats: AdminOrgExecutionStats;
  users: AdminOrgUser[];
  api_keys: AdminOrgApiKey[];
  models: AdminOrgModel[];
  recent_executions: AdminOrgExecution[];
  recent_transactions: AdminOrgTransaction[];
}
