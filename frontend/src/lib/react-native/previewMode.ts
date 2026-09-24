import type { Variant } from "../../components/commits/types";
import type { PreviewMode } from "./previewHtml";

// "streaming" while the agent is still writing App.jsx with create_file: the
// file is incomplete, so the preview keeps the last good render and shows a
// "Writing App.jsx…" badge instead of an error panel. Between tool calls the
// file is complete, so errors show (DESIGN.md §5.5).
export function previewModeFor(variant: Variant | undefined): PreviewMode {
  if (!variant || variant.status !== "generating") return "final";
  // Nothing written yet: a blank phone, not a "no default export" error.
  if (!variant.code.trim()) return "streaming";
  const writing = (variant.agentEvents ?? []).some(
    (event) =>
      event.type === "tool" &&
      event.toolName === "create_file" &&
      event.status === "running"
  );
  return writing ? "streaming" : "final";
}
