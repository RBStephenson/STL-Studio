import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import TagsPanel from "./TagsPanel";

type Props = React.ComponentProps<typeof TagsPanel>;

const defaults: Props = {
  tags: [],
  autoTags: [],
  removedAutoTags: [],
  editingTags: false,
  tagSuggestions: [],
  showHiddenTags: false,
  onSetUserTags: vi.fn(),
  onDoneEditing: vi.fn(),
  onOpenEditor: vi.fn(),
  onAdd: vi.fn(),
  onSuppress: vi.fn(),
  onRestore: vi.fn(),
  onToggleHidden: vi.fn(),
};

const renderPanel = (over: Partial<Props> = {}) =>
  render(
    <MemoryRouter>
      <TagsPanel {...defaults} {...over} />
    </MemoryRouter>
  );

describe("TagsPanel", () => {
  it("renders user tags as browse links and an Edit/Add button", () => {
    renderPanel({ tags: ["dragon", "hero"] });
    expect(screen.getByRole("link", { name: "dragon" })).toHaveAttribute("href", "/?tag=dragon");
    expect(screen.getByRole("button", { name: /Edit tags/ })).toBeInTheDocument();
  });

  it("shows 'Add tag' when there are no tags and calls onOpenEditor", () => {
    const onOpenEditor = vi.fn();
    renderPanel({ onOpenEditor });
    fireEvent.click(screen.getByRole("button", { name: /Add tag/ }));
    expect(onOpenEditor).toHaveBeenCalled();
  });

  it("lists visible auto tags (excluding removed) and fires onAdd / onSuppress", () => {
    const onAdd = vi.fn();
    const onSuppress = vi.fn();
    renderPanel({ autoTags: ["knight", "gone"], removedAutoTags: ["gone"], onAdd, onSuppress });
    // "gone" is suppressed → not shown among visible auto tags
    expect(screen.getByText("Auto-detected · click + to add as tag · × to remove · click label to browse")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "knight" })).toBeInTheDocument();
    const addBtn = screen.getByTitle("Add as user tag");
    fireEvent.click(addBtn);
    expect(onAdd).toHaveBeenCalledWith("knight");
    fireEvent.click(screen.getByTitle("Remove this auto-detected tag"));
    expect(onSuppress).toHaveBeenCalledWith("knight");
  });

  it("disables the add control for auto tags already promoted", () => {
    renderPanel({ tags: ["knight"], autoTags: ["knight"] });
    expect(screen.getByTitle("Already a tag")).toBeDisabled();
  });

  it("shows a collapsed hidden-tags toggle and restores on click when expanded", () => {
    const onRestore = vi.fn();
    renderPanel({ autoTags: ["ghost"], removedAutoTags: ["ghost"], showHiddenTags: true, onRestore });
    expect(screen.getByText(/1 hidden auto-tag/)).toBeInTheDocument();
    fireEvent.click(screen.getByTitle("Restore this auto-detected tag"));
    expect(onRestore).toHaveBeenCalledWith("ghost");
  });
});
