import { expect, type Page } from "@playwright/test";

/**
 * Seed a builder document via the real backend.
 *
 * Why: 3 specs (breadcrumbs, cron, attachments) need a fresh document to navigate
 * to or attach versions/triggers to. Hand-rolled POST + .ok() checks drifted across
 * them — some used relative URL, some used `${BASE_URL}` prefix.
 */
export async function seedBuilderDocument(
  page: Page,
  name: string
): Promise<{ id: string }> {
  const resp = await page.request.post("/api/v2/builder/", { data: { name } });
  await expect(resp, `seedBuilderDocument failed: ${resp.status()}`).toBeOK();
  return (await resp.json()) as { id: string };
}

/**
 * Best-effort teardown of a builder document. Errors are swallowed since
 * jaot_test is reset between CI runs and a failed delete is not a test failure.
 */
export async function deleteBuilderDocument(page: Page, id: string): Promise<void> {
  await page.request.delete(`/api/v2/builder/${id}`).catch(() => {});
}
