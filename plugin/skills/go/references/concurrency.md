# Go concurrency — goroutines, channels, sync, context

> Don't communicate by sharing memory; share memory by communicating.

Channels orchestrate; mutexes protect state. Every goroutine needs a defined
exit path — a leaked goroutine is a bug.

## Primitives

| Primitive | Purpose |
| --- | --- |
| `goroutine` | Lightweight concurrent execution |
| `channel` | Communication / synchronization |
| `select` | Multiplex channel ops, timeouts, non-blocking |
| `sync.Mutex` / `RWMutex` | Mutual exclusion for shared state |
| `sync.WaitGroup` | Wait for a set of goroutines |
| `context.Context` | Cancellation, deadlines, request values |
| `errgroup.Group` | Concurrent ops that can fail, with cancellation |

## Rules that prevent the common bugs

- **Close channels from the sender side only.** Closing from a receiver, or
  closing twice, panics.
- **Every goroutine has an exit path.** Select on `ctx.Done()` so cancellation
  reaches it.
- **Buffer only when you know the count.** An unbounded buffer hides leaks.
- **Prefer channels over `time.Sleep` for synchronization.** Sleep-based "sync"
  is a race waiting to happen.
- **`errgroup` for concurrent fallible work** — first error cancels the rest.

## Worker pool

Bounded concurrency, results collected, cancellation honored.

```go
func WorkerPool(ctx context.Context, workers int, jobs <-chan Job) <-chan Result {
	results := make(chan Result)
	var wg sync.WaitGroup
	for i := 0; i < workers; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for job := range jobs {
				select {
				case <-ctx.Done():
					return
				case results <- process(job):
				}
			}
		}()
	}
	go func() { wg.Wait(); close(results) }()
	return results
}
```

The sender goroutine closes `results` once all workers finish — receivers
`range` until close.

## Fan-out / fan-in

Run multiple instances of a stage, then merge their outputs.

```go
func merge(ctx context.Context, cs ...<-chan int) <-chan int {
	out := make(chan int)
	var wg sync.WaitGroup
	wg.Add(len(cs))
	for _, c := range cs {
		go func(c <-chan int) {
			defer wg.Done()
			for n := range c {
				select {
				case <-ctx.Done():
					return
				case out <- n:
				}
			}
		}(c)
	}
	go func() { wg.Wait(); close(out) }()
	return out
}
```

## errgroup with cancellation and a concurrency limit

```go
func fetchAll(ctx context.Context, urls []string, limit int) ([]string, error) {
	g, ctx := errgroup.WithContext(ctx)
	g.SetLimit(limit)
	results := make([]string, len(urls))
	for i, url := range urls {
		g.Go(func() error {
			r, err := fetch(ctx, url)
			if err != nil {
				return fmt.Errorf("fetch %s: %w", url, err)
			}
			results[i] = r
			return nil
		})
	}
	if err := g.Wait(); err != nil {
		return nil, err
	}
	return results, nil
}
```

The first non-nil error cancels `ctx`, stopping the rest. (`i, url` no longer
need capturing since Go 1.22's per-iteration loop variables.)

## select patterns

```go
select {
case v := <-ch:
	use(v)
case <-time.After(time.Second):
	// timeout
case <-ctx.Done():
	return ctx.Err()
default:
	// non-blocking: nothing ready
}
```

## Graceful shutdown

```go
ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
defer cancel()

srv.Start(ctx)
<-ctx.Done()        // wait for signal
srv.Shutdown(5 * time.Second)
```

`Shutdown` should `wg.Wait()` in a goroutine and race it against
`time.After(timeout)` so a stuck worker can't block exit forever.

## State: mutex vs sync.Map

- Default to `sync.RWMutex` guarding a plain map.
- `sync.Map` only for read-heavy, write-rare key sets (caches, registries).
- High write contention → shard the map across N `RWMutex`-guarded buckets.

## Verifying concurrency code

Always run the race detector — it is the single highest-value check here:

```sh
go test -race ./...
go run -race .
```

For a hang/deadlock at runtime, capture goroutine stacks and drive a live
session — see `references/debugging.md` (`SIGQUIT` dump, `dlv goroutines`,
`dbga session`).
