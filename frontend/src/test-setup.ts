import "@testing-library/jest-dom";

// jsdom doesn't implement scrollIntoView; components call it on form open.
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}

// Node 26+ pre-defines a `localStorage`/`sessionStorage` global of its own
// (an experimental Web Storage API that warns and evaluates to `undefined`
// unless the process was started with --localstorage-file) before vitest's
// jsdom environment ever runs. jsdom's environment setup only installs its
// own Storage implementation when the property is completely absent, so on
// Node 26 it finds Node's own stub already sitting there and leaves it alone
// — meaning `localStorage`/`sessionStorage` silently resolve to `undefined`
// in every test, where the same code worked fine on Node <26 (which never
// defines that global at all). The check below is only ever true on Node
// 26+, so this is a no-op everywhere else.
import { JSDOM } from "jsdom";

function needsRealStorage(key: "localStorage" | "sessionStorage"): boolean {
  const desc = Object.getOwnPropertyDescriptor(globalThis, key);
  if (!desc) return true; // not defined at all yet
  // Node's own stub is a getter (and reading it is what emits the
  // ExperimentalWarning) — check its shape instead of its value so this
  // never triggers that warning itself. A real Storage is installed below
  // as a plain value, never a getter.
  if (typeof desc.get === "function") return true;
  return typeof (desc.value as Storage | undefined)?.getItem !== "function";
}

if (needsRealStorage("localStorage") || needsRealStorage("sessionStorage")) {
  // A real (non-opaque) origin — localStorage throws a SecurityError on the
  // default "about:blank" origin a bare `new JSDOM()` gets.
  const { window: storageWindow } = new JSDOM("", { url: "http://localhost/" });
  for (const key of ["localStorage", "sessionStorage"] as const) {
    if (needsRealStorage(key)) {
      Object.defineProperty(globalThis, key, {
        configurable: true,
        value: storageWindow[key],
      });
    }
  }
}
