import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Queue from "./Queue";
import { QueryWrapper } from "../test/queryWrapper";
import type { Model } from "../api/client";

const list = vi.fn();
const reorderQueue = vi.fn();
const setPrintStatus = vi.fn();
const toastMock = vi.fn();

vi.mock("../context/NSFWContext", () => ({ useNSFW: () => ({ showNSFW: true }) }));
vi.mock("../context/AppSettingsContext", () => ({ useAppSettings: () => ({ settings: { recent_days: 30 } }) }));
vi.mock("../context/ToastContext", () => ({ useToast: () => ({ toast: toastMock }) }));
vi.mock("../components/QuickAssignPopover", () => ({ default: () => null }));

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      models: {
        ...actual.api.models,
        list: (...a: unknown[]) => list(...a),
        reorderQueue: (...a: unknown[]) => reorderQueue(...a),
        setPrintStatus: (...a: unknown[]) => setPrintStatus(...a),
        setFavorite: vi.fn(async () => ({ ok: true, is_favorite: false })),
        setRating: vi.fn(async () => ({ ok: true, user_rating: 4 })),
        setNSFW: vi.fn(async () => ({ ok: true })),
        setExcluded: vi.fn(async () => ({ ok: true, excluded: false })),
        update: vi.fn(async () => ({})),
        variants: vi.fn(async () => ({ items: [] })),
      },
      collections: { list: vi.fn(async () => []) },
      fileUrl: (p: string) => p,
    },
  };
});

const queuedModel = {
  id: 7,
  name: "Dragon",
  title: "Dragon",
  character: null,
  variant_count: 1,
  nsfw: false,
  is_favorite: false,
  needs_review: false,
  print_status: "queued",
  print_count: 0,
  auto_tags: [],
  tags: [],
  thumbnail_path: null,
  thumbnail_url: null,
  source_site: null,
  creator_id: 1,
  created_at: "2020-01-01T00:00:00",
  updated_at: "2020-01-01T00:00:00",
} as unknown as Model;

function renderQueue() {
  return render(
    <QueryWrapper>
      <MemoryRouter>
        <Queue />
      </MemoryRouter>
    </QueryWrapper>
  );
}

describe("Queue loading skeleton", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("shows the loading skeleton while pending, then swaps to real content", async () => {
    let resolveList!: (v: { items: Model[]; total: number }) => void;
    list.mockReturnValue(new Promise((resolve) => { resolveList = resolve; }));
    renderQueue();

    expect(screen.getByTestId("queue-loading-skeleton")).toBeInTheDocument();
    expect(screen.queryByText("Dragon")).toBeNull();

    resolveList({ items: [queuedModel], total: 1 });
    expect(await screen.findAllByText("Dragon")).not.toHaveLength(0);
    expect(screen.queryByTestId("queue-loading-skeleton")).toBeNull();
  });
});

describe("Queue error state", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    reorderQueue.mockResolvedValue({ ok: true, updated: 0 });
  });

  it("shows the shared error state when the queue fails to load, with a working Retry", async () => {
    list.mockRejectedValueOnce(new Error("Network down"));
    renderQueue();

    expect(await screen.findByRole("alert")).toHaveTextContent("Something went wrong loading your queue.");
    expect(screen.getByText("Couldn't load the print queue")).toBeInTheDocument();

    list.mockImplementation(async (params: Record<string, unknown>) => {
      if (params.print_status === "queued") return { items: [queuedModel], total: 1 };
      return { items: [], total: 0 };
    });
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(await screen.findByText("Dragon")).toBeInTheDocument();
  });
});

describe("Queue cache coherence (#848)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setPrintStatus.mockResolvedValue({ ok: true, print_status: "printing", print_count: 0 });
    reorderQueue.mockResolvedValue({ ok: true, updated: 0 });
    list.mockImplementation(async (params: Record<string, unknown>) => {
      if (params.print_status === "queued") {
        return { items: setPrintStatus.mock.calls.length ? [] : [queuedModel], total: 1 };
      }
      if (params.print_status === "printed") {
        return { items: [], total: 0 };
      }
      return { items: [], total: 0 };
    });
  });

  it("refetches the queue when a card's print status changes", async () => {
    renderQueue();

    const status = await screen.findByRole("button", { name: /print status queued/i });
    fireEvent.click(status);

    await waitFor(() => expect(setPrintStatus).toHaveBeenCalledWith(7, "printing"));
    await waitFor(() => expect(screen.getByText("Your print queue is empty")).toBeInTheDocument());
    expect(list.mock.calls.filter(([params]) => params.print_status === "queued").length).toBeGreaterThan(1);
  });
});
