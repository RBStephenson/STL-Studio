import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import DataTab from "./DataTab";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

vi.mock("../../api/client", () => ({
  api: {
    database: {
      backup: vi.fn(),
      restore: vi.fn(),
      reset: vi.fn(),
      health: vi.fn().mockResolvedValue({ ok: true, status: "healthy", detail: "ok" }),
      repair: vi.fn().mockResolvedValue({
        ok: true,
        status: "healthy",
        detail: "ok",
        before: "wrong # of entries in index uq_paints_line_code",
        repaired: true,
        snapshot: "/data/backups/pre_repair_20260706_000000",
      }),
    },
  },
}));

describe("DataTab database health", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("checks database health and shows the result", async () => {
    const { api } = await import("../../api/client");

    render(<DataTab />);

    await userEvent.click(screen.getByRole("button", { name: /check health/i }));

    expect(api.database.health).toHaveBeenCalled();
    expect(await screen.findByText(/healthy/i)).toBeInTheDocument();
    expect(screen.getByText("ok")).toBeInTheDocument();
  });

  it("shows progress while the database health check is running", async () => {
    const { api } = await import("../../api/client");
    const health = deferred<{ ok: boolean; status: "healthy"; detail: string }>();
    vi.mocked(api.database.health).mockReturnValue(health.promise);

    render(<DataTab />);

    await userEvent.click(screen.getByRole("button", { name: /check health/i }));

    expect(screen.getByRole("status")).toHaveTextContent(/checking database/i);
    expect(screen.getByRole("button", { name: /checking/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /repair database/i })).toBeDisabled();

    health.resolve({ ok: true, status: "healthy", detail: "ok" });

    expect(await screen.findByText(/healthy/i)).toBeInTheDocument();
  });

  it("confirms repair before calling the repair endpoint", async () => {
    const { api } = await import("../../api/client");
    vi.mocked(api.database.health).mockResolvedValue({
      ok: false,
      status: "corrupt",
      detail: "wrong # of entries in index uq_paints_line_code",
    });

    render(<DataTab />);

    await userEvent.click(screen.getByRole("button", { name: /check health/i }));
    await userEvent.click(screen.getByRole("button", { name: /repair database/i }));
    await userEvent.type(screen.getByPlaceholderText("ACKNOWLEDGED"), "ACKNOWLEDGED");
    const repairButtons = screen.getAllByRole("button", { name: /^repair database$/i });
    await userEvent.click(repairButtons[1]);

    expect(api.database.repair).toHaveBeenCalled();
    expect(await screen.findByText(/database repaired/i)).toBeInTheDocument();
  });

  it("shows progress while all data is being deleted", async () => {
    const { api } = await import("../../api/client");
    const reset = deferred<{ ok: boolean }>();
    vi.mocked(api.database.reset).mockReturnValue(reset.promise);

    render(<DataTab />);

    await userEvent.click(screen.getByRole("button", { name: /delete all data/i }));
    await userEvent.type(screen.getByPlaceholderText("ACKNOWLEDGED"), "ACKNOWLEDGED");
    await userEvent.click(screen.getByRole("button", { name: /delete everything/i }));

    expect(screen.getByRole("status")).toHaveTextContent(/creating a recovery snapshot/i);
    expect(screen.getByRole("button", { name: /deleting/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /cancel/i })).toBeDisabled();
  });
});
