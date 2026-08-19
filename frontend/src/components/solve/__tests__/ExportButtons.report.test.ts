import { describe, it, expect } from "vitest";
import { buildReportHtml, type ExportLabels } from "../ExportButtons";
import type { ModelExecution } from "@/lib/types";

/**
 * The printable solution report (G7e). The owner hit real defects here: a
 * duplicated unclosed .meta-item nested the meta-grid, the report had no
 * model/solver/gap/constraints, and every zero variable printed (pages of
 * zeros). These tests parse the generated document and pin the fixes.
 */

const labels: ExportLabels = {
  solutionReport: "Solution report",
  generatedAt: "8/5/2026, 10:00:00",
  variableAssignments: "Variables",
  constraintDetails: "Constraints",
  executionId: "Execution",
  status: "Status",
  solverStatus: "Solver status",
  objectiveValue: "Objective",
  origin: "Origin",
  originValue: "Visual builder",
  modelLabel: "Model",
  solverLabel: "Solver",
  gapLabel: "Gap",
  nameHeader: "Name",
  typeHeader: "Type",
  valueHeader: "Value",
  lowerBound: "Lower",
  upperBound: "Upper",
  expression: "Expression",
  bindingStatus: "Binding",
  gapConvergence: "Gap convergence",
  generated: "Generated",
  solveTime: "Solve time",
  triggerIdLabel: "Trigger",
  noVariables: "No variables",
  noConstraints: "No constraints",
  printSaveAsPdf: "Print / Save as PDF",
  dateLabel: "Date",
  popupBlocked: "Popup blocked",
  zeroOmitted: (count) => `${count} zeros omitted`,
  rowsCapped: (shown, total) => `showing ${shown} of ${total}`,
};

function makeExecution(overrides: Partial<ModelExecution> = {}): ModelExecution {
  return {
    id: "exec_report_test",
    organization_model_id: null,
    status: "completed",
    solver_status: "optimal",
    objective_value: 42.5,
    execution_time_ms: 1234,
    created_at: "2026-07-16T10:00:00Z",
    origin: "api",
    solver_name: "scip",
    model_name: "Report Probe Model",
    result_data: {
      status: "optimal",
      gap: 0.0125,
      variables: [
        { name: "x1", type: "binary", value: 1 },
        { name: "x2", type: "binary", value: 0 },
        { name: "x3", type: "continuous", value: 3.75 },
        { name: "x4", type: "binary", value: 0 },
      ],
    } as unknown as ModelExecution["result_data"],
    input_data: {
      name: "Report Probe Model",
      constraints: [
        { name: "c1", expression: "x1 + x2 >= 1" },
        { name: "c2", expression: "x3 <= 10" },
      ],
    },
    ...overrides,
  } as ModelExecution;
}

function parse(html: string): Document {
  return new DOMParser().parseFromString(html, "text/html");
}

describe("buildReportHtml", () => {
  it("meta items are DIRECT children of the meta-grid (the duplicated-div regression)", () => {
    const doc = parse(buildReportHtml(makeExecution(), labels, "en"));
    const items = Array.from(doc.querySelectorAll(".meta-item"));
    expect(items.length).toBeGreaterThanOrEqual(6);
    for (const item of items) {
      expect(item.parentElement?.classList.contains("meta-grid")).toBe(true);
      expect(item.querySelector(".meta-item")).toBeNull();
    }
    // Every meta item is well-formed: one label + one value.
    for (const item of items) {
      expect(item.querySelectorAll(".meta-label")).toHaveLength(1);
      expect(item.querySelectorAll(".meta-value")).toHaveLength(1);
    }
  });

  it("carries model name, solver, gap and the constraints section", () => {
    const doc = parse(buildReportHtml(makeExecution(), labels, "en"));
    const text = doc.body.textContent ?? "";
    expect(text).toContain("Report Probe Model");
    expect(text).toContain("SCIP"); // brand casing, same as the page it came from
    expect(text).toContain("1.25%");
    expect(text).toContain("x1 + x2 >= 1");
    expect(text).toContain("x3 <= 10");
  });

  it("names the solver that actually ran, not the one requested", () => {
    // Under solver_name="auto" only result_data.solver_used records where the
    // backend routed — the detail page reads it, so the report must agree.
    const execution = makeExecution({
      solver_name: "auto",
      result_data: {
        status: "optimal",
        solver_used: "highs",
        variables: [{ name: "x1", type: "binary", value: 1 }],
      } as unknown as ModelExecution["result_data"],
    });
    const doc = parse(buildReportHtml(execution, labels, "en"));
    const solverItem = [...doc.querySelectorAll(".meta-item")]
      .map((n) => n.textContent ?? "")
      .find((t) => t.includes(labels.solverLabel));
    expect(solverItem).toContain("HiGHS");
    expect(solverItem).not.toContain("auto");
  });

  it("prints the origin label it was handed, not the execution's raw slug", () => {
    // Scope note: resolving slug → label is `originLabel`, tested directly in
    // src/lib/__tests__/execution-origin.test.ts. What belongs here is that the
    // template renders the resolved value and never reaches for `execution.origin`
    // itself — the header beside it is translated, so an English slug in the value
    // made the line read "Quelle: ai_builder" in a document meant to be handed on.
    const doc = parse(
      buildReportHtml(makeExecution({ origin: "ai_builder" }), labels, "de"),
    );
    const meta = [...doc.querySelectorAll(".meta-item")].map((n) => n.textContent ?? "");
    const originItem = meta.find((t) => t.includes(labels.origin));
    expect(originItem).toContain(labels.originValue);
    expect(originItem).not.toContain("ai_builder");
  });

  it("omits zero variables by default and says how many", () => {
    const doc = parse(buildReportHtml(makeExecution(), labels, "en"));
    const varNames = Array.from(doc.querySelectorAll(".var-name")).map((n) => n.textContent);
    expect(varNames).toContain("x1");
    expect(varNames).toContain("x3");
    expect(varNames).not.toContain("x2");
    expect(varNames).not.toContain("x4");
    expect(doc.body.textContent).toContain("2 zeros omitted");
  });

  it("caps the variables table and reports the cap", () => {
    const many = Array.from({ length: 620 }, (_, i) => ({
      name: `v${i}`,
      type: "continuous",
      value: i + 1,
    }));
    const execution = makeExecution({
      result_data: { status: "optimal", variables: many } as unknown as ModelExecution["result_data"],
    });
    const doc = parse(buildReportHtml(execution, labels, "en"));
    // .var-name appears once per variable row (constraints use it too — filter by v-prefix).
    const varRows = Array.from(doc.querySelectorAll(".var-name")).filter((n) =>
      n.textContent?.startsWith("v"),
    );
    expect(varRows).toHaveLength(500);
    expect(doc.body.textContent).toContain("showing 500 of 620");
  });

  // CONTRACT-TEST: a printable report stays printable on a real indexed model.
  it("caps the constraints table and truncates a runaway expression", () => {
    // Measured on the reference install: 97,642 constraints totalling 11 MB of
    // expressions, one of them 14,221 characters. Uncapped, with break-all
    // wrapping, that is a "printable" document over 200,000 px tall.
    const many = Array.from({ length: 900 }, (_, i) => ({
      name: `c${i}`,
      expression: `${"x".repeat(2000)} <= ${i}`,
    }));
    const execution = makeExecution({ input_data: { name: "Huge", constraints: many } });
    const doc = parse(buildReportHtml(execution, labels, "en"));

    const constraintRows = Array.from(doc.querySelectorAll(".constraint-expr"));
    expect(constraintRows).toHaveLength(300);
    expect(doc.body.textContent).toContain("showing 300 of 900");
    for (const cell of constraintRows) {
      expect((cell.textContent ?? "").length).toBeLessThanOrEqual(401);
    }
  });

  it("treats a stringy zero as zero, like the on-screen explorer does", () => {
    const execution = makeExecution({
      result_data: {
        status: "optimal",
        variables: [
          { name: "kept", type: "continuous", value: "3.5" },
          { name: "dropped", type: "continuous", value: "0" },
        ],
      } as unknown as ModelExecution["result_data"],
    });
    const doc = parse(buildReportHtml(execution, labels, "en"));
    const varNames = Array.from(doc.querySelectorAll(".var-name")).map((n) => n.textContent);
    expect(varNames).toContain("kept");
    expect(varNames).not.toContain("dropped");
  });

  it("stamps the caller's locale on the document (not a hardcoded en)", () => {
    const doc = parse(buildReportHtml(makeExecution(), labels, "fr"));
    expect(doc.documentElement.getAttribute("lang")).toBe("fr");
  });

  it("uses system fonts only — the app's webfonts are not embedded in the standalone file", () => {
    const html = buildReportHtml(makeExecution(), labels, "en");
    expect(html).not.toContain("Geist");
  });

  it("escapes user-controlled values — a hostile model name/variable cannot inject markup", () => {
    // Model authors control these strings, and the fused marketplace means the
    // author may be a third party; the report runs on a same-origin blob URL.
    const payload = '<img src=x onerror="window.__pwned=1">';
    const execution = makeExecution({
      model_name: `Evil ${payload}`,
      result_data: {
        status: "optimal",
        variables: [{ name: payload, type: `t${payload}`, value: 1 }],
      } as unknown as ModelExecution["result_data"],
      input_data: {
        name: "Evil",
        constraints: [{ name: payload, expression: `x <= 1 ${payload}` }],
      },
    });
    const html = buildReportHtml(execution, labels, "en");
    expect(html).not.toContain(payload);

    const doc = parse(html);
    // Nothing materialized as an element…
    expect(doc.querySelector("img")).toBeNull();
    // …and the hostile string survives as visible TEXT.
    expect(doc.body.textContent).toContain(payload);
  });

  it("renders honest empty states", () => {
    const execution = makeExecution({
      result_data: { status: "optimal", variables: [] } as unknown as ModelExecution["result_data"],
      input_data: { name: "Empty" },
    });
    const doc = parse(buildReportHtml(execution, labels, "en"));
    const text = doc.body.textContent ?? "";
    expect(text).toContain("No variables");
    expect(text).toContain("No constraints");
  });
});
