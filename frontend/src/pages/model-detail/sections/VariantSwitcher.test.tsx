import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import VariantSwitcher from "./VariantSwitcher";
import { Model, ModelDetail as ModelDetailType } from "../../../api/client";

const model = { id: 1, character: "Knight", variant_group: null } as unknown as ModelDetailType;

const mkVariant = (over: Partial<Model>): Model =>
  ({
    id: 1,
    name: "v",
    title: "",
    thumbnail_path: null,
    thumbnail_url: null,
    updated_at: null,
    is_favorite: false,
    print_status: "none",
    nsfw: false,
    ...over,
  } as unknown as Model);

const render1 = (variants: Model[], extra: Partial<React.ComponentProps<typeof VariantSwitcher>> = {}) =>
  render(
    <MemoryRouter>
      <VariantSwitcher
        variants={variants}
        model={model}
        favorite={false}
        printStatus="none"
        nsfw={false}
        showNSFW={false}
        backTo="/"
        {...extra}
      />
    </MemoryRouter>
  );

describe("VariantSwitcher", () => {
  it("renders nothing with one or zero variants", () => {
    const { container } = render1([mkVariant({ id: 1 })]);
    expect(container).toBeEmptyDOMElement();
  });

  it("lists variant count and one link per variant", () => {
    render1([mkVariant({ id: 1, title: "A" }), mkVariant({ id: 2, title: "B" })]);
    expect(screen.getByText(/2 variants of Knight/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "A" })).toHaveAttribute("href", "/models/1");
    expect(screen.getByRole("link", { name: "B" })).toHaveAttribute("href", "/models/2");
  });

  it("blurs NSFW variants when showNSFW is off", () => {
    render1([mkVariant({ id: 1, title: "A", thumbnail_url: "x.png", nsfw: true }), mkVariant({ id: 2, title: "B" })]);
    expect(screen.getByText("NSFW")).toBeInTheDocument();
  });

  it("uses live favorite for the current variant over the fetched value", () => {
    // current variant (id 1) fetched is_favorite=false, but local favorite=true
    render1(
      [mkVariant({ id: 1, title: "A", is_favorite: false }), mkVariant({ id: 2, title: "B" })],
      { favorite: true }
    );
    // Star badge only rendered when favorite → the current variant link contains an svg star
    const link = screen.getByRole("link", { name: "A" });
    expect(link.querySelector("svg")).toBeTruthy();
  });
});
