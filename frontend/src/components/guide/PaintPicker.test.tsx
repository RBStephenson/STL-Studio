import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import PaintPicker from "./PaintPicker";

vi.mock("../../api/client", async (importOriginal) => {
  const orig = await importOriginal<typeof import("../../api/client")>();
  return { ...orig, api: { painting: { paints: { list: vi.fn() } } } };
});

describe("PaintPicker", () => {
  beforeEach(() => vi.clearAllMocks());

  it("searches the shelf and emits the chosen paint", async () => {
    const { api } = await import("../../api/client");
    vi.mocked(api.painting.paints.list).mockResolvedValue({
      total: 1, page: 1, page_size: 20,
      items: [{ id: 9, name: "Titanium White", code: "MPA-001", hex: "#ffffff" }],
    } as never);

    const onChange = vi.fn();
    render(<PaintPicker value={null} onChange={onChange} />);

    await userEvent.click(screen.getByRole("button", { name: /choose paint/i }));
    await userEvent.type(screen.getByLabelText("Search paints"), "white");

    const opt = await screen.findByRole("button", { name: /Titanium White/i });
    await userEvent.click(opt);

    expect(onChange).toHaveBeenCalledWith({ id: 9, name: "Titanium White", code: "MPA-001", hex: "#ffffff" });
  });

  it("renders the current selection and clears it", async () => {
    const onChange = vi.fn();
    render(<PaintPicker value={{ id: 3, name: "Cadmium", code: "MPA-002", hex: "#f00" }} onChange={onChange} />);

    expect(screen.getByText("Cadmium")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Clear paint" }));
    expect(onChange).toHaveBeenCalledWith(null);
  });
});
