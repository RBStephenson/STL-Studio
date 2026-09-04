import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import StorefrontEnrich from "./StorefrontEnrich";

const MATCH = {
  local_model_id: 1,
  local_name: "Dragon",
  local_folder: "/x/dragon",
  score: 0.9,
  confidence: "high",
  product: {
    title: "Dragon Deluxe",
    source_url: "https://www.myminifactory.com/object/dragon-1",
    source_site: "myminifactory",
    external_id: "1",
    thumbnail_url: null,
  },
};

function mockFetch(applyBody: object) {
  return vi.fn(async (url: string) => {
    if (url.includes("/enrich/storefront/match")) {
      return { ok: true, json: async () => [MATCH] } as Response;
    }
    if (url.includes("/enrich/storefront/apply")) {
      return { ok: true, json: async () => applyBody } as Response;
    }
    throw new Error(`unexpected fetch: ${url}`);
  });
}

const DETAIL = {
  description: "A fearsome dragon.",
  tags: ["dragon", "fantasy"],
  category: "Creatures",
  license: "CC-BY",
};

function mockFetchWithDetail(detailResponse: { ok: boolean; body?: object }) {
  return vi.fn(async (url: string) => {
    if (url.includes("/enrich/storefront/match")) {
      return { ok: true, json: async () => [MATCH] } as Response;
    }
    if (url.includes("/scrape/fetch")) {
      return { ok: detailResponse.ok, json: async () => detailResponse.body } as Response;
    }
    throw new Error(`unexpected fetch: ${url}`);
  });
}

async function runMatch() {
  await userEvent.type(
    screen.getByPlaceholderText(/myminifactory\.com\/users/i),
    "https://www.myminifactory.com/users/someone",
  );
  await userEvent.click(screen.getByRole("button", { name: /^Match$/ }));
  await screen.findByText(/Dragon Deluxe/);
}

async function runAndApply() {
  await userEvent.type(
    screen.getByPlaceholderText(/myminifactory\.com\/users/i),
    "https://www.myminifactory.com/users/someone",
  );
  await userEvent.click(screen.getByRole("button", { name: /^Match$/ }));
  // High-confidence match auto-selects; apply it.
  await userEvent.click(await screen.findByRole("button", { name: /Apply 1 match/i }));
}

describe("StorefrontEnrich – apply result counts", () => {
  beforeEach(() => { vi.useRealTimers(); });
  afterEach(() => { vi.restoreAllMocks(); });

  it("reports deep + shallow counts after apply", async () => {
    vi.stubGlobal("fetch", mockFetch({ ok: true, applied: 3, enriched_deep: 2, fallback_shallow: 1, errors: 0 }));
    render(<StorefrontEnrich creatorId={5} creatorName="Acme" onDone={() => {}} />);

    await runAndApply();

    const banner = await screen.findByText(/Applied to 3 models/i);
    expect(banner).toHaveTextContent("2 fully enriched");
    expect(banner).toHaveTextContent("1 basic");
    expect(banner).toHaveTextContent(/couldn't fetch full detail/i);
  });

  it("omits the shallow note when everything enriched deeply", async () => {
    vi.stubGlobal("fetch", mockFetch({ ok: true, applied: 1, enriched_deep: 1, fallback_shallow: 0, errors: 0 }));
    render(<StorefrontEnrich creatorId={5} creatorName="Acme" onDone={() => {}} />);

    await runAndApply();

    const banner = await screen.findByText(/Applied to 1 model/i);
    expect(banner).toHaveTextContent("1 fully enriched");
    expect(banner).not.toHaveTextContent("basic");
    expect(banner).not.toHaveTextContent("failed to apply");
  });

  it("surfaces a partial-failure count when the server reports apply errors", async () => {
    vi.stubGlobal("fetch", mockFetch({ ok: true, applied: 2, enriched_deep: 2, fallback_shallow: 0, errors: 1 }));
    render(<StorefrontEnrich creatorId={5} creatorName="Acme" onDone={() => {}} />);

    await runAndApply();

    const banner = await screen.findByText(/Applied to 2 models/i);
    expect(banner).toHaveTextContent("1 model failed to apply");
  });

  it("shows the server's error detail when apply fails outright", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url.includes("/enrich/storefront/match")) {
        return { ok: true, json: async () => [MATCH] } as Response;
      }
      if (url.includes("/enrich/storefront/apply")) {
        return { ok: false, json: async () => ({ detail: "Database locked" }) } as Response;
      }
      throw new Error(`unexpected fetch: ${url}`);
    }));
    render(<StorefrontEnrich creatorId={5} creatorName="Acme" onDone={() => {}} />);

    await runAndApply();

    expect(await screen.findByText("Database locked")).toBeInTheDocument();
  });
});

describe("StorefrontEnrich – deep field preview on expand", () => {
  beforeEach(() => { vi.useRealTimers(); });
  afterEach(() => { vi.restoreAllMocks(); });

  it("fetches and shows deep fields when a match is expanded", async () => {
    vi.stubGlobal("fetch", mockFetchWithDetail({ ok: true, body: DETAIL }));
    render(<StorefrontEnrich creatorId={5} creatorName="Acme" onDone={() => {}} />);
    await runMatch();

    await userEvent.click(screen.getByRole("button", { name: /preview details/i }));

    expect(await screen.findByText("A fearsome dragon.")).toBeInTheDocument();
    expect(screen.getByText(/Creatures/)).toBeInTheDocument();
    expect(screen.getByText(/CC-BY/)).toBeInTheDocument();
    expect(screen.getByText("dragon")).toBeInTheDocument();
  });

  it("does not refetch detail when re-expanding the same match", async () => {
    const fetchMock = mockFetchWithDetail({ ok: true, body: DETAIL });
    vi.stubGlobal("fetch", fetchMock);
    render(<StorefrontEnrich creatorId={5} creatorName="Acme" onDone={() => {}} />);
    await runMatch();

    await userEvent.click(screen.getByRole("button", { name: /preview details/i }));
    await screen.findByText("A fearsome dragon.");
    // Collapse, then expand again — served from cache.
    await userEvent.click(screen.getByRole("button", { name: /hide details/i }));
    await userEvent.click(screen.getByRole("button", { name: /preview details/i }));
    await screen.findByText("A fearsome dragon.");

    const detailCalls = fetchMock.mock.calls.filter(([u]) => String(u).includes("/scrape/fetch"));
    expect(detailCalls).toHaveLength(1);
  });

  it("shows an error when detail fetch fails", async () => {
    vi.stubGlobal("fetch", mockFetchWithDetail({ ok: false }));
    render(<StorefrontEnrich creatorId={5} creatorName="Acme" onDone={() => {}} />);
    await runMatch();

    await userEvent.click(screen.getByRole("button", { name: /preview details/i }));

    expect(await screen.findByText(/couldn't load details/i)).toBeInTheDocument();
  });

  it("expanding does not toggle the match selection", async () => {
    vi.stubGlobal("fetch", mockFetchWithDetail({ ok: true, body: DETAIL }));
    render(<StorefrontEnrich creatorId={5} creatorName="Acme" onDone={() => {}} />);
    await runMatch();

    // High-confidence match auto-selects → button reads "Apply 1 matches".
    expect(screen.getByRole("button", { name: /Apply 1 match/i })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /preview details/i }));
    await screen.findByText("A fearsome dragon.");
    // Still selected (expand used stopPropagation).
    expect(screen.getByRole("button", { name: /Apply 1 match/i })).toBeInTheDocument();
  });
});

describe("StorefrontEnrich – deferred hand-back", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  // STUDIO-349. `onDone` makes the parent re-fetch and re-render, so firing it
  // 2.5s after this panel is gone touches a component that no longer exists.
  // The pending count is read at unmount, before the advance — after it, the
  // count is zero either way.
  it("does not hand back to the parent after the panel unmounts", async () => {
    // Real time drives the clock so RTL's findBy still resolves; the 2.5s
    // linger is then jumped manually rather than waited out.
    vi.useFakeTimers({ shouldAdvanceTime: true, advanceTimeDelta: 20 });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    vi.stubGlobal(
      "fetch",
      mockFetch({ ok: true, applied: 1, enriched_deep: 1, fallback_shallow: 0, errors: 0 }),
    );
    const onDone = vi.fn();
    const { unmount } = render(
      <StorefrontEnrich creatorId={5} creatorName="Acme" onDone={onDone} />,
    );

    await user.type(
      screen.getByPlaceholderText(/myminifactory\.com\/users/i),
      "https://www.myminifactory.com/users/someone",
    );
    await user.click(screen.getByRole("button", { name: /^Match$/ }));
    await user.click(await screen.findByRole("button", { name: /Apply 1 match/i }));
    await screen.findByText(/Applied to 1 model/i);

    const pending = vi.getTimerCount();
    expect(pending).toBeGreaterThan(0);

    unmount();
    expect(vi.getTimerCount()).toBe(pending - 1);

    await vi.advanceTimersByTimeAsync(3000);
    expect(onDone).not.toHaveBeenCalled();
  });
});
