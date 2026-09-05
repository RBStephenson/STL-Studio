import { useState } from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import TemplateEditor from "./TemplateEditor";

// A stand-in for what the settings payload sends, NOT a copy of the component's
// default — the component has none any more (STUDIO-406). Tests that care about
// where the value comes from pass their own, deliberately different, string.
const SERVER_DEFAULT = "{creator}/{character}/{title}";

vi.mock("../../api/client", () => {
  class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  }
  return {
    ApiError,
    api: { reorganize: { templatePreview: (...args: unknown[]) => templatePreviewMock(...args) } },
  };
});

const templatePreviewMock = vi.fn();
import { ApiError } from "../../api/client";

function sample(over: Record<string, unknown> = {}) {
  return {
    model_id: 1,
    model_name: "Joker Bust",
    source_dir: "Abe3D/Joker Bust",
    proposed_dir: "Abe3D/Joker/Joker Bust",
    unclassifiable: false,
    missing_fields: [],
    over_length: false,
    reserved_name: false,
    ...over,
  };
}

function previewResponse(over: Record<string, unknown> = {}) {
  return { template: SERVER_DEFAULT, samples: [sample()], package_mode: false, ...over };
}

/** The component is controlled, so the tests need something holding the value —
 *  the same job both host pages do. */
function Harness({
  initial = SERVER_DEFAULT,
  onCommit,
  rootId,
  defaultTemplate = SERVER_DEFAULT,
}: {
  initial?: string;
  onCommit?: () => void;
  rootId?: number;
  defaultTemplate?: string;
}) {
  const [value, setValue] = useState(initial);
  return (
    <TemplateEditor
      value={value}
      onChange={setValue}
      onCommit={onCommit}
      rootId={rootId}
      defaultTemplate={defaultTemplate}
      scopeNote="Applies to this plan only."
    />
  );
}

const field = () =>
  screen.getByRole("textbox", { name: /destination template/i }) as HTMLInputElement;

beforeEach(() => {
  vi.clearAllMocks();
  templatePreviewMock.mockResolvedValue(previewResponse());
});

describe("TemplateEditor token chips", () => {
  it("inserts a token at the caret and leaves the caret after it", async () => {
    render(<Harness />);
    const input = field();
    input.focus();
    // Between "{creator}/" and "{character}".
    input.setSelectionRange(10, 10);

    await userEvent.click(screen.getByRole("button", { name: "{scale}" }));

    expect(input).toHaveValue("{creator}/{scale}{character}/{title}");
    // Without an explicit restore a controlled input drops the caret at the end,
    // so the next chip click lands in the wrong place (STUDIO-402).
    expect(input.selectionStart).toBe(10 + "{scale}".length);
  });

  it("replaces the selected text rather than inserting beside it", async () => {
    render(<Harness />);
    const input = field();
    input.focus();
    // Select "{character}".
    input.setSelectionRange(10, 21);

    await userEvent.click(screen.getByRole("button", { name: "{scale}" }));

    expect(input).toHaveValue("{creator}/{scale}/{title}");
  });

  it("appends when the field has never been focused", async () => {
    render(<Harness initial="{creator}" />);
    await userEvent.click(screen.getByRole("button", { name: "{title}" }));
    expect(field()).toHaveValue("{creator}{title}");
  });
});

describe("TemplateEditor presets", () => {
  it("fills the field and leaves it editable", async () => {
    render(<Harness initial="{creator}" />);
    await userEvent.click(screen.getByRole("button", { name: /Creator → Title/ }));

    const input = field();
    expect(input).toHaveValue("{creator}/{title}");
    expect(input).toBeEnabled();

    await userEvent.type(input, "X");
    expect(input).toHaveValue("{creator}/{title}X");
  });

  it("marks the preset matching the current template as active", () => {
    render(<Harness />);
    expect(screen.getByRole("button", { name: /Built-in default/ }))
      .toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: /^Creator → Title$/ }))
      .toHaveAttribute("aria-pressed", "false");
  });

  // The whole point of STUDIO-406: the default is the server's, so a test that
  // used the canonical string couldn't tell "read from settings" apart from
  // "still hard-coded in the component".
  it("takes the default preset from the server, not from a built-in literal", async () => {
    render(<Harness initial="{creator}" defaultTemplate="{creator}/{scale}" />);
    await userEvent.click(screen.getByRole("button", { name: /Built-in default/ }));
    expect(field()).toHaveValue("{creator}/{scale}");
  });

  // `loaded` can go true with blank settings when the fetch failed, and a
  // preset button that pastes "" is worse than one preset fewer. Inventing a
  // local fallback is exactly the drift this ticket removed.
  it("drops the default preset entirely when the server sent no default", () => {
    render(<Harness initial="{creator}" defaultTemplate="" />);
    expect(screen.queryByRole("button", { name: /Built-in default/ })).toBeNull();
    // The fixed presets are unaffected.
    expect(screen.getByRole("button", { name: /^Creator → Title$/ })).toBeInTheDocument();
  });

  // Scale auto-tags are missing on most models, so a required {scale} blocks
  // most of a library at once — a one-click preset must not hand someone that.
  it("uses the optional form of scale so the preset can't block a whole library", async () => {
    render(<Harness initial="{creator}" />);
    await userEvent.click(screen.getByRole("button", { name: /Creator → Scale → Character → Title/ }));
    expect(field()).toHaveValue("{creator}/{scale?}/{character}/{title}");
  });
});

describe("TemplateEditor live example", () => {
  it("renders real models through the template", async () => {
    render(<Harness />);
    expect(await screen.findByText("Joker Bust")).toBeInTheDocument();
    expect(screen.getByText("Abe3D/Joker Bust")).toBeInTheDocument();
    expect(screen.getByText("→ Abe3D/Joker/Joker Bust")).toBeInTheDocument();
  });

  it("names the fields a template-blocked model is missing", async () => {
    templatePreviewMock.mockResolvedValue(previewResponse({
      samples: [sample({ unclassifiable: true, missing_fields: ["character"] })],
    }));
    render(<Harness />);
    expect(await screen.findByText("no character")).toBeInTheDocument();
  });

  it("flags over-length and reserved renders", async () => {
    templatePreviewMock.mockResolvedValue(previewResponse({
      samples: [sample({ over_length: true, reserved_name: true })],
    }));
    render(<Harness />);
    expect(await screen.findByText("too long")).toBeInTheDocument();
    expect(screen.getByText("reserved name")).toBeInTheDocument();
  });

  // The constraint inherited from STUDIO-401, and the easiest thing here to get
  // quietly wrong: these flags cover only what the TEMPLATE caused. Locks,
  // symlinks, collisions and missing files all need the disk the endpoint
  // deliberately never touches, so a clean sample is not a promise to move.
  it("never presents a clean sample as an eligibility verdict", async () => {
    render(<Harness />);
    const caveat = await screen.findByText(/Template rendering only/);
    expect(caveat).toHaveTextContent("does not say whether a model can move");
    expect(caveat).toHaveTextContent("Collisions, locks, symlinks and missing files need a built plan");
    expect(screen.queryByText(/will move/i)).not.toBeInTheDocument();
  });

  it("scopes the example to a scan root when the host supplies one", async () => {
    render(<Harness rootId={7} />);
    await waitFor(() =>
      expect(templatePreviewMock).toHaveBeenCalledWith(SERVER_DEFAULT, 7),
    );
  });

  it("says so when the library has nothing to render against", async () => {
    templatePreviewMock.mockResolvedValue(previewResponse({ samples: [] }));
    render(<Harness />);
    expect(await screen.findByText(/No models to render against yet/)).toBeInTheDocument();
  });

  it("debounces typing instead of firing a request per keystroke", async () => {
    render(<Harness initial="" />);
    await userEvent.type(field(), "{{creator}/{{title}");

    await waitFor(() =>
      expect(templatePreviewMock).toHaveBeenLastCalledWith("{creator}/{title}", undefined),
    );
    expect(templatePreviewMock.mock.calls.length).toBeLessThan(5);
  });
});

describe("TemplateEditor validation", () => {
  it("shows the server's parse message without clearing what was typed", async () => {
    templatePreviewMock.mockRejectedValue(new ApiError(400, "Unknown token: {creater}"));
    render(<Harness initial="{creater}/{title}" />);

    expect(await screen.findByText("Unknown token: {creater}")).toBeInTheDocument();
    // Losing the text is worse than an invalid template sitting in the field.
    expect(field()).toHaveValue("{creater}/{title}");
    expect(screen.queryByText("Example destinations")).not.toBeInTheDocument();
  });

  it("recovers once the template is valid again", async () => {
    templatePreviewMock.mockRejectedValueOnce(new ApiError(400, "Unknown token: {creater}"));
    render(<Harness initial="{creater}" />);
    expect(await screen.findByText("Unknown token: {creater}")).toBeInTheDocument();

    await userEvent.clear(field());
    await userEvent.type(field(), "{{creator}");
    expect(await screen.findByText("Example destinations")).toBeInTheDocument();
    expect(screen.queryByText("Unknown token: {creater}")).not.toBeInTheDocument();
  });

  // A blank template makes the endpoint fall back to the SAVED one, so previewing
  // it would confidently render a template the user isn't looking at.
  it("never previews an empty template", async () => {
    render(<Harness initial="" />);
    expect(await screen.findByText(/The template is empty/)).toBeInTheDocument();
    await waitFor(() => expect(templatePreviewMock).not.toHaveBeenCalled());
  });
});

describe("TemplateEditor package mode", () => {
  it("warns that the template is inert when the server reports package mode", async () => {
    templatePreviewMock.mockResolvedValue(previewResponse({ package_mode: true }));
    render(<Harness />);
    expect(await screen.findByText(/Package preservation is on/)).toHaveTextContent(
      "this template does not decide placement",
    );
  });

  it("stays quiet when package mode is off", async () => {
    render(<Harness />);
    expect(await screen.findByText("Example destinations")).toBeInTheDocument();
    expect(screen.queryByText(/Package preservation is on/)).not.toBeInTheDocument();
  });
});

describe("TemplateEditor commit boundary", () => {
  // Settings saves on blur. Committing on the INPUT's blur would fire on every
  // chip click and save a half-typed template mid-edit.
  it("does not commit when focus moves to a chip inside the editor", () => {
    const onCommit = vi.fn();
    render(<Harness onCommit={onCommit} />);
    fireEvent.blur(field(), {
      relatedTarget: screen.getByRole("button", { name: "{scale}" }),
    });
    expect(onCommit).not.toHaveBeenCalled();
  });

  it("commits once focus leaves the editor entirely", () => {
    const onCommit = vi.fn();
    render(<Harness onCommit={onCommit} />);
    fireEvent.blur(field(), { relatedTarget: document.body });
    expect(onCommit).toHaveBeenCalledTimes(1);
  });

  it("clicking a chip keeps focus in the field, so nothing is saved mid-edit", async () => {
    const onCommit = vi.fn();
    render(<Harness onCommit={onCommit} />);
    const input = field();
    input.focus();

    await userEvent.click(screen.getByRole("button", { name: "{title}" }));

    expect(input).toHaveFocus();
    expect(onCommit).not.toHaveBeenCalled();
  });

  it("stays silent when the host passes no commit handler", () => {
    render(<Harness />);
    // The Reorganize page's field is a one-off; there is nothing to save.
    expect(() => fireEvent.blur(field(), { relatedTarget: document.body })).not.toThrow();
  });
});
