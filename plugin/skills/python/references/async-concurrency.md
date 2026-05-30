# Python — async & concurrency

Python-specific deltas. async-first for I/O-bound work; processes for CPU-bound; threads only to wrap blocking sync libs.

## The one rule: never block the event loop

A single synchronous call (`time.sleep`, `requests.get`, blocking file/DB I/O) stalls **every** concurrent task on that loop.

```python
# BAD — blocks the whole loop
async def fetch():
    time.sleep(1)
    return requests.get(url)

# GOOD — async-native
async def fetch(url: str):
    await asyncio.sleep(1)
    async with httpx.AsyncClient() as client:
        return await client.get(url)
```

When a sync library is unavoidable, offload it to a thread so the loop keeps running:

```python
async def read_file_async(path: str) -> str:
    return await asyncio.to_thread(Path(path).read_text)   # 3.9+
```

For CPU-bound work use `loop.run_in_executor` with a `ProcessPoolExecutor`, or `concurrent.futures` directly — threads won't help past the GIL.

## Concurrent fan-out with gather

Independent awaitables run concurrently; gather collects them in order.

```python
async def get_user_data(db: AsyncDB, user_id: int) -> dict:
    user, orders, profile = await asyncio.gather(
        db.fetch_one(f"users:{user_id}"),
        db.execute(f"orders:{user_id}"),
        db.fetch_one(f"profiles:{user_id}"),
    )
    return {"user": user, "orders": orders, "profile": profile}
```

On 3.11+ prefer `asyncio.TaskGroup` when you want structured concurrency with automatic cancellation of siblings on first failure.

By default `gather` is **fail-fast**: the first exception propagates and the remaining tasks are left running, not awaited. Pass `return_exceptions=True` to collect results *and* exceptions positionally — the call never raises, so you inspect failures yourself:

```python
results = await asyncio.gather(*tasks, return_exceptions=True)
ok   = [r for r in results if not isinstance(r, Exception)]
errs = [r for r in results if isinstance(r, Exception)]
```

At a breakpoint, check this first when a fan-out returns wrong data: an `Exception` sitting in the results where a value should be.

## Bound concurrency with a Semaphore

Cap in-flight work so you don't overwhelm a service or exhaust connections.

```python
async def rate_limited(urls: list[str], max_concurrent: int = 5) -> list[dict]:
    sem = asyncio.Semaphore(max_concurrent)

    async def call(url: str) -> dict:
        async with sem:
            async with httpx.AsyncClient() as client:
                r = await client.get(url)
                return {"url": url, "status": r.status_code}

    return await asyncio.gather(*(call(u) for u in urls))
```

For HTTP throughput, also reuse one client and a bounded connection pool (`httpx.AsyncClient` / `aiohttp.TCPConnector(limit=..., limit_per_host=...)`) rather than opening a client per request.

## Producer–consumer with a Queue

```python
async def producer(q: asyncio.Queue[str | None], n: int) -> None:
    for i in range(n):
        await q.put(f"item-{i}")
    await q.put(None)

async def consumer(q: asyncio.Queue[str | None]) -> None:
    while True:
        item = await q.get()
        if item is None:
            q.task_done()
            break
        await handle(item)
        q.task_done()
```

## Async context managers, iterators, locks

- **Resources:** implement `__aenter__`/`__aexit__` so cleanup runs on every exit path; consume with `async with`.
- **Streaming:** `async def` + `yield` is an async generator; consume with `async for` (paginate APIs, stream rows without loading everything).
- **Shared mutable state:** guard read-modify-write across `await` points with `asyncio.Lock` — an `await` inside a critical section yields control and lets another task interleave.

```python
class Counter:
    def __init__(self) -> None:
        self._value = 0
        self._lock = asyncio.Lock()

    async def increment(self) -> None:
        async with self._lock:
            self._value += 1
```

## Cancellation & timeouts

The two most common async hangs: a task that never finishes, and a cancelled task that never cleaned up.

**Bound every await that can stall.** `wait_for` cancels the inner task and raises on expiry; `asyncio.timeout()` (3.11+) is the context-manager form for a block:

```python
try:
    result = await asyncio.wait_for(fetch(url), timeout=2.0)
except asyncio.TimeoutError:         # all versions; aliases builtin TimeoutError on 3.11+
    ...                              # inner task already cancelled

async with asyncio.timeout(2.0):     # 3.11+
    result = await fetch(url)
```

**Cancellation is delivered as an exception you must let propagate.** When a task is cancelled, `asyncio.CancelledError` is raised at its current `await`. Catch it only to clean up, then re-raise — swallowing it leaves the task half-cancelled and the canceller hanging:

```python
async def worker() -> None:
    try:
        while True:
            await do_unit()
    except asyncio.CancelledError:
        await release_resources()
        raise                        # re-raise — never swallow
```

Since 3.8 `CancelledError` subclasses `BaseException`, so `except Exception:` won't catch it — but a too-broad `except BaseException:` will, a frequent cause of "Ctrl-C / shutdown doesn't work." When a `dbga` session shows a task wedged at an `await` that should have been cancelled, look upstream for a handler eating the `CancelledError`.

## Debugging async

Hangs and "wrong value after await" are where source-reading fails hardest. Set a `dbga` breakpoint inside the coroutine and inspect live state across the `await` — see `references/debugging.md` and the `debug-agent` skill.
