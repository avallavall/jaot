
export interface FeatureAnalyticsKPI {
  total_events: number;
  active_users: number;
  events_today: number;
  top_event_type: string | null;
  top_event_count: number;
  period: string;
  prev_total_events?: number | null;
  prev_active_users?: number | null;
  prev_events_today?: number | null;
}

export interface TimeSeriesEntry {
  date: string;
  count: number;
  event_type?: string;
}

export interface EventBreakdownEntry {
  event_type: string;
  count: number;
  prev_count?: number | null;
}

export interface DomainSummaryEntry {
  domain: string;
  count: number;
}

export interface FunnelStep {
  name: string;
  value: number;
  fill: string;
  prev_value?: number | null;
}

export interface RecentEvent {
  id: string;
  event_type: string;
  user_id: string;
  country_code?: string;
  created_at: string;
  metadata?: Record<string, unknown>;
}

export interface CountryEntry {
  country_code: string;
  count: number;
}

export interface GroupedTimeSeriesEntry {
  date: string;
  series: Record<string, number>;
}

export interface FeatureAnalyticsOverview {
  kpi: FeatureAnalyticsKPI;
  time_series: {
    data: TimeSeriesEntry[];
    period: string;
  };
  event_breakdown: EventBreakdownEntry[];
  domain_summary: DomainSummaryEntry[];
  funnel: {
    steps: FunnelStep[];
  };
  country_distribution: CountryEntry[];
  grouped_time_series?: GroupedTimeSeriesEntry[] | null;
}

export interface PaginatedRecentEvents {
  items: RecentEvent[];
  total: number;
  page: number;
  page_size: number;
}

export interface AnalyticsFilters {
  eventType: string | null;
  countryCode: string | null;
  domain: string | null;
  compare: boolean;
}

export type Period = "1h" | "12h" | "today" | "7d" | "30d" | "90d" | "all";

export interface SortConfig {
  field: string;
  direction: "asc" | "desc";
}

export type TimeSeriesMode = "aggregate" | "domain" | "event_type";
