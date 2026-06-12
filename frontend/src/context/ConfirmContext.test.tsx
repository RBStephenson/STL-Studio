import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { ConfirmProvider, useConfirm } from "./ConfirmContext";

// A consumer that fires confirm() and reports the resolved boolean.
function Harness({ onResult }: { onResult: (r: boolean) => void }) {
  const confirm = useConfirm();
  return (
    <button
      onClick={async () => onResult(await confirm({ message: "Do the thing?", confirmLabel: "Do it" }))}
    >
      ask
    </button>
  );
}

const renderHarness = () => {
  const onResult = vi.fn();
  render(
    <ConfirmProvider>
      <Harness onResult={onResult} />
    </ConfirmProvider>,
  );
  return onResult;
};

describe("ConfirmContext (#284)", () => {
  it("does not show a dialog until confirm() is called", () => {
    renderHarness();
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("resolves true when the confirm button is clicked", async () => {
    const onResult = renderHarness();
    await act(async () => { fireEvent.click(screen.getByText("ask")); });

    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    await act(async () => { fireEvent.click(screen.getByText("Do it")); });

    expect(onResult).toHaveBeenCalledWith(true);
    expect(screen.queryByRole("alertdialog")).toBeNull(); // dialog closes
  });

  it("resolves false when cancelled", async () => {
    const onResult = renderHarness();
    await act(async () => { fireEvent.click(screen.getByText("ask")); });
    await act(async () => { fireEvent.click(screen.getByText("Cancel")); });

    expect(onResult).toHaveBeenCalledWith(false);
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });
});
