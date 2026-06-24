import type {
  LoginResult,
  UserInfo,
  Organization,
  OrgProfile,
  User,
  UserProfile,
  APIKey,
  CreateKeyResponse,
  ModelCatalogItem,
  OrganizationModel,
  ModelExecution,
  AsyncTask,
  AsyncTaskStatus,
  OptimizationProblem,
  SolveResult,
  ValidationResult,
  CreditBalance,
  CreditSettings,
  CreditTransaction,
  Withdrawal,
  WithdrawalSchedule,
  NotificationList,
  NotificationPreferencesResponse,
  OnboardingStatus,
  Review,
  ReviewList,
  AdminStats,
  PaginatedResponse,
  InputField,
  TemplateSummary,
  BuilderDocument,
  BuilderDocumentListItem,
  BuilderDocumentUpdate,
  ModelVersion,
  ModelVersionListItem,
  SolveTrigger,
  CreateTriggerResponse,
  CreateTriggerRequest,
  TriggerRun,
  Workspace,
  WorkspaceMember,
  WorkspaceInvite,
  WorkspaceRole,
  AuditLogEntry,
  CreditPool,
  MultiObjectiveConfig,
  MultiObjectiveResult,
  GuidanceState,
  GuidanceUpdate,
  TriggerSchedule,
  ScheduleCreateRequest,
  ScheduleUpdateRequest,
  CronValidationResponse,
  EarningsSummary,
  SalesHistoryResponse,
  AnalyticsSummary,
  TimeSeriesDataPoint,
  GeoDistributionEntry,
  ModelPerformanceRow,
  ConversionFunnel,
  AdminAnalytics,
  PlacementPricing,
  FeaturedPlacement,
  AdminPlacement,
  VerificationRequestStatus,
  AdminVerificationEntry,
  FileImportPreviewResponse,
  SolveAnalyticsSummary,
  SolveAnalyticsTrends,
  SolveAnalyticsCompare,
} from "./types";

import type { AttachmentInfo } from "./llm-types";

export type { AttachmentInfo } from "./llm-types";

export type {
  LoginResult,
  UserInfo,
  Organization,
  OrgProfile,
  User,
  UserProfile,
  APIKey,
  CreateKeyResponse,
  ModelCatalogItem,
  OrganizationModel,
  ModelExecution,
  AsyncTask,
  AsyncTaskStatus,
  OptimizationProblem,
  OptimizationResult,
  SolveResult,
  ValidationResult,
  CreditBalance,
  CreditSettings,
  CreditTransaction,
  Withdrawal,
  WithdrawalSchedule,
  Notification,
  NotificationList,
  NotificationPreferenceEntry,
  NotificationPreferencesResponse,
  OnboardingStatus,
  Review,
  ReviewList,
  AdminStats,
  PaginatedResponse,
  InputField,
  TemplateSummary,
  BuilderDocument,
  BuilderDocumentListItem,
  BuilderDocumentUpdate,
  ModelVersion,
  ModelVersionListItem,
  SolveTrigger,
  CreateTriggerResponse,
  CreateTriggerRequest,
  TriggerRun,
  OverrideField,
  TriggerRunStatus,
  Workspace,
  WorkspaceMember,
  WorkspaceInvite,
  WorkspaceRole,
  AuditLogEntry,
  CreditPool,
  MultiObjectiveConfig,
  MultiObjectiveResult,
  ObjectiveSpec,
  ParetoPoint,
  WarmStartConfig,
  ConstraintSensitivity,
  SensitivityResult,
  GuidanceState,
  GuidanceUpdate,
  TriggerSchedule,
  ScheduleCreateRequest,
  ScheduleUpdateRequest,
  CronValidationResponse,
  EarningsSummary,
  SaleRecord,
  SalesHistoryResponse,
  AnalyticsSummary,
  TimeSeriesDataPoint,
  GeoDistributionEntry,
  ModelPerformanceRow,
  ConversionFunnel,
  SellerLeaderboardEntry,
  AdminAnalytics,
  PlacementPricing,
  FeaturedPlacement,
  AdminPlacement,
  VerificationRequestStatus,
  AdminVerificationEntry,
  FileImportPreviewResponse,
  SolveAnalyticsSummary,
  SolveAnalyticsTrends,
  SolveAnalyticsCompare,
  TrendBucket,
  ComparedExecution,
} from "./types";

export interface RegistryEntry {
  key: string;
  label: string;
  description: string;
  category: string;
  setting_type: "int" | "float" | "bool" | "str" | "json";
  min_value: number | null;
  max_value: number | null;
  unit: string | null;
  is_secret: boolean;
  is_readonly: boolean;
}

export interface SettingValue {
  value: string;
  env_default: string | null;
  is_modified: boolean;
  last_changed_by: string | null;
  last_changed_at: string | null;
  source?: "db" | "env" | "none" | "default" | null;
}

export interface SettingsRegistryResponse {
  categories: Record<string, RegistryEntry[]>;
}

export interface SettingsValuesResponse {
  settings: Record<string, SettingValue>;
}

export interface SettingsUpdateResponse {
  updated: string[];
  errors: Record<string, string>;
}

export interface SettingsAuditEntry {
  id: number;
  setting_key: string;
  old_value: string | null;
  new_value: string | null;
  changed_by: string;
  changed_at: string;
  category: string | null;
}

export interface SettingsAuditLogResponse {
  items: SettingsAuditEntry[];
  total: number;
  page: number;
  page_size: number;
}

export interface PlanTiersResponse {
  plans: Record<string, Record<string, string>>;
}

export class ApiError extends Error {
  status: number;
  detail?: string;

  constructor(status: number, message: string, detail?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export interface AuthTokenResponse {
  success: boolean;
  user: { id: string; name: string; email: string; is_admin: boolean; is_org_owner?: boolean };
  organization: { id: string; name: string; plan: string; credits_balance: number };
  permissions: { can_build_plugins: boolean; ai_builder_enabled: boolean };
  email_verified: boolean;
}

export interface EmailSignupResponse {
  user_id: string;
  organization_id: string;
  api_key: string;
  credits_balance: number;
  plan: string;
  message: string;
  email_verified: boolean;
}

const BASE_URL =
  typeof window !== "undefined"
    ? (process.env.NEXT_PUBLIC_API_URL ?? window.location.origin)
    : "http://localhost:8001";

function getApiKey(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("jaot_api_key");
}

function authHeaders(): Record<string, string> {
  const key = getApiKey();
  if (!key) return {};
  return { Authorization: `Bearer ${key}` };
}

type QueryParams = Record<string, string | number | boolean | undefined | null>;

function buildUrl(path: string, params?: QueryParams): string {
  const url = new URL(path, BASE_URL);
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null) {
        url.searchParams.set(k, String(v));
      }
    }
  }
  return url.toString();
}

// Exponential backoff for transient failures (5xx, network errors).
interface RetryConfig {
  maxAttempts: number;
  baseDelayMs: number;
}

const DEFAULT_RETRY: RetryConfig = { maxAttempts: 3, baseDelayMs: 1000 };

function isRetryableStatus(status: number): boolean {
  return status >= 500;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// Single-flight refresh prevents parallel refresh race condition.
let refreshPromise: Promise<void> | null = null;

async function refreshAccessToken(): Promise<void> {
  if (refreshPromise) return refreshPromise;
  refreshPromise = fetch(`${BASE_URL}/api/v2/auth/refresh`, {
    method: "POST",
    credentials: "include",
  })
    .then((res) => {
      if (!res.ok) throw new Error("Refresh failed");
    })
    .finally(() => {
      refreshPromise = null;
    });
  return refreshPromise;
}

export type RequestOptions = RequestInit & {
  params?: QueryParams;
  _retried?: boolean;
  /** Set to false to disable automatic retry on 5xx / network errors */
  retry?: boolean | RetryConfig;
};

async function request<T>(
  path: string,
  options: RequestOptions = {}
): Promise<T> {
  const { params, _retried, retry, ...fetchOptions } = options;
  const url = buildUrl(path, params);

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...authHeaders(),
    ...(fetchOptions.headers as Record<string, string> | undefined),
  };

  if (!fetchOptions.body) {
    delete headers["Content-Type"];
  }

  const retryConfig: RetryConfig | null =
    retry === false
      ? null
      : typeof retry === "object"
        ? retry
        : DEFAULT_RETRY;

  const maxAttempts = retryConfig?.maxAttempts ?? 1;
  const baseDelay = retryConfig?.baseDelayMs ?? 1000;

  let lastError: unknown = null;

  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    let res: Response;
    try {
      res = await fetch(url, {
        ...fetchOptions,
        headers,
        credentials: "include",
      });
    } catch (networkError) {
      lastError = networkError;
      if (retryConfig && attempt < maxAttempts) {
        const delayMs = baseDelay * Math.pow(2, attempt - 1);
        await sleep(delayMs);
        continue;
      }
      throw networkError;
    }

    if (!res.ok) {
      if (
        retryConfig &&
        isRetryableStatus(res.status) &&
        attempt < maxAttempts
      ) {
        // Don't retry maintenance 503s; fall through to maintenance handling.
        if (res.status === 503) {
          try {
            const body = await res.clone().json();
            if (body.status === "maintenance") {
              // fall through
            } else {
              const delayMs = baseDelay * Math.pow(2, attempt - 1);
              await sleep(delayMs);
              continue;
            }
          } catch {
            const delayMs = baseDelay * Math.pow(2, attempt - 1);
            await sleep(delayMs);
            continue;
          }
        } else {
          const delayMs = baseDelay * Math.pow(2, attempt - 1);
          await sleep(delayMs);
          continue;
        }
      }

      if (res.status === 503) {
        try {
          const body = await res.clone().json();
          if (body.status === "maintenance" && typeof window !== "undefined") {
            window.dispatchEvent(new CustomEvent("jaot:maintenance", { detail: body }));
            throw new ApiError(503, body.detail || "Platform under maintenance", body.detail);
          }
        } catch (e) {
          if (e instanceof ApiError) throw e;
        }
      }

      // Auto-refresh on expired access token; let 401 propagate if refresh fails.
      if (res.status === 401 && !_retried) {
        try {
          await refreshAccessToken();
          return request<T>(path, { ...options, _retried: true });
        } catch {
          // refresh failed
        }
      }

      let message = `Request failed (${res.status})`;
      let detail: string | undefined;
      try {
        const body = await res.json();
        // Pydantic validation errors come as body.detail = [{msg, ...}, ...].
        if (Array.isArray(body.detail)) {
          message = body.detail.map((e: { msg?: string }) => e.msg || String(e)).join("; ");
        } else if (typeof body.detail === "object" && body.detail !== null) {
          // Rate limit or structured error — extract nested message.
          message = body.detail.message || body.detail.error || JSON.stringify(body.detail);
        } else {
          message = body.error || body.detail || body.message || message;
        }
        detail = typeof body.detail === "string" ? body.detail : undefined;
      } catch {
        // ignore parse errors
      }
      throw new ApiError(res.status, message, detail);
    }

    if (res.status === 204) {
      return undefined as T;
    }

    return res.json();
  }

  throw lastError;
}

export const api = {
  request<T = unknown>(path: string, options?: RequestOptions): Promise<T> {
    return request<T>(path, options);
  },

  setApiKey(key: string): void {
    if (typeof window !== "undefined") localStorage.setItem("jaot_api_key", key);
  },
  clearApiKey(): void {
    if (typeof window !== "undefined") localStorage.removeItem("jaot_api_key");
  },
  getApiKey(): string | null {
    return getApiKey();
  },
  isAuthenticated(): boolean {
    return !!getApiKey();
  },

  async login(apiKey: string): Promise<LoginResult> {
    localStorage.setItem("jaot_api_key", apiKey);
    try {
      const result = await request<LoginResult>("/api/v2/auth/login", {
        method: "POST",
        body: JSON.stringify({ api_key: apiKey }),
      });
      return result;
    } catch (err) {
      localStorage.removeItem("jaot_api_key");
      throw err;
    }
  },

  getMe(): Promise<UserInfo> {
    return request("/api/v2/auth/me");
  },

  async loginWithEmail(
    email: string,
    password: string,
    rememberMe: boolean = false
  ): Promise<AuthTokenResponse> {
    return request("/api/v2/auth/login/email", {
      method: "POST",
      body: JSON.stringify({ email, password, remember_me: rememberMe }),
    });
  },

  async signupWithEmail(data: {
    email: string;
    name: string;
    organization_name: string;
    plan: string;
    password: string;
    confirm_password: string;
    tos_accepted?: boolean;
  }): Promise<EmailSignupResponse> {
    return request("/api/v2/auth/signup/email", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  async verifyEmail(
    token: string
  ): Promise<{ success: boolean; message: string }> {
    return request("/api/v2/auth/verify-email", {
      method: "POST",
      body: JSON.stringify({ token }),
    });
  },

  async forgotPassword(
    email: string
  ): Promise<{ success: boolean; message: string }> {
    return request("/api/v2/auth/forgot-password", {
      method: "POST",
      body: JSON.stringify({ email }),
    });
  },

  async resetPassword(
    token: string,
    password: string
  ): Promise<{ success: boolean; message: string }> {
    return request("/api/v2/auth/reset-password", {
      method: "POST",
      body: JSON.stringify({ token, password }),
    });
  },

  async logoutSession(): Promise<void> {
    return request("/api/v2/auth/logout", { method: "POST" });
  },

  async exportUserData(): Promise<void> {
    const response = await fetch(buildUrl("/api/v2/user/data-export"), {
      headers: authHeaders(),
      credentials: "include",
    });
    if (!response.ok) throw new Error("Export failed");
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "jaot-data-export.json";
    a.click();
    URL.revokeObjectURL(url);
  },

  async deleteUserAccount(password: string): Promise<void> {
    return request("/api/v2/user/account", {
      method: "DELETE",
      body: JSON.stringify({ password, confirmation: "DELETE" }),
    });
  },

  getMyModels(params?: QueryParams): Promise<PaginatedResponse<OrganizationModel>> {
    return request("/api/v2/models/", { params });
  },

  getMyModel(modelId: string): Promise<OrganizationModel> {
    return request(`/api/v2/models/${modelId}`);
  },

  getMyModelSchema(modelId: string): Promise<{ input_fields: InputField[]; example_input: Record<string, unknown> }> {
    return request(`/api/v2/models/${modelId}/schema`);
  },

  updateMyModel(modelId: string, data: Partial<OrganizationModel>): Promise<OrganizationModel> {
    return request(`/api/v2/models/${modelId}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    });
  },

  deactivateMyModel(modelId: string): Promise<void> {
    return request(`/api/v2/models/${modelId}`, { method: "DELETE" });
  },

  createModel(data: Record<string, unknown>): Promise<OrganizationModel> {
    return request("/api/v2/models/", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  getCatalog(params?: QueryParams): Promise<PaginatedResponse<ModelCatalogItem>> {
    return request("/api/v2/models/catalog", { params });
  },

  getCatalogModel(modelId: string): Promise<ModelCatalogItem> {
    return request(`/api/v2/models/catalog/${modelId}`);
  },

  getCatalogModelSchema(modelId: string): Promise<{ input_fields: InputField[]; example_input: Record<string, unknown> }> {
    return request(`/api/v2/models/catalog/${modelId}/schema`);
  },

  activateCatalogModel(modelId: string, options?: { customName?: string }): Promise<OrganizationModel> {
    const body: Record<string, unknown> = {};
    if (options?.customName) {
      body.custom_name = options.customName;
    }
    return request(`/api/v2/models/catalog/${modelId}/activate`, {
      method: "POST",
      body: JSON.stringify(body),
    });
  },

  executeModel(modelId: string, data: Record<string, unknown>, solverName?: string): Promise<ModelExecution> {
    const url = solverName
      ? `/api/v2/models/${modelId}/execute?solver_name=${encodeURIComponent(solverName)}`
      : `/api/v2/models/${modelId}/execute`;
    return request(url, {
      method: "POST",
      body: JSON.stringify({ input_data: data, async_mode: false }),
    });
  },

  executeModelAsync(modelId: string, data: Record<string, unknown>, solverName?: string): Promise<AsyncTask> {
    const url = solverName
      ? `/api/v2/models/${modelId}/execute?solver_name=${encodeURIComponent(solverName)}`
      : `/api/v2/models/${modelId}/execute`;
    return request(url, {
      method: "POST",
      body: JSON.stringify({ input_data: data, async_mode: true }),
    });
  },

  getAsyncTaskStatus(taskId: string): Promise<AsyncTaskStatus> {
    return request(`/api/v2/models/async/${taskId}`);
  },

  cancelAsyncTask(taskId: string): Promise<void> {
    return request(`/api/v2/models/async/${taskId}/cancel`, { method: "POST" });
  },

  getModelExecutions(modelId: string, params?: QueryParams): Promise<PaginatedResponse<ModelExecution>> {
    return request(`/api/v2/models/${modelId}/executions`, { params });
  },

  getAllExecutions(params?: QueryParams): Promise<PaginatedResponse<ModelExecution>> {
    return request("/api/v2/models/executions/all", { params });
  },

  getExecution(executionId: string): Promise<ModelExecution> {
    return request(`/api/v2/models/executions/${executionId}`);
  },

  getSolvers(): Promise<{
    solvers: Array<{
      name: string;
      available: boolean;
      description?: string;
      multiplier?: number;
      reason?: string;
      retry_after?: number | null;
    }>;
  }> {
    return request("/api/v2/solvers/available");
  },

  getExecutionInsights(executionId: string): Promise<{ execution_id: string; insights: { category: string; message: string; severity: string }[] }> {
    return request(`/api/v2/solve/insights/${executionId}`);
  },

  solve(problem: OptimizationProblem, workspaceId?: string): Promise<SolveResult> {
    return request("/api/v2/solve", {
      method: "POST",
      body: JSON.stringify(problem),
      params: workspaceId ? { workspace_id: workspaceId } : undefined,
    });
  },

  validateProblem(problem: OptimizationProblem): Promise<ValidationResult> {
    return request("/api/v2/solve/validate", {
      method: "POST",
      body: JSON.stringify(problem),
    });
  },

  solveMultiObjective(
    problem: OptimizationProblem,
    config: MultiObjectiveConfig,
    workspaceId?: string
  ): Promise<MultiObjectiveResult> {
    return request("/api/v2/solve/multi-objective", {
      method: "POST",
      params: workspaceId ? { workspace_id: workspaceId } : undefined,
      body: JSON.stringify({ problem, config }),
    });
  },

  getFavorites(): Promise<OrganizationModel[]> {
    return request("/api/v2/models/favorites");
  },

  addFavorite(modelId: string): Promise<void> {
    return request(`/api/v2/models/favorites/${modelId}`, { method: "POST" });
  },

  removeFavorite(modelId: string): Promise<void> {
    return request(`/api/v2/models/favorites/${modelId}`, { method: "DELETE" });
  },

  getRecents(params?: QueryParams): Promise<OrganizationModel[]> {
    return request("/api/v2/models/recents", { params });
  },

  getCreditBalance(): Promise<CreditBalance> {
    return request("/api/v2/credits/balance");
  },

  getCreditSettings(): Promise<CreditSettings> {
    return request("/api/v2/credits/settings");
  },

  getCreditTransactions(params?: QueryParams): Promise<CreditTransaction[]> {
    return request("/api/v2/credits/transactions", { params });
  },

  getWithdrawals(): Promise<Withdrawal[]> {
    return request("/api/v2/credits/withdrawals");
  },

  createWithdrawal(data: { credits_amount: number; currency: string }): Promise<Withdrawal> {
    return request("/api/v2/credits/withdrawals", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  getWithdrawalSchedules(): Promise<WithdrawalSchedule[]> {
    return request("/api/v2/credits/schedules");
  },

  createWithdrawalSchedule(data: Record<string, unknown>): Promise<WithdrawalSchedule> {
    return request("/api/v2/credits/schedules", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  deleteWithdrawalSchedule(id: string): Promise<void> {
    return request(`/api/v2/credits/schedules/${id}`, { method: "DELETE" });
  },

  updateCurrency(data: { currency: string }): Promise<void> {
    return request("/api/v2/credits/settings/currency", {
      method: "PUT",
      body: JSON.stringify(data),
    });
  },

  createTopupCheckout(data: {
    credits: number;
    success_url: string;
    cancel_url: string;
  }): Promise<{ checkout_url: string; session_id: string }> {
    return request("/api/v2/billing/checkout/topup", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  getSellerEarningsSummary(): Promise<EarningsSummary> {
    return request("/api/v2/seller/earnings/summary");
  },

  getSellerSalesHistory(params?: { page?: number; page_size?: number }): Promise<SalesHistoryResponse> {
    return request("/api/v2/seller/earnings/sales", { params });
  },

  getSellerAnalyticsSummary(period: string = "30d"): Promise<AnalyticsSummary> {
    return request("/api/v2/seller/analytics/summary", { params: { period } });
  },

  getSellerAnalyticsTimeSeries(period: string = "30d"): Promise<{ data: TimeSeriesDataPoint[]; period: string }> {
    return request("/api/v2/seller/analytics/time-series", { params: { period } });
  },

  getSellerAnalyticsGeo(period: string = "30d"): Promise<{ data: GeoDistributionEntry[] }> {
    return request("/api/v2/seller/analytics/geo", { params: { period } });
  },

  getSellerAnalyticsModels(period: string = "30d"): Promise<ModelPerformanceRow[]> {
    return request("/api/v2/seller/analytics/models", { params: { period } });
  },

  getSellerAnalyticsFunnel(period: string = "30d"): Promise<ConversionFunnel> {
    return request("/api/v2/seller/analytics/funnel", { params: { period } });
  },

  getAdminSellerAnalytics(period: string = "30d"): Promise<AdminAnalytics> {
    return request("/api/v2/admin/marketplace/seller-analytics", { params: { period } });
  },

  getPlacementPricing(): Promise<PlacementPricing[]> {
    return request("/api/v2/seller/placements/pricing");
  },

  purchasePlacement(data: { catalog_model_id: string; placement_type: string; duration_days: number }): Promise<FeaturedPlacement> {
    return request("/api/v2/seller/placements/purchase", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  getActivePlacements(): Promise<{ items: FeaturedPlacement[]; total: number }> {
    return request("/api/v2/seller/placements/active");
  },

  requestVerification(): Promise<VerificationRequestStatus> {
    return request("/api/v2/seller/verification/request", {
      method: "POST",
      body: JSON.stringify({}),
    });
  },

  getVerificationStatus(): Promise<VerificationRequestStatus | null> {
    return request("/api/v2/seller/verification/status");
  },

  getNotificationPreferences(): Promise<NotificationPreferencesResponse> {
    return request("/api/v2/seller/notifications/preferences");
  },

  updateNotificationPreference(data: { event_type: string; channel: string; enabled: boolean }): Promise<NotificationPreferencesResponse> {
    return request("/api/v2/seller/notifications/preferences", {
      method: "PUT",
      body: JSON.stringify(data),
    });
  },

  getOnboardingStatus(): Promise<OnboardingStatus> {
    return request("/api/v2/seller/onboarding/status");
  },

  getAdminPromotions(): Promise<AdminPlacement[]> {
    return request("/api/v2/admin/marketplace/promotions");
  },

  revokePromotion(id: string): Promise<void> {
    return request(`/api/v2/admin/marketplace/promotions/${id}/revoke`, { method: "POST" });
  },

  extendPromotion(id: string, extraDays: number): Promise<{ status: string }> {
    return request(`/api/v2/admin/marketplace/promotions/${id}/extend`, {
      method: "POST",
      body: JSON.stringify({ extra_days: extraDays }),
    });
  },

  getAdminVerificationRequests(): Promise<AdminVerificationEntry[]> {
    return request("/api/v2/admin/marketplace/verification");
  },

  decideVerification(id: string, decision: { status: "approved" | "rejected"; admin_note?: string }): Promise<{ status: string }> {
    return request(`/api/v2/admin/marketplace/verification/${id}/decide`, {
      method: "POST",
      body: JSON.stringify(decision),
    });
  },

  async getKeys(): Promise<APIKey[]> {
    const res = await request<PaginatedResponse<APIKey>>("/api/v2/keys/");
    return res.items;
  },

  createKey(data: { name: string; description?: string; expires_days?: number }): Promise<CreateKeyResponse> {
    return request("/api/v2/keys/", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  deleteKey(id: string): Promise<void> {
    return request(`/api/v2/keys/${id}`, { method: "DELETE" });
  },

  getNotifications(params?: QueryParams): Promise<NotificationList> {
    return request("/api/v2/notifications", { params });
  },

  getUnreadCount(): Promise<{ unread_count: number }> {
    return request("/api/v2/notifications/unread-count");
  },

  markAsRead(id: string): Promise<void> {
    return request(`/api/v2/notifications/${id}/read`, { method: "POST" });
  },

  markAllAsRead(): Promise<void> {
    return request("/api/v2/notifications/read-all", { method: "POST" });
  },

  publishModel(modelId: string, data: Record<string, unknown>): Promise<ModelCatalogItem> {
    return request(`/api/v2/models/${modelId}/publish`, {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  getOrgProfile(orgId: string): Promise<OrgProfile> {
    return request(`/api/v2/organizations/${orgId}/public`);
  },

  getOrgModels(orgId: string): Promise<ModelCatalogItem[]> {
    return request(`/api/v2/organizations/${orgId}/models`);
  },

  updateOrgProfile(data: Record<string, unknown>): Promise<OrgProfile> {
    return request("/api/v2/organizations/profile", {
      method: "PATCH",
      body: JSON.stringify(data),
    });
  },

  getUserProfile(userId: string): Promise<UserProfile> {
    return request(`/api/v2/users/${userId}/public`);
  },

  updateUserProfile(data: Record<string, unknown>): Promise<UserProfile> {
    return request("/api/v2/users/profile", {
      method: "PATCH",
      body: JSON.stringify(data),
    });
  },

  getUserReviews(userId: string): Promise<Review[]> {
    return request(`/api/v2/users/${userId}/reviews`);
  },

  getCatalogReviews(catalogId: string, params?: QueryParams): Promise<ReviewList> {
    return request(`/api/v2/models/catalog/${catalogId}/reviews`, { params });
  },

  createReview(catalogId: string, data: { rating: number; title?: string; comment?: string }): Promise<Review> {
    return request(`/api/v2/models/catalog/${catalogId}/reviews`, {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  deleteReview(reviewId: string): Promise<void> {
    return request(`/api/v2/models/reviews/${reviewId}`, { method: "DELETE" });
  },

  reportReview(reviewId: string, data: { reason: string }): Promise<void> {
    return request(`/api/v2/models/reviews/${reviewId}/report`, {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  createBuilderDocument(name?: string, workspaceId?: string, signal?: AbortSignal): Promise<BuilderDocument> {
    return request("/api/v2/builder/", {
      method: "POST",
      body: JSON.stringify({ name: name ?? "Untitled Model" }),
      params: workspaceId ? { workspace_id: workspaceId } : undefined,
      signal,
    });
  },

  listBuilderDocuments(workspaceId?: string): Promise<BuilderDocumentListItem[]> {
    return request("/api/v2/builder/", {
      params: workspaceId ? { workspace_id: workspaceId } : undefined,
    });
  },

  getBuilderDocument(id: string, workspaceId?: string): Promise<BuilderDocument> {
    return request(`/api/v2/builder/${id}`, {
      params: workspaceId ? { workspace_id: workspaceId } : undefined,
    });
  },

  updateBuilderDocument(id: string, data: BuilderDocumentUpdate, workspaceId?: string): Promise<BuilderDocument> {
    return request(`/api/v2/builder/${id}`, {
      method: "PUT",
      body: JSON.stringify(data),
      params: workspaceId ? { workspace_id: workspaceId } : undefined,
    });
  },

  deleteBuilderDocument(id: string, workspaceId?: string): Promise<void> {
    return request(`/api/v2/builder/${id}`, {
      method: "DELETE",
      params: workspaceId ? { workspace_id: workspaceId } : undefined,
    });
  },

  listTemplates(): Promise<{ templates: TemplateSummary[] }> {
    return request("/api/v2/solve/templates");
  },

  getTemplate(templateId: string): Promise<Record<string, unknown>> {
    return request(`/api/v2/solve/templates/${templateId}`);
  },

  solveTemplate(templateId: string, input: Record<string, unknown>, workspaceId?: string): Promise<SolveResult> {
    return request(`/api/v2/solve/templates/${templateId}/solve`, {
      method: "POST",
      body: JSON.stringify(input),
      params: workspaceId ? { workspace_id: workspaceId } : undefined,
    });
  },

  previewModel(modelId: string, inputData: Record<string, unknown>): Promise<OptimizationProblem> {
    return request(`/api/v2/models/${modelId}/preview`, {
      method: "POST",
      body: JSON.stringify({ input_data: inputData }),
    });
  },

  previewTemplate(templateId: string, inputData?: Record<string, unknown>): Promise<OptimizationProblem> {
    return request(`/api/v2/solve/templates/${templateId}/preview`, {
      method: "POST",
      body: JSON.stringify(inputData ?? null),
    });
  },

  listVersions(documentId: string, params?: { limit?: number; skip?: number }, workspaceId?: string): Promise<ModelVersionListItem[]> {
    // Trailing slash matches the backend collection route (@router.get("/")).
    // Without it FastAPI issues a 307 redirect that downgrades https→http behind
    // the proxy, which browsers block as mixed content. See createVersion below.
    return request(`/api/v2/builder/${documentId}/versions/`, {
      params: { ...params, ...(workspaceId ? { workspace_id: workspaceId } : {}) },
    });
  },

  getVersion(documentId: string, versionId: string, workspaceId?: string): Promise<ModelVersion> {
    return request(`/api/v2/builder/${documentId}/versions/${versionId}`, {
      params: workspaceId ? { workspace_id: workspaceId } : undefined,
    });
  },

  createVersion(documentId: string, data: { canvas_json: Record<string, unknown> }, workspaceId?: string): Promise<ModelVersion> {
    // Trailing slash matches the backend collection route (@router.post("/")) to
    // avoid the 307 redirect that downgrades https→http (mixed content) in prod.
    return request(`/api/v2/builder/${documentId}/versions/`, {
      method: "POST",
      body: JSON.stringify(data),
      params: workspaceId ? { workspace_id: workspaceId } : undefined,
    });
  },

  promoteVersion(
    documentId: string,
    versionId: string,
    data: { version_name: string; version_description?: string },
    workspaceId?: string,
  ): Promise<ModelVersion> {
    return request(`/api/v2/builder/${documentId}/versions/${versionId}`, {
      method: "PATCH",
      body: JSON.stringify(data),
      params: workspaceId ? { workspace_id: workspaceId } : undefined,
    });
  },

  restoreVersion(
    documentId: string,
    versionId: string,
    data: { current_canvas_json: Record<string, unknown> },
    workspaceId?: string,
  ): Promise<{ checkpoint_id: string; document: BuilderDocument }> {
    return request(`/api/v2/builder/${documentId}/versions/${versionId}/restore`, {
      method: "POST",
      body: JSON.stringify(data),
      params: workspaceId ? { workspace_id: workspaceId } : undefined,
    });
  },

  triggers: {
    list: (documentId?: string, workspaceId?: string): Promise<SolveTrigger[]> => {
      const params: QueryParams = {};
      if (documentId) params.document_id = documentId;
      if (workspaceId) params.workspace_id = workspaceId;
      return request<SolveTrigger[]>("/api/v2/triggers/", { params });
    },
    get: (triggerId: string, workspaceId?: string): Promise<SolveTrigger> =>
      request<SolveTrigger>(`/api/v2/triggers/${triggerId}`, {
        params: workspaceId ? { workspace_id: workspaceId } : undefined,
      }),
    create: (body: CreateTriggerRequest, workspaceId?: string): Promise<CreateTriggerResponse> =>
      request<CreateTriggerResponse>("/api/v2/triggers/", {
        method: "POST",
        body: JSON.stringify(body),
        params: workspaceId ? { workspace_id: workspaceId } : undefined,
      }),
    update: (triggerId: string, body: Partial<CreateTriggerRequest>, workspaceId?: string): Promise<SolveTrigger> =>
      request<SolveTrigger>(`/api/v2/triggers/${triggerId}`, {
        method: "PATCH",
        body: JSON.stringify(body),
        params: workspaceId ? { workspace_id: workspaceId } : undefined,
      }),
    delete: (triggerId: string, workspaceId?: string): Promise<void> =>
      request<void>(`/api/v2/triggers/${triggerId}`, {
        method: "DELETE",
        params: workspaceId ? { workspace_id: workspaceId } : undefined,
      }),
    toggle: (triggerId: string, enabled: boolean, workspaceId?: string): Promise<SolveTrigger> =>
      request<SolveTrigger>(`/api/v2/triggers/${triggerId}/toggle`, {
        method: "POST",
        body: JSON.stringify({ enabled }),
        params: workspaceId ? { workspace_id: workspaceId } : undefined,
      }),
    runs: {
      list: (
        triggerId: string,
        page = 1,
        pageSize = 20,
        workspaceId?: string,
      ): Promise<{ items: TriggerRun[]; total: number; page: number; page_size: number }> => {
        const params: QueryParams = { page: String(page), page_size: String(pageSize) };
        if (workspaceId) params.workspace_id = workspaceId;
        return request<{ items: TriggerRun[]; total: number; page: number; page_size: number }>(
          `/api/v2/triggers/${triggerId}/runs`, { params }
        );
      },
      get: (triggerId: string, runId: string, workspaceId?: string): Promise<TriggerRun> =>
        request<TriggerRun>(`/api/v2/triggers/${triggerId}/runs/${runId}`, {
          params: workspaceId ? { workspace_id: workspaceId } : undefined,
        }),
      rerun: (triggerId: string, runId: string): Promise<{ run_id: string }> =>
        request<{ run_id: string }>(
          `/api/v2/triggers/${triggerId}/runs/${runId}/rerun`,
          { method: "POST" }
        ),
    },
  },

  schedules: {
    get(triggerId: string): Promise<TriggerSchedule> {
      return request<TriggerSchedule>(`/api/v2/triggers/${triggerId}/schedule`);
    },
    create(triggerId: string, body: ScheduleCreateRequest): Promise<TriggerSchedule> {
      return request<TriggerSchedule>(`/api/v2/triggers/${triggerId}/schedule`, {
        method: "POST",
        body: JSON.stringify(body),
      });
    },
    update(triggerId: string, body: ScheduleUpdateRequest): Promise<TriggerSchedule> {
      return request<TriggerSchedule>(`/api/v2/triggers/${triggerId}/schedule`, {
        method: "PATCH",
        body: JSON.stringify(body),
      });
    },
    delete(triggerId: string): Promise<void> {
      return request<void>(`/api/v2/triggers/${triggerId}/schedule`, { method: "DELETE" });
    },
    validate(body: ScheduleCreateRequest): Promise<CronValidationResponse> {
      return request<CronValidationResponse>("/api/v2/schedules/validate", {
        method: "POST",
        body: JSON.stringify(body),
      });
    },
  },

  attachments: {
    async upload(conversationId: string, file: File): Promise<AttachmentInfo> {
      const doUpload = async (): Promise<Response> => {
        const formData = new FormData();
        formData.append("file", file);
        return fetch(
          buildUrl(`/api/v2/llm/conversations/${conversationId}/attachments`),
          {
            method: "POST",
            headers: authHeaders(), // NO Content-Type — browser sets multipart boundary
            body: formData,
            credentials: "include",
          }
        );
      };

      let res = await doUpload();

      if (res.status === 401) {
        await refreshAccessToken();
        res = await doUpload();
      }

      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        const detail = typeof body.detail === "string" ? body.detail : undefined;
        throw new ApiError(res.status, detail || `Upload failed (${res.status})`, detail);
      }

      return res.json();
    },

    async remove(conversationId: string, attachmentId: string): Promise<void> {
      return request<void>(
        `/api/v2/llm/conversations/${conversationId}/attachments/${attachmentId}`,
        { method: "DELETE" }
      );
    },
  },

  fileImport: {
    async preview(file: File): Promise<FileImportPreviewResponse> {
      const doUpload = async (): Promise<Response> => {
        const formData = new FormData();
        formData.append("file", file);
        return fetch(buildUrl("/api/v2/solve/import/preview"), {
          method: "POST",
          headers: authHeaders(),
          body: formData,
          credentials: "include",
        });
      };

      let res = await doUpload();

      if (res.status === 401) {
        await refreshAccessToken();
        res = await doUpload();
      }

      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        const detail = typeof body.detail === "string" ? body.detail : undefined;
        throw new ApiError(res.status, detail || `Preview failed (${res.status})`, detail);
      }

      return res.json();
    },

    async import(file: File, solverName?: string): Promise<SolveResult> {
      const doUpload = async (): Promise<Response> => {
        const formData = new FormData();
        formData.append("file", file);
        if (solverName) {
          formData.append("solver_name", solverName);
        }
        return fetch(buildUrl("/api/v2/solve/import"), {
          method: "POST",
          headers: authHeaders(),
          body: formData,
          credentials: "include",
        });
      };

      let res = await doUpload();

      if (res.status === 401) {
        await refreshAccessToken();
        res = await doUpload();
      }

      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        const detail = typeof body.detail === "string" ? body.detail : undefined;
        throw new ApiError(res.status, detail || `Import failed (${res.status})`, detail);
      }

      return res.json();
    },
  },

  fileExport: {
    async download(executionId: string, fmt: string): Promise<Blob> {
      const url = buildUrl(`/api/v2/solve/export/${executionId}/${fmt}`);
      const doFetch = async (): Promise<Response> =>
        fetch(url, {
          headers: { ...authHeaders() },
          credentials: "include",
        });

      let res = await doFetch();

      if (res.status === 401) {
        await refreshAccessToken();
        res = await doFetch();
      }

      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        const detail = typeof body.detail === "string" ? body.detail : undefined;
        throw new ApiError(res.status, detail || `Export failed (${res.status})`, detail);
      }

      return res.blob();
    },
  },

  solveAnalytics: {
    getSummary(days = 30): Promise<SolveAnalyticsSummary> {
      return request(`/api/v2/solve/analytics/summary`, { params: { days } });
    },
    getTrends(days = 30, bucket: "day" | "week" = "day"): Promise<SolveAnalyticsTrends> {
      return request(`/api/v2/solve/analytics/trends`, { params: { days, bucket } });
    },
    compare(ids: string[]): Promise<SolveAnalyticsCompare> {
      return request(`/api/v2/solve/analytics/compare`, { params: { ids: ids.join(",") } });
    },
  },

  createWorkspace(data: { name: string; description?: string }): Promise<Workspace> {
    return request("/api/v2/workspaces/", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  listWorkspaces(page?: number, limit?: number): Promise<PaginatedResponse<Workspace>> {
    return request("/api/v2/workspaces/", { params: { page, limit } });
  },

  getWorkspace(workspaceId: string): Promise<Workspace> {
    return request(`/api/v2/workspaces/${workspaceId}`);
  },

  updateWorkspace(workspaceId: string, data: { name?: string; description?: string }): Promise<Workspace> {
    return request(`/api/v2/workspaces/${workspaceId}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    });
  },

  deleteWorkspace(workspaceId: string): Promise<void> {
    return request(`/api/v2/workspaces/${workspaceId}`, { method: "DELETE" });
  },

  listMembers(workspaceId: string): Promise<WorkspaceMember[]> {
    return request(`/api/v2/workspaces/${workspaceId}/members/`);
  },

  updateMemberRole(workspaceId: string, userId: string, role: WorkspaceRole): Promise<void> {
    return request(`/api/v2/workspaces/${workspaceId}/members/${userId}`, {
      method: "PATCH",
      body: JSON.stringify({ role }),
    });
  },

  removeMember(workspaceId: string, userId: string): Promise<void> {
    return request(`/api/v2/workspaces/${workspaceId}/members/${userId}`, { method: "DELETE" });
  },

  createEmailInvite(
    workspaceId: string,
    data: { email: string; role: WorkspaceRole }
  ): Promise<WorkspaceInvite> {
    return request(`/api/v2/workspaces/${workspaceId}/invites/email`, {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  createLinkInvite(
    workspaceId: string,
    data: { role: WorkspaceRole }
  ): Promise<{ invite_url: string; expires_at: string }> {
    return request(`/api/v2/workspaces/${workspaceId}/invites/link`, {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  acceptInvite(token: string): Promise<void> {
    return request("/api/v2/workspaces/invites/accept", {
      method: "POST",
      body: JSON.stringify({ token }),
    });
  },

  listInvites(workspaceId: string): Promise<WorkspaceInvite[]> {
    return request(`/api/v2/workspaces/${workspaceId}/invites/`);
  },

  revokeInvite(workspaceId: string, inviteId: string): Promise<void> {
    return request(`/api/v2/workspaces/${workspaceId}/invites/${inviteId}`, { method: "DELETE" });
  },

  listAuditLogs(
    workspaceId: string,
    params?: {
      action?: string;
      actor_id?: string;
      date_from?: string;
      date_to?: string;
      page?: number;
      limit?: number;
    }
  ): Promise<PaginatedResponse<AuditLogEntry>> {
    return request(`/api/v2/workspaces/${workspaceId}/audit/`, { params });
  },

  getPoolStats(workspaceId: string): Promise<CreditPool> {
    return request(`/api/v2/workspaces/${workspaceId}/credits/`);
  },

  allocateCredits(workspaceId: string, amount: number): Promise<CreditPool> {
    return request(`/api/v2/workspaces/${workspaceId}/credits/allocate`, {
      method: "POST",
      body: JSON.stringify({ amount }),
    });
  },

  getGuidance(): Promise<GuidanceState> {
    return request("/api/v2/guidance");
  },

  updateGuidance(update: GuidanceUpdate): Promise<GuidanceState> {
    return request("/api/v2/guidance", {
      method: "PATCH",
      body: JSON.stringify(update),
    });
  },

  admin: {
    getStats(): Promise<AdminStats> {
      return request("/api/v2/admin/stats");
    },

    getOrganizations(params?: QueryParams): Promise<PaginatedResponse<Organization>> {
      return request("/api/v2/admin/organizations", { params });
    },

    createOrganization(data: Record<string, unknown>): Promise<Organization> {
      return request("/api/v2/admin/organizations", {
        method: "POST",
        body: JSON.stringify(data),
      });
    },

    updateOrganization(id: string, data: Record<string, unknown>): Promise<Organization> {
      return request(`/api/v2/admin/organizations/${id}`, {
        method: "PATCH",
        body: JSON.stringify(data),
      });
    },

    deleteOrganization(id: string): Promise<void> {
      return request(`/api/v2/admin/organizations/${id}`, { method: "DELETE" });
    },

    verifyOrg(id: string): Promise<void> {
      return request(`/api/v2/admin/organizations/${id}/verify`, { method: "POST" });
    },

    unverifyOrg(id: string): Promise<void> {
      return request(`/api/v2/admin/organizations/${id}/verify`, { method: "DELETE" });
    },

    getUsers(params?: QueryParams): Promise<PaginatedResponse<User>> {
      return request("/api/v2/admin/users", { params });
    },

    createUser(data: Record<string, unknown>): Promise<User> {
      return request("/api/v2/admin/users", {
        method: "POST",
        body: JSON.stringify(data),
      });
    },

    updateUser(id: string, data: Record<string, unknown>): Promise<User> {
      return request(`/api/v2/admin/users/${id}`, {
        method: "PATCH",
        body: JSON.stringify(data),
      });
    },

    deleteUser(id: string): Promise<void> {
      return request(`/api/v2/admin/users/${id}`, { method: "DELETE" });
    },

    getApiKeys(params?: QueryParams): Promise<PaginatedResponse<APIKey>> {
      return request("/api/v2/admin/api-keys", { params });
    },

    createApiKey(data: Record<string, unknown>): Promise<APIKey> {
      return request("/api/v2/admin/api-keys", {
        method: "POST",
        body: JSON.stringify(data),
      });
    },

    toggleApiKey(id: string): Promise<APIKey> {
      return request(`/api/v2/admin/api-keys/${id}/toggle`, { method: "PATCH" });
    },

    deleteApiKey(id: string): Promise<void> {
      return request(`/api/v2/admin/api-keys/${id}`, { method: "DELETE" });
    },

    adjustCredits(data: Record<string, unknown>): Promise<void> {
      return request("/api/v2/admin/credits/adjust", {
        method: "POST",
        body: JSON.stringify(data),
      });
    },

    getTransactions(params?: QueryParams): Promise<PaginatedResponse<CreditTransaction>> {
      return request("/api/v2/admin/credits/transactions", { params });
    },

    getModels(params?: QueryParams): Promise<PaginatedResponse<ModelCatalogItem>> {
      return request("/api/v2/admin/models", { params });
    },

    updateModelVisibility(id: string, isPublic: boolean): Promise<void> {
      return request(`/api/v2/admin/models/${id}/visibility?is_public=${isPublic}`, {
        method: "PATCH",
      });
    },

    updateModel(id: string, data: Record<string, unknown>): Promise<void> {
      return request(`/api/v2/admin/models/${id}`, {
        method: "PATCH",
        body: JSON.stringify(data),
      });
    },

    getExecutions(params?: QueryParams): Promise<PaginatedResponse<ModelExecution>> {
      return request("/api/v2/admin/executions", { params });
    },

    getReportedReviews(): Promise<Review[]> {
      return request("/api/v2/admin/reviews/reported");
    },

    deleteReview(id: string): Promise<void> {
      return request(`/api/v2/admin/reviews/${id}`, { method: "DELETE" });
    },

    updateReviewVisibility(id: string, visible: boolean): Promise<void> {
      return request(`/api/v2/admin/reviews/${id}/visibility?visible=${visible}`, {
        method: "PATCH",
      });
    },

    getSettingsRegistry(): Promise<SettingsRegistryResponse> {
      return request("/api/v2/admin/settings/registry");
    },
    getSettingsValues(category?: string): Promise<SettingsValuesResponse> {
      const params = category ? { category } : undefined;
      return request("/api/v2/admin/settings/values", { params });
    },
    updateSettings(updates: Record<string, string>): Promise<SettingsUpdateResponse> {
      return request("/api/v2/admin/settings/values", {
        method: "PUT",
        body: JSON.stringify({ updates }),
      });
    },
    resetSetting(key: string): Promise<{ value: string; env_default: string | null }> {
      return request(`/api/v2/admin/settings/reset/${key}`, { method: "POST" });
    },
    getSettingsAudit(params?: { page?: number; page_size?: number; category?: string; changed_by?: string }): Promise<SettingsAuditLogResponse> {
      return request("/api/v2/admin/settings/audit", { params });
    },
    getPlanTiers(): Promise<PlanTiersResponse> {
      return request("/api/v2/admin/settings/plans");
    },
    updatePlanTiers(plans: Record<string, Record<string, string>>): Promise<PlanTiersResponse> {
      return request("/api/v2/admin/settings/plans", {
        method: "PUT",
        body: JSON.stringify({ plans }),
      });
    },
  },
};
