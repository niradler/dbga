# Advanced TypeScript types

Node/TS-specific. The rule is *model the domain so illegal states are unrepresentable*, then let inference do the work. One example per pattern.

## Discriminated unions — state machines & exhaustiveness

Tag each variant with a literal `kind`; narrow on it; close with a `never` default so adding a variant becomes a compile error.

```typescript
type Result<T, E> =
  | { kind: "ok"; value: T }
  | { kind: "err"; error: E };

function unwrap<T, E>(r: Result<T, E>): T {
  switch (r.kind) {
    case "ok":
      return r.value;
    case "err":
      throw r.error;
    default:
      return assertNever(r);
  }
}

function assertNever(x: never): never {
  throw new Error(`unhandled variant: ${JSON.stringify(x)}`);
}
```

## Branded types — domain safety with zero runtime cost

Stop `UserId` and `OrderId` (both `string`) from being mixed up.

```typescript
type Brand<T, B> = T & { readonly __brand: B };
type UserId = Brand<string, "UserId">;

const asUserId = (s: string): UserId => s as UserId;
```

## Conditional types + `infer` — extract from a shape

```typescript
type ElementOf<T> = T extends readonly (infer E)[] ? E : never;
type Awaited<T> = T extends Promise<infer U> ? Awaited<U> : T;
```

## Mapped types — transform a shape

```typescript
type Nullable<T> = { [K in keyof T]: T[K] | null };
type Mutable<T> = { -readonly [K in keyof T]: T[K] };
```

Key remapping with `as` renames keys:

```typescript
type Getters<T> = {
  [K in keyof T as `get${Capitalize<string & K>}`]: () => T[K];
};
```

## Template literal types — typed string contracts

```typescript
type Route = `/${string}`;
type EventName = `on${Capitalize<"click" | "focus">}`;
```

## Generic constraints — restrict, don't widen

```typescript
function pick<T, K extends keyof T>(obj: T, keys: K[]): Pick<T, K> {
  return Object.fromEntries(keys.map((k) => [k, obj[k]])) as Pick<T, K>;
}
```

## Type guards — narrow at runtime boundaries

Prefer predicates and `assert` functions over `as`. Casts silence the compiler; guards prove the type.

```typescript
function isUser(x: unknown): x is { id: string } {
  return typeof x === "object" && x !== null && "id" in x;
}
```

## Utility types — reach for these before hand-rolling

`Partial`, `Required`, `Readonly`, `Pick`, `Omit`, `Record`, `Extract`, `Exclude`, `NonNullable`, `ReturnType`, `Parameters`, `Awaited`.

## Discipline

- `strict: true`; no `any` without a `// reason:` justification — use `unknown` at boundaries and narrow.
- `const` assertions (`as const`) preserve literal types for unions and tuples.
- Type-only imports (`import type`) keep emit clean and avoid cycles.
- 100% type coverage on public API surface; validate non-trivial type logic with type-level tests (`expectTypeOf` in Vitest).
