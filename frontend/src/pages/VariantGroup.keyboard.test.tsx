import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import { MemoryRouter, Routes, Route, useLocation } from "react-router-dom";
import VariantGroup from "./VariantGroup";

const variantsMock = vi.fn().mockResolvedValue({
  items: [
    { id: 10, name: "Bust" },
    { id: 11, name: "Full size" },
  ],
});

vi.mock("../api/client", () => ({
  api: {
    models: {
      variants: (...a: unknown[]) => variantsMock(...a),
      characters: vi.fn().mockResolvedValue([]),
      setGroupOverride: vi.fn().mockResolvedValue({}),
    },
    collections: {
      list: vi.fn().mockResolvedValue([]),
    },
  },
}));

vi.mock("../context/ToastContext", () => ({ useToast: () => ({ toast: vi.fn() }) }));

vi.mock("../components/ModelCard", () => ({
  default: ({ model, focused }: { model: { id: number; name: string }; focused?: boolean }) => (
    <div data-testid={`card-${model.id}`} data-focused={focused ? "1" : "0"}>
      {model.name}
    </div>
  ),
}));

function LocationProbe() {
  const loc = useLocation();
  return <div data-testid="loc">{loc.pathname}</div>;
}

const renderPage = () =>
  render(
    <MemoryRouter initialEntries={["/groups/3/Rocky"]}>
      <Routes>
        <Route path="/groups/:creatorId/:character" element={<><VariantGroup /><LocationProbe /></>} />
        <Route path="*" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  );

const flush = () => act(async () => { await Promise.resolve(); });
const press = (key: string) => act(() => {
  window.dispatchEvent(new KeyboardEvent("keydown", { key }));
});

describe("VariantGroup keyboard navigation (#169)", () => {
  beforeEach(() => variantsMock.mockClear());

  it("moves the focus ring with WASD and opens the focused variant on Enter", async () => {
    renderPage();
    await flush();

    expect(screen.getByTestId("card-10").dataset.focused).toBe("0");

    press("d");                       // first move → first variant
    expect(screen.getByTestId("card-10").dataset.focused).toBe("1");

    press("d");                       // → second variant
    expect(screen.getByTestId("card-11").dataset.focused).toBe("1");

    press("Enter");
    expect(screen.getByTestId("loc").textContent).toBe("/models/11");
  });
});
