import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import React from "react";

import type { ComparisonBatchDetail } from "@/lib/types";
import { MatrixTable } from "../MatrixTable";

/**
 * The matrix printed the API's solver keys in capitals ("HIGHS") where every
 * other page prints the brand name ("HiGHS"). The header row is also styled in
 * capitals, so the solver cells opt out of that style.
 */
describe("the solver matrix's column headers", () => {
  it("print the brand names, not the keys in capitals", () => {
    const batch = {
      batch_id: "cmb_1",
      status: "completed",
      solver_names: ["scip", "highs", "jaos"],
      rows: [],
    } as unknown as ComparisonBatchDetail;

    render(<MatrixTable batch={batch} metric="time" openRow={null} onOpenRow={() => {}} />);

    const headers = screen.getAllByRole("columnheader").map((th) => th.textContent);
    expect(headers).toEqual(["studio.matrix.colDataset", "SCIP", "HiGHS", "JAOS"]);
    const highs = screen.getByRole("columnheader", { name: "HiGHS" });
    expect(highs.className).toContain("normal-case");
  });
});
