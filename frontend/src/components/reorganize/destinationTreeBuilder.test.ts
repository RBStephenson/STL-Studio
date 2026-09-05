import { describe, it, expect } from "vitest";
import { mkEntry, mkFileMove } from "../../test/reorganize";
import { buildDestinationTree, NO_DESTINATION_LABEL, type DestinationNode } from "./destinationTreeBuilder";

/** Walks to a node by its rendered labels, so tests read like the UI does. */
function at(nodes: DestinationNode[], ...labels: string[]): DestinationNode {
  let level = nodes;
  let found: DestinationNode | undefined;
  for (const label of labels) {
    found = level.find((n) => n.label === label);
    if (!found) throw new Error(`no node "${label}" among [${level.map((n) => n.label).join(", ")}]`);
    level = found.children;
  }
  return found!;
}

const NONE = new Set<number>();

describe("buildDestinationTree", () => {
  it("groups destinations by common prefix into creator → character → title", () => {
    const roots = buildDestinationTree([
      mkEntry({ model_id: 1, proposed_dir: "/lib/Abe3D/Joker/Bust" }),
      mkEntry({ model_id: 2, proposed_dir: "/lib/Abe3D/Joker/Statue" }),
      mkEntry({ model_id: 3, proposed_dir: "/lib/Abe3D/Batman/Bust" }),
    ], NONE);

    // "/lib" has one child so it collapses into the creator level — and so
    // does Batman, whose single title compacts to "Batman/Bust". Joker has two
    // titles, so it stays a folder with children.
    expect(roots.map((n) => n.label)).toEqual(["/lib/Abe3D"]);
    expect(at(roots, "/lib/Abe3D").children.map((n) => n.label)).toEqual(["Batman/Bust", "Joker"]);
    expect(at(roots, "/lib/Abe3D", "Joker").children.map((n) => n.label)).toEqual(["Bust", "Statue"]);
  });

  it("collapses a single-child spine into one row instead of a ladder", () => {
    const roots = buildDestinationTree(
      [mkEntry({ proposed_dir: "C:/STL Library/Models/Abe3D/Joker/Bust" })],
      NONE,
    );
    expect(roots).toHaveLength(1);
    expect(roots[0].label).toBe("C:/STL Library/Models/Abe3D/Joker/Bust");
    expect(roots[0].children).toHaveLength(0);
  });

  it("stops collapsing at a folder that holds models of its own", () => {
    // Abe3D has one child (Joker) but also a model sitting directly in it, so
    // collapsing it away would lose that model's home.
    const roots = buildDestinationTree([
      mkEntry({ model_id: 1, proposed_dir: "/lib/Abe3D" }),
      mkEntry({ model_id: 2, proposed_dir: "/lib/Abe3D/Joker" }),
    ], NONE);

    expect(roots.map((n) => n.label)).toEqual(["/lib/Abe3D"]);
    expect(at(roots, "/lib/Abe3D").entries.map((e) => e.model_id)).toEqual([1]);
    expect(at(roots, "/lib/Abe3D", "Joker").entries.map((e) => e.model_id)).toEqual([2]);
  });

  it("rolls model, file, blocked and collision counts up the subtree", () => {
    const roots = buildDestinationTree([
      mkEntry({ model_id: 1, proposed_dir: "/lib/Abe3D/Joker/Bust", files: [mkFileMove("a"), mkFileMove("b")] }),
      mkEntry({ model_id: 2, proposed_dir: "/lib/Abe3D/Joker/Statue", files: [mkFileMove("c")], eligible: false, collision: true }),
      mkEntry({ model_id: 3, proposed_dir: "/lib/Abe3D/Batman/Bust", files: [mkFileMove("d")], eligible: false }),
    ], NONE);

    const creator = at(roots, "/lib/Abe3D");
    expect(creator.modelCount).toBe(3);
    expect(creator.fileCount).toBe(4);
    expect(creator.blockedCount).toBe(2);
    expect(creator.collisionCount).toBe(1);

    const joker = at(roots, "/lib/Abe3D", "Joker");
    expect(joker.modelCount).toBe(2);
    expect(joker.fileCount).toBe(3);
    expect(joker.blockedCount).toBe(1);
    expect(joker.collisionCount).toBe(1);
  });

  it("counts a package entry as one package but all of its models", () => {
    const roots = buildDestinationTree([
      mkEntry({
        model_id: 1, proposed_dir: "/lib/Abe3D/Joker/Wave One",
        package_mode: true, model_ids: [1, 2, 3],
      }),
    ], NONE);

    const node = at(roots, "/lib/Abe3D/Joker/Wave One");
    expect(node.entryCount).toBe(1);
    expect(node.modelCount).toBe(3);
  });

  it("selects only what the page says is selectable, not every model below", () => {
    // The whole STUDIO-160 hazard in one assertion: three models under the
    // node, one of them actually selectable.
    const roots = buildDestinationTree([
      mkEntry({ model_id: 1, proposed_dir: "/lib/Abe3D/Joker/Bust" }),
      mkEntry({ model_id: 2, proposed_dir: "/lib/Abe3D/Joker/Statue", eligible: false }),
      mkEntry({ model_id: 3, proposed_dir: "/lib/Abe3D/Batman/Bust", eligible: false }),
    ], new Set([1]));

    const creator = at(roots, "/lib/Abe3D");
    expect(creator.modelCount).toBe(3);
    expect(creator.selectableIds).toEqual([1]);
    expect(at(roots, "/lib/Abe3D", "Batman/Bust").selectableIds).toEqual([]);
  });

  it("attaches the shared character envelope to the character folder, not the package", () => {
    const roots = buildDestinationTree([
      mkEntry({
        model_id: 1, proposed_dir: "/lib/Abe3D/Joker/Wave One",
        package_mode: true, character_proposed_dir: "/lib/Abe3D/Joker",
        character_package_ids: [1, 2], shared_files: [mkFileMove("art.jpg"), mkFileMove("lore.txt")],
      }),
      mkEntry({
        model_id: 2, proposed_dir: "/lib/Abe3D/Joker/Wave Two",
        package_mode: true, character_proposed_dir: "/lib/Abe3D/Joker",
        character_package_ids: [1, 2],
      }),
    ], NONE);

    const character = at(roots, "/lib/Abe3D/Joker");
    expect(character.sharedFileCount).toBe(2);
    expect(character.sharedPackageIds).toEqual([1, 2]);
    // And the packages below it are still two separate nodes.
    expect(character.children.map((n) => n.label)).toEqual(["Wave One", "Wave Two"]);
    expect(at(roots, "/lib/Abe3D/Joker", "Wave One").sharedFileCount).toBe(0);
  });

  it("keeps a character folder that owns an envelope but only one package", () => {
    // Without the envelope this chain would collapse to ".../Joker/Wave One"
    // and the all-packages-or-nothing rule would have nowhere to render.
    const roots = buildDestinationTree([
      mkEntry({
        model_id: 1, proposed_dir: "/lib/Abe3D/Joker/Wave One",
        package_mode: true, character_proposed_dir: "/lib/Abe3D/Joker",
        character_package_ids: [1], shared_files: [mkFileMove("art.jpg")],
      }),
    ], NONE);

    expect(roots.map((n) => n.label)).toEqual(["/lib/Abe3D/Joker"]);
    expect(at(roots, "/lib/Abe3D/Joker").sharedFileCount).toBe(1);
    expect(at(roots, "/lib/Abe3D/Joker").children.map((n) => n.label)).toEqual(["Wave One"]);
  });

  it("counts the envelope's files at the character folder", () => {
    const roots = buildDestinationTree([
      mkEntry({
        model_id: 1, proposed_dir: "/lib/Abe3D/Joker/Wave One", files: [mkFileMove("a")],
        package_mode: true, character_proposed_dir: "/lib/Abe3D/Joker",
        character_package_ids: [1], shared_files: [mkFileMove("art.jpg"), mkFileMove("lore.txt")],
      }),
    ], NONE);

    expect(at(roots, "/lib/Abe3D/Joker").fileCount).toBe(3);
    expect(at(roots, "/lib/Abe3D/Joker", "Wave One").fileCount).toBe(1);
  });

  it("keeps destinations that differ only by case as separate folders", () => {
    // They are two folders in the plan; the collision count is what says they
    // will fight on a case-insensitive filesystem.
    const roots = buildDestinationTree([
      mkEntry({ model_id: 1, proposed_dir: "/lib/Abe3D/joker", collision: true, collision_kind: "case_only" }),
      mkEntry({ model_id: 2, proposed_dir: "/lib/Abe3D/Joker", collision: true, collision_kind: "case_only" }),
    ], NONE);

    expect(at(roots, "/lib/Abe3D").children.map((n) => n.label).sort()).toEqual(["Joker", "joker"]);
    expect(at(roots, "/lib/Abe3D").collisionCount).toBe(2);
  });

  it("buckets an entry with no destination instead of rendering a blank node", () => {
    const roots = buildDestinationTree([
      mkEntry({ model_id: 1, proposed_dir: "" }),
      mkEntry({ model_id: 2, proposed_dir: "/lib/Abe3D/Joker" }),
    ], NONE);

    const bucket = roots.find((n) => n.label === NO_DESTINATION_LABEL);
    expect(bucket).toBeDefined();
    expect(bucket!.entries.map((e) => e.model_id)).toEqual([1]);
  });

  it("keeps a relative destination out of the same bucket as an absolute one", () => {
    const roots = buildDestinationTree([
      mkEntry({ model_id: 1, proposed_dir: "/lib/Abe3D" }),
      mkEntry({ model_id: 2, proposed_dir: "lib/Abe3D" }),
    ], NONE);

    expect(roots.map((n) => n.label).sort()).toEqual(["/lib/Abe3D", "lib/Abe3D"]);
  });

  it("sorts folders and the models inside them by name", () => {
    const roots = buildDestinationTree([
      mkEntry({ model_id: 1, model_name: "Zeta", proposed_dir: "/lib/Abe3D/Joker" }),
      mkEntry({ model_id: 2, model_name: "Alpha", proposed_dir: "/lib/Abe3D/Joker" }),
    ], NONE);

    expect(at(roots, "/lib/Abe3D/Joker").entries.map((e) => e.model_name)).toEqual(["Alpha", "Zeta"]);
  });

  it("returns nothing for an empty manifest", () => {
    expect(buildDestinationTree([], NONE)).toEqual([]);
  });
});
