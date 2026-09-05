import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import type { ReorganizeEntry } from "../../api/client";
import { mkEntry, mkFileMove } from "../../test/reorganize";
import DestinationTree from "./DestinationTree";

function renderTree(over: {
  entries?: ReorganizeEntry[];
  selectableIds?: Set<number>;
  selected?: Set<number>;
  onSelect?: (ids: number[], select: boolean) => void;
  packageMode?: boolean;
} = {}) {
  const onSelect = over.onSelect ?? vi.fn();
  const entries = over.entries ?? [mkEntry()];
  render(
    <DestinationTree
      entries={entries}
      selectableIds={over.selectableIds ?? new Set(entries.map((e) => e.model_id))}
      selected={over.selected ?? new Set()}
      onSelect={onSelect}
      packageMode={over.packageMode ?? false}
    />,
  );
  return { onSelect };
}

describe("DestinationTree", () => {
  it("renders the destination folders with rolled-up counts", () => {
    renderTree({
      entries: [
        mkEntry({ model_id: 1, proposed_dir: "/lib/Abe3D/Joker/Bust", files: [mkFileMove("a"), mkFileMove("b")] }),
        mkEntry({ model_id: 2, proposed_dir: "/lib/Abe3D/Joker/Statue", files: [mkFileMove("c")] }),
      ],
    });
    expect(screen.getByText("/lib/Abe3D/Joker")).toBeInTheDocument();
    expect(screen.getByText(/2 models · 3 files/)).toBeInTheDocument();
  });

  it("counts packages as well as models in package mode", () => {
    renderTree({
      packageMode: true,
      entries: [
        mkEntry({ model_id: 1, proposed_dir: "/lib/Abe3D/Joker/Wave One", package_mode: true, model_ids: [1, 2, 3] }),
      ],
    });
    expect(screen.getByText(/1 package · 3 models/)).toBeInTheDocument();
  });

  it("says how many models a node will select before it applies", () => {
    // The STUDIO-160 hazard: the node covers three models but only two are
    // eligible, and the checkbox has to name the number it will actually act on.
    renderTree({
      entries: [
        mkEntry({ model_id: 1, proposed_dir: "/lib/Abe3D/Joker/Bust" }),
        mkEntry({ model_id: 2, proposed_dir: "/lib/Abe3D/Joker/Statue" }),
        mkEntry({ model_id: 3, proposed_dir: "/lib/Abe3D/Joker/Cape", eligible: false }),
      ],
      selectableIds: new Set([1, 2]),
    });
    expect(
      screen.getByRole("checkbox", { name: "Select 2 eligible models under /lib/Abe3D/Joker" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/3 models · 0 files · 2 eligible/)).toBeInTheDocument();
  });

  it("selects every eligible model beneath a node and none of the blocked ones", () => {
    const { onSelect } = renderTree({
      entries: [
        mkEntry({ model_id: 1, proposed_dir: "/lib/Abe3D/Joker/Bust" }),
        mkEntry({ model_id: 2, proposed_dir: "/lib/Abe3D/Joker/Statue" }),
        mkEntry({ model_id: 3, proposed_dir: "/lib/Abe3D/Joker/Cape", eligible: false }),
      ],
      selectableIds: new Set([1, 2]),
    });
    fireEvent.click(screen.getByRole("checkbox", { name: /Select 2 eligible models under/ }));
    expect(onSelect).toHaveBeenCalledWith([1, 2], true);
  });

  it("deselects a fully-selected node instead of re-selecting it", () => {
    const { onSelect } = renderTree({
      entries: [
        mkEntry({ model_id: 1, proposed_dir: "/lib/Abe3D/Joker/Bust" }),
        mkEntry({ model_id: 2, proposed_dir: "/lib/Abe3D/Joker/Statue" }),
      ],
      selected: new Set([1, 2]),
    });
    const box = screen.getByRole("checkbox", { name: /Deselect 2 eligible models under/ });
    expect(box).toBeChecked();
    fireEvent.click(box);
    expect(onSelect).toHaveBeenCalledWith([1, 2], false);
  });

  it("shows a half-selected node as indeterminate, not as unchecked", () => {
    renderTree({
      entries: [
        mkEntry({ model_id: 1, proposed_dir: "/lib/Abe3D/Joker/Bust" }),
        mkEntry({ model_id: 2, proposed_dir: "/lib/Abe3D/Joker/Statue" }),
      ],
      selected: new Set([1]),
    });
    const box = screen.getByRole("checkbox", { name: /Select 2 eligible models under/ }) as HTMLInputElement;
    expect(box.checked).toBe(false);
    expect(box.indeterminate).toBe(true);
  });

  it("offers no checkbox at all on a branch with nothing selectable", () => {
    renderTree({
      entries: [mkEntry({ model_id: 1, proposed_dir: "/lib/Abe3D/Joker/Bust", eligible: false, locked: true })],
      selectableIds: new Set(),
    });
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });

  it("flags a problem branch without needing it expanded", () => {
    renderTree({
      entries: [
        mkEntry({ model_id: 1, proposed_dir: "/lib/Abe3D/Joker/Bust", eligible: false, collision: true }),
        mkEntry({ model_id: 2, proposed_dir: "/lib/Abe3D/Joker/Statue", eligible: false, locked: true }),
      ],
      selectableIds: new Set(),
    });
    // Asserted on the parent row specifically: the whole point is that the
    // branch advertises the problem while its contents are still collapsed.
    const branch = screen.getByTitle("/lib/Abe3D/Joker").closest("div")!;
    expect(within(branch).getByText("1 collision")).toBeInTheDocument();
    expect(within(branch).getByText("2 blocked")).toBeInTheDocument();
  });

  it("keeps descendants hidden until their folder is expanded", () => {
    renderTree({
      entries: [
        mkEntry({ model_id: 1, model_name: "Joker Bust", proposed_dir: "/lib/Abe3D/Joker/Bust" }),
        mkEntry({ model_id: 2, model_name: "Joker Statue", proposed_dir: "/lib/Abe3D/Joker/Statue" }),
      ],
    });
    // The root is open by default; its children are not.
    expect(screen.queryByText("Joker Bust")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Expand Bust" }));
    expect(screen.getByText("Joker Bust")).toBeInTheDocument();
    expect(screen.queryByText("Joker Statue")).not.toBeInTheDocument();
  });

  it("collapses an open folder again", () => {
    renderTree({
      entries: [mkEntry({ model_id: 1, model_name: "Joker Bust", proposed_dir: "/lib/Abe3D/Joker/Bust" })],
    });
    // A single chain collapses to one root node, which starts open.
    expect(screen.getByText("Joker Bust")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Collapse/ }));
    expect(screen.queryByText("Joker Bust")).not.toBeInTheDocument();
  });

  it("shows a model's kind and its blockers on the leaf row", () => {
    renderTree({
      entries: [mkEntry({
        model_id: 1, model_name: "Joker Bust", proposed_dir: "/lib/Abe3D/Joker/Bust",
        eligible: false, locked: true, kind: "rename",
      })],
      selectableIds: new Set(),
    });
    expect(screen.getByText("rename")).toBeInTheDocument();
    expect(screen.getByText("locked")).toBeInTheDocument();
  });

  it("warns that shared character files stay put until every package is selected", () => {
    renderTree({
      packageMode: true,
      entries: [
        mkEntry({
          model_id: 1, proposed_dir: "/lib/Abe3D/Joker/Wave One", package_mode: true,
          character_proposed_dir: "/lib/Abe3D/Joker", character_package_ids: [1, 2],
          shared_files: [mkFileMove("art.jpg")],
        }),
        mkEntry({ model_id: 2, proposed_dir: "/lib/Abe3D/Joker/Wave Two", package_mode: true, character_package_ids: [1, 2] }),
      ],
      selected: new Set([1]),
    });
    expect(
      screen.getByText(/1 shared character file will remain unless all 2 packages are selected/),
    ).toBeInTheDocument();
  });

  it("confirms the envelope moves once every package is selected", () => {
    renderTree({
      packageMode: true,
      entries: [
        mkEntry({
          model_id: 1, proposed_dir: "/lib/Abe3D/Joker/Wave One", package_mode: true,
          character_proposed_dir: "/lib/Abe3D/Joker", character_package_ids: [1, 2],
          shared_files: [mkFileMove("art.jpg")],
        }),
        mkEntry({ model_id: 2, proposed_dir: "/lib/Abe3D/Joker/Wave Two", package_mode: true, character_package_ids: [1, 2] }),
      ],
      selected: new Set([1, 2]),
    });
    expect(
      screen.getByText(/1 shared character file will move with the complete character/),
    ).toBeInTheDocument();
  });

  it("caps how many children it draws at once and offers the rest on request", () => {
    // Lazy expansion is the answer to a wide library, but one folder holding
    // thousands of models would still render them all the moment it opened.
    const many = Array.from({ length: 205 }, (_, i) =>
      mkEntry({ model_id: i + 1, model_name: `Model ${i}`, proposed_dir: `/lib/Abe3D/Char${i}` }),
    );
    renderTree({ entries: many });

    expect(screen.getByText(/Show 5 more under \/lib\/Abe3D/)).toBeInTheDocument();
    expect(screen.getAllByTitle(/^\/lib\/Abe3D\/Char/)).toHaveLength(200);
    fireEvent.click(screen.getByText(/Show 5 more under/));
    expect(screen.getAllByTitle(/^\/lib\/Abe3D\/Char/)).toHaveLength(205);
  });

  it("says so plainly when the current filter leaves no destinations", () => {
    renderTree({ entries: [] });
    expect(screen.getByText("No destinations in this view.")).toBeInTheDocument();
  });
});
