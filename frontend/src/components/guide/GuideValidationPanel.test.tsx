import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import GuideValidationPanel from "./GuideValidationPanel";
import { GuideValidationResult, ValidationFlag } from "../../api/client";

function flag(over: Partial<ValidationFlag> = {}): ValidationFlag {
  return {
    severity: "warn", code: "step_no_swatches", message: "Step has no paint swatches.",
    tab_index: 0, phase_index: 0, step_index: 1, swatch_index: null, path: "Skin › Base › Step 2",
    ...over,
  };
}

describe("GuideValidationPanel", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("shows a clean state when there are no flags", () => {
    const res: GuideValidationResult = { ok: true, flags: [] };
    render(<GuideValidationPanel result={res} loading={false} />);
    expect(screen.getByText(/no validation issues/i)).toBeInTheDocument();
  });

  it("lists block flags first and headlines the blocking count", () => {
    const res: GuideValidationResult = {
      ok: false,
      flags: [
        flag({ severity: "warn", message: "warn one" }),
        flag({ severity: "block", code: "paint_not_owned", message: "Cadmium 002 isn't owned." }),
      ],
    };
    render(<GuideValidationPanel result={res} loading={false} />);

    expect(screen.getByText(/1 blocking issue — resolve before publishing/i)).toBeInTheDocument();
    const items = screen.getAllByRole("button");
    // Block flag sorted to the top.
    expect(items[0]).toHaveTextContent("Cadmium 002 isn't owned.");
  });

  it("jumps to the flagged step on click", () => {
    const scrollIntoView = vi.fn();
    vi.spyOn(document, "getElementById").mockReturnValue({ scrollIntoView } as unknown as HTMLElement);
    const res: GuideValidationResult = { ok: false, flags: [flag()] };

    render(<GuideValidationPanel result={res} loading={false} />);
    fireEvent.click(screen.getByRole("button"));

    expect(document.getElementById).toHaveBeenCalledWith("guide-step-0-0-1");
    expect(scrollIntoView).toHaveBeenCalled();
  });
});
