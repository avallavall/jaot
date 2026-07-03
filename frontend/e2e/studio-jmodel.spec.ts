import { test, expect, request, type Page } from "@playwright/test";
import { interceptGuidanceApi } from "./helpers/dismiss-wizard";

/**
 * Studio JModel (DSL) lens E2E (P5). The feature ships DARK behind the JAOT_DSL
 * platform flag, so this spec drives the flag itself via a throwaway admin API
 * context (the regular `page` session is a non-admin user), then asserts:
 *   - gating: flag OFF → the JModel sub-lens is hidden and ?lens=jmodel falls back;
 *   - flow: flag ON → a valid source compiles, a broken source blocks solve, and a
 *     valid model solves through the Solve tab.
 * The flag is restored to OFF in afterAll so it never leaks into other specs.
 */

const NAV = 20_000;
const BASE = process.env.BASE_URL || "http://localhost:3000";
const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL || "admin@jaot.io";
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD || "AdminPass123!";

// pick 2 of {a:2, b:3, c:4} to maximize → c + b = 7.
const VALID_JMODEL = `set I := {a, b, c};
param w{I} := a 2, b 3, c 4;
var x{I} binary;
maximize obj: sum{i in I} w[i] * x[i];
subject to pick_two: sum{i in I} x[i] <= 2;`;

// §8 Scenarios: the same pick-2 knapsack, but declaration-only — the sets/params
// carry NO inline values; a named dataset must fill them at compile time.
const DECL_JMODEL = `set I;
param w{I};
var x{I} binary;
maximize obj: sum{i in I} w[i] * x[i];
subject to pick_two: sum{i in I} x[i] <= 2;`;

// NOTE: the params must exactly match the model's declarations — a dataset symbol
// the model does not declare is a compile error by design (typo safety).
const DATASET_JSON = JSON.stringify(
  { sets: { I: ["a", "b", "c"] }, params: { w: { a: 2, b: 3, c: 4 } } },
  null,
  2
);

// A small valid model used to drift the canonical model AWAY from the DSL source
// (applied through the JSON editor lens — deterministic, unlike canvas drag-drop).
const DRIFT_MODEL = {
  variables: [{ name: "z", type: "continuous", lower_bound: 0, upper_bound: 5 }],
  objective: { sense: "minimize", expression: "z" },
  constraints: [{ name: "c1", expression: "z >= 1" }],
};

async function setDslFlag(value: "true" | "false"): Promise<void> {
  const ctx = await request.newContext({ baseURL: BASE });
  try {
    const login = await ctx.post("/api/v2/auth/login/email", {
      data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
    });
    expect(login.ok(), `admin login failed: ${login.status()}`).toBeTruthy();
    const resp = await ctx.put("/api/v2/admin/settings/values", {
      data: { updates: { JAOT_DSL: value } },
    });
    expect(resp.ok(), `set JAOT_DSL=${value} failed: ${resp.status()}`).toBeTruthy();
  } finally {
    await ctx.dispose();
  }
}

/** Read the current JAOT_DSL flag so afterAll can restore it (the owner may run local
 *  with it ON to test — this spec must not silently turn it off for them). */
async function readDslFlag(): Promise<"true" | "false"> {
  const ctx = await request.newContext({ baseURL: BASE });
  try {
    const login = await ctx.post("/api/v2/auth/login/email", {
      data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
    });
    expect(login.ok(), `admin login failed: ${login.status()}`).toBeTruthy();
    const resp = await ctx.get("/api/v2/dsl/status");
    expect(resp.ok(), `read JAOT_DSL failed: ${resp.status()}`).toBeTruthy();
    return (await resp.json()).enabled ? "true" : "false";
  } finally {
    await ctx.dispose();
  }
}

async function createBlankProject(page: Page): Promise<string> {
  await page.goto("/studio/new");
  const blank = page.getByTestId("launcher-tile-blank");
  await expect(blank).toBeVisible({ timeout: NAV });
  await blank.click();
  await page.waitForURL(/\/studio\/(mp_[A-Za-z0-9]+)\/build/, { timeout: NAV });
  const match = page.url().match(/\/studio\/(mp_[A-Za-z0-9]+)\//);
  if (!match) throw new Error(`No project id in URL: ${page.url()}`);
  return match[1];
}

test.describe("Studio — JModel DSL lens (P5, gated by JAOT_DSL)", () => {
  let priorDslFlag: "true" | "false" = "false";

  test.beforeAll(async () => {
    priorDslFlag = await readDslFlag();
  });

  test.beforeEach(async ({ page }) => {
    await interceptGuidanceApi(page);
  });

  test.afterAll(async () => {
    // Restore whatever the flag was before the suite ran (do not clobber the owner's ON).
    await setDslFlag(priorDslFlag);
  });

  test("gating: flag OFF hides the lens and ?lens=jmodel falls back to canvas", async ({
    page,
  }) => {
    await setDslFlag("false");
    const projectId = await createBlankProject(page);
    await page.goto(`/studio/${projectId}/build?lens=jmodel`);

    // The workspace renders (canvas sub-lens present)...
    await expect(page.getByTestId("studio-sublens-canvas")).toBeVisible({ timeout: NAV });
    // ...but the JModel tab is not offered and the deep-link shows no JModel editor.
    await expect(page.getByTestId("studio-sublens-jmodel")).toHaveCount(0);
    await expect(page.getByTestId("studio-jmodel-textarea")).toHaveCount(0);
    // S4: the Datos tab shares the same gate — hidden while the flag is off.
    await expect(page.getByTestId("studio-tab-data")).toHaveCount(0);
  });

  test("flag ON: valid source compiles, broken blocks solve, valid model solves", async ({
    page,
  }) => {
    await setDslFlag("true");
    const projectId = await createBlankProject(page);
    await page.goto(`/studio/${projectId}/build?lens=jmodel`);

    const textarea = page.getByTestId("studio-jmodel-textarea");
    await expect(textarea).toBeVisible({ timeout: NAV });
    const headerSolve = page.getByTestId("studio-header-solve");

    // Valid JModel → compiles (no error) and solve is enabled.
    await textarea.fill(VALID_JMODEL);
    await expect(page.getByTestId("studio-jmodel-error")).toHaveCount(0, { timeout: NAV });
    await expect(headerSolve).toBeEnabled({ timeout: NAV });

    // Broken source → inline error and solve blocked.
    await textarea.fill("set I := {a, b}\nvar x{I} binary;");
    await expect(page.getByTestId("studio-jmodel-error")).toBeVisible({ timeout: NAV });
    await expect(headerSolve).toBeDisabled();

    // The block SURVIVES leaving the lens (client-side tab nav): the Solve tab's run
    // button is blocked too — the old unmount cleanup cleared the flag and silently
    // solved the previous good model. Coming back re-derives the compile error from
    // the persisted source, so the block stays explained.
    await page.getByTestId("studio-tab-solve").click();
    await expect(page.getByTestId("studio-solve-run")).toBeDisabled();
    await page.getByTestId("studio-tab-build").click();
    await page.getByTestId("studio-sublens-jmodel").click();
    await expect(page.getByTestId("studio-jmodel-error")).toBeVisible({ timeout: NAV });
    await expect(headerSolve).toBeDisabled();

    // Fixing it clears the block, and the compiled model solves on the Solve tab.
    await textarea.fill(VALID_JMODEL);
    await expect(page.getByTestId("studio-jmodel-error")).toHaveCount(0, { timeout: NAV });
    await expect(headerSolve).toBeEnabled({ timeout: NAV });

    // Wait until the compiled model is autosaved (as a user does — they see "Saved"
    // before moving on). The compile is async and the draft autosaves 800ms after it;
    // switching tabs before that would race the persist. This is the ONE realistic wait
    // that keeps the client-side tab nav deterministic (a human never switches in the
    // ~600ms window the test otherwise hit).
    await expect(page.getByTestId("studio-saved")).toBeVisible({ timeout: NAV });

    // Client-side tab nav (NOT a reload) so the in-memory compiled model survives.
    await page.getByTestId("studio-tab-solve").click();
    const runBtn = page.getByTestId("studio-solve-run");
    await expect(runBtn).toBeEnabled({ timeout: NAV });
    await runBtn.click();
    await expect(page.getByTestId("studio-solve-done")).toBeVisible({ timeout: 40_000 });
    // (The compiled model's optimum = 7 is asserted by the compiler unit tests, which
    // solve it through the real SCIPAdapter; here we prove the studio path solves.)
  });

  // S2c: a .dat file imports into the dataset editor as a PREVIEW (nothing stored
  // until saved through the normal create), suggesting the filename as the name.
  test("dataset import: a .dat file pre-fills the editor and saves", async ({ page }) => {
    await setDslFlag("true");
    const projectId = await createBlankProject(page);
    await page.goto(`/studio/${projectId}/data`);

    await page.getByTestId("studio-dataset-new").click();
    await page.getByTestId("studio-dataset-import-input").setInputFiles({
      name: "q4_forecast.dat",
      mimeType: "text/plain",
      buffer: Buffer.from("set I := a b c;\nparam cap := 10;\nparam w := a 2, b 3, c 4;\n"),
    });
    await expect(page.getByTestId("studio-dataset-json")).toHaveValue(/"cap": 10/, {
      timeout: NAV,
    });
    await expect(page.getByTestId("studio-dataset-name")).toHaveValue("q4_forecast");
    await page.getByTestId("studio-dataset-save").click();
    await expect(
      page.getByTestId("studio-dataset-row").filter({ hasText: "q4_forecast" }),
    ).toHaveCount(1, { timeout: NAV });
  });

  // §8 Scenarios: a declaration-only source (`set I;` / `param w{I};`) carries no
  // data of its own — it must error without a dataset, compile against a named
  // dataset created in Analyze, solve with the chip naming which data ran, and
  // error again the moment the dataset is deselected.
  test("scenarios: declaration-only source compiles against a named dataset and solves", async ({
    page,
  }) => {
    await setDslFlag("true");
    const projectId = await createBlankProject(page);
    await page.goto(`/studio/${projectId}/build?lens=jmodel`);

    const textarea = page.getByTestId("studio-jmodel-textarea");
    await expect(textarea).toBeVisible({ timeout: NAV });
    const headerSolve = page.getByTestId("studio-header-solve");

    // Without data, the declaration-only source is a compile error and blocks solve.
    await textarea.fill(DECL_JMODEL);
    await expect(page.getByTestId("studio-jmodel-error")).toBeVisible({ timeout: NAV });
    await expect(headerSolve).toBeDisabled();

    // Create a dataset in the Datos tab (S4) and mark it as the one in use.
    await page.getByTestId("studio-tab-data").click();
    await page.getByTestId("studio-dataset-new").click();
    await page.getByTestId("studio-dataset-name").fill("Scenario A");
    // S2a: the skeleton button pre-fills the editor with the model's REAL declared
    // symbols (parse-only /dsl/inspect — works while the source doesn't compile).
    // Anchor on `"I": []` — unique to the skeleton; the dialog's starting template
    // also contains `"sets"`, so a looser match would pass before the response lands
    // and the late overwrite would clobber the DATASET_JSON filled next.
    await page.getByTestId("studio-dataset-skeleton").click();
    await expect(page.getByTestId("studio-dataset-json")).toHaveValue(/"I": \[\]/, {
      timeout: NAV,
    });
    await page.getByTestId("studio-dataset-json").fill(DATASET_JSON);
    await page.getByTestId("studio-dataset-save").click();
    await expect(page.getByTestId("studio-dataset-row")).toHaveCount(1, { timeout: NAV });
    await page.getByTestId("studio-dataset-use").click();

    // Back on JModel, the persisted error re-derives against the ACTIVE dataset → ok,
    // and the compiled model autosaves ("Saved") before the user moves on.
    await page.getByTestId("studio-tab-build").click();
    await page.getByTestId("studio-sublens-jmodel").click();
    await expect(page.getByTestId("studio-jmodel-error")).toHaveCount(0, { timeout: NAV });
    await expect(headerSolve).toBeEnabled({ timeout: NAV });
    await expect(page.getByTestId("studio-saved")).toBeVisible({ timeout: NAV });

    // Solve — the chip names the dataset the canonical model was compiled with.
    await page.getByTestId("studio-tab-solve").click();
    await expect(page.getByTestId("studio-solve-dataset-chip")).toContainText("Scenario A", {
      timeout: NAV,
    });
    const runBtn = page.getByTestId("studio-solve-run");
    await expect(runBtn).toBeEnabled({ timeout: NAV });
    await runBtn.click();
    await expect(page.getByTestId("studio-solve-done")).toBeVisible({ timeout: 40_000 });

    // Deselecting the dataset recompiles immediately → the source errors again.
    // Realistic pacing (audit lesson): a user sees the canvas render and the
    // persisted source back on screen before touching the dataset selector.
    await page.getByTestId("studio-tab-build").click();
    await expect(page.getByTestId("studio-sublens-canvas")).toBeVisible({ timeout: NAV });
    await page.getByTestId("studio-sublens-jmodel").click();
    await expect(textarea).toHaveValue(/param w/, { timeout: NAV });
    await page.getByTestId("studio-jmodel-dataset").selectOption("");
    await expect(page.getByTestId("studio-jmodel-error")).toBeVisible({ timeout: NAV });
    await expect(headerSolve).toBeDisabled();

    // §8/S1: the executions history says WHICH dataset each run was compiled
    // against — persisted server-side (name snapshot), not browser memory.
    await page.goto("/solve/executions");
    await expect(
      page
        .getByTestId("execution-dataset-badge")
        .filter({ hasText: "Scenario A" })
        .first(),
    ).toBeVisible({ timeout: NAV });
  });

  // A model edited from ANOTHER lens leaves the JModel source drifted (lowering is
  // one-way). The drifted source is NOT the applied model, so it locks read-only and
  // re-applying it must be the explicit "recompile" action — a deliberate replace of
  // the newer model, never a silent clobber from a stray keystroke.
  test("stale source locks read-only until explicitly recompiled (deliberate replace)", async ({
    page,
  }) => {
    await setDslFlag("true");
    const projectId = await createBlankProject(page);
    await page.goto(`/studio/${projectId}/build?lens=jmodel`);

    const textarea = page.getByTestId("studio-jmodel-textarea");
    await expect(textarea).toBeVisible({ timeout: NAV });
    await textarea.fill(VALID_JMODEL);
    await expect(page.getByTestId("studio-jmodel-error")).toHaveCount(0, { timeout: NAV });
    // Realistic pace: the user sees "Saved" before moving on to another lens.
    await expect(page.getByTestId("studio-saved")).toBeVisible({ timeout: NAV });

    // Edit the model from another lens (the JSON editor — deterministic, no canvas DnD).
    await page.getByTestId("studio-sublens-editor").click();
    const editor = page.getByTestId("studio-editor-textarea");
    await expect(editor).toBeVisible({ timeout: NAV });
    await editor.fill(JSON.stringify(DRIFT_MODEL, null, 2));
    await expect(page.getByTestId("studio-editor-error")).toHaveCount(0, { timeout: NAV });

    // Back on JModel: drifted source → stale notice + read-only + recompile action.
    await page.getByTestId("studio-sublens-jmodel").click();
    await expect(textarea).toBeVisible({ timeout: NAV });
    await expect(page.getByTestId("studio-jmodel-recompile")).toBeVisible({ timeout: NAV });
    await expect(textarea).toHaveJSProperty("readOnly", true);

    // The explicit recompile re-applies this source: staleness (and the lock) end.
    await page.getByTestId("studio-jmodel-recompile").click();
    await expect(page.getByTestId("studio-jmodel-recompile")).toHaveCount(0, {
      timeout: NAV,
    });
    await expect(textarea).toHaveJSProperty("readOnly", false);
    await expect(page.getByTestId("studio-jmodel-error")).toHaveCount(0);
  });
});
