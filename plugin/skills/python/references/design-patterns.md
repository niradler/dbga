# Python — design patterns & structure

Python-specific deltas only. Clean-code rules (naming, nesting, no comments) live in `_shared/clean-code.md` — follow them here.

## Start simple — pattern only when it earns its place

A dict beats a registry/factory until you actually need pluggability.

```python
FORMATTERS = {"json": JsonFormatter, "csv": CsvFormatter, "xml": XmlFormatter}

def get_formatter(name: str) -> Formatter:
    if name not in FORMATTERS:
        raise ValueError(f"unknown format: {name}")
    return FORMATTERS[name]()
```

**Rule of three:** two similar functions are often genuinely different (different validation, different errors). Duplication is cheaper than the wrong abstraction — wait for the third case, and even then prefer explicit over clever.

## Single responsibility — split HTTP / logic / data

Each unit has one reason to change. Keep HTTP parsing, business rules, and data access in separate layers so a change to one doesn't ripple.

```python
class UserService:
    def __init__(self, repo: UserRepository) -> None:
        self._repo = repo

    async def create_user(self, data: CreateUserInput) -> User:
        user = User(email=data.email, name=data.name)
        return await self._repo.save(user)

class UserHandler:
    def __init__(self, service: UserService) -> None:
        self._service = service

    async def create_user(self, request: Request) -> Response:
        data = CreateUserInput(**(await request.json()))
        user = await self._service.create_user(data)
        return Response(user.to_dict(), status=201)
```

Layering: **handler** (parse/format) → **service** (domain rules, pure where possible) → **repository** (SQL, external APIs, cache). Each layer depends only on the one below.

## Composition over inheritance

Inject collaborators; don't bake them in via a base class. Composition is testable (swap a fake) and flexible.

```python
class NotificationService:
    def __init__(
        self,
        email: EmailSender,
        sms: SmsSender | None = None,
        push: PushSender | None = None,
    ) -> None:
        self._email, self._sms, self._push = email, sms, push

    async def notify(self, user: User, message: str, channels: set[str] | None = None) -> None:
        channels = channels or {"email"}
        if "email" in channels:
            await self._email.send(user.email, message)
        if "sms" in channels and self._sms and user.phone:
            await self._sms.send(user.phone, message)
        if "push" in channels and self._push and user.device_token:
            await self._push.send(user.device_token, message)
```

## Dependency injection via Protocols

Type dependencies as `Protocol`s (structural typing — see `references/type-hints.md`), pass them through `__init__`. Production wires real implementations; tests wire fakes.

```python
class Cache(Protocol):
    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str, ttl: int) -> None: ...

class UserService:
    def __init__(self, repo: UserRepository, cache: Cache) -> None:
        self._repo, self._cache = repo, cache

    async def get_user(self, user_id: str) -> User:
        cached = await self._cache.get(f"user:{user_id}")
        if cached:
            return User.from_json(cached)
        user = await self._repo.get_by_id(user_id)
        if user:
            await self._cache.set(f"user:{user_id}", user.to_json(), ttl=300)
        return user
```

```python
prod = UserService(PostgresUserRepository(db), RedisCache(redis))
test = UserService(InMemoryUserRepository(), FakeCache())
```

## Function size

Extract when a function exceeds ~20–50 lines, serves multiple purposes, or nests 3+ levels. Compose from focused, well-named calls so the top-level reads as a workflow.

```python
def process_order(order: Order) -> Result:
    validate_order(order)
    reserve_inventory(order)
    payment = charge_payment(order)
    send_confirmation(order, payment)
    return Result(success=True, order_id=order.id)
```

## Anti-patterns to refuse

| Anti-pattern | Fix |
| --- | --- |
| Exposing ORM/internal types from an API | Return a DTO / response schema (`UserResponse.from_orm(user)`) |
| I/O mixed into business logic | Repository pattern; keep domain functions pure and easily tested |
| Scattered timeout/retry per call site | Centralize in a decorator or client wrapper |
| Double retry (app **and** client both retry) | Retry at exactly one layer |
| Hard-coded config / secrets | `pydantic-settings` `BaseSettings` reading env vars |
| Bare `except Exception: pass` | Catch specific exceptions; log or re-raise — see `references/errors-structure.md` |
| Generic `list` / untyped collections | Parameterize: `list[User]` — see `references/type-hints.md` |
| Blocking calls inside `async def` | Async-native libs or `asyncio.to_thread` — see `references/async-concurrency.md` |
| Only happy-path tests | Cover error and edge cases; mock only external services, not everything |
