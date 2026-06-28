import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import RefreshEnrich from "./RefreshEnrich";

const toastMock = vi.fn();
vi.mock("../context/ToastContext", () => ({ useToast: () => ({ toast: toastMock }) }));

function mockRefresh(body: object) {
  return vi.fn(async (url: string) => {
    if (url.includes("/enrich/refresh")) {
      return { ok: true, json: async () => body } as Response;
    }
    throw new Error(`unexpected fetch: ${url}`);
  });
}

/** Read the JSON body sent to the last /enrich/refresh POST. */
function lastBody(fetchMock: ReturnType<typeof vi.fn>) {
  const calls = fetchMock.mock.calls;
  const call = calls[calls.length - 1];
  return JSON.parse((call[1] as RequestInit).body as string);
}

describe("RefreshEnrich", () => {
  beforeEach(() => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
  });
  afterEach(() => { vi.restoreAllMocks(); toastMock.mockClear(); });

  it("does nothing when the confirm is declined", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    const fetchMock = mockRefresh({ candidates: 1, refreshed: 1, failed: 0 });
    vi.stubGlobal("fetch", fetchMock);

    render(<RefreshEnrich scopeLabel="your whole library" />);
    await userEvent.click(screen.getByRole("button", { name: /refresh metadata/i }));

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("library-wide refresh posts stale_days and no creator_id", async () => {
    const fetchMock = mockRefresh({ candidates: 4, refreshed: 4, failed: 0 });
    vi.stubGlobal("fetch", fetchMock);

    render(<RefreshEnrich scopeLabel="your whole library" />);
    await userEvent.click(screen.getByRole("button", { name: /refresh metadata/i }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const body = lastBody(fetchMock);
    expect(body).toEqual({ stale_days: 30 });           // default; no creator_id
    expect(toastMock).toHaveBeenCalledWith(
      expect.stringContaining("Refreshed 4 of 4 models"), "success"
    );
  });

  it("per-creator refresh includes creator_id", async () => {
    const fetchMock = mockRefresh({ candidates: 2, refreshed: 2, failed: 0 });
    vi.stubGlobal("fetch", fetchMock);

    render(<RefreshEnrich creatorId={7} scopeLabel="Acme" compact />);
    await userEvent.click(screen.getByRole("button", { name: /refresh/i }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(lastBody(fetchMock)).toEqual({ creator_id: 7, stale_days: 30 });
  });

  it("the 'All' staleness option drops stale_days from the request", async () => {
    const fetchMock = mockRefresh({ candidates: 5, refreshed: 5, failed: 0 });
    vi.stubGlobal("fetch", fetchMock);

    render(<RefreshEnrich creatorId={7} scopeLabel="Acme" />);
    await userEvent.selectOptions(screen.getByLabelText("Refresh staleness"), "all");
    await userEvent.click(screen.getByRole("button", { name: /refresh metadata/i }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(lastBody(fetchMock)).toEqual({ creator_id: 7 });   // no stale_days
  });

  it("reports the failed count when some fetches fail", async () => {
    vi.stubGlobal("fetch", mockRefresh({ candidates: 3, refreshed: 2, failed: 1 }));

    render(<RefreshEnrich scopeLabel="your whole library" />);
    await userEvent.click(screen.getByRole("button", { name: /refresh metadata/i }));

    await waitFor(() => expect(toastMock).toHaveBeenCalledWith(
      expect.stringContaining("1 couldn't be fetched"), "success"
    ));
  });

  it("shows an info toast when there is nothing to refresh", async () => {
    vi.stubGlobal("fetch", mockRefresh({ candidates: 0, refreshed: 0, failed: 0 }));

    render(<RefreshEnrich scopeLabel="your whole library" />);
    await userEvent.click(screen.getByRole("button", { name: /refresh metadata/i }));

    await waitFor(() => expect(toastMock).toHaveBeenCalledWith(
      expect.stringContaining("Nothing to refresh"), "info"
    ));
  });
});
