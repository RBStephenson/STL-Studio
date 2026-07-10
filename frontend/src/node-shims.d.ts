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
