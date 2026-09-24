import { AgentEvent, Variant } from "../../components/commits/types";
import { previewModeFor } from "./previewMode";

function tool(toolName: string, status: AgentEvent["status"]): AgentEvent {
  return { id: `${toolName}-${status}`, type: "tool", toolName, status, startedAt: 0 };
}

function variant(status: Variant["status"], agentEvents: AgentEvent[]): Variant {
  return { code: "export default function App() {}", history: [], status, agentEvents };
}

describe("previewModeFor", () => {
  test("streams while create_file is writing", () => {
    expect(previewModeFor(variant("generating", [tool("create_file", "running")]))).toBe("streaming");
  });

  test("is final between tool calls, so real errors show", () => {
    expect(
      previewModeFor(
        variant("generating", [tool("create_file", "complete"), tool("screenshot_preview", "running")])
      )
    ).toBe("final");
    expect(previewModeFor(variant("generating", [tool("edit_file", "running")]))).toBe("final");
  });

  test("is final once the variant stops, even mid-write", () => {
    expect(previewModeFor(variant("complete", [tool("create_file", "running")]))).toBe("final");
    expect(previewModeFor(variant("cancelled", [tool("create_file", "running")]))).toBe("final");
  });

  test("is final with no variant", () => {
    expect(previewModeFor(undefined)).toBe("final");
  });

  test("streams before the first line is written", () => {
    expect(previewModeFor({ code: "", history: [], status: "generating", agentEvents: [] })).toBe(
      "streaming"
    );
  });
});
