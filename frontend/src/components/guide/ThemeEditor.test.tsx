import { describe, it, expect, vi } from "vitest";
import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ThemeEditor from "./ThemeEditor";
import { GuideTheme } from "../../api/client";

// Controlled harness so typing accumulates (the real parents feed value back).
function Harness({ initial, onChange }: { initial: GuideTheme; onChange: (t: GuideTheme) => void }) {
  const [value, setValue] = useState<GuideTheme>(initial);
  return (
    <ThemeEditor
      value={value}
      onChange={(t) => { setValue(t); onChange(t); }}
    />
  );
}

describe("ThemeEditor", () => {
  it("emits the edited field, preserving existing values", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Harness initial={{ bg: "#000000" }} onChange={onChange} />);

    await user.type(screen.getByLabelText("Accent hex"), "#ff0000");

    const last = onChange.mock.calls[onChange.mock.calls.length - 1][0];
    expect(last).toMatchObject({ bg: "#000000", accent: "#ff0000" });
  });

  it("clears a field to null when emptied", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<ThemeEditor value={{ accent: "#ff0000" }} onChange={onChange} />);

    await user.clear(screen.getByLabelText("Accent hex"));

    expect(onChange).toHaveBeenLastCalledWith({ accent: null });
  });

  it("renders a live preview driven by the theme", () => {
    render(<ThemeEditor value={{ accent: "#abcdef" }} onChange={vi.fn()} />);
    expect(screen.getByTestId("theme-preview")).toBeInTheDocument();
  });
});
