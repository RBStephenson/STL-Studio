import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route, useLocation } from "react-router-dom";
import VariantGroup from "./VariantGroup";

const batchSetGroup = vi.fn();
const batchThumbnailFromUrl = vi.fn();
const setGroupRep = vi.fn();
const reorderGroup = vi.fn();
const variantsMock = vi.fn();
const toast = vi.fn();

vi.mock("../api/client", () => ({
  api: {
    models: {
      variants: (...a: unknown[]) => variantsMock(...a),
      characters: vi.fn().mockResolvedValue(["Rocky", "Apollo"]),
      setGroupOverride: vi.fn().mockResolvedValue({}),
      batchSetGroup: (...a: unknown[]) => batchSetGroup(...a),
      batchThumbnailFromUrl: (...a: unknown[]) => batchThumbnailFromUrl(...a),
      setGroupRep: (...a: unknown[]) => setGroupRep(...a),
      reorderGroup: (...a: unknown[]) => reorderGroup(...a),
    },
  },
}));

vi.mock("../context/ToastContext", () => ({ useToast: () => ({ toast }) }));

vi.mock("../components/ModelCard", () => ({
  default: ({ model }: { model: { id: number; name: string } }) => (
    <div data-testid={`card-${model.id}`}>{model.name}</div>
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

beforeEach(() => {
  batchSetGroup.mockReset();
  batchThumbnailFromUrl.mockReset();
  setGroupRep.mockReset();
  reorderGroup.mockReset();
  toast.mockReset();
  variantsMock.mockReset();
  variantsMock.mockResolvedValue({
    items: [
      { id: 10, name: "Bust", character: "Rocky", is_group_rep: false },
      { id: 11, name: "Full size", character: "Rocky", is_group_rep: false },
    ],
  });
});

describe("VariantGroup bulk management (#183)", () => {
  it("moves only the selected models to another group and drops them from the grid", async () => {
    batchSetGroup.mockResolvedValue({ ok: true, character: "Apollo", updated: [10], missing: [] });
    renderPage();
    await flush();

    fireEvent.click(screen.getByLabelText("Select Bust"));
    fireEvent.click(screen.getByLabelText("Move selected to group"));
    fireEvent.change(screen.getByLabelText("Target group"), { target: { value: "Apollo" } });
    await act(async () => { fireEvent.click(screen.getByText("Move")); });

    expect(batchSetGroup).toHaveBeenCalledWith([10], "Apollo");
    await waitFor(() => expect(screen.queryByTestId("card-10")).toBeNull());
    expect(screen.getByTestId("card-11")).toBeTruthy();
  });

  it("ungroups all selected models and navigates back when the group empties", async () => {
    batchSetGroup.mockResolvedValue({ ok: true, character: null, updated: [10, 11], missing: [] });
    renderPage();
    await flush();

    fireEvent.click(screen.getByText("Select all"));
    await act(async () => { fireEvent.click(screen.getByText("Ungroup")); });

    expect(batchSetGroup).toHaveBeenCalledWith([10, 11], null);
    await waitFor(() => expect(screen.getByTestId("loc").textContent).toBe("/"));
  });

  it("renames the whole group and navigates to the new group URL", async () => {
    batchSetGroup.mockResolvedValue({ ok: true, character: "Rocky II", updated: [10, 11], missing: [] });
    renderPage();
    await flush();

    fireEvent.click(screen.getByRole("button", { name: /Rocky/ }));
    fireEvent.change(screen.getByLabelText("Group name"), { target: { value: "Rocky II" } });
    await act(async () => { fireEvent.click(screen.getByLabelText("Save name")); });

    expect(batchSetGroup).toHaveBeenCalledWith([10, 11], "Rocky II");
    await waitFor(() =>
      expect(screen.getByTestId("loc").textContent).toBe("/groups/3/Rocky%20II"),
    );
  });

  it("sets one image on the selected members (#184) and refetches", async () => {
    batchThumbnailFromUrl.mockResolvedValue({ ok: true, downloaded: true, updated: [10], missing: [] });
    renderPage();
    await flush();

    fireEvent.click(screen.getByLabelText("Select Bust"));
    fireEvent.click(screen.getByLabelText("Set image for selected"));
    fireEvent.change(screen.getByLabelText("Image URL"), { target: { value: "https://cdn.example.com/g.png" } });
    await act(async () => { fireEvent.click(screen.getByText("Apply")); });

    expect(batchThumbnailFromUrl).toHaveBeenCalledWith([10], "https://cdn.example.com/g.png");
    expect(toast).toHaveBeenCalledWith(expect.stringContaining("Image set on 1 model"), "success");
    // Refetched to cache-bust the grid thumbnails.
    expect(variantsMock).toHaveBeenCalledTimes(2);
  });

  it("warns when the server-side download fails (bare link stored)", async () => {
    batchThumbnailFromUrl.mockResolvedValue({ ok: true, downloaded: false, detail: "403", updated: [10], missing: [] });
    renderPage();
    await flush();

    fireEvent.click(screen.getByLabelText("Select Bust"));
    fireEvent.click(screen.getByLabelText("Set image for selected"));
    fireEvent.change(screen.getByLabelText("Image URL"), { target: { value: "https://cdn.example.com/blocked.png" } });
    await act(async () => { fireEvent.click(screen.getByText("Apply")); });

    expect(toast).toHaveBeenCalledWith(expect.stringContaining("may not load"), "error");
  });

  it("sets a member as the group display thumbnail (#193) and refetches", async () => {
    setGroupRep.mockResolvedValue({ ok: true, is_group_rep: true });
    renderPage();
    await flush();

    await act(async () => {
      fireEvent.click(screen.getAllByLabelText("Set as group thumbnail")[0]);
    });

    expect(setGroupRep).toHaveBeenCalledWith(10, true);
    expect(toast).toHaveBeenCalledWith("Group thumbnail updated.", "success");
    // Refetched so the new rep / ordering is reflected.
    expect(variantsMock).toHaveBeenCalledTimes(2);
  });

  it("reports skipped models from a partial bulk result", async () => {
    batchSetGroup.mockResolvedValue({ ok: true, character: "Apollo", updated: [10], missing: [11] });
    renderPage();
    await flush();

    fireEvent.click(screen.getByText("Select all"));
    fireEvent.click(screen.getByLabelText("Move selected to group"));
    fireEvent.change(screen.getByLabelText("Target group"), { target: { value: "Apollo" } });
    await act(async () => { fireEvent.click(screen.getByText("Move")); });

    expect(toast).toHaveBeenCalledWith(expect.stringContaining("1 skipped"), "success");
  });

  it("shows Reset order when a manual order exists and clears it (#399)", async () => {
    variantsMock.mockResolvedValue({
      items: [
        { id: 10, name: "Bust", character: "Rocky", is_group_rep: false, variant_order: 0 },
        { id: 11, name: "Full size", character: "Rocky", is_group_rep: false, variant_order: 1 },
      ],
    });
    reorderGroup.mockResolvedValue({ ok: true, reset: true, updated: 2 });
    renderPage();
    await flush();

    await act(async () => { fireEvent.click(screen.getByText("Reset order")); });

    // Empty ids = reset the whole (creator, character) group.
    expect(reorderGroup).toHaveBeenCalledWith(3, "Rocky", []);
    expect(toast).toHaveBeenCalledWith("Order reset to default.", "success");
    expect(variantsMock).toHaveBeenCalledTimes(2); // reloaded
  });

  it("hides Reset order when no manual order is set", async () => {
    renderPage();
    await flush();
    expect(screen.queryByText("Reset order")).not.toBeInTheDocument();
  });
});
