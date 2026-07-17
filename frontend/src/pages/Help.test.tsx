import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeAll, describe, expect, it, vi } from "vitest";
import Help from "./Help";

vi.mock("../components/SystemInfoPanel", () => ({ default: () => null }));

beforeAll(() => {
  vi.stubGlobal("IntersectionObserver", class {
    observe() {}
    unobserve() {}
    disconnect() {}
  });
});

describe("Help", () => {
  it("documents storage recovery, desktop updates, and optional network integrations", () => {
    render(
      <MemoryRouter>
        <Help />
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { name: "External storage recovery" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Desktop updates" })).toBeVisible();
    expect(screen.getByText(/optional AI and storefront integrations make network requests/i)).toBeVisible();
    expect(screen.getByText(/file-moving tools such as Import and Reorganize/i)).toBeVisible();
  });
});
