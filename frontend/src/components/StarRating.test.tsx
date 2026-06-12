import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import StarRating from "./StarRating";

describe("StarRating (#167)", () => {
  it("renders five star buttons", () => {
    render(<StarRating value={null} onChange={() => {}} />);
    expect(screen.getAllByRole("radio")).toHaveLength(5);
  });

  it("marks the current rating as checked", () => {
    render(<StarRating value={3} onChange={() => {}} />);
    expect(screen.getByRole("radio", { name: "3 stars" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: "4 stars" })).toHaveAttribute("aria-checked", "false");
  });

  it("calls onChange with the clicked star value", () => {
    const onChange = vi.fn();
    render(<StarRating value={null} onChange={onChange} />);
    fireEvent.click(screen.getByRole("radio", { name: "4 stars" }));
    expect(onChange).toHaveBeenCalledWith(4);
  });

  it("clears the rating when the current star is clicked again", () => {
    const onChange = vi.fn();
    render(<StarRating value={3} onChange={onChange} />);
    fireEvent.click(screen.getByRole("radio", { name: "3 stars" }));
    expect(onChange).toHaveBeenCalledWith(null);
  });

  it("does not fire onChange in read-only mode", () => {
    const onChange = vi.fn();
    render(<StarRating value={2} onChange={onChange} readOnly />);
    fireEvent.click(screen.getByRole("radio", { name: "5 stars" }));
    expect(onChange).not.toHaveBeenCalled();
  });
});
