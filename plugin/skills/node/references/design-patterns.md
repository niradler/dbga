# Design patterns (Node/TS)

Node/TS-specific structural patterns. Clarity and testability over cleverness — see `_shared/clean-code.md`.

## Dependency injection — inject, don't import-and-hope

Pass collaborators in so they can be substituted in tests. Hard-coded module imports are untestable seams.

```typescript
interface UserRepo {
  findById(id: string): Promise<User | null>;
}

class UserService {
  constructor(private readonly repo: UserRepo) {}

  async profile(id: string): Promise<User> {
    const user = await this.repo.findById(id);
    if (!user) throw new NotFoundError("User");
    return user;
  }
}
```

Tests pass a fake `UserRepo`; production passes the real one. No module mocking needed.

## Repository pattern — isolate data access

Hide the ORM/SQL behind an interface so business logic never imports a database client. Swap Postgres for an in-memory map in tests without touching callers.

## Composition over inheritance

Prefer small functions and object composition. Reach for classes when you have genuine identity + behavior + lifecycle (services, stateful clients); reach for plain functions and modules otherwise.

```typescript
const withRetry =
  <A extends unknown[], R>(fn: (...a: A) => Promise<R>, n = 3) =>
  async (...args: A): Promise<R> => {
    let last: unknown;
    for (let i = 0; i < n; i++) {
      try {
        return await fn(...args);
      } catch (e) {
        last = e;
      }
    }
    throw last;
  };
```

## Middleware pipeline

Chain single-purpose handlers for cross-cutting concerns (auth, logging, validation). Each does one thing and calls `next`.

## Factory functions

Return a closed-over object instead of exposing a class when you don't need `instanceof` or inheritance — simpler, no `this` foot-guns.

```typescript
function createCounter(start = 0) {
  let count = start;
  return {
    inc: () => ++count,
    value: () => count,
  };
}
```

## Anti-patterns to refactor away

- **`any` as an escape hatch** — use `unknown` + narrowing, or fix the type.
- **God modules** — a file exporting 30 unrelated things; split by responsibility.
- **Deep callback / `.then()` nesting** — flatten with `async/await`.
- **Floating promises** — every promise is awaited or explicitly `.catch`-ed.
- **Re-throwing without context** — attach `cause` so the stack trace survives.
- **Mutating shared state** — prefer immutable updates (spread, `readonly`).
- **Barrel-file cycles** — `import type` and direct paths break import cycles.
