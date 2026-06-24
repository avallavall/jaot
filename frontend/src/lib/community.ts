// Community feature helpers: Discourse forum status + feedback links

export const FEEDBACK_URL =
  "https://github.com/avallavall/jaot/issues/new/choose";

export interface CommunityStatus {
  discourse_enabled: boolean;
  discourse_url: string | null;
}

const DEFAULT_STATUS: CommunityStatus = {
  discourse_enabled: false,
  discourse_url: null,
};

const BASE_URL =
  typeof window !== "undefined"
    ? (process.env.NEXT_PUBLIC_API_URL ?? window.location.origin)
    : "http://localhost:8001";

// Fetch community status from backend
export async function fetchCommunityStatus(): Promise<CommunityStatus> {
  try {
    const resp = await fetch(`${BASE_URL}/api/v2/community/status`);
    if (!resp.ok) {
      return DEFAULT_STATUS;
    }
    return await resp.json();
  } catch {
    return DEFAULT_STATUS;
  }
}
