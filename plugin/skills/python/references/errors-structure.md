# Python — error handling & structure

Python-specific deltas. Errors carry structured context, chain to preserve the debug trail, and never silently vanish.

## Custom exception hierarchies

Give a domain its own base exception; subclass for specific failures and attach the data a handler needs.

```python
class ApiError(Exception):
    def __init__(self, message: str, status_code: int, body: str | None = None) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(message)

class RateLimitError(ApiError):
    def __init__(self, retry_after: int) -> None:
        self.retry_after = retry_after
        super().__init__(f"rate limit exceeded; retry after {retry_after}s", status_code=429)
```

`match` over a status (or any discriminant) keeps multi-branch dispatch flat — no nested `if`:

```python
def handle(response: Response) -> dict:
    match response.status_code:
        case 200:
            return response.json()
        case 401:
            raise ApiError("invalid credentials", 401)
        case 429:
            raise RateLimitError(int(response.headers.get("Retry-After", 60)))
        case code if 400 <= code < 500:
            raise ApiError(f"client error: {response.text}", code)
        case code if code >= 500:
            raise ApiError(f"server error: {response.text}", code)
```

## Chain exceptions — `raise ... from e`

Translate low-level errors into domain errors, but keep the original cause so the traceback (and `dbga diagnose`) shows the real root.

```python
def upload_file(path: str) -> str:
    try:
        with open(path, "rb") as f:
            r = httpx.post("https://upload.example.com", files={"file": f})
            r.raise_for_status()
            return r.json()["url"]
    except FileNotFoundError as e:
        raise ServiceError(f"upload failed: no file at {path!r}") from e
    except httpx.HTTPStatusError as e:
        raise ServiceError(f"upload failed: server returned {e.response.status_code}") from e
```

Never `except Exception: pass` — it hides bugs forever. Catch the specific type; log or re-raise.

## Partial-failure batches

One bad item must not abort the batch. Track success and failure per index and let the caller decide.

```python
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")

@dataclass
class BatchResult(Generic[T]):
    succeeded: dict[int, T]
    failed: dict[int, Exception]

    @property
    def all_succeeded(self) -> bool:
        return not self.failed

def process_batch(items: list[Item]) -> BatchResult[ProcessedItem]:
    succeeded: dict[int, ProcessedItem] = {}
    failed: dict[int, Exception] = {}
    for idx, item in enumerate(items):
        try:
            succeeded[idx] = process_single_item(item)
        except Exception as e:
            failed[idx] = e
    return BatchResult(succeeded, failed)
```

For long batches, accept an optional `Callable[[int, int, str], None]` progress callback instead of coupling the loop to any UI.

## Validate at the boundary

Reject bad input where it enters (API edge, CLI arg, config load) — not deep in business logic where the failure is cryptic.

```python
def create_user(data: dict) -> User:
    validated = CreateUserInput.model_validate(data)
    return User.from_input(validated)
```

`pydantic` models / `pydantic-settings` `BaseSettings` are the idiomatic boundary validators; raise a domain error on failure.

## Resources: always a context manager

```python
def read_file(path: str) -> str:
    with open(path) as f:
        return f.read()
```

A leaked file/socket/connection survives an exception. `with` (or `async with`) guarantees cleanup on every path. Implement `__enter__`/`__exit__` (or the async pair) for your own resources.

## When an exception is the bug

Don't reason about which branch raised — observe it. `dbga diagnose -- python app.py` pauses at the deepest user frame with the live locals that produced the error. See `references/debugging.md`.
