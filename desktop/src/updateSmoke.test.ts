import { describe, expect, it } from "vitest";

import { readUpdateSmokeConfig } from "./updateSmoke";

describe("readUpdateSmokeConfig", () => {
  it("is disabled unless explicitly enabled", () => {
    expect(readUpdateSmokeConfig({ STL_STUDIO_UPDATE_FEED_URL: "http://127.0.0.1:9" })).toBeNull();
  });

  it("accepts only a loopback HTTP feed", () => {
    expect(readUpdateSmokeConfig({
      STL_STUDIO_UPDATE_SMOKE: "1",
      STL_STUDIO_UPDATE_FEED_URL: "http://127.0.0.1:8123/feed",
    })).toEqual({ feedUrl: "http://127.0.0.1:8123/feed" });
    expect(() => readUpdateSmokeConfig({
      STL_STUDIO_UPDATE_SMOKE: "1",
      STL_STUDIO_UPDATE_FEED_URL: "https://example.com/feed",
    })).toThrow(/loopback/i);
  });

  it("requires a feed URL in smoke mode", () => {
    expect(() => readUpdateSmokeConfig({ STL_STUDIO_UPDATE_SMOKE: "1" })).toThrow(/requires/i);
  });
});
