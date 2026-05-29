# Third-Party Notices

This plugin's language skills and expert agents are derived in part from two
MIT-licensed upstream projects. Content was borrowed and refined (adapted,
condensed, and rewritten in this plugin's house style) rather than copied
verbatim, but the files below draw substantially on the listed sources. The
full MIT license text of each upstream is reproduced at the end, as the MIT
license requires — a commit SHA alone is not MIT compliance.

---

## wshobson/agents

- Repository: https://github.com/wshobson/agents
- License: MIT — Copyright (c) 2024 Seth Hobson
- Used for: per-topic skill content (design patterns, type safety, error
  handling, async, concurrency, anti-patterns) and lean specialist agent
  structure.

### Files derived from this source

| Plugin file | Upstream path | Commit SHA |
| --- | --- | --- |
| `skills/python/references/design-patterns.md` | `plugins/python-development/skills/python-design-patterns/references/details.md` (+ `python-anti-patterns/SKILL.md`) | `707d9c42` (+ `ee62f8c1`) |
| `skills/python/references/type-hints.md` | `plugins/python-development/skills/python-type-safety/references/details.md` | (blob SHA not captured) |
| `skills/python/references/async-concurrency.md` | `plugins/python-development/skills/async-python-patterns/references/details.md` | `475eb9ae` |
| `skills/python/references/errors-structure.md` | `plugins/python-development/skills/python-error-handling/references/details.md` | `64f6611d` |
| `skills/go/references/concurrency.md` | `plugins/systems-programming/skills/go-concurrency-patterns/SKILL.md` (+ `references/details.md`) | `be57c0b2` |
| `skills/node/references/design-patterns.md` | `plugins/javascript-typescript/skills/nodejs-backend-patterns/SKILL.md` | `516bae62` |
| `skills/node/references/async-patterns.md` | `plugins/javascript-typescript/skills/{nodejs-backend-patterns,modern-javascript-patterns}/SKILL.md` | `516bae62` / `a7739c73` |
| `skills/node/references/errors-structure.md` | `plugins/javascript-typescript/skills/nodejs-backend-patterns/SKILL.md` | `516bae62` |
| `skills/node/references/typescript-types.md` | `plugins/javascript-typescript/skills/typescript-advanced-types/SKILL.md` | `5057af79` |
| `agents/python-expert.md` | `plugins/python-development/agents/python-pro.md` | `e03c788f` |
| `agents/go-expert.md` | `plugins/systems-programming/agents/golang-pro.md` | `56848874` |
| `agents/node-expert.md` | `plugins/javascript-typescript/agents/typescript-pro.md` | `3cc2a5a5` |

### License (verbatim)

```
MIT License

Copyright (c) 2024 Seth Hobson

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

## VoltAgent/awesome-claude-code-subagents

- Repository: https://github.com/VoltAgent/awesome-claude-code-subagents
- License: MIT — Copyright (c) 2025 VoltAgent
- Used for: deep specialist-agent sections (operational checklists, type-system
  mastery, async, testing methodology, security, collaboration protocol) and
  the Node JS-fallback content.

### Files derived from this source

| Plugin file | Upstream path | Commit SHA |
| --- | --- | --- |
| `agents/python-expert.md` | `categories/02-language-specialists/python-pro.md` | `7a6ee971` |
| `agents/go-expert.md` | `categories/02-language-specialists/golang-pro.md` | `c3e5f7a5` |
| `agents/node-expert.md` | `categories/02-language-specialists/typescript-pro.md` | `dc87923e` |
| `skills/node/references/js-fallback.md` | `categories/02-language-specialists/javascript-pro.md` | `2f45e056` |

### License (verbatim)

```
MIT License

Copyright (c) 2025 VoltAgent

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
