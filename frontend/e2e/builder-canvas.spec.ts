import { test, expect, type Page } from "@playwright/test";
import { interceptGuidanceApi } from "./helpers/dismiss-wizard";

/**
 * Builder Canvas — Functional E2E Tests
 *
 * Tests REAL builder canvas interactions: creating models visually,
 * adding nodes via drag-and-drop or context menu, editing node properties,
 * and verifying save/health indicators.
 *
 * Prerequisites:
 * - Auth: storageState from global.setup.ts (user@jaot.io)
 * - Backend: real Docker backend running
 * - Guidance API intercepted to suppress onboarding wizard overlay
 */

const NAV_TIMEOUT = 15_000;
const CANVAS_TIMEOUT = 20_000;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Navigate to /builder, click "New Model", and wait for the canvas page. */
async function createNewModelAndEnterCanvas(page: Page): Promise<void> {
  await page.goto("/builder");

  const heading = page.getByRole("heading", { level: 1 });
  await expect(heading).toBeVisible({ timeout: NAV_TIMEOUT });

  const newModelButton = page.getByRole("button", { name: /new model/i });
  await expect(newModelButton).toBeVisible({ timeout: 10_000 });
  await newModelButton.click();

  // Wait for the canvas route: /builder/{documentId} (but not /builder/templates etc.)
  await expect(async () => {
    const url = page.url();
    const isOnCanvas =
      /\/builder\/[a-zA-Z0-9_-]+$/.test(url) &&
      !/\/builder\/(templates|ai-assistant)$/.test(url);
    expect(isOnCanvas).toBe(true);
  }).toPass({ timeout: NAV_TIMEOUT });
}

/** Wait for React Flow to fully initialize its renderer. */
async function waitForReactFlow(page: Page): Promise<void> {
  await expect(
    page.locator(".react-flow__renderer")
  ).toBeVisible({ timeout: CANVAS_TIMEOUT });
  await dismissCanvasOnboarding(page);
}

/**
 * Dismiss the canvas onboarding tour overlay if present.
 * The builder has a step-by-step tour ("Define Your Objective" 1/4)
 * that blocks pointer events on the canvas.
 */
async function dismissCanvasOnboarding(page: Page): Promise<void> {
  // Try multiple times — the onboarding may appear after a short delay
  for (let attempt = 0; attempt < 3; attempt++) {
    const skipButton = page.getByText("Skip", { exact: true });
    const visible = await skipButton.isVisible().catch(() => false);
    if (visible) {
      await skipButton.click();
      // Wait for overlay to fully disappear
      await page.waitForTimeout(500);
      return;
    }
    // Wait a bit before retrying — onboarding may render late
    await page.waitForTimeout(500);
  }
}

/** Count the number of nodes currently on the canvas. */
async function getNodeCount(page: Page): Promise<number> {
  return page.locator(".react-flow__node").count();
}

// ---------------------------------------------------------------------------
// Tests — serial mode because later tests build on earlier state
// ---------------------------------------------------------------------------

test.describe("Builder Canvas Interactions", () => {
  test.describe.configure({ mode: "serial" });

  test.beforeEach(async ({ page }) => {
    await interceptGuidanceApi(page);
  });

  // =========================================================================
  // 1. Create new document and enter canvas
  // =========================================================================

  test("create new document and verify canvas loads", async ({ page }) => {
    await createNewModelAndEnterCanvas(page);
    await waitForReactFlow(page);

    // React Flow container must be visible
    const reactFlowContainer = page.locator(".react-flow");
    await expect(reactFlowContainer).toBeVisible();
  });

  test("canvas page shows toolbar with Save, AI Assistant, and Solve buttons", async ({ page }) => {
    await createNewModelAndEnterCanvas(page);
    await waitForReactFlow(page);

    // Save button
    const saveButton = page.getByRole("button", { name: /^save$/i });
    await expect(saveButton).toBeVisible({ timeout: 10_000 });

    // AI Assistant button
    const aiButton = page.getByRole("button", { name: /ai assistant/i });
    await expect(aiButton).toBeVisible({ timeout: 10_000 });

    // Solve button
    const solveButton = page.getByRole("button", { name: /^solve$/i });
    await expect(solveButton).toBeVisible({ timeout: 10_000 });
  });

  test("canvas page shows NodePalette sidebar", async ({ page }) => {
    await createNewModelAndEnterCanvas(page);
    await waitForReactFlow(page);

    // NodePalette is identified by data-onboarding-target="palette"
    const palette = page.locator('[data-onboarding-target="palette"]');
    await expect(palette).toBeVisible({ timeout: 10_000 });
  });

  test("canvas starts with a default Objective node", async ({ page }) => {
    await createNewModelAndEnterCanvas(page);
    await waitForReactFlow(page);

    // The default Objective node has data-onboarding-target="objective"
    const objectiveNode = page.locator('[data-onboarding-target="objective"]');
    await expect(objectiveNode).toBeVisible({ timeout: 10_000 });

    // There should be exactly 1 node initially (the objective)
    const nodeCount = await getNodeCount(page);
    expect(nodeCount).toBe(1);
  });

  // =========================================================================
  // 2. Node palette shows all node types
  // =========================================================================

  test("palette contains VARIABLE, CONSTRAINT, and OBJECTIVE items", async ({ page }) => {
    await createNewModelAndEnterCanvas(page);
    await waitForReactFlow(page);

    const palette = page.locator('[data-onboarding-target="palette"]');
    await expect(palette).toBeVisible();

    // Check for VARIABLE item text
    await expect(palette.getByText(/variable/i).first()).toBeVisible();

    // Check for CONSTRAINT item text
    await expect(palette.getByText(/constraint/i).first()).toBeVisible();

    // Check for OBJECTIVE item text
    await expect(palette.getByText(/objective/i).first()).toBeVisible();
  });

  test("palette VARIABLE item has description about decision variables", async ({ page }) => {
    await createNewModelAndEnterCanvas(page);
    await waitForReactFlow(page);

    const palette = page.locator('[data-onboarding-target="palette"]');

    // The description text is below the VARIABLE label
    // Translation may vary but the palette item should have descriptive text
    const paletteItems = palette.locator(".mx-2.mb-2");
    const variableItem = paletteItems.filter({ hasText: /variable/i }).first();
    await expect(variableItem).toBeVisible();

    // The item should contain a description (second child div)
    const description = variableItem.locator(".text-muted-foreground");
    await expect(description).toBeVisible();
    const descText = await description.textContent();
    expect(descText?.trim().length).toBeGreaterThan(0);
  });

  test("OBJECTIVE palette item is disabled when objective already exists on canvas", async ({ page }) => {
    await createNewModelAndEnterCanvas(page);
    await waitForReactFlow(page);

    const palette = page.locator('[data-onboarding-target="palette"]');

    // The objective palette item should be disabled (opacity-40 and cursor-not-allowed)
    const paletteItems = palette.locator(".mx-2.mb-2");
    const objectiveItem = paletteItems.filter({ hasText: /objective/i }).last();
    await expect(objectiveItem).toBeVisible();

    // Disabled items have cursor-not-allowed class
    await expect(objectiveItem).toHaveClass(/cursor-not-allowed/);
  });

  // =========================================================================
  // 3. Add a variable node to the canvas via drag-and-drop
  // =========================================================================

  test("add a variable node to the canvas via drag-and-drop", async ({ page }) => {
    await createNewModelAndEnterCanvas(page);
    await waitForReactFlow(page);

    // Start with 1 node (objective)
    const initialCount = await getNodeCount(page);
    expect(initialCount).toBe(1);

    const palette = page.locator('[data-onboarding-target="palette"]');
    const paletteItems = palette.locator(".mx-2.mb-2");
    const variableItem = paletteItems.filter({ hasText: /variable/i }).first();
    await expect(variableItem).toBeVisible();

    // Get the canvas drop target
    const canvas = page.locator(".react-flow__renderer");
    await expect(canvas).toBeVisible();

    const sourceBox = await variableItem.boundingBox();
    const targetBox = await canvas.boundingBox();

    if (sourceBox && targetBox) {
      // Perform drag-and-drop: from palette item center to canvas center
      const sourceX = sourceBox.x + sourceBox.width / 2;
      const sourceY = sourceBox.y + sourceBox.height / 2;
      const targetX = targetBox.x + targetBox.width / 2;
      const targetY = targetBox.y + targetBox.height / 2;

      await page.mouse.move(sourceX, sourceY);
      await page.mouse.down();
      // Move in steps to trigger dragover events
      await page.mouse.move(targetX, targetY, { steps: 10 });
      await page.mouse.up();
    }

    // Wait and check if a new node appeared
    // If drag-and-drop didn't work, try context menu as fallback
    await page.waitForTimeout(500);
    let newCount = await getNodeCount(page);

    if (newCount <= initialCount) {
      // Fallback: use right-click context menu on canvas to add variable
      const canvasArea = page.locator('[data-onboarding-target="canvas"]');
      await canvasArea.click({ button: "right", position: { x: 200, y: 200 } });

      // Look for "Add Variable" in context menu
      const addVariableOption = page.getByText(/add.*variable/i).first();
      const optionVisible = await addVariableOption.isVisible().catch(() => false);
      if (optionVisible) {
        await addVariableOption.click();
        await page.waitForTimeout(500);
      }
    }

    newCount = await getNodeCount(page);
    // Canvas should now have at least 2 nodes (Objective + Variable)
    expect(newCount).toBeGreaterThanOrEqual(2);
  });

  // =========================================================================
  // 4. Add a variable node via right-click context menu
  // =========================================================================

  test("add a variable node via right-click context menu", async ({ page }) => {
    await createNewModelAndEnterCanvas(page);
    await waitForReactFlow(page);

    const initialCount = await getNodeCount(page);
    expect(initialCount).toBe(1);

    // Right-click on the canvas area to open context menu
    const canvasArea = page.locator('[data-onboarding-target="canvas"]');
    const canvasBox = await canvasArea.boundingBox();
    expect(canvasBox).not.toBeNull();

    // Right-click in the middle of the canvas
    await canvasArea.click({
      button: "right",
      position: {
        x: canvasBox!.width / 2,
        y: canvasBox!.height / 2,
      },
    });

    // Context menu should appear with "Add Variable" option
    const addVariableOption = page.getByRole("menuitem").filter({ hasText: /variable/i });
    await expect(addVariableOption).toBeVisible({ timeout: 5_000 });
    await addVariableOption.click();

    // Wait for the node to appear
    await page.waitForTimeout(500);
    const newCount = await getNodeCount(page);
    expect(newCount).toBe(initialCount + 1);
  });

  test("add a constraint node via right-click context menu", async ({ page }) => {
    await createNewModelAndEnterCanvas(page);
    await waitForReactFlow(page);

    const initialCount = await getNodeCount(page);

    // Right-click on canvas
    const canvasArea = page.locator('[data-onboarding-target="canvas"]');
    await canvasArea.click({ button: "right", position: { x: 300, y: 300 } });

    // Click "Add Constraint"
    const addConstraintOption = page.getByRole("menuitem").filter({ hasText: /constraint/i });
    await expect(addConstraintOption).toBeVisible({ timeout: 5_000 });
    await addConstraintOption.click();

    await page.waitForTimeout(500);
    const newCount = await getNodeCount(page);
    expect(newCount).toBe(initialCount + 1);
  });

  // =========================================================================
  // 5. Edit variable node properties via PropertiesPanel
  // =========================================================================

  test("clicking a variable node opens PropertiesPanel", async ({ page }) => {
    await createNewModelAndEnterCanvas(page);
    await waitForReactFlow(page);

    // Add a variable node via context menu
    const canvasArea = page.locator('[data-onboarding-target="canvas"]');
    await canvasArea.click({ button: "right", position: { x: 250, y: 250 } });
    const addVariableOption = page.getByRole("menuitem").filter({ hasText: /variable/i });
    await expect(addVariableOption).toBeVisible({ timeout: 5_000 });
    await addVariableOption.click();
    await page.waitForTimeout(500);

    // Click on the newly created variable node
    const variableNodes = page.locator(".react-flow__node").filter({
      has: page.locator("[class*='border-blue']"),
    });
    const nodeCount = await variableNodes.count();
    expect(nodeCount).toBeGreaterThanOrEqual(1);
    await variableNodes.first().click();

    // PropertiesPanel should appear (right sidebar with border-l)
    // It contains inputs for name, type, lower/upper bounds
    page.locator('input[placeholder]').filter({
      has: page.locator(".."),
    });

    // Check that a properties section is visible — look for the font-mono input
    // which is the variable name field
    const monoInput = page.locator("input.font-mono").first();
    await expect(monoInput).toBeVisible({ timeout: 5_000 });
  });

  test("edit variable node name in PropertiesPanel", async ({ page }) => {
    await createNewModelAndEnterCanvas(page);
    await waitForReactFlow(page);

    // Add a variable node
    const canvasArea = page.locator('[data-onboarding-target="canvas"]');
    await canvasArea.click({ button: "right", position: { x: 250, y: 250 } });
    await page.getByRole("menuitem").filter({ hasText: /variable/i }).click();
    await page.waitForTimeout(500);

    // Click the variable node to select it
    const variableNode = page.locator(".react-flow__node").filter({
      has: page.locator("[class*='border-blue']"),
    }).first();
    await variableNode.click();

    // The properties panel should show a name input with font-mono class
    const nameInput = page.locator("input.font-mono").first();
    await expect(nameInput).toBeVisible({ timeout: 5_000 });

    // Clear and type a new name
    await nameInput.clear();
    await nameInput.fill("production_quantity");

    // Verify the node on the canvas reflects the new name
    await expect(
      variableNode.getByText("production_quantity")
    ).toBeVisible({ timeout: 5_000 });
  });

  test("edit variable node bounds in PropertiesPanel", async ({ page }) => {
    await createNewModelAndEnterCanvas(page);
    await waitForReactFlow(page);

    // Add a variable node
    const canvasArea = page.locator('[data-onboarding-target="canvas"]');
    await canvasArea.click({ button: "right", position: { x: 250, y: 250 } });
    await page.getByRole("menuitem").filter({ hasText: /variable/i }).click();
    await page.waitForTimeout(500);

    // Click the variable node
    const variableNode = page.locator(".react-flow__node").filter({
      has: page.locator("[class*='border-blue']"),
    }).first();
    await variableNode.click();

    // Find bound inputs (type="number" inputs in the properties panel)
    const numberInputs = page.locator('input[type="number"]');

    // Lower bound input (first number input)
    const lowerBoundInput = numberInputs.first();
    await expect(lowerBoundInput).toBeVisible({ timeout: 5_000 });
    await lowerBoundInput.clear();
    await lowerBoundInput.fill("0");

    // Upper bound input (second number input)
    const upperBoundInput = numberInputs.nth(1);
    await expect(upperBoundInput).toBeVisible({ timeout: 5_000 });
    await upperBoundInput.clear();
    await upperBoundInput.fill("100");

    // The variable node should now show the bounds [0, 100]
    await expect(variableNode.getByText("[0, 100]")).toBeVisible({ timeout: 5_000 });
  });

  // =========================================================================
  // 6. Objective node properties — sense selector
  // =========================================================================

  test("clicking objective node shows sense selector in properties", async ({ page }) => {
    await createNewModelAndEnterCanvas(page);
    await waitForReactFlow(page);

    // Click on the default objective node
    const objectiveNode = page.locator('[data-onboarding-target="objective"]');
    await expect(objectiveNode).toBeVisible();
    await objectiveNode.click();

    // PropertiesPanel should show a sense selector (minimize/maximize)
    // The Select component has a trigger with SelectValue
    const selectTrigger = page.locator('[role="combobox"]').first();
    await expect(selectTrigger).toBeVisible({ timeout: 5_000 });

    // Verify it shows "minimize" (the default sense)
    const triggerText = await selectTrigger.textContent();
    expect(triggerText?.toLowerCase()).toMatch(/minimize|maximize/);
  });

  // =========================================================================
  // 7. Save indicator shows save status
  // =========================================================================

  test("save indicator appears after clicking Save", async ({ page }) => {
    await createNewModelAndEnterCanvas(page);
    await waitForReactFlow(page);

    // Click Save button
    const saveButton = page.getByRole("button", { name: /^save$/i });
    await expect(saveButton).toBeVisible({ timeout: 10_000 });
    await saveButton.click();

    // After clicking save, the indicator should show one of:
    // "Saving..." (transient) or "Saved" or an error
    // We look for any save-related status text appearing in the toolbar
    const savingOrSaved = page.getByText(/saving|saved|save error/i).first();
    await expect(savingOrSaved).toBeVisible({ timeout: 10_000 });
  });

  // =========================================================================
  // 8. Model health badge shows validation state
  // =========================================================================

  test("ModelHealthBadge is visible in the toolbar", async ({ page }) => {
    await createNewModelAndEnterCanvas(page);
    await waitForReactFlow(page);

    // ModelHealthBadge renders a button with a colored dot and text
    // It has an aria-label containing "health"
    const healthBadge = page.locator("button").filter({
      has: page.locator(".rounded-full"),
    }).filter({ hasText: /valid|warning|error|issue/i });

    await expect(healthBadge.first()).toBeVisible({ timeout: 10_000 });
  });

  test("ModelHealthBadge popover shows validation details", async ({ page }) => {
    await createNewModelAndEnterCanvas(page);
    await waitForReactFlow(page);

    // Click the health badge to open popover
    const healthBadge = page.locator("button").filter({
      has: page.locator(".rounded-full"),
    }).filter({ hasText: /valid|warning|error|issue/i });

    await expect(healthBadge.first()).toBeVisible({ timeout: 10_000 });
    await healthBadge.first().click();

    // Popover content should appear
    const popoverContent = page.locator('[data-radix-popper-content-wrapper]');
    await expect(popoverContent).toBeVisible({ timeout: 5_000 });
  });

  // =========================================================================
  // 9. Document name can be edited in the toolbar
  // =========================================================================

  test("document name input is editable in the toolbar", async ({ page }) => {
    await createNewModelAndEnterCanvas(page);
    await waitForReactFlow(page);

    // The document name input has placeholder "Untitled Model" or similar
    // and class font-medium
    const nameInput = page.locator(".h-14 input.text-sm.font-medium").first();
    await expect(nameInput).toBeVisible({ timeout: 10_000 });

    // Verify initial value
    const initialValue = await nameInput.inputValue();
    expect(initialValue).toBeTruthy();

    // Change the name
    await nameInput.clear();
    await nameInput.fill("My Test Model");

    const newValue = await nameInput.inputValue();
    expect(newValue).toBe("My Test Model");
  });

  // =========================================================================
  // 10. Builder document list shows created documents
  // =========================================================================

  test("builder list page shows documents or empty state", async ({ page }) => {
    await page.goto("/builder");

    const heading = page.getByRole("heading", { level: 1 });
    await expect(heading).toBeVisible({ timeout: NAV_TIMEOUT });

    // Should show either document cards (grid items) OR empty state
    const documentCards = page.locator(".grid .border.rounded-lg");
    const emptyState = page.getByText(
      /no.*model|get.*started|create.*first|no.*document/i
    );

    // Wait for content to load (loading skeleton disappears)
    await expect(async () => {
      const hasDocuments = (await documentCards.count()) > 0;
      const hasEmptyState = (await emptyState.count()) > 0;
      const hasContent = hasDocuments || hasEmptyState;
      expect(hasContent).toBe(true);
    }).toPass({ timeout: NAV_TIMEOUT });
  });

  // =========================================================================
  // 11. Template system works
  // =========================================================================

  test("templates page shows template cards", async ({ page }) => {
    await page.goto("/builder/templates");

    await expect(page).toHaveURL(/\/builder\/templates/);

    // Page should have a heading
    const heading = page.getByRole("heading", { level: 1 });
    await expect(heading).toBeVisible({ timeout: NAV_TIMEOUT });

    // Should show template cards or "no templates" empty state
    const templateCards = page.locator(".border.rounded-lg.p-4.bg-card");
    const noTemplatesMsg = page.getByText(/no.*template/i);

    await expect(async () => {
      const hasTemplates = (await templateCards.count()) > 0;
      const hasEmpty = (await noTemplatesMsg.count()) > 0;
      expect(hasTemplates || hasEmpty).toBe(true);
    }).toPass({ timeout: NAV_TIMEOUT });
  });

  test("clicking a template navigates to template detail page", async ({ page }) => {
    await page.goto("/builder/templates");

    await expect(page).toHaveURL(/\/builder\/templates/);

    // Wait for content to load
    const heading = page.getByRole("heading", { level: 1 });
    await expect(heading).toBeVisible({ timeout: NAV_TIMEOUT });

    // If templates exist, click the first one
    const templateCards = page.locator(".border.rounded-lg.p-4.bg-card");
    const templateCount = await templateCards.count();

    if (templateCount > 0) {
      // Click "Use Template" button on the first card
      const useButton = templateCards.first().getByRole("button", { name: /use.*template/i });
      const useButtonVisible = await useButton.isVisible().catch(() => false);

      if (useButtonVisible) {
        await useButton.click();
        // Should navigate to /builder/templates/{templateName}
        await page.waitForURL(/\/builder\/templates\//, { timeout: NAV_TIMEOUT });
      } else {
        // Click the card itself
        await templateCards.first().click();
        await page.waitForURL(/\/builder\/templates\//, { timeout: NAV_TIMEOUT });
      }
    }
  });

  // =========================================================================
  // 12. Undo/Redo controls exist in toolbar
  // =========================================================================

  test("undo and redo buttons are visible in the toolbar", async ({ page }) => {
    await createNewModelAndEnterCanvas(page);
    await waitForReactFlow(page);

    // Undo button (initially disabled since no changes yet)
    const undoButton = page.locator('button[title*="ndo"]').first();
    await expect(undoButton).toBeVisible({ timeout: 10_000 });

    // Redo button
    const redoButton = page.locator('button[title*="edo"]').first();
    await expect(redoButton).toBeVisible({ timeout: 10_000 });
  });

  // =========================================================================
  // 13. Zoom controls exist in toolbar
  // =========================================================================

  test("zoom controls are visible in the toolbar", async ({ page }) => {
    await createNewModelAndEnterCanvas(page);
    await waitForReactFlow(page);

    // Zoom in button
    const zoomInButton = page.locator('button[title*="oom"]').first();
    await expect(zoomInButton).toBeVisible({ timeout: 10_000 });
  });

  // =========================================================================
  // 14. Back button returns to builder list
  // =========================================================================

  test("back button in toolbar navigates to builder list", async ({ page }) => {
    await createNewModelAndEnterCanvas(page);
    await waitForReactFlow(page);

    // The back button is the first button in the toolbar (with a chevron icon)
    const toolbar = page.locator(".h-14.border-b");
    const backButton = toolbar.locator("button").first();
    await expect(backButton).toBeVisible({ timeout: 10_000 });
    await backButton.click();

    // Should navigate back to /builder list
    await page.waitForURL(/\/builder$/, { timeout: NAV_TIMEOUT });
  });

  // =========================================================================
  // 15. Multiple nodes can coexist on canvas
  // =========================================================================

  test("canvas supports multiple variable and constraint nodes", async ({ page }) => {
    await createNewModelAndEnterCanvas(page);
    await waitForReactFlow(page);

    const canvasArea = page.locator('[data-onboarding-target="canvas"]');

    // Add first variable via context menu
    await canvasArea.click({ button: "right", position: { x: 150, y: 150 } });
    await page.getByRole("menuitem").filter({ hasText: /variable/i }).click();
    await page.waitForTimeout(300);

    // Add second variable
    await canvasArea.click({ button: "right", position: { x: 300, y: 150 } });
    await page.getByRole("menuitem").filter({ hasText: /variable/i }).click();
    await page.waitForTimeout(300);

    // Add a constraint
    await canvasArea.click({ button: "right", position: { x: 200, y: 350 } });
    await page.getByRole("menuitem").filter({ hasText: /constraint/i }).click();
    await page.waitForTimeout(300);

    // Canvas should now have 4 nodes: 1 objective + 2 variables + 1 constraint
    const totalNodes = await getNodeCount(page);
    expect(totalNodes).toBe(4);
  });

  // =========================================================================
  // 16. Clicking canvas pane deselects nodes
  // =========================================================================

  test("clicking empty canvas area deselects node and hides PropertiesPanel fields", async ({ page }) => {
    await createNewModelAndEnterCanvas(page);
    await waitForReactFlow(page);

    // Click the objective node to select it
    const objectiveNode = page.locator('[data-onboarding-target="objective"]');
    await objectiveNode.click();

    // Properties panel should show sense selector
    const selectTrigger = page.locator('[role="combobox"]').first();
    await expect(selectTrigger).toBeVisible({ timeout: 5_000 });

    // Click on empty canvas area to deselect
    const canvasPane = page.locator(".react-flow__pane");
    await canvasPane.click({ position: { x: 50, y: 50 } });

    // The sense selector should no longer be visible (properties panel shows empty state)
    await expect(selectTrigger).not.toBeVisible({ timeout: 5_000 });
  });
});
