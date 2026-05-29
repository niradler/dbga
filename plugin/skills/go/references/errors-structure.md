# Go error handling & structure

Errors are values. Handle them explicitly at the level that can act on them.
`panic` is for programmer errors only — never for expected failure.

## Wrap with context using %w

Add what *this* layer knows; preserve the chain so callers can inspect it.

```go
func loadConfig(path string) (*Config, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("load config %s: %w", path, err)
	}
	...
}
```

`%w` (not `%v`) keeps the wrapped error reachable by `errors.Is`/`errors.As`.
Wrap with `%w` at most once per error in a chain; use `%v` if you only want the
text, not unwrap-ability.

## Inspect: errors.Is and errors.As

```go
if errors.Is(err, os.ErrNotExist) {
	// matches a sentinel anywhere in the chain
}

var perr *fs.PathError
if errors.As(err, &perr) {
	log.Printf("op=%s path=%s", perr.Op, perr.Path)
}
```

Never compare with `==` against a wrapped error, and never match on
`err.Error()` string contents — both break the moment a layer re-wraps.

## Sentinel errors — known, value-comparable conditions

```go
var ErrNotFound = errors.New("not found")

func (s *Store) Get(id string) (User, error) {
	u, ok := s.m[id]
	if !ok {
		return User{}, ErrNotFound
	}
	return u, nil
}

// caller
if errors.Is(err, ErrNotFound) { ... }
```

## Typed errors — when the caller needs structured data

Implement the `error` interface; expose fields and (optionally) `Unwrap`.

```go
type ValidationError struct {
	Field string
	Err   error
}

func (e *ValidationError) Error() string {
	return fmt.Sprintf("validation failed on %s: %v", e.Field, e.Err)
}

func (e *ValidationError) Unwrap() error { return e.Err }
```

Retrieve it with `errors.As(err, &ve)`.

## Multiple errors (Go 1.20+)

`errors.Join` collects several errors; `errors.Is`/`As` match against any of
them.

```go
var errs error
for _, item := range items {
	if err := validate(item); err != nil {
		errs = errors.Join(errs, err)
	}
}
return errs
```

## panic / recover — the boundary

- `panic` only for unrecoverable programmer bugs (impossible state, broken
  invariant).
- `recover` only at a process boundary you own — e.g. a server's per-request
  handler — to convert a panic into a 500 + logged stack, never to mask logic
  errors.

```go
func safeHandler(h http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		defer func() {
			if v := recover(); v != nil {
				log.Printf("panic: %v\n%s", v, debug.Stack())
				http.Error(w, "internal error", http.StatusInternalServerError)
			}
		}()
		h.ServeHTTP(w, r)
	})
}
```

## Discipline

- Handle each error once: log **or** return, not both.
- Add context going up; don't strip the chain.
- Return early on error to keep the happy path flat.
- Don't ignore errors — `_ = f()` only with a comment justifying why it is safe.

When the error chain doesn't explain *why* a value went wrong at runtime, stop
reading source and gather evidence — see `references/debugging.md`.
