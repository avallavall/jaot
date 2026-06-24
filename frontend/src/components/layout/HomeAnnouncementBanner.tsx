import { HomeAnnouncementBannerClient } from "./HomeAnnouncementBannerClient";

interface AnnouncementPayload {
  enabled: boolean;
  messages: string[];
  rotation_seconds: number;
}

const apiUrl =
  process.env.API_PROXY_URL ??
  process.env.NEXT_PUBLIC_API_URL ??
  "http://localhost:8001";

async function fetchAnnouncement(locale: string): Promise<AnnouncementPayload | null> {
  try {
    // Admin-editable content: never cache the response so toggling the banner
    // takes effect on the next page load. The endpoint is cheap (a few PSS
    // lookups) so this has no meaningful cost.
    const res = await fetch(
      `${apiUrl}/api/v2/home/announcement?locale=${encodeURIComponent(locale)}`,
      { cache: "no-store" },
    );
    if (!res.ok) return null;
    return (await res.json()) as AnnouncementPayload;
  } catch {
    return null;
  }
}

interface HomeAnnouncementBannerProps {
  locale: string;
}

export async function HomeAnnouncementBanner({ locale }: HomeAnnouncementBannerProps) {
  const data = await fetchAnnouncement(locale);
  if (!data || !data.enabled || data.messages.length === 0) {
    return null;
  }
  return (
    <HomeAnnouncementBannerClient
      messages={data.messages}
      rotationSeconds={data.rotation_seconds}
    />
  );
}
