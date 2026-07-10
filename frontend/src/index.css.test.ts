import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const css = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "index.css"), "utf-8");

describe("global focus-visible ring", () => {
  it("targets buttons, links, and role=button/tab primitives", () => {
    const rule =
      /button:focus-visible,[\s\S]*?a:focus-visible,[\s\S]*?\[role="button"\]:focus-visible,[\s\S]*?\[role="tab"\]:focus-visible\s*\{([^}]+)\}/;
    const match = css.match(rule);
    expect(match).not.toBeNull();
    const body = match![1];
    expect(body).toContain("outline: 2px solid var(--color-accent-start)");
    expect(body).toContain("outline-offset: 2px");
  });

  it("does not apply the ring to plain :focus (keyboard-only)", () => {
    expect(css).not.toMatch(/button:focus\s*[,{]/);
  });
});
