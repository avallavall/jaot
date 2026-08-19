import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import React from "react";

/**
 * A declaration-only JModel source (`set I; param w{I}; var x{I} binary`) has no
 * variables until a dataset says what `I` is. The panel reported "Variables 0"
 * beside two scenarios that had just solved that same model, and a reader takes
 * that for a broken model rather than for a model waiting on its numbers.
 */

import { createModelProjectStore } from "../store/createModelProjectStore";
import { ModelProjectStoreContext } from "../store/useModelProjectStore";
import { LiveStatsPanel } from "../LiveStatsPanel";
import type { OptimizationProblem } from "@/lib/types";

const EMPTY: OptimizationProblem = {
  variables: [],
  objective: { sense: "minimize", expression: "0" },
  constraints: [],
};

const GROUNDED: OptimizationProblem = {
  variables: [{ name: "x", type: "binary" }],
  objective: { sense: "maximize", expression: "x" },
  constraints: [{ name: "c", expression: "x <= 1" }],
};

const UNGROUNDED_NOTE = "stats-ungrounded";

function renderPanel(setup: (store: ReturnType<typeof createModelProjectStore>) => void) {
  const store = createModelProjectStore({ modelId: "mp_1", name: "T", problem: EMPTY });
  setup(store);
  return render(
    <ModelProjectStoreContext.Provider value={store}>
      <LiveStatsPanel />
    </ModelProjectStoreContext.Provider>
  );
}

describe("Model at a glance, on a model that has no numbers yet", () => {
  // CONTRACT-TEST: a count of zero that has an explanation carries it
  it("says the source needs a dataset instead of leaving a bare zero", () => {
    renderPanel((store) => {
      store.getState().setProjectLoaded(true);
      store.getState().setDraftDslSource("set I; var x{I} binary;");
    });

    expect(screen.getByTestId(UNGROUNDED_NOTE)).toBeInTheDocument();
    expect(screen.getByText("studio.statsUngrounded")).toBeInTheDocument();
  });

  it("says nothing once a dataset is bound", () => {
    renderPanel((store) => {
      store.getState().setProjectLoaded(true);
      store.getState().setDraftDslSource("set I; var x{I} binary;");
      store.getState().setActiveDataset({ id: "ds_1", name: "January" });
    });

    expect(screen.queryByTestId(UNGROUNDED_NOTE)).not.toBeInTheDocument();
  });

  it("says nothing about a model built on the canvas, which has no source", () => {
    renderPanel((store) => {
      store.getState().setProjectLoaded(true);
    });

    expect(screen.queryByTestId(UNGROUNDED_NOTE)).not.toBeInTheDocument();
  });

  it("says nothing about a model that already has variables", () => {
    renderPanel((store) => {
      store.getState().setProjectLoaded(true);
      store.getState().setDraftDslSource("set I := {1,2}; var x{I} binary;");
      store.getState().setProblem(GROUNDED, { source: "dsl" });
    });

    expect(screen.queryByTestId(UNGROUNDED_NOTE)).not.toBeInTheDocument();
  });

  // The same lesson as the matrix panel: an empty store field is not a fact
  // about the model until the project GET has answered.
  it("says nothing before the project has been read", () => {
    renderPanel((store) => {
      store.getState().setDraftDslSource("set I; var x{I} binary;");
    });

    expect(screen.queryByTestId(UNGROUNDED_NOTE)).not.toBeInTheDocument();
  });
});

/**
 * Every count on this card comes from the canonical model, which starts empty.
 * It painted "Class —, Variables 0, Constraints 0" while the project loaded:
 * measured at 4 s on a 15-variable model, 6 s on a 48,556-variable one and 40 s
 * on a 22,650-variable one, all of it a number that was wrong.
 */
describe("Model at a glance, before the project has been read", () => {
  function valueFor(label: string): string {
    const row = screen.getByText(label).closest("div") as HTMLElement;
    return row.querySelector("dd")?.textContent?.trim() ?? "";
  }

  // CONTRACT-TEST: the card says "not known yet" rather than a wrong number
  it("shows a dash, not a zero, until the model has arrived", () => {
    renderPanel(() => {});

    expect(valueFor("studio.statVariables")).toBe("—");
    expect(valueFor("studio.statConstraints")).toBe("—");
    expect(valueFor("studio.statClass")).toBe("—");
  });

  it("shows the real counts once it has", () => {
    renderPanel((store) => {
      store.getState().setProjectLoaded(true);
      store.getState().setProblem(GROUNDED, { source: "dsl" });
    });

    expect(valueFor("studio.statVariables")).toBe("1");
    expect(valueFor("studio.statConstraints")).toBe("1");
  });

  // A model that genuinely has none still reads zero — the dash is about not
  // knowing, not about being empty.
  it("shows a zero for a model that really is empty", () => {
    renderPanel((store) => store.getState().setProjectLoaded(true));

    expect(valueFor("studio.statVariables")).toBe("0");
  });
});
