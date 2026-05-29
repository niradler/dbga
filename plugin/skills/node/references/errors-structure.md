# Errors & structure (Node/TS)

Node/TS-specific. Errors carry type-safe context; control flow stays explicit.

## Custom error classes — typed, categorized

Extend `Error`, set `name`, and attach a typed payload. Restore the prototype chain so `instanceof` survives transpilation to ES5 targets.

```typescript
class AppError extends Error {
  constructor(
    message: string,
    readonly statusCode: number,
    readonly cause?: unknown,
  ) {
    super(message);
    this.name = new.target.name;
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

class NotFoundError extends AppError {
  constructor(resource: string) {
    super(`${resource} not found`, 404);
  }
}
```

Use the built-in `cause` option (`new Error(msg, { cause })`) to chain without losing the original.

## Result types — errors as values

For expected, recoverable failures (validation, parsing), return a `Result` instead of throwing. Throw only for *exceptional* conditions.

```typescript
type Result<T, E = Error> =
  | { ok: true; value: T }
  | { ok: false; error: E };

function parsePort(s: string): Result<number, string> {
  const n = Number(s);
  if (!Number.isInteger(n) || n < 1 || n > 65535) {
    return { ok: false, error: `invalid port: ${s}` };
  }
  return { ok: true, value: n };
}
```

## Exhaustiveness with `never`

Force every error variant to be handled; a new variant becomes a compile error (see `references/typescript-types.md`).

## Async error wrapping — no naked async handlers

In Express-style frameworks an `async` handler that rejects bypasses error middleware. Wrap it.

```typescript
const asyncHandler =
  <T extends RequestHandler>(fn: T): RequestHandler =>
  (req, res, next) =>
    Promise.resolve(fn(req, res, next)).catch(next);

app.get(
  "/users/:id",
  asyncHandler(async (req, res) => {
    const user = await repo.findById(req.params.id);
    if (!user) throw new NotFoundError("User");
    res.json(user);
  }),
);
```

## `catch` is `unknown`, not `Error`

Under `useUnknownInCatchVariables` (on with `strict`), narrow before use.

```typescript
try {
  await risky();
} catch (e) {
  if (e instanceof AppError) return reply(e.statusCode, e.message);
  throw e;
}
```

## Process-level safety nets

Log and exit on the unexpected — never swallow silently.

```typescript
process.on("unhandledRejection", (reason) => {
  logger.error({ reason }, "unhandled rejection");
  process.exit(1);
});
```

## Structure

- One module = one responsibility; export the public surface, keep helpers private.
- Dependency injection over hard-coded imports for anything you'll mock in tests.
- Validate external input at the boundary (zod or a guard) so the typed core can trust its inputs.
