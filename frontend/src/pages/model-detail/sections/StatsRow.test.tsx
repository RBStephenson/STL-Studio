import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import StatsRow from "./StatsRow";
import { ModelDetail as ModelDetailType } from "../../../api/client";

const base = {
  like_count: null,
  download_count: null,
  source_site: null,
  license: null,
} as unknown as ModelDetailType;

describe("StatsRow", () => {
  it("renders like and download counts localized", () => {
    render(<StatsRow model={{ ...base, like_count: 1234, download_count: 5678 } as ModelDetailType} />);
    expect(screen.getByText("1,234")).toBeInTheDocument();
    expect(screen.getByText("5,678")).toBeInTheDocument();
  });

  it("omits counts when null", () => {
    render(<StatsRow model={base} />);
    expect(screen.queryByText(/,/)).not.toBeInTheDocument();
  });

  it("shows source site and license badges when present", () => {
    render(<StatsRow model={{ ...base, source_site: "thingiverse", license: "CC-BY" } as ModelDetailType} />);
    expect(screen.getByText("thingiverse")).toBeInTheDocument();
    expect(screen.getByText("CC-BY")).toBeInTheDocument();
  });
});
