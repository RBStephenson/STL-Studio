import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import ReorganizeStatsBar from "./ReorganizeStatsBar";
import type { ReorganizeStats } from "../../api/client";

const stats: ReorganizeStats = {
  total: 10,
  eligible: 6,
  moves_needed: 5,
  already_in_place: 1,
  collisions: 2,
  unclassifiable: 1,
  over_length: 0,
  reserved: 0,
  overlaps: 0,
  blocked: 4,
};

describe("ReorganizeStatsBar (#323)", () => {
  it("renders each summary stat with its value and label", () => {
    render(<ReorganizeStatsBar stats={stats} />);
    const list = screen.getByRole("list", { name: /reorganize summary/i });
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(7);

    // Spot-check a few label/value pairings on the containing listitem.
    expect(screen.getByText("Total").closest("[role=listitem]")).toHaveTextContent("10");
    expect(screen.getByText("Eligible").closest("[role=listitem]")).toHaveTextContent("6");
    expect(screen.getByText("Blocked").closest("[role=listitem]")).toHaveTextContent("4");
  });

  it("tones collisions/blocked as warnings when non-zero", () => {
    render(<ReorganizeStatsBar stats={stats} />);
    const collisions = screen.getByText("Collisions").closest("[role=listitem]")!;
    const blocked = screen.getByText("Blocked").closest("[role=listitem]")!;
    expect(collisions.className).toMatch(/yellow/);
    expect(blocked.className).toMatch(/orange/);
  });

  it("keeps a clean run neutral (no warn/bad tones at zero)", () => {
    const clean: ReorganizeStats = { ...stats, collisions: 0, unclassifiable: 0, blocked: 0 };
    render(<ReorganizeStatsBar stats={clean} />);
    const collisions = screen.getByText("Collisions").closest("[role=listitem]")!;
    const blocked = screen.getByText("Blocked").closest("[role=listitem]")!;
    expect(collisions.className).not.toMatch(/yellow/);
    expect(blocked.className).not.toMatch(/orange/);
  });
});
