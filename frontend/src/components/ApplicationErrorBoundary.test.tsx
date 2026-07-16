import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import ApplicationErrorBoundary from "./ApplicationErrorBoundary";

function Broken({ fail }: { fail: boolean }) {
  if (fail) throw new Error("render failed");
  return <p>Catalog ready</p>;
}

describe("ApplicationErrorBoundary", () => {
  afterEach(() => vi.restoreAllMocks());

  it("shows recovery actions when a descendant render fails", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    render(
      <ApplicationErrorBoundary>
        <Broken fail />
      </ApplicationErrorBoundary>,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("unexpected error");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reload STL Studio" })).toBeInTheDocument();
  });

  it("can retry after the failing child is replaced", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    const view = render(
      <ApplicationErrorBoundary>
        <Broken fail />
      </ApplicationErrorBoundary>,
    );
    view.rerender(
      <ApplicationErrorBoundary>
        <Broken fail={false} />
      </ApplicationErrorBoundary>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(screen.getByText("Catalog ready")).toBeInTheDocument();
  });
});
