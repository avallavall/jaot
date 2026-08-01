/**
 * The welcome wizard is the first screen a new account sees, and it opens for
 * everyone: it is mounted globally in `app/[locale]/providers.tsx` and shows
 * until completed or dismissed. What it must never do again:
 *
 *  - send the reader into `/builder`, the area the product retired in favour of
 *    the studio ("the studio IS the one door" — components/layout/nav-items.tsx);
 *  - claim that a formulation was produced. Step 2 used to collect the reader's
 *    problem in a textarea nothing ever read, and step 3 then told them "the AI
 *    assistant has turned your words into a mathematical model with variables,
 *    constraints, and an objective". Nothing had run, and the assistant opened
 *    empty;
 *  - hand out a map of the product that is not the product's map. Step 4 offered
 *    three fixed buttons and named neither the studio nor half of what exists.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import React from "react";

import enMessages from "../../../../messages/en.json";

const { dslStatus } = vi.hoisted(() => ({ dslStatus: vi.fn() }));

vi.mock("@/lib/api", () => ({ api: { dslStatus } }));
vi.mock("@/lib/community", () => ({
  FEEDBACK_URL: "https://example.invalid/feedback",
  fetchCommunityStatus: vi.fn().mockResolvedValue({ discourse_enabled: false }),
}));

import { WizardStepContent } from "../WizardStepContent";

const noop = () => {};

function renderStep(step: number) {
  return render(
    <WizardStepContent step={step} selectedSkillLevel="beginner" onSkillLevelChange={noop} />,
  );
}

const hrefsOf = (container: HTMLElement) =>
  Array.from(container.querySelectorAll("a[href]")).map((a) => a.getAttribute("href"));

describe("WelcomeWizard steps", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    dslStatus.mockResolvedValue({ enabled: false });
  });

  it("never links into the retired /builder area", () => {
    for (const step of [1, 2, 3, 4]) {
      const { container, unmount } = renderStep(step);
      expect(hrefsOf(container).filter((h) => (h ?? "").includes("/builder"))).toEqual([]);
      unmount();
    }
  });

  it("points the reader at the studio launcher, which covers every way in", () => {
    const { container } = renderStep(3);
    expect(hrefsOf(container)).toContain("/studio/new");
  });

  it("does not ask for a problem it will not read", () => {
    const { container } = renderStep(2);
    expect(container.querySelector("textarea")).toBeNull();
    expect(container.querySelector("input")).toBeNull();
  });

  it("shows the worked example as an example", () => {
    renderStep(2);
    expect(screen.getByText(/backpack that holds 15 kg/)).toBeInTheDocument();
  });
});

describe("WelcomeWizard names every way into a model", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("lists the launcher's own starting points", async () => {
    dslStatus.mockResolvedValue({ enabled: false });
    renderStep(3);

    // The suite-wide next-intl mock renders keys, which is what makes this a
    // check that the wizard reads the LAUNCHER's strings and not copies of them.
    for (const key of [
      "studio.tileAi",
      "studio.tileVisual",
      "studio.tileEditor",
      "studio.tileImport",
      "studio.tileTemplate",
      "studio.tileMarketplace",
      "studio.tileBlank",
    ]) {
      expect(screen.getByText(key)).toBeInTheDocument();
    }
  });

  it("hides JModel exactly when the launcher hides it — JAOT_DSL ships off", async () => {
    dslStatus.mockResolvedValue({ enabled: false });
    const { unmount } = renderStep(3);
    expect(screen.queryByText("studio.tileJModel")).not.toBeInTheDocument();
    unmount();

    dslStatus.mockResolvedValue({ enabled: true });
    renderStep(3);
    await waitFor(() => {
      expect(screen.getByText("studio.tileJModel")).toBeInTheDocument();
    });
  });
});

describe("WelcomeWizard hands out the real map", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    dslStatus.mockResolvedValue({ enabled: false });
  });

  it("links every area of the sidebar's three groups", async () => {
    const { container } = renderStep(4);
    await waitFor(() => expect(hrefsOf(container).length).toBeGreaterThan(0));

    for (const href of [
      "/studio",
      "/studio/new",
      "/studio/templates",
      "/marketplace",
      "/solve/favorites",
      "/solve/executions",
      "/solve/analytics",
    ]) {
      expect(hrefsOf(container)).toContain(href);
    }
  });

  it("does not send a new account to triggers, which cannot automate a studio model", () => {
    // `Trigger.document_id` is a NOT NULL foreign key to model_builder_documents
    // and the studio never creates one, so the feature is a dead end from here.
    const { container } = renderStep(4);
    expect(hrefsOf(container).filter((h) => (h ?? "").includes("/triggers"))).toEqual([]);
  });
});

describe("WelcomeWizard copy", () => {
  const guidance = enMessages.common.guidance as Record<string, string>;

  it("never states that a model was already generated", () => {
    const claims = [
      /has turned your words into/i,
      /the AI generated a model/i,
      /will convert it into a mathematical formulation/i,
    ];
    const step23 = Object.entries(guidance)
      .filter(([key]) => key.startsWith("step2") || key.startsWith("step3"))
      .map(([, value]) => value);

    for (const text of step23) {
      for (const claim of claims) {
        expect(text).not.toMatch(claim);
      }
    }
  });

  it("dropped the strings whose callers are gone", () => {
    for (const orphan of ["step2NextHint", "modelCatalog", "visualBuilder", "executions"]) {
      expect(guidance[orphan]).toBeUndefined();
    }
  });
});
