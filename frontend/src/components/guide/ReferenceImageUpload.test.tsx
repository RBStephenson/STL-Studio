import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ReferenceImageUpload from "./ReferenceImageUpload";

const toast = vi.fn();
vi.mock("../../context/ToastContext", () => ({ useToast: () => ({ toast }) }));

vi.mock("../../api/client", async (orig) => {
  const mod = await orig<typeof import("../../api/client")>();
  return {
    ...mod,
    api: {
      ...mod.api,
      painting: {
        ...mod.api.painting,
        guides: {
          ...mod.api.painting.guides,
          uploadReferenceImage: vi.fn(),
          deleteReferenceImage: vi.fn(),
          referenceImageUrl: (id: number, v?: number) => `/api/painting/guides/${id}/reference-image?v=${v}`,
        },
      },
    },
  };
});

async function mocks() {
  const { api } = await import("../../api/client");
  return vi.mocked(api.painting.guides);
}

const pngFile = () => new File(["x"], "ref.png", { type: "image/png" });

describe("ReferenceImageUpload (#536)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("uploads a chosen file and reports the new id", async () => {
    const g = await mocks();
    g.uploadReferenceImage.mockResolvedValue({ id: 99 } as never);
    const onChange = vi.fn();

    render(<ReferenceImageUpload guideId={7} referenceImageId={null} onChange={onChange} />);

    await userEvent.upload(screen.getByTestId("reference-image-input"), pngFile());

    await waitFor(() => expect(g.uploadReferenceImage).toHaveBeenCalledWith(7, expect.any(File)));
    expect(onChange).toHaveBeenCalledWith(99);
  });

  it("rejects a non-image without calling the API", async () => {
    const g = await mocks();
    const onChange = vi.fn();

    render(<ReferenceImageUpload guideId={7} referenceImageId={null} onChange={onChange} />);

    const bad = new File(["x"], "notes.txt", { type: "text/plain" });
    // applyAccept:false so the change fires past the input's accept filter and
    // the component's own type guard is what rejects it.
    await userEvent.upload(screen.getByTestId("reference-image-input"), bad, { applyAccept: false });

    expect(g.uploadReferenceImage).not.toHaveBeenCalled();
    expect(toast).toHaveBeenCalledWith(expect.stringMatching(/PNG, JPEG/i), "error");
    expect(onChange).not.toHaveBeenCalled();
  });

  it("renders a preview and removes on demand", async () => {
    const g = await mocks();
    g.deleteReferenceImage.mockResolvedValue({ ok: true } as never);
    const onChange = vi.fn();

    render(<ReferenceImageUpload guideId={7} referenceImageId={42} onChange={onChange} />);

    expect(screen.getByRole("img", { name: /reference/i })).toHaveAttribute(
      "src",
      "/api/painting/guides/7/reference-image?v=42",
    );

    await userEvent.click(screen.getByRole("button", { name: /remove/i }));

    await waitFor(() => expect(g.deleteReferenceImage).toHaveBeenCalledWith(7));
    expect(onChange).toHaveBeenCalledWith(null);
  });
});
