# Plain JavaScript fallback (no types)

Use only when the project has no TypeScript and adding it is out of scope. TypeScript is the default everywhere else — see the other references. The goal here is to recover as much type safety as JS allows.

## Recover type checking with JSDoc + `checkJs`

JSDoc annotations give you editor checking and `tsc` validation on plain `.js`. Add a `jsconfig.json` (or `tsconfig` with `allowJs`/`checkJs`) and run `tsc --noEmit` over the JS.

```javascript
// @ts-check

/**
 * @param {string} id
 * @returns {Promise<{ id: string, name: string } | null>}
 */
async function findUser(id) {
  return db.users.get(id) ?? null;
}
```

`/** @typedef */` and `@type` import types from `.d.ts` files, so you can share contracts without converting the codebase.

## Modern JS baseline

- **ESM only** — `import`/`export`, not `require`. Set `"type": "module"` in `package.json`.
- **Optional chaining + nullish coalescing** — `obj?.a?.b ?? fallback`. `??` defaults only on `null`/`undefined`, unlike `||`.
- **Private class fields** — `#field` for true encapsulation.
- **`const` by default**, `let` only when reassigning, never `var`.

## Defensive coding (no compiler to catch you)

- Validate inputs at every public boundary — type checks, range checks, null guards. The types that TS would enforce must now be enforced at runtime.
- Pure functions and immutable updates (spread, array methods over in-place mutation) keep behavior predictable.
- Higher-order functions for composition; destructure for readable signatures.

```javascript
const isNonEmptyString = (x) => typeof x === "string" && x.length > 0;

function greet(name) {
  if (!isNonEmptyString(name)) throw new TypeError("name must be a non-empty string");
  return `hello ${name}`;
}
```

## Guardrails

- Strict ESLint config (`eslint:recommended` + `no-floating-promises` via the promise plugin) to catch what the type system would.
- `WeakRef` / `FinalizationRegistry` only for genuine memory-pressure cases — rare.
- Async error handling is identical to TS (see `references/async-patterns.md` and `references/errors-structure.md`); `catch (e)` is untyped, so narrow with `instanceof` before using.

## Note

JSDoc-typed JS is debuggable with the same `dbga` Node recipes (`.js .mjs .cjs` auto-detect) — see `references/debugging.md`.
