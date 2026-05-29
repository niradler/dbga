# Async patterns (Node/TS)

Node/TS-specific. `async/await` everywhere; raw `.then()` chains only when composing combinators.

## Concurrency — parallel by default, bounded when needed

Sequential `await` in a loop serializes I/O. Parallelize when order is independent.

```typescript
const users = await Promise.all(ids.map((id) => fetchUser(id)));
```

Bound concurrency so you don't open 10k sockets at once:

```typescript
import pLimit from "p-limit";

const limit = pLimit(5);
const users = await Promise.all(ids.map((id) => limit(() => fetchUser(id))));
```

## Promise combinators — pick the right one

- `Promise.all` — all succeed, or reject on first failure.
- `Promise.allSettled` — every result, success or failure (batch jobs, fan-out where partial failure is fine).
- `Promise.race` — first to settle (timeouts).
- `Promise.any` — first to *fulfill* (fastest healthy replica).

```typescript
function withTimeout<T>(p: Promise<T>, ms: number): Promise<T> {
  const timeout = new Promise<never>((_, reject) =>
    setTimeout(() => reject(new Error("timeout")), ms),
  );
  return Promise.race([p, timeout]);
}
```

## AbortController — cancellation, not orphaned work

```typescript
const ac = new AbortController();
const res = await fetch(url, { signal: ac.signal });
setTimeout(() => ac.abort(), 5000);
```

## Streams — backpressure for free

For large data, stream instead of buffering. `pipeline` propagates errors and cleans up.

```typescript
import { pipeline } from "node:stream/promises";
import { createReadStream, createWriteStream } from "node:fs";

await pipeline(createReadStream(src), gzip(), createWriteStream(dst));
```

## EventEmitter — decouple producers from consumers

```typescript
import { EventEmitter } from "node:events";

class Jobs extends EventEmitter {
  async run(job: Job): Promise<void> {
    await execute(job);
    this.emit("done", job);
  }
}
```

Always attach an `error` listener — an unhandled `error` event crashes the process.

## Graceful shutdown — close resources, then exit

```typescript
const server = app.listen(3000);

process.on("SIGTERM", () => {
  server.close(async () => {
    await db.disconnect();
    process.exit(0);
  });
  setTimeout(() => process.exit(1), 10_000).unref();
});
```

## Pitfalls

- **Unhandled rejection** — every async call needs an `await` with surrounding `try/catch`, or a `.catch()`. A floating promise swallows failures.
- **`forEach` is not async-aware** — it ignores returned promises; use `for...of` with `await`, or `Promise.all(map(...))`.
- **Microtask vs timer ordering** — awaited promises (microtasks) drain before `setTimeout` (macrotasks). Don't rely on `setTimeout(0)` for ordering.
- **`async` in an event handler** that throws → unhandled rejection. Wrap the body.
