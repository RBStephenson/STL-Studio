import { describe, it, expect, beforeEach } from "vitest";
import { collectLegacyPreferences, clearLegacyPreferences } from "./legacyPreferences";
import { mkSettings } from "../test/settings";

describe("collectLegacyPreferences (#32 one-time migration)", () => {
  beforeEach(() => localStorage.clear());

  it("returns an empty patch when localStorage has no legacy keys", () => {
    expect(collectLegacyPreferences(mkSettings())).toEqual({});
  });

  it("migrates showNSFW=true when the server is still on the default", () => {
    localStorage.setItem("showNSFW", "true");
    expect(collectLegacyPreferences(mkSettings())).toEqual({ show_nsfw: true });
  });

  it("does not migrate showNSFW when the server already has it on", () => {
    localStorage.setItem("showNSFW", "true");
    expect(collectLegacyPreferences(mkSettings({ show_nsfw: true }))).toEqual({});
  });

  it("ignores showNSFW=false — same as the server default", () => {
    localStorage.setItem("showNSFW", "false");
    expect(collectLegacyPreferences(mkSettings())).toEqual({});
  });

  it("migrates presets only when the server has none", () => {
    const presets = [{ name: "Favs", qs: "is_favorite=1" }];
    localStorage.setItem("stl_filter_presets", JSON.stringify(presets));

    expect(collectLegacyPreferences(mkSettings())).toEqual({ filter_presets: presets });
    expect(
      collectLegacyPreferences(mkSettings({ filter_presets: [{ name: "Server", qs: "q=x" }] }))
    ).toEqual({});
  });

  it("drops malformed preset entries and survives unparseable JSON", () => {
    localStorage.setItem(
      "stl_filter_presets",
      JSON.stringify([{ name: "ok", qs: "q=1" }, { name: 7 }, "junk", null])
    );
    expect(collectLegacyPreferences(mkSettings())).toEqual({
      filter_presets: [{ name: "ok", qs: "q=1" }],
    });

    localStorage.setItem("stl_filter_presets", "{not json");
    expect(collectLegacyPreferences(mkSettings())).toEqual({});
  });
});

describe("clearLegacyPreferences", () => {
  it("removes both legacy keys", () => {
    localStorage.setItem("showNSFW", "true");
    localStorage.setItem("stl_filter_presets", "[]");
    clearLegacyPreferences();
    expect(localStorage.getItem("showNSFW")).toBeNull();
    expect(localStorage.getItem("stl_filter_presets")).toBeNull();
  });
});
