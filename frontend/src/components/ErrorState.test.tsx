import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ErrorState from "./ErrorState";

describe("ErrorState", () => {
  it("renders the message with a default title and no Retry button when onRetry is omitted", () => {
    render(<ErrorState message="Could not load models." />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText("Something went wrong")).toBeInTheDocument();
    expect(screen.getByText("Could not load models.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /retry/i })).toBeNull();
  });

  it("renders a custom title and calls onRetry when the Retry button is clicked", async () => {
    const onRetry = vi.fn();
    render(<ErrorState title="Couldn't load guides" message="boom" onRetry={onRetry} />);
    expect(screen.getByText("Couldn't load guides")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
