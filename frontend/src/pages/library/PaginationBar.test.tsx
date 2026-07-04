import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import PaginationBar from "./PaginationBar";

const renderBar = (props: Partial<React.ComponentProps<typeof PaginationBar>> = {}) => {
  const onPage = props.onPage ?? vi.fn();
  render(<PaginationBar page={2} totalPages={5} onPage={onPage} {...props} />);
  return onPage;
};

describe("PaginationBar", () => {
  it("shows the current page and total", () => {
    renderBar();
    expect(screen.getByRole("textbox")).toHaveValue("2");
    expect(screen.getByText("/ 5")).toBeInTheDocument();
  });

  it("pages back and forward via Prev/Next", () => {
    const onPage = renderBar({ page: 2 });
    fireEvent.click(screen.getByRole("button", { name: "Prev" }));
    expect(onPage).toHaveBeenCalledWith(1);
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(onPage).toHaveBeenCalledWith(3);
  });

  it("disables Prev on the first page and Next on the last", () => {
    renderBar({ page: 1 });
    expect(screen.getByRole("button", { name: "Prev" })).toBeDisabled();
    renderBar({ page: 5 });
    expect(screen.getAllByRole("button", { name: "Next" }).some((b) => (b as HTMLButtonElement).disabled)).toBe(true);
  });

  it("commits a typed page on blur, clamped to range", () => {
    const onPage = renderBar();
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "99" } });
    fireEvent.blur(input);
    expect(onPage).toHaveBeenCalledWith(5); // clamped to totalPages
  });

  it("commits on Enter", () => {
    const onPage = renderBar();
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "3" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onPage).toHaveBeenCalledWith(3);
  });
});
