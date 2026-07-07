import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import DataTab from "./DataTab";

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
});
