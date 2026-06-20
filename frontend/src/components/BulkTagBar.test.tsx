import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import BulkTagBar from "./BulkTagBar";
import { Collection } from "../api/client";

vi.mock("../api/client", () => ({
  api: {
    models: {
      bulkTag: vi.fn(async () => ({ ok: true, updated: 2 })),
      bulkExclude: vi.fn(async () => ({ ok: true, updated: 2 })),
      bulkReview: vi.fn(async () => ({ ok: true, updated: 2 })),
      bulkEnrich: vi.fn(async () => ({ ok: true, updated: 2 })),
    },
    collections: {
      bulkAddModels: vi.fn(async () => ({ ok: true })),
    },
  },
}));

// confirm resolves true by default; individual tests can override.
const confirmMock = vi.fn(async () => true);
vi.mock("../context/ConfirmContext", () => ({ useConfirm: () => confirmMock }));
const toastMock = vi.fn();
vi.mock("../context/ToastContext", () => ({ useToast: () => ({ toast: toastMock }) }));

import { api } from "../api/client";

const COLLECTIONS: Collection[] = [];

const baseProps = () => ({
  selectedIds: [1, 2],
  totalOnPage: 5,
  onSelectAll: vi.fn(),
  onClear: vi.fn(),
  onDone: vi.fn(),
  collections: COLLECTIONS,
});

describe("BulkTagBar bulk actions (#164)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    confirmMock.mockResolvedValue(true);
  });

  it("shows the selection count", () => {
    render(<BulkTagBar {...baseProps()} />);
    expect(screen.getByText("2 selected")).toBeInTheDocument();
  });

  it("flags selected models for review and clears selection", async () => {
    const props = baseProps();
    render(<BulkTagBar {...props} />);
    fireEvent.click(screen.getByRole("button", { name: /mark review/i }));
    await waitFor(() => expect(vi.mocked(api.models.bulkReview)).toHaveBeenCalledWith([1, 2], true));
    expect(props.onDone).toHaveBeenCalled();
    expect(props.onClear).toHaveBeenCalled();
    expect(toastMock).toHaveBeenCalledWith(expect.stringMatching(/review/i), "success");
  });

  it("confirms before hiding, then excludes and clears selection", async () => {
    const props = baseProps();
    render(<BulkTagBar {...props} />);
    fireEvent.click(screen.getByRole("button", { name: /^hide$/i }));
    await waitFor(() => expect(confirmMock).toHaveBeenCalled());
    await waitFor(() => expect(vi.mocked(api.models.bulkExclude)).toHaveBeenCalledWith([1, 2], true));
    expect(props.onClear).toHaveBeenCalled();
  });

  it("does not exclude when the confirm is declined", async () => {
    confirmMock.mockResolvedValue(false);
    const props = baseProps();
    render(<BulkTagBar {...props} />);
    fireEvent.click(screen.getByRole("button", { name: /^hide$/i }));
    await waitFor(() => expect(confirmMock).toHaveBeenCalled());
    expect(vi.mocked(api.models.bulkExclude)).not.toHaveBeenCalled();
    expect(props.onClear).not.toHaveBeenCalled();
  });

  it("sizes the Hide button like the other action buttons (#381)", () => {
    render(<BulkTagBar {...baseProps()} />);
    const hide = screen.getByRole("button", { name: /^hide$/i });
    const addTags = screen.getByRole("button", { name: /add tags/i });
    // Same padding/sizing + shrink-0 so Hide stays inside the toolbar, aligned.
    for (const cls of ["px-3", "py-1.5", "shrink-0", "text-sm"]) {
      expect(hide).toHaveClass(cls);
      expect(addTags).toHaveClass(cls);
    }
  });

  it("adds tags via the bulk endpoint", async () => {
    render(<BulkTagBar {...baseProps()} />);
    fireEvent.click(screen.getByRole("button", { name: /add tags/i }));
    fireEvent.change(screen.getByPlaceholderText("tag1, tag2, tag3…"), { target: { value: "foo, bar" } });
    fireEvent.click(screen.getByRole("button", { name: /apply/i }));
    await waitFor(() => expect(vi.mocked(api.models.bulkTag)).toHaveBeenCalledWith([1, 2], ["foo", "bar"], []));
  });
});

describe("BulkTagBar enrich mode (#429)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows enrich button in idle mode", () => {
    render(<BulkTagBar {...baseProps()} />);
    expect(screen.getByRole("button", { name: /enrich/i })).toBeInTheDocument();
  });

  it("shows creator/character/title fields when enrich mode active", () => {
    render(<BulkTagBar {...baseProps()} />);
    fireEvent.click(screen.getByRole("button", { name: /enrich/i }));
    expect(screen.getByPlaceholderText("Creator")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Character")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Title")).toBeInTheDocument();
  });

  it("Apply is disabled when all fields empty", () => {
    render(<BulkTagBar {...baseProps()} />);
    fireEvent.click(screen.getByRole("button", { name: /enrich/i }));
    expect(screen.getByRole("button", { name: /apply/i })).toBeDisabled();
  });

  it("calls bulkEnrich with only filled fields", async () => {
    render(<BulkTagBar {...baseProps()} />);
    fireEvent.click(screen.getByRole("button", { name: /enrich/i }));
    fireEvent.change(screen.getByPlaceholderText("Creator"), { target: { value: "Some Creator" } });
    fireEvent.click(screen.getByRole("button", { name: /apply/i }));
    await waitFor(() =>
      expect(vi.mocked(api.models.bulkEnrich)).toHaveBeenCalledWith([1, 2], { creator_name: "Some Creator" })
    );
  });

  it("calls bulkEnrich with all three fields when all provided", async () => {
    render(<BulkTagBar {...baseProps()} />);
    fireEvent.click(screen.getByRole("button", { name: /enrich/i }));
    fireEvent.change(screen.getByPlaceholderText("Creator"), { target: { value: "MC" } });
    fireEvent.change(screen.getByPlaceholderText("Character"), { target: { value: "Orc" } });
    fireEvent.change(screen.getByPlaceholderText("Title"), { target: { value: "Big Pack" } });
    fireEvent.click(screen.getByRole("button", { name: /apply/i }));
    await waitFor(() =>
      expect(vi.mocked(api.models.bulkEnrich)).toHaveBeenCalledWith(
        [1, 2],
        { creator_name: "MC", character: "Orc", title: "Big Pack" }
      )
    );
  });

  it("resets to idle on Escape", () => {
    render(<BulkTagBar {...baseProps()} />);
    fireEvent.click(screen.getByRole("button", { name: /enrich/i }));
    fireEvent.keyDown(screen.getByPlaceholderText("Creator"), { key: "Escape" });
    expect(screen.getByRole("button", { name: /enrich/i })).toBeInTheDocument();
  });
});
