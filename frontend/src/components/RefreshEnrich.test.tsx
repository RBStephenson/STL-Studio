import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import RefreshEnrich from "./RefreshEnrich";

const toastMock = vi.fn();
vi.mock("../context/ToastContext", () => ({ useToast: () => ({ toast: toastMock }) }));

/** POST /enrich/refresh starts the job; GET /enrich/refresh/status reports it
 * done (running: false) on the very first poll, so tests don't need to
 * advance fake timers through the polling interval. */
function mockRefresh(finalStatus: Omit<Record<string, unknown>, "running">) {
  return vi.fn(async (url: string, init?: RequestInit) => {
    if (url.includes("/enrich/refresh/status")) {
      return { ok: true, json: async () => ({ running: false, message: "done", ...finalStatus }) } as Response;
    }
    if (url.includes("/enrich/refresh") && init?.method === "POST") {
      return { ok: true, status: 200, json: async () => ({ ok: true, running: true, message: "refresh started" }) } as Response;
    }
    throw new Error(`unexpected fetch: ${url}`);
  });
}

function mock409() {
  return vi.fn(async (url: string, init?: RequestInit) => {
    if (url.includes("/enrich/refresh") && init?.method === "POST") {
      return { ok: false, status: 409, json: async () => ({ detail: "Refresh already running" }) } as Response;
    }
    throw new Error(`unexpected fetch: ${url}`);
  });
}

/** Read the JSON body sent to the /enrich/refresh POST. */
function lastPostBody(fetchMock: ReturnType<typeof vi.fn>) {
  const call = fetchMock.mock.calls.find(
    (args: unknown[]) => (args[0] as string).includes("/enrich/refresh") && (args[1] as RequestInit | undefined)?.method === "POST"
  );
  return JSON.parse((call![1] as RequestInit).body as string);
}

describe("RefreshEnrich", () => {
  beforeEach(() => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
  });
  afterEach(() => { vi.restoreAllMocks(); toastMock.mockClear(); });

  it("does nothing when the confirm is declined", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    const fetchMock = mockRefresh({ candidates: 1, refreshed: 1, failed: 0, errors: 0 });
    vi.stubGlobal("fetch", fetchMock);

    render(<RefreshEnrich scopeLabel="your whole library" />);
    await userEvent.click(screen.getByRole("button", { name: /refresh metadata/i }));

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("library-wide refresh posts stale_days and no creator_id", async () => {
    const fetchMock = mockRefresh({ candidates: 4, refreshed: 4, failed: 0, errors: 0 });
    vi.stubGlobal("fetch", fetchMock);

    render(<RefreshEnrich scopeLabel="your whole library" />);
    await userEvent.click(screen.getByRole("button", { name: /refresh metadata/i }));

    await waitFor(() => expect(lastPostBody(fetchMock)).toEqual({ stale_days: 30 }));  // default; no creator_id
    await waitFor(() => expect(toastMock).toHaveBeenCalledWith(
      expect.stringContaining("Refreshed 4 of 4 models"), "success"
    ));
  });

  it("per-creator refresh includes creator_id", async () => {
    const fetchMock = mockRefresh({ candidates: 2, refreshed: 2, failed: 0, errors: 0 });
    vi.stubGlobal("fetch", fetchMock);

    render(<RefreshEnrich creatorId={7} scopeLabel="Acme" compact />);
    await userEvent.click(screen.getByRole("button", { name: /refresh/i }));

    await waitFor(() => expect(lastPostBody(fetchMock)).toEqual({ creator_id: 7, stale_days: 30 }));
  });

  it("the 'All' staleness option drops stale_days from the request", async () => {
    const fetchMock = mockRefresh({ candidates: 5, refreshed: 5, failed: 0, errors: 0 });
    vi.stubGlobal("fetch", fetchMock);

    render(<RefreshEnrich creatorId={7} scopeLabel="Acme" />);
    await userEvent.selectOptions(screen.getByLabelText("Refresh staleness"), "all");
    await userEvent.click(screen.getByRole("button", { name: /refresh metadata/i }));

    await waitFor(() => expect(lastPostBody(fetchMock)).toEqual({ creator_id: 7 }));   // no stale_days
  });

  it("reports the failed count when some fetches fail", async () => {
    vi.stubGlobal("fetch", mockRefresh({ candidates: 3, refreshed: 2, failed: 1, errors: 0 }));

    render(<RefreshEnrich scopeLabel="your whole library" />);
    await userEvent.click(screen.getByRole("button", { name: /refresh metadata/i }));

    await waitFor(() => expect(toastMock).toHaveBeenCalledWith(
      expect.stringContaining("1 couldn't be fetched"), "success"
    ));
  });

  it("shows an info toast when there is nothing to refresh", async () => {
    vi.stubGlobal("fetch", mockRefresh({ candidates: 0, refreshed: 0, failed: 0, errors: 0 }));

    render(<RefreshEnrich scopeLabel="your whole library" />);
    await userEvent.click(screen.getByRole("button", { name: /refresh metadata/i }));

    await waitFor(() => expect(toastMock).toHaveBeenCalledWith(
      expect.stringContaining("Nothing to refresh"), "info"
    ));
  });

  it("shows an info toast instead of erroring when a refresh is already running", async () => {
    vi.stubGlobal("fetch", mock409());

    render(<RefreshEnrich scopeLabel="your whole library" />);
    await userEvent.click(screen.getByRole("button", { name: /refresh metadata/i }));

    await waitFor(() => expect(toastMock).toHaveBeenCalledWith(
      expect.stringContaining("already running"), "info"
    ));
  });
});
