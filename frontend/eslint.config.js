import js from "@eslint/js";
import tseslint from "typescript-eslint";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";

export default tseslint.config(
  { ignores: ["dist/", "node_modules/"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      globals: globals.browser,
    },
    plugins: {
      "react-hooks": reactHooks,
    },
    rules: {
      // Classic hooks rules only. The react-hooks v6 compiler rules
      // (set-state-in-effect, immutability, ...) flag ~40 existing spots that
      // the STUDIO-61/63 refactors will remove — enable them after that lands.
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "warn",
      // Ratchet locked (STUDIO-64): the original 36 `any`s were cleared during
      // the STUDIO-59/61/63 refactors (+ #759), so this is now an error to keep
      // the count at zero. Justified casts may use an inline eslint-disable.
      "@typescript-eslint/no-explicit-any": "error",
      // Intentionally-unused args/vars are prefixed with _ by convention.
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
      // `cond ? set.delete(x) : set.add(x)` is an established idiom here.
      "@typescript-eslint/no-unused-expressions": [
        "error",
        { allowTernary: true, allowShortCircuit: true },
      ],
      // Ratchet (STUDIO-349): a fire-and-forget timer that updates state keeps
      // running after unmount, and in jsdom it lands after teardown as
      // `ReferenceError: window is not defined` — an unhandled error that fails
      // the whole frontend job even when every test passes. Fixed three times
      // now (STUDIO-95, STUDIO-348, STUDIO-349), so it is a rule rather than a
      // habit. Scope is deliberately narrow: this flags a DISCARDED return
      // value, not missing cleanup, so `const t = setTimeout(...)` with no
      // matching clearTimeout still passes. That shape has never been the one
      // that bit us; the bare call always has.
      "no-restricted-syntax": [
        "error",
        {
          selector:
            "ExpressionStatement > CallExpression[callee.name=/^(setTimeout|setInterval)$/]",
          message:
            "Store the timer id (useRef / const) and clear it on unmount — a discarded setTimeout/setInterval fires against a dead tree (STUDIO-349). See PaintPicker.tsx for the useEffect form, ModelCard.tsx for the ref form.",
        },
        {
          selector:
            "ExpressionStatement > CallExpression[callee.object.name='window'][callee.property.name=/^(setTimeout|setInterval)$/]",
          message:
            "Store the timer id (useRef / const) and clear it on unmount — a discarded window.setTimeout/setInterval fires against a dead tree (STUDIO-349). See Navbar.tsx for the useEffect form.",
        },
      ],
    },
  },
);
