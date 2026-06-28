import { describe, it, expect, vi, beforeEach } from "vitest";

const { mockPreview } = vi.hoisted(() => ({ mockPreview: vi.fn() }));

vi.mock("@/lib/api", () => ({
  api: { fileImport: { preview: mockPreview } },
}));

import { parseModelFile } from "../import-model";

function makeFile(name: string, content: string): File {
  return new File([content], name, { type: "text/plain" });
}

describe("parseModelFile", () => {
  beforeEach(() => vi.clearAllMocks());

  it("parses a builder JSON file locally without hitting the import endpoint", async () => {
    const problem = {
      name: "x",
      variables: [{ name: "a" }],
      objective: { sense: "minimize" },
    };
    const { problem: parsed, baseName } = await parseModelFile(
      makeFile("my-model.json", JSON.stringify(problem))
    );

    expect(baseName).toBe("my-model");
    expect(parsed).toEqual(problem);
    expect(mockPreview).not.toHaveBeenCalled();
  });

  it("routes solver formats (MPS) through the server import-preview endpoint", async () => {
    const previewProblem = { name: "srv", variables: [], objective: {} };
    mockPreview.mockResolvedValue({ problem: previewProblem });
    const file = makeFile("plant.mps", "NAME plant\n");

    const { problem, baseName } = await parseModelFile(file);

    expect(mockPreview).toHaveBeenCalledWith(file);
    expect(problem).toEqual(previewProblem);
    expect(baseName).toBe("plant");
  });

  it("strips a gzipped solver extension when deriving the base name", async () => {
    mockPreview.mockResolvedValue({ problem: {} });
    const { baseName } = await parseModelFile(makeFile("net.lp.gz", "gz"));

    expect(baseName).toBe("net");
    expect(mockPreview).toHaveBeenCalled();
  });
});
