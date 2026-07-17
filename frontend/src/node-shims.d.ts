// Minimal ambient types for Node built-ins used in test-only source files.
// The project has no @types/node dependency; these cover just what's used
// (src/index.css.test.ts reads the stylesheet from disk to assert CSS rules).
declare module "node:fs" {
  export function readFileSync(path: string, encoding: string): string;
}
declare module "node:path" {
  export function dirname(path: string): string;
  export function join(...parts: string[]): string;
}
declare module "node:url" {
  export function fileURLToPath(url: string): string;
}

// jsdom ships no types of its own, and @types/jsdom (DefinitelyTyped) is
// capped at major 28 while the project depends on jsdom 29 — covers just
// what test-setup.ts uses: constructing a Window and reading its Storage.
declare module "jsdom" {
  export class JSDOM {
    constructor(html?: string, options?: { url?: string });
    window: { localStorage: Storage; sessionStorage: Storage };
  }
}
