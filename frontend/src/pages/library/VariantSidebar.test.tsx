/**
 * Variant group side panel (STUDIO-350).
 *
 * Covers the panel in isolation: content states, keyboard dismissal, the
 * width-clamping rules, and the density steps that make rows use the space a
 * wider panel gives them. Library.variantSidebar.test.tsx covers the URL
 * plumbing and the feature flag.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryWrapper } from "../../test/queryWrapper";
import VariantSidebar, {
  PANEL_DEFAULT_WIDTH, PANEL_MIN_WIDTH, clampPanelWidth, maxPanelWidth, rowDensity,
} from "./VariantSidebar";

const variantsMock = vi.fn();

vi.mock("../../api/client", () => ({
  api: {
    models: { variants: (...a: unknown[]) => variantsMock(...a) },
    fileUrl: (p: string) => `/files/${p}`,
  },
}));

function mkVariant(over: Record<string, unknown> = {}) {
  return {
    id: 1, name: "Winged Guardian - Base", title: "Winged Guardian - Base",
    auto_tags: [], removed_auto_tags: [], tags: [], is_group_rep: false,
    variant_group: { label: "Winged Guardian" }, ...over,
  };
}

function renderPanel(props: Partial<React.ComponentProps<typeof VariantSidebar>> = {}) {
  const onClose = vi.fn();
  const onWidthChange = vi.fn();
  const utils = render(
    <QueryWrapper>
      <MemoryRouter>
        <VariantSidebar
          groupId={1}
          fallbackLabel="Winged Guardian"
          fullViewTo="/groups/1/Winged%20Guardian?gid=1"
          onClose={onClose}
          width={PANEL_DEFAULT_WIDTH}
          onWidthChange={onWidthChange}
          {...props}
        />
      </MemoryRouter>
    </QueryWrapper>,
  );
  return { ...utils, onClose, onWidthChange };
}

beforeEach(() => {
  variantsMock.mockReset();
  variantsMock.mockResolvedValue({ items: [mkVariant()], total: 1 });
});

describe("VariantSidebar content states", () => {
  it("fetches the group by id, not by creator/character", async () => {
    renderPanel({ groupId: 42 });
    await waitFor(() => expect(variantsMock).toHaveBeenCalled());
    expect(variantsMock.mock.calls[0][2]).toBe(42);
  });

  it("shows a loading skeleton before the fetch resolves", () => {
    variantsMock.mockReturnValue(new Promise(() => {}));
    renderPanel();
    expect(screen.getByLabelText("Loading variants")).toBeInTheDocument();
  });

  it("lists the variants once loaded", async () => {
    variantsMock.mockResolvedValue({
      items: [mkVariant(), mkVariant({ id: 2, title: "Winged Guardian - Flying pose" })],
      total: 2,
    });
    renderPanel();
    expect(await screen.findByText("Winged Guardian - Flying pose")).toBeInTheDocument();
    expect(screen.getByText("2 variants")).toBeInTheDocument();
  });

  it("offers a retry when the fetch fails", async () => {
    variantsMock.mockRejectedValue(new Error("boom"));
    renderPanel();
    expect(await screen.findByRole("button", { name: /try again/i })).toBeInTheDocument();
  });

  it("says so when the group is empty rather than rendering a blank panel", async () => {
    variantsMock.mockResolvedValue({ items: [], total: 0 });
    renderPanel();
    expect(await screen.findByText(/no models in it/i)).toBeInTheDocument();
  });

  it("marks the representative variant", async () => {
    variantsMock.mockResolvedValue({ items: [mkVariant({ is_group_rep: true })], total: 1 });
    renderPanel();
    expect(await screen.findByText("REP")).toBeInTheDocument();
  });

  it("shows the model's tags, auto tags included and removed ones excluded", async () => {
    variantsMock.mockResolvedValue({
      items: [mkVariant({ auto_tags: ["statue", "bust"], removed_auto_tags: ["bust"], tags: ["mine"] })],
      total: 1,
    });
    renderPanel();
    expect(await screen.findByText("statue")).toBeInTheDocument();
    expect(screen.getByText("mine")).toBeInTheDocument();
    expect(screen.queryByText("bust")).not.toBeInTheDocument();
  });

  it("links each row to its model and the footer to the full group page", async () => {
    renderPanel();
    const row = await screen.findByRole("link", { name: /Winged Guardian - Base/ });
    expect(row).toHaveAttribute("href", "/models/1");
    expect(screen.getByRole("link", { name: /open full view/i }))
      .toHaveAttribute("href", "/groups/1/Winged%20Guardian?gid=1");
  });
});

describe("VariantSidebar dismissal", () => {
  it("closes on the close button", async () => {
    const { onClose } = renderPanel();
    await userEvent.click(screen.getByRole("button", { name: /close variants panel/i }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("closes on Escape", async () => {
    const { onClose } = renderPanel();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("stops listening for Escape once unmounted", () => {
    const { onClose, unmount } = renderPanel();
    unmount();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();
  });
});

describe("panel width rules", () => {
  it("never goes below the minimum", () => {
    expect(clampPanelWidth(100, 1600)).toBe(PANEL_MIN_WIDTH);
  });

  it("never takes more than its share of a narrow window", () => {
    // 45% of 900 = 405; a stored 700 from a wider monitor must not starve the grid.
    expect(clampPanelWidth(700, 900)).toBe(405);
  });

  it("caps at the hard ceiling on a very wide window", () => {
    expect(maxPanelWidth(4000)).toBe(720);
  });

  it("keeps the minimum usable even on a tiny window", () => {
    expect(maxPanelWidth(400)).toBe(PANEL_MIN_WIDTH);
  });
});

describe("row density follows the panel width", () => {
  it("uses compact rows at the default width", () => {
    expect(rowDensity(PANEL_DEFAULT_WIDTH)).toMatchObject({ thumb: 56, tags: 3 });
  });

  it("grows thumbnails and shows more tags as the panel widens", () => {
    const narrow = rowDensity(380);
    const mid = rowDensity(500);
    const wide = rowDensity(700);
    expect(mid.thumb).toBeGreaterThan(narrow.thumb);
    expect(wide.thumb).toBeGreaterThan(mid.thumb);
    expect(mid.tags).toBeGreaterThan(narrow.tags);
    expect(wide.tags).toBeGreaterThan(mid.tags);
  });

  it("renders more tag chips at a wider width", async () => {
    const tags = ["a", "b", "c", "d", "e", "f"];
    variantsMock.mockResolvedValue({ items: [mkVariant({ auto_tags: tags })], total: 1 });
    const { unmount } = renderPanel({ width: 380 });
    expect(await screen.findByText("+3")).toBeInTheDocument();  // 3 shown, 3 hidden
    unmount();

    renderPanel({ width: 700 });
    expect(await screen.findByText("+1")).toBeInTheDocument();  // 5 shown, 1 hidden
  });
});

describe("resize handle", () => {
  it("is reachable and adjustable from the keyboard", async () => {
    const { onWidthChange } = renderPanel({ width: 400 });
    const handle = screen.getByRole("separator", { name: /resize variants panel/i });
    expect(handle).toHaveAttribute("tabIndex", "0");

    fireEvent.keyDown(handle, { key: "ArrowLeft" });
    expect(onWidthChange).toHaveBeenLastCalledWith(416);   // left widens a right-docked panel

    fireEvent.keyDown(handle, { key: "ArrowRight" });
    expect(onWidthChange).toHaveBeenLastCalledWith(384);

    fireEvent.keyDown(handle, { key: "End" });
    expect(onWidthChange).toHaveBeenLastCalledWith(PANEL_MIN_WIDTH);
  });

  it("resets to the default width on double-click", async () => {
    const { onWidthChange } = renderPanel({ width: 640 });
    fireEvent.doubleClick(screen.getByRole("separator", { name: /resize variants panel/i }));
    expect(onWidthChange).toHaveBeenCalledWith(PANEL_DEFAULT_WIDTH);
  });

  it("exposes its range to assistive tech", () => {
    renderPanel({ width: 400 });
    const handle = screen.getByRole("separator", { name: /resize variants panel/i });
    expect(handle).toHaveAttribute("aria-valuenow", "400");
    expect(handle).toHaveAttribute("aria-valuemin", String(PANEL_MIN_WIDTH));
  });
});
