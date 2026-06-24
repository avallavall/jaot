export const CONSENT_KEY = "jaot_cookie_consent";

export interface ConsentState {
  essential: true;
  analytics: boolean;
  timestamp: string;
}

export function getConsent(): ConsentState | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(CONSENT_KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    // Type guard: validate shape
    if (
      typeof parsed === "object" &&
      parsed !== null &&
      "essential" in parsed &&
      (parsed as Record<string, unknown>).essential === true &&
      "analytics" in parsed &&
      typeof (parsed as Record<string, unknown>).analytics === "boolean" &&
      "timestamp" in parsed &&
      typeof (parsed as Record<string, unknown>).timestamp === "string"
    ) {
      return parsed as ConsentState;
    }
    return null;
  } catch {
    return null;
  }
}

export function setConsent(analytics: boolean): void {
  const state: ConsentState = {
    essential: true,
    analytics,
    timestamp: new Date().toISOString(),
  };
  localStorage.setItem(CONSENT_KEY, JSON.stringify(state));
}

export function clearConsent(): void {
  localStorage.removeItem(CONSENT_KEY);
}
