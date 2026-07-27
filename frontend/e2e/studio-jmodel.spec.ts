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

// The flat lowering of the pick-2 knapsack (VALID_JMODEL): a binary family x_{a,b,c}
// with a weighted objective and a single cardinality constraint. Built in another lens
// so B2's de-grounder has an indexed structure to recover back into a compact JModel.
const FLAT_FAMILY_MODEL = {
  variables: [
    { name: "x_a", type: "binary", lower_bound: 0, upper_bound: 1 },
    { name: "x_b", type: "binary", lower_bound: 0, upper_bound: 1 },
    { name: "x_c", type: "binary", lower_bound: 0, upper_bound: 1 },
  ],
  objective: { sense: "maximize", expression: "2*x_a + 3*x_b + 4*x_c" },
  constraints: [{ name: "pick_two", expression: "x_a + x_b + x_c <= 2" }],
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
    // Pre-seed cookie consent (same pattern as feature-showcase): the fixed
    // bottom banner otherwise intercepts clicks on bottom-of-page controls
    // (the scenarios table's lower rows).
    await page.addInitScript(() => {
      window.localStorage.setItem(
        "jaot_cookie_consent",
        JSON.stringify({
          essential: true,
          analytics: false,
          timestamp: "2026-06-26T00:00:00.000Z",
        }),
      );
    });
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

    // S2b: the table view edits the SAME text — change the scalar and see it
    // round-trip back into the raw JSON.
    await page.getByTestId("studio-dataset-view-table").click();
    await expect(page.getByTestId("studio-dataset-table")).toBeVisible({ timeout: NAV });
    await page.getByTestId("studio-dataset-table-scalar").fill("25");
    await page.getByTestId("studio-dataset-view-json").click();
    await expect(page.getByTestId("studio-dataset-json")).toHaveValue(/"cap": 25/, {
      timeout: NAV,
    });

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

    // "Use" APPLIES immediately (provider-level recompile): going straight to
    // Solve — without ever visiting the JModel lens — must enable the normal
    // Resolver, not just "Solve all" (owner's 2026-07-03 report: the canonical
    // model stayed empty and only the Scenarios section could solve).
    await page.getByTestId("studio-tab-solve").click();
    await expect(page.getByTestId("studio-solve-run")).toBeEnabled({ timeout: NAV });
    await expect(headerSolve).toBeEnabled();

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

  // Scenarios need a JModel SOURCE (a flat/imported model is already grounded):
  // without one, "Run all" must not sit mutely disabled — the section explains why
  // and links to the JModel lens (owner live-testing 2026-07-04).
  test("scenarios: without a JModel source the section explains why Run-all is off", async ({
    page,
  }) => {
    await setDslFlag("true");
    const projectId = await createBlankProject(page);

    // A dataset exists, but the project never got a JModel formulation.
    await page.goto(`/studio/${projectId}/data`);
    await page.getByTestId("studio-dataset-new").click();
    await page.getByTestId("studio-dataset-name").fill("Loose data");
    await page.getByTestId("studio-dataset-json").fill('{ "sets": { "I": ["a"] } }');
    await page.getByTestId("studio-dataset-save").click();
    await expect(page.getByTestId("studio-dataset-row")).toHaveCount(1, { timeout: NAV });

    await page.getByTestId("studio-tab-solve").click();
    await expect(page.getByTestId("studio-scenarios-needs-jmodel")).toBeVisible({
      timeout: NAV,
    });
    await page.getByTestId("studio-scenario-check").first().check();
    await expect(page.getByTestId("studio-scenarios-run-all")).toBeDisabled();

    // The CTA lands on the JModel lens, where the missing formulation is written.
    await page.getByTestId("studio-scenarios-open-jmodel").click();
    await expect(page.getByTestId("studio-jmodel-textarea")).toBeVisible({ timeout: NAV });
  });

  // S6 (tuple sets): a declaration-only TUPLE-set model — the miniature of the TFM
  // MDPDP bridge — fills from a dataset whose members use the composite "a,b"
  // encoding, applies via "Use" and solves straight from the Solve tab.
  test("scenarios: a tuple-set model (dimen 2) fills from composite members and solves", async ({
    page,
  }) => {
    await setDslFlag("true");
    const projectId = await createBlankProject(page);
    await page.goto(`/studio/${projectId}/build?lens=jmodel`);

    const textarea = page.getByTestId("studio-jmodel-textarea");
    await expect(textarea).toBeVisible({ timeout: NAV });
    const headerSolve = page.getByTestId("studio-header-solve");

    // Sparse arc model: cheapest way to reach c is the b->c arc (w = 2).
    await textarea.fill(`set ARCS dimen 2;
param w{ARCS};
var use{ARCS} binary;
minimize total: sum{(i, j) in ARCS} w[i, j] * use[i, j];
subject to reach_c: sum{(i, j) in ARCS : j == c} use[i, j] >= 1;`);
    await expect(page.getByTestId("studio-jmodel-error")).toBeVisible({ timeout: NAV });
    await expect(headerSolve).toBeDisabled();

    await page.getByTestId("studio-tab-data").click();
    await page.getByTestId("studio-dataset-new").click();
    await page.getByTestId("studio-dataset-name").fill("Sparse arcs");
    await page.getByTestId("studio-dataset-json").fill(
      JSON.stringify(
        {
          sets: { ARCS: ["a,b", "b,c", "a,c"] },
          params: { w: { "a,b": 1, "b,c": 2, "a,c": 4 } },
        },
        null,
        2,
      ),
    );
    await page.getByTestId("studio-dataset-save").click();
    await expect(page.getByTestId("studio-dataset-row")).toHaveCount(1, { timeout: NAV });
    await page.getByTestId("studio-dataset-use").click();

    // "Use" applies the compiled tuple model everywhere: straight to Solve.
    await page.getByTestId("studio-tab-solve").click();
    await expect(page.getByTestId("studio-solve-dataset-chip")).toContainText("Sparse arcs", {
      timeout: NAV,
    });
    const runBtn = page.getByTestId("studio-solve-run");
    await expect(runBtn).toBeEnabled({ timeout: NAV });
    await runBtn.click();
    await expect(page.getByTestId("studio-solve-done")).toBeVisible({ timeout: 40_000 });
    // (Optimum 2 through the real solver is pinned by the compiler unit tests;
    // here we prove the tuple encoding travels the full UI/API path.)
  });

  // S3: run the model against N datasets in one click; the comparison table is
  // server-derived (latest run per dataset), a dataset that does not fill the model
  // becomes a failed row with the compiler message, and 2 completed selections diff
  // their solutions variable by variable.
  test("scenarios compare: run all datasets, failed row for a non-filling one, solution diff", async ({
    page,
  }) => {
    test.setTimeout(180_000);
    await setDslFlag("true");
    const projectId = await createBlankProject(page);
    await page.goto(`/studio/${projectId}/build?lens=jmodel`);

    const textarea = page.getByTestId("studio-jmodel-textarea");
    await expect(textarea).toBeVisible({ timeout: NAV });
    await textarea.fill(DECL_JMODEL);
    await expect(page.getByTestId("studio-jmodel-error")).toBeVisible({ timeout: NAV });

    // Three datasets: two that fill the model with different data, one that doesn't.
    // S5: while typing, the editor shows live guidance against the model's
    // declarations — "✓ fills" for a good one, the offending name for a bad one.
    const createDataset = async (name: string, json: string, expectCheckText?: string) => {
      await page.getByTestId("studio-dataset-new").click();
      await page.getByTestId("studio-dataset-name").fill(name);
      await page.getByTestId("studio-dataset-json").fill(json);
      if (expectCheckText) {
        await expect(page.getByTestId("studio-dataset-check")).toContainText(
          expectCheckText,
          { timeout: NAV },
        );
      }
      await page.getByTestId("studio-dataset-save").click();
      await expect(
        page.getByTestId("studio-dataset-row").filter({ hasText: name }),
      ).toHaveCount(1, { timeout: NAV });
    };
    await page.getByTestId("studio-tab-data").click();
    await createDataset("Base", DATASET_JSON, "✓"); // optimum 7 (picks b+c)
    await createDataset(
      "Alta",
      JSON.stringify(
        { sets: { I: ["a", "b", "c"] }, params: { w: { a: 10, b: 1, c: 1 } } },
        null,
        2,
      ),
    ); // optimum 11 (picks a + one of b/c)
    await createDataset(
      "Rota",
      JSON.stringify(
        { sets: { I: ["a", "b", "c"] }, params: { peso: { a: 1, b: 1, c: 1 } } },
        null,
        2,
      ),
      "peso", // S5 live guidance names the undeclared param before saving
    ); // unknown param -> compile error row, never a crash

    // Solve tab: the Scenarios section lists the datasets; run all three.
    await page.getByTestId("studio-tab-solve").click();
    await expect(page.getByTestId("studio-scenarios")).toBeVisible({ timeout: NAV });
    const checks = page.getByTestId("studio-scenario-check");
    await expect(checks).toHaveCount(3, { timeout: NAV });
    for (let i = 0; i < 3; i++) await checks.nth(i).check();
    await page.getByTestId("studio-scenarios-run-all").click();

    // The non-filling dataset fails at compile with the structured message...
    await expect(page.getByTestId("studio-scenario-failed")).toBeVisible({ timeout: NAV });
    await expect(page.getByTestId("studio-scenario-failed")).toContainText("peso");
    // ...and the two real runs complete with their objectives (server-derived rows).
    const objectives = page.getByTestId("studio-scenario-objective");
    await expect(objectives.filter({ hasText: "7" })).toHaveCount(1, { timeout: 60_000 });
    await expect(objectives.filter({ hasText: "11" })).toHaveCount(1, { timeout: 60_000 });

    // Exactly two completed selections -> solution diff (x_a differs: 0 vs 1).
    await checks.nth(2).uncheck();
    await page.getByTestId("studio-scenarios-compare").click();
    await expect(page.getByTestId("studio-scenarios-diff")).toBeVisible({ timeout: NAV });
    await expect(page.getByTestId("studio-scenarios-diff")).toContainText("x_a");
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

  // The drift-on-reload footgun: a reload loses `lastSource`, so the rehydrated source
  // used to come back EDITABLE — one keystroke could silently clobber a model last
  // edited from another lens. The rehydrated source now locks read-only (maybe-stale)
  // until the explicit recompile proves — or deliberately replaces — the current model.
  test("reload locks the rehydrated source read-only until explicitly recompiled", async ({
    page,
  }) => {
    await setDslFlag("true");
    const projectId = await createBlankProject(page);
    await page.goto(`/studio/${projectId}/build?lens=jmodel`);

    const textarea = page.getByTestId("studio-jmodel-textarea");
    await expect(textarea).toBeVisible({ timeout: NAV });
    await textarea.fill(VALID_JMODEL);
    await expect(page.getByTestId("studio-jmodel-error")).toHaveCount(0, { timeout: NAV });
    await expect(page.getByTestId("studio-saved")).toBeVisible({ timeout: NAV });

    // Typing autosaves TWICE: first the source (model still empty), then — once the
    // debounced compile returns — the compiled model. The first "Saved" is the source
    // one, so reloading on it rehydrates a project with NO model, and the lock
    // deliberately does not arm (with no model, no keystroke can clobber anything).
    // What this test needs is the PERSISTED state — a draft that carries the
    // compiled model — so it polls for that rather than listening for the save.
    //
    // Watching the traffic made it a race the test could only lose: whether the
    // model is written by a second autosave or by the first depends on the
    // debounce beating the compile round-trip, and on a fast machine the compile
    // wins, there is exactly ONE save, and a listener registered after it waits
    // forever for a second one that is never coming.
    await expect
      .poll(
        async () => {
          const res = await page.request.get(`/api/v2/projects/${projectId}`);
          if (!res.ok()) return 0;
          const project = (await res.json()) as {
            draft_model_json?: { variables?: unknown[] } | null;
          };
          return project.draft_model_json?.variables?.length ?? 0;
        },
        {
          timeout: NAV,
          message: "the compiled model never reached the saved draft",
        }
      )
      .toBeGreaterThan(0);

    // A real reload: model + source rehydrate with their sync state unknowable.
    await page.reload();
    await expect(textarea).toBeVisible({ timeout: NAV });
    await expect(textarea).toHaveJSProperty("readOnly", true);
    await expect(page.getByTestId("studio-jmodel-recompile")).toBeVisible({ timeout: NAV });
    // ...locked as a RELOAD, not as "changed elsewhere". Pinning the wording matters:
    // this test used to pass off a phantom canvas drift (a bug) that locked the lens
    // for the wrong reason and said something untrue while doing it.
    await expect(page.getByText(/page was reloaded/i)).toBeVisible();

    // The explicit recompile applies the source (here: identical model) → lock ends.
    await page.getByTestId("studio-jmodel-recompile").click();
    await expect(page.getByTestId("studio-jmodel-recompile")).toHaveCount(0, {
      timeout: NAV,
    });
    await expect(textarea).toHaveJSProperty("readOnly", false);
    await expect(page.getByTestId("studio-jmodel-error")).toHaveCount(0);
  });

  // B1 — the split-pane renders the source as symbolic math (KaTeX) and the Σ toggle
  // collapses it back to a plain editor.
  test("B1: math split-pane renders the notation and the Σ toggle collapses it", async ({
    page,
  }) => {
    await setDslFlag("true");
    const projectId = await createBlankProject(page);
    await page.goto(`/studio/${projectId}/build?lens=jmodel`);

    const textarea = page.getByTestId("studio-jmodel-textarea");
    await expect(textarea).toBeVisible({ timeout: NAV });
    await textarea.fill(VALID_JMODEL);
    await expect(page.getByTestId("studio-jmodel-error")).toHaveCount(0, { timeout: NAV });

    // The math pane is on by default and typesets the parsed model (KaTeX emits .katex).
    const mathPane = page.getByTestId("studio-jmodel-math");
    await expect(mathPane).toBeVisible({ timeout: NAV });
    await expect(mathPane.locator(".katex").first()).toBeVisible({ timeout: NAV });

    // The Σ toggle collapses the pane back to a plain editor, and restores it.
    await page.getByTestId("studio-jmodel-math-toggle").click();
    await expect(page.getByTestId("studio-jmodel-math")).toHaveCount(0);
    await page.getByTestId("studio-jmodel-math-toggle").click();
    await expect(page.getByTestId("studio-jmodel-math")).toBeVisible({ timeout: NAV });
  });

  // B2 — a model built in another lens (no JModel source) can be de-grounded back into a
  // compact JModel draft that compiles. FLAT_FAMILY_MODEL is the flat lowering of the
  // pick-2 knapsack, so the de-grounder recovers the family + sum objective/constraint.
  test("B2: derive a compiling JModel draft from a flat model built elsewhere", async ({
    page,
  }) => {
    await setDslFlag("true");
    const projectId = await createBlankProject(page);
    await page.goto(`/studio/${projectId}/build?lens=jmodel`);
    await expect(page.getByTestId("studio-jmodel-textarea")).toBeVisible({ timeout: NAV });

    // Build the model in the JSON lens (deterministic) — the JModel source stays empty.
    await page.getByTestId("studio-sublens-editor").click();
    const editor = page.getByTestId("studio-editor-textarea");
    await expect(editor).toBeVisible({ timeout: NAV });
    await editor.fill(JSON.stringify(FLAT_FAMILY_MODEL, null, 2));
    await expect(page.getByTestId("studio-editor-error")).toHaveCount(0, { timeout: NAV });

    // Back on JModel: empty source + a model that exists ⇒ "Derive draft" is offered.
    await page.getByTestId("studio-sublens-jmodel").click();
    const derive = page.getByTestId("studio-jmodel-derive");
    await expect(derive).toBeVisible({ timeout: NAV });
    await derive.click();

    // The draft lands in the editor, compiles (no error), and is not a decline. The
    // de-grounder may recover a `sum{}` family OR a compact scalar model (its honest
    // choice for a small model) — either is a valid derive; here we assert the flow
    // succeeded (objective recovered + compiles), the family specifics being unit-tested.
    const textarea = page.getByTestId("studio-jmodel-textarea");
    await expect(textarea).toHaveValue(/maximize obj/, { timeout: NAV });
    await expect(page.getByTestId("studio-jmodel-derive-declined")).toHaveCount(0);
    await expect(page.getByTestId("studio-jmodel-error")).toHaveCount(0, { timeout: NAV });
  });

  // B3 — "Generate with AI" opens the dialog and guards an empty request. The full
  // generate→compile→apply path is NOT driven here: it would call the real model
  // server-side, and integration_proof §1 forbids mocking the JAOT /dsl/generate
  // boundary. That path is covered by the backend endpoint tests (real DB, faked
  // Anthropic client) + the JModelGenerateDialog unit test.
  test("B3: generate-with-AI dialog opens and guards input", async ({ page }) => {
    await setDslFlag("true");
    const projectId = await createBlankProject(page);
    await page.goto(`/studio/${projectId}/build?lens=jmodel`);
    await expect(page.getByTestId("studio-jmodel-textarea")).toBeVisible({ timeout: NAV });

    await page.getByTestId("studio-jmodel-generate-open").click();
    await expect(page.getByTestId("studio-jmodel-generate-dialog")).toBeVisible({ timeout: NAV });

    // Empty request is guarded — submit is disabled until there is a description.
    const submit = page.getByTestId("studio-jmodel-generate-submit");
    await expect(submit).toBeDisabled();
    await page.getByTestId("studio-jmodel-generate-description").fill("pick the two best items");
    await expect(submit).toBeEnabled();

    // Escape closes the dialog (no submit — see the note above).
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("studio-jmodel-generate-dialog")).toHaveCount(0, { timeout: NAV });
  });

  /**
   * B3 vision — the browser half of "screenshot a formulation, get a JModel".
   *
   * The backend half is already covered by unit tests (tests/api/test_dsl_api.py
   * forwards the vision attachment and rejects unknown media types). What had no
   * coverage at all was the part only a real browser can exercise: picking a file
   * through the OS input, reading it into RAW base64 (no `data:` prefix — the API
   * wants bytes), enforcing the type/size/count guards, and shipping it in the
   * request. That path was only ever verified by hand.
   *
   * Nothing is mocked here. The request goes to the real backend, and when the
   * server has a key it really does reach Claude with the image — meaning this
   * test SPENDS LLM BUDGET on every run (one generation, small images). That is
   * deliberate: a vision test that never sends an image proves nothing. E2E is
   * not in CI, so the cost is bounded by how often it is run by hand.
   *
   * Because the answer therefore depends on the server's key and budget, the
   * assertions split: the outgoing payload is pinned exactly, and the outcome is
   * only required to be one of the two REAL ones — a source loaded, or a visible
   * error the user can act on. A blank dialog that silently ate the click fails
   * either way.
   */
  test("B3 vision: an attached image is validated, listed and sent as raw base64", async ({
    page,
  }) => {
    await setDslFlag("true");
    const projectId = await createBlankProject(page);
    await page.goto(`/studio/${projectId}/build?lens=jmodel`);
    await expect(page.getByTestId("studio-jmodel-textarea")).toBeVisible({ timeout: NAV });

    await page.getByTestId("studio-jmodel-generate-open").click();
    await expect(page.getByTestId("studio-jmodel-generate-dialog")).toBeVisible({ timeout: NAV });

    const fileInput = page.locator('input[type="file"]');
    const items = page.getByTestId("studio-jmodel-generate-attachment");
    const error = page.getByTestId("studio-jmodel-generate-error");
    const attachButton = page.getByTestId("studio-jmodel-generate-attach");
    const submit = page.getByTestId("studio-jmodel-generate-submit");

    // A 1x1 PNG — real bytes with a real signature, so the base64 assertion below
    // proves an actual file round-tripped rather than a string we invented.
    const png = Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
      "base64",
    );

    await fileInput.setInputFiles({ name: "formulation.png", mimeType: "image/png", buffer: png });
    await expect(items).toHaveCount(1);
    await expect(items.first()).toContainText("formulation.png");

    // An attachment ALONE must be enough to submit: a screenshot of a formulation
    // is a complete request, not a decoration on a description.
    await expect(submit).toBeEnabled();

    // A type Claude cannot read is refused in the browser, not discovered by the API.
    await fileInput.setInputFiles({
      name: "notes.txt",
      mimeType: "text/plain",
      buffer: Buffer.from("min cost subject to demand"),
    });
    await expect(error).toBeVisible();
    await expect(items).toHaveCount(1);

    // Over the per-file ceiling: right media type, wrong size.
    await fileInput.setInputFiles({
      name: "huge.png",
      mimeType: "image/png",
      buffer: Buffer.concat([png, Buffer.alloc(6 * 1024 * 1024)]),
    });
    await expect(error).toBeVisible();
    await expect(items).toHaveCount(1);

    // Fill to the cap. The button disables itself at the limit...
    await fileInput.setInputFiles(
      ["b", "c", "d"].map((n) => ({ name: `page-${n}.png`, mimeType: "image/png", buffer: png })),
    );
    await expect(items).toHaveCount(4);
    await expect(attachButton).toBeDisabled();

    // ...and removing one lets you attach again.
    await items.first().getByRole("button").click();
    await expect(items).toHaveCount(3);
    await expect(attachButton).toBeEnabled();

    // The payload: raw base64 of the real bytes, with the media type the picker saw.
    const outgoing = page.waitForRequest(
      (r) => r.url().includes("/dsl/generate") && r.method() === "POST",
      { timeout: NAV },
    );

    await page.getByTestId("studio-jmodel-generate-description").fill("read the attached model");
    await submit.click();

    const body = JSON.parse((await outgoing).postData() ?? "{}");
    expect(body.attachments).toHaveLength(3);
    for (const att of body.attachments) {
      expect(att.media_type).toBe("image/png");
      // Raw bytes only — a leaked "data:image/png;base64," prefix would be sent
      // verbatim to Claude and rejected there, far from where it was introduced.
      expect(att.data.startsWith("data:")).toBe(false);
      expect(Buffer.from(att.data, "base64").subarray(0, 8)).toEqual(png.subarray(0, 8));
    }

    // Either real outcome is acceptable; silence is not.
    const dialog = page.getByTestId("studio-jmodel-generate-dialog");
    await expect
      .poll(async () => (await error.count()) > 0 || (await dialog.count()) === 0, {
        timeout: 120_000,
      })
      .toBe(true);
  });
});
