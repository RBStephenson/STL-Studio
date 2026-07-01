import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route, useLocation } from "react-router-dom";
import VariantGroup from "./VariantGroup";

const mergeGroup = vi.fn();
const splitGroup = vi.fn();
const patchGroup = vi.fn();
const batchThumbnailFromUrl = vi.fn();
const applyGroup = vi.fn();
const setGroupRep = vi.fn();
const reorderGroup = vi.fn();
const variantsMock = vi.fn();
const toast = vi.fn();

vi.mock("../api/client", () => ({
  api: {
    models: {
      variants: (...a: unknown[]) => variantsMock(...a),
      characters: vi.fn().mockResolvedValue(["Rocky", "Apollo"]),
      mergeGroup: (...a: unknown[]) => mergeGroup(...a),
      splitGroup: (...a: unknown[]) => splitGroup(...a),
      patchGroup: (...a: unknown[]) => patchGroup(...a),
      batchThumbnailFromUrl: (...a: unknown[]) => batchThumbnailFromUrl(...a),
      setGroupRep: (...a: unknown[]) => setGroupRep(...a),
      reorderGroup: (...a: unknown[]) => reorderGroup(...a),
    },
    scrape: {
      applyGroup: (...a: unknown[]) => applyGroup(...a),
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

// gid=5 mirrors modelLinkTo's real links: every durable group carries one
// post-#678, and moveToGroup/removeFromGroup/saveRename all depend on it.
const renderPage = () =>
  render(
    <MemoryRouter initialEntries={["/groups/3/Rocky?gid=5"]}>
      <Routes>
        <Route path="/groups/:creatorId/:character" element={<><VariantGroup /><LocationProbe /></>} />
        <Route path="*" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  );

const flush = () => act(async () => { await Promise.resolve(); });

beforeEach(() => {
  mergeGroup.mockReset();
  splitGroup.mockReset();
  patchGroup.mockReset();
  batchThumbnailFromUrl.mockReset();
  applyGroup.mockReset();
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
    // The lookup call (variantsMock, same fixture) finds no rep with a
    // variant_group_id, so this creates a brand-new durable group labeled "Apollo".
    mergeGroup.mockResolvedValue({ id: 99, creator_id: 3, label: "Apollo", rep_model_id: null, source: "manual", reason: null, confidence: null });
    renderPage();
    await flush();

    fireEvent.click(screen.getByLabelText("Select Bust"));
    fireEvent.click(screen.getByLabelText("Move selected to group"));
    fireEvent.change(screen.getByLabelText("Target group"), { target: { value: "Apollo" } });
    await act(async () => { fireEvent.click(screen.getByText("Move")); });

    expect(mergeGroup).toHaveBeenCalledWith([10], { label: "Apollo" });
    await waitFor(() => expect(screen.queryByTestId("card-10")).toBeNull());
    expect(screen.getByTestId("card-11")).toBeTruthy();
  });

  it("moves selected models into an existing durable group when the target already has one", async () => {
    variantsMock.mockImplementation((_creatorId: number, character: string) =>
      character === "Apollo"
        ? Promise.resolve({ items: [{ id: 20, variant_group_id: 7, variant_group: { label: "Apollo Creed" } }] })
        : Promise.resolve({
            items: [
              { id: 10, name: "Bust", character: "Rocky", is_group_rep: false },
              { id: 11, name: "Full size", character: "Rocky", is_group_rep: false },
            ],
          }),
    );
    mergeGroup.mockResolvedValue({ id: 7, creator_id: 3, label: "Apollo Creed", rep_model_id: 20, source: "manual", reason: null, confidence: null });
    renderPage();
    await flush();

    fireEvent.click(screen.getByLabelText("Select Bust"));
    fireEvent.click(screen.getByLabelText("Move selected to group"));
    fireEvent.change(screen.getByLabelText("Target group"), { target: { value: "Apollo" } });
    await act(async () => { fireEvent.click(screen.getByText("Move")); });

    expect(mergeGroup).toHaveBeenCalledWith([10], { groupId: 7, label: "Apollo Creed" });
  });

  it("ungroups all selected models and navigates back when the group empties", async () => {
    splitGroup.mockResolvedValue({ ok: true, removed: [10, 11] });
    renderPage();
    await flush();

    fireEvent.click(screen.getByText("Select all"));
    await act(async () => { fireEvent.click(screen.getByText("Ungroup")); });

    expect(splitGroup).toHaveBeenCalledWith(5, [10, 11]);
    await waitFor(() => expect(screen.getByTestId("loc").textContent).toBe("/"));
  });

  it("renames the whole group and navigates to the new group URL", async () => {
    patchGroup.mockResolvedValue({ id: 5, creator_id: 3, label: "Rocky II", rep_model_id: null, source: "manual", reason: null, confidence: null });
    renderPage();
    await flush();

    fireEvent.click(screen.getByRole("button", { name: /Rocky/ }));
    fireEvent.change(screen.getByLabelText("Group name"), { target: { value: "Rocky II" } });
    await act(async () => { fireEvent.click(screen.getByLabelText("Save name")); });

    expect(patchGroup).toHaveBeenCalledWith(5, { label: "Rocky II" });
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

  it("sets the store page on the selected members + fetches/applies (#545) and refetches", async () => {
    applyGroup.mockResolvedValue({
      applied: 1, scraped: true, source_site: "myminifactory", missing: [],
      message: "Fetched and applied to 1 variant(s).",
    });
    renderPage();
    await flush();

    fireEvent.click(screen.getByLabelText("Select Bust"));
    fireEvent.click(screen.getByLabelText("Set store page for selected"));
    fireEvent.change(screen.getByLabelText("Store page URL"), {
      target: { value: "https://www.myminifactory.com/object/x-1" },
    });
    await act(async () => { fireEvent.click(screen.getByText("Apply")); });

    expect(applyGroup).toHaveBeenCalledWith([10], "https://www.myminifactory.com/object/x-1");
    expect(toast).toHaveBeenCalledWith(expect.stringContaining("Fetched and applied"), "success");
    // Refetched so the grid reflects the change.
    expect(variantsMock).toHaveBeenCalledTimes(2);
  });

  it("reports skipped models + info toast when the site can't be scraped (#545)", async () => {
    applyGroup.mockResolvedValue({
      applied: 2, scraped: false, source_site: "patreon.com", missing: [11],
      message: "Store page set on 2 variant(s); metadata couldn't be fetched for this site.",
    });
    renderPage();
    await flush();

    fireEvent.click(screen.getByText("Select all"));
    fireEvent.click(screen.getByLabelText("Set store page for selected"));
    fireEvent.change(screen.getByLabelText("Store page URL"), {
      target: { value: "https://www.patreon.com/x" },
    });
    await act(async () => { fireEvent.click(screen.getByText("Apply")); });

    expect(applyGroup).toHaveBeenCalledWith([10, 11], "https://www.patreon.com/x");
    expect(toast).toHaveBeenCalledWith(expect.stringContaining("1 skipped"), "info");
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

  // No ?gid= on the URL — shouldn't happen via modelLinkTo post-#678, but guard
  // the durable-write paths against it rather than calling split/patch with a
  // garbage id.
  const renderPageNoGid = () =>
    render(
      <MemoryRouter initialEntries={["/groups/3/Rocky"]}>
        <Routes>
          <Route path="/groups/:creatorId/:character" element={<><VariantGroup /><LocationProbe /></>} />
          <Route path="*" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>,
    );

  it("refuses to ungroup without a durable group id", async () => {
    renderPageNoGid();
    await flush();

    fireEvent.click(screen.getByText("Select all"));
    await act(async () => { fireEvent.click(screen.getByText("Ungroup")); });

    expect(splitGroup).not.toHaveBeenCalled();
    expect(toast).toHaveBeenCalledWith(expect.stringContaining("no durable group id"), "error");
  });

  it("refuses to rename without a durable group id", async () => {
    renderPageNoGid();
    await flush();

    fireEvent.click(screen.getByRole("button", { name: /Rocky/ }));
    fireEvent.change(screen.getByLabelText("Group name"), { target: { value: "Rocky II" } });
    await act(async () => { fireEvent.click(screen.getByLabelText("Save name")); });

    expect(patchGroup).not.toHaveBeenCalled();
    expect(toast).toHaveBeenCalledWith(expect.stringContaining("no durable group id"), "error");
  });
});
