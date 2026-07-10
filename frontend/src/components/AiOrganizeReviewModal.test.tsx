import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import AiOrganizeReviewModal from "./AiOrganizeReviewModal";
import { AiOrganizePreviewResult, STLFile } from "../api/client";

vi.mock("../api/client", async (importOriginal) => {
  const orig = await importOriginal<typeof import("../api/client")>();
  return { ...orig, api: { models: { aiOrganizeApply: vi.fn() } } };
});

const stlFiles = [
  { id: 1, filename: "widget.stl", path: "/widget.stl", size_bytes: 1024, sup_of_id: null, part_type: null, part_name: null },
] as STLFile[];

function renderModal(result: AiOrganizePreviewResult) {
  return render(
    <AiOrganizeReviewModal
      modelId={1}
      result={result}
      stlFiles={stlFiles}
      onApplied={vi.fn()}
      onClose={vi.fn()}
    />
  );
}

describe("AiOrganizeReviewModal — success-via-API-or-nothing (#821)", () => {
  it("shows the review table with no banner when llm_status is ok", () => {
    renderModal({
      suggestions: [{ id: 1, filename: "widget.stl", part_type: "Weapon", part_name: "Widget", sup_of_id: null, sup_base_filename: null }],
      llm_status: "ok",
      llm_detail: null,
    });
    expect(screen.getByText("widget.stl")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Apply/ })).toBeInTheDocument();
    expect(screen.queryByText(/AI Organize has no API configured/)).not.toBeInTheDocument();
  });

  it("shows an error banner and no table/Apply button when llm_status is error", () => {
    renderModal({
      suggestions: [],
      llm_status: "error",
      llm_detail: "Timed out after 60s calling http://ollama:11434 — raise this API's timeout in Settings.",
    });
    expect(screen.getByText(/Timed out after 60s/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Apply/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Close" })).toBeInTheDocument();
  });

  it("shows a disabled-feedback banner and no heuristic fallback when llm_status is disabled", () => {
    renderModal({ suggestions: [], llm_status: "disabled", llm_detail: null });
    expect(screen.getByText(/AI Organize has no API configured/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Apply/ })).not.toBeInTheDocument();
  });

  it("shows a skipped-feedback banner (not an error) when the AI had nothing to refine", () => {
    renderModal({ suggestions: [], llm_status: "skipped", llm_detail: null });
    expect(screen.getByText(/AI had nothing to refine/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Apply/ })).not.toBeInTheDocument();
  });

  it("never renders a suggestion row unless llm_status is ok, even if suggestions were somehow non-empty", () => {
    // Defense in depth: the backend never sends suggestions for a non-"ok"
    // status, but the modal must not render them even if it did.
    renderModal({
      suggestions: [{ id: 1, filename: "widget.stl", part_type: "Weapon", part_name: "Widget", sup_of_id: null, sup_base_filename: null }],
      llm_status: "error",
      llm_detail: "boom",
    });
    expect(screen.queryByText("widget.stl")).not.toBeInTheDocument();
  });

  it("category dropdown offers the same canonical categories as the app's Category combobox", () => {
    // Regression: this modal used to have its own stale, mismatched category
    // list ("Accessory", "Arm", "Leg", "Unknown", ...) instead of the
    // canonical one — an edit made here could save a non-canonical value
    // (e.g. "Accessory") that /ai-organize/apply writes verbatim, with no
    // server-side re-normalization, producing a category the real Category
    // combobox doesn't offer.
    renderModal({
      suggestions: [{ id: 1, filename: "widget.stl", part_type: "Accessories", part_name: "Widget", sup_of_id: null, sup_base_filename: null }],
      llm_status: "ok",
      llm_detail: null,
    });
    const select = screen.getByRole("combobox") as HTMLSelectElement;
    const optionValues = Array.from(select.options).map((o) => o.value);

    expect(optionValues).toContain("Accessories");
    expect(optionValues).not.toContain("Accessory");
    expect(optionValues).not.toContain("Unknown");
    // A couple of real canonical categories the old stale list was missing.
    expect(optionValues).toContain("Right Arm");
    expect(optionValues).toContain("Torso");
    // "Full" is itself a canonical category (a one-piece full-body sculpt) —
    // not the old list's mismatch this test guards against.
    expect(optionValues).toContain("Full");
  });

  it("lists category options alphabetically, not in PART_TYPE_SUGGESTIONS's grouped-by-body-part order", () => {
    renderModal({
      suggestions: [{ id: 1, filename: "widget.stl", part_type: "Weapon", part_name: "Widget", sup_of_id: null, sup_base_filename: null }],
      llm_status: "ok",
      llm_detail: null,
    });
    const select = screen.getByRole("combobox") as HTMLSelectElement;
    // First option is the blank "—" placeholder; the rest must be sorted.
    const categoryOptions = Array.from(select.options).map((o) => o.value).slice(1);
    const sorted = [...categoryOptions].sort((a, b) => a.localeCompare(b));
    expect(categoryOptions).toEqual(sorted);
  });
});
