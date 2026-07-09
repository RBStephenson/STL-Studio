import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import AiOrganizeStrategyModal from "./AiOrganizeStrategyModal";

describe("AiOrganizeStrategyModal (#878)", () => {
  it("shows both strategy options with explanatory tooltips", () => {
    render(<AiOrganizeStrategyModal onChoose={vi.fn()} onClose={vi.fn()} />);

    const unitButton = screen.getByRole("button", { name: /unit-based/i });
    const partsButton = screen.getByRole("button", { name: /parts-based/i });
    expect(unitButton).toBeInTheDocument();
    expect(partsButton).toBeInTheDocument();
    // Native title-attribute tooltip explaining each approach.
    expect(unitButton.getAttribute("title")).toMatch(/in-game unit or character/i);
    expect(partsButton.getAttribute("title")).toMatch(/physical part type/i);
  });

  it("calls onChoose('unit') when Unit-based is clicked", () => {
    const onChoose = vi.fn();
    render(<AiOrganizeStrategyModal onChoose={onChoose} onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /unit-based/i }));
    expect(onChoose).toHaveBeenCalledWith("unit");
  });

  it("calls onChoose('parts') when Parts-based is clicked", () => {
    const onChoose = vi.fn();
    render(<AiOrganizeStrategyModal onChoose={onChoose} onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /parts-based/i }));
    expect(onChoose).toHaveBeenCalledWith("parts");
  });

  it("calls onClose when the close button is clicked", () => {
    const onClose = vi.fn();
    render(<AiOrganizeStrategyModal onChoose={vi.fn()} onClose={onClose} />);
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalled();
  });
});
