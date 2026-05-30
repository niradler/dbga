# Python — type hints & the type system

Python-specific deltas. Target `mypy --strict`. Use 3.10+ syntax: `X | None` (not `Optional[X]`), `list[str]`/`dict[str, int]` (not `typing.List`), builtins over `typing` aliases.

## Baseline

- Annotate **every** public signature and class attribute. Return types too.
- Parameterize collections: `list[User]`, never bare `list`.
- Minimize `Any`; it's acceptable only for genuinely dynamic data, and isolate it behind a typed boundary.
- `mypy --strict` clean is the bar. Don't add `# type: ignore` without a `[code]` and a reason.

## Protocols — structural typing without inheritance

A class satisfies a `Protocol` by shape, not by subclassing. This is the idiomatic way to type injected dependencies (see `references/design-patterns.md`).

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class Serializable(Protocol):
    def to_dict(self) -> dict: ...

def serialize(obj: Serializable) -> str:
    return json.dumps(obj.to_dict())
```

Reusable shapes: `Closeable` (`close()`), `Readable` (`read()`), `HasId` (`id` property). `@runtime_checkable` enables `isinstance` checks against the protocol.

## Generics

```python
from typing import Generic, TypeVar
from abc import ABC, abstractmethod

T = TypeVar("T")
ID = TypeVar("ID")

class Repository(ABC, Generic[T, ID]):
    @abstractmethod
    async def get(self, id: ID) -> T | None: ...
    @abstractmethod
    async def save(self, entity: T) -> T: ...

class UserRepository(Repository[User, str]):
    async def get(self, id: str) -> User | None: ...
    async def save(self, entity: User) -> User: ...
```

**Bounded TypeVar** restricts the parameter and preserves the concrete return type:

```python
from typing import TypeVar
from pydantic import BaseModel

ModelT = TypeVar("ModelT", bound=BaseModel)

def validate_and_create(model_cls: type[ModelT], data: dict) -> ModelT:
    return model_cls.model_validate(data)

user = validate_and_create(User, {"name": "Alice", "email": "a@b.com"})
```

`validate_and_create(str, ...)` is a type error — `str` is not a `BaseModel`.

## Type aliases (version-aware)

PEP 695 `type` statement is **3.12+**. For 3.10/3.11 use `TypeAlias`.

```python
type UserId = str                        # 3.12+
type Handler[T] = Callable[[Request], T]  # 3.12+ generic alias
```

```python
from typing import TypeAlias              # 3.10/3.11
from collections.abc import Callable

UserId: TypeAlias = str
Handler: TypeAlias = Callable[[Request], Response]
```

## Callable types & callbacks

Import `Callable`/`Awaitable` from `collections.abc`, not `typing`.

```python
from collections.abc import Callable, Awaitable

ProgressCallback = Callable[[int, int], None]
AsyncHandler = Callable[[Request], Awaitable[Response]]
```

For keyword args in a callback, use a `Protocol` with `__call__`:

```python
class OnProgress(Protocol):
    def __call__(self, current: int, total: int, *, message: str = "") -> None: ...
```

## Narrowing — proving `X | None` is `X`

Most `AttributeError: 'NoneType' object has no attribute …` bugs are a missing narrow: the type is `X | None` and the code touched it without ruling out `None`. Narrow explicitly so mypy *and* the runtime agree:

```python
def process(user: User | None) -> str:
    if user is None:
        raise ValueError("user required")
    return user.name           # narrowed to User

names = [u.name for u in users if u is not None]   # filter narrows each element
```

`isinstance` narrows by type; `assert x is not None` narrows inline (but is stripped under `python -O`). For a custom predicate, return `TypeGuard[T]` (3.10+) / `TypeIs[T]` (3.13+) so the narrowing survives across the function boundary:

```python
from typing import TypeGuard

def all_strings(xs: list[object]) -> TypeGuard[list[str]]:
    return all(isinstance(x, str) for x in xs)
```

When a `dbga` stop shows `None` where you expected a value, walk back to the branch that should have narrowed it — the missing guard is the bug.

## Also reach for

`TypedDict` (structured dicts), `Literal` (constants/enums-lite), `ParamSpec` (decorators preserving signatures), `@overload` (input-dependent return types).

## mypy strict config

```toml
[tool.mypy]
python_version = "3.12"
strict = true
warn_return_any = true
warn_unused_ignores = true
disallow_untyped_defs = true
no_implicit_optional = true
```

Adopting strict on a legacy codebase: enable per-module with `# mypy: strict` or `pyproject.toml` overrides, then expand outward.
