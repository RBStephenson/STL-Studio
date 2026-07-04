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
    },
  },
);
