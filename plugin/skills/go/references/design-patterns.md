# Go design patterns & idioms

Go-specific deltas only. General clean-code rules: `_shared/clean-code.md`.

## Accept interfaces, return structs

Define the interface where it is *consumed*, not where the type is implemented.
Keep interfaces small — one or two methods.

```go
type Store interface {
	Get(ctx context.Context, id string) (User, error)
}

func NewService(s Store) *Service { return &Service{store: s} }
```

The caller depends on `Store`; any concrete struct with a matching `Get`
satisfies it implicitly. This makes testing trivial — pass a fake.

## Composition over inheritance (embedding)

```go
type Logger struct{ prefix string }

func (l Logger) Log(msg string) { fmt.Println(l.prefix, msg) }

type Server struct {
	Logger
	addr string
}
```

`Server` promotes `Log` — no inheritance, just composition. Embed interfaces to
extend behavior, embed structs to reuse it.

## Functional options for configuration

Preferred over giant config structs or many constructors. Each option is a
closure that mutates the target; defaults stay in the constructor.

```go
type Server struct {
	addr    string
	timeout time.Duration
}

type Option func(*Server)

func WithTimeout(d time.Duration) Option {
	return func(s *Server) { s.timeout = d }
}

func NewServer(addr string, opts ...Option) *Server {
	s := &Server{addr: addr, timeout: 30 * time.Second}
	for _, opt := range opts {
		opt(s)
	}
	return s
}

s := NewServer(":8080", WithTimeout(5*time.Second))
```

## Generics — when type parameters earn their place

Use generics to remove `interface{}` and runtime type assertions from genuinely
type-agnostic code (containers, map/filter/reduce). Do **not** reach for them
when a plain interface expresses the contract better.

```go
func Map[T, U any](s []T, f func(T) U) []U {
	out := make([]U, len(s))
	for i, v := range s {
		out[i] = f(v)
	}
	return out
}
```

Constrain with `comparable` or `constraints.Ordered` when the body needs `==`
or `<`.

## Package layout

- Package name = its purpose, lower-case, no `util`/`common` dumping grounds.
- Exported API at the top of the file; unexported helpers below.
- `internal/` for code that must not be imported by other modules.
- One responsibility per package; avoid circular imports by depending on
  interfaces, not concrete packages.

## Idioms

- Zero value should be useful (`sync.Mutex`, `bytes.Buffer` work unboxed).
- `defer` for cleanup right after acquiring a resource — pair `Open`/`Close`,
  `Lock`/`Unlock` on adjacent lines.
- Return early; keep the happy path un-indented.
- Slices: pre-allocate with `make([]T, 0, n)` when the size is known.

## Anti-patterns to reject

| Anti-pattern | Do instead |
| --- | --- |
| Empty `interface{}` / `any` everywhere | A focused interface or generics |
| Returning concrete errors as `bool` ok-flags for failure | Return `error` |
| Giant interfaces ("god interface") | Split into role-specific interfaces |
| Naked `panic` for expected failures | Return an `error` (see `errors-structure.md`) |
| Goroutine without a defined exit path | Bound it with `context` (see `concurrency.md`) |
| `util` / `helpers` packages | Name packages by what they provide |

When in doubt, run `go vet ./...` and `golangci-lint run` — they catch most of
these mechanically.
