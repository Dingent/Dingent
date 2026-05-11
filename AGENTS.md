# Dingent Agentic Coding Instructions (AGENTS.md)

This document provides core system instructions for AI coding agents operating within the Dingent repository. Follow these guidelines rigorously to ensure consistency, correct tool usage, and safe operations.

## 1. Project Context & Architecture

Dingent is a cross-platform AI agent framework.
- **Backend:** Python (FastAPI, LangGraph, SQLModel, Loguru, Typer CLI). Located under `src/dingent/`.
- **Frontend:** Node.js / React / Next.js. Located in the `ui/` directory.
- **Package Manager:** `uv` for Python (see `pyproject.toml`, `uv.lock`), `bun` for frontend.
- **Task Runner:** `just` (see `justfile`).

## 2. Environment & Commands

### Prerequisites
- Python >= 3.12, < 3.14 (Target is Python 3.13)
- `uv` for Python dependency management
- `bun` for Frontend dependency management
- `just` command runner

### Build & Run
- **Frontend Build:** `just _build-ui` or `cd ui/ && bun install && bun run build`
- **Full Assembly:** `just build`
- **CLI Execution:** Use `dingent run` or `uv run dingent` to launch.

### Linting & Formatting
We use `ruff` for formatting and linting, and `basedpyright` for static type checking.
- **Format:** `uv run ruff format .` (Line length is strictly 180 characters, uses double quotes).
- **Lint:** `uv run ruff check . --fix`
- **Type Check:** `uv run basedpyright`
- **Pre-commit:** Always ensure hooks pass (`uv run pre-commit run --all-files`).

### Testing
We use `pytest` with `pytest-asyncio` for the backend.
- **Run all tests:** `uv run pytest`
- **Run tests in a specific directory:** `uv run pytest tests/`
- **Run a single test file:** `uv run pytest tests/path_to_test.py`
- **Run a single test method (Crucial for fast feedback loops):**
  `uv run pytest tests/path_to_test.py::test_function_name -v -s`
- **Coverage:** `uv run pytest --cov=src/dingent tests/`

When writing tests, place them in the `tests/` directory. Make extensive use of `pytest.mark.asyncio` for asynchronous tests. Use `pytest-mock` for mocking instead of `unittest.mock`.

## 3. Python Code Style Guidelines

### 3.1. General Formatting & Syntax
- Target **Python 3.13** syntax.
- File headers typically include `from __future__ import annotations`.
- Line length limit is **180**.
- Docstrings: Use standard formats. Ruff format is enabled for docstrings (line length 20 inside docstrings).
- Never perform function calls in argument defaults (`B008` is ignored in Ruff config, but prefer strict default boundaries anyway).

### 3.2. Types & Annotations
- Use strict and exhaustive type hinting for all function arguments and return types.
- Use built-in types (`list`, `dict`) rather than `typing` module equivalents (`List`, `Dict`) per modern Python standards.
- Use `Annotated` from `typing` where appropriate for dependency injection or metadata.
- `basedpyright` is configured in `standard` mode with `reportMissingImports="error"`. Do not use unknown imports or bypass type checking unnecessarily.

### 3.3. Naming Conventions
- **Classes:** `PascalCase`
- **Functions, Variables, Attributes:** `snake_case`
- **Constants:** `UPPER_SNAKE_CASE`
- **Protected/Private:** Prefix with a single underscore `_`.

### 3.4. Async Programming
- The framework is heavily asynchronous (FastAPI, LangGraph, Aiohttp).
- Use `async def` and `await` by default for I/O operations (Database, Network, File operations).
- Avoid mixing synchronous and asynchronous I/O if possible. Run blocking operations in thread pools.

### 3.5. Error Handling & Logging
- Use standard Python exceptions.
- For API endpoints, raise `HTTPException`. Note: Ruff `B904` (raising exceptions without `from e`) is explicitly ignored to allow clean `HTTPException` raises.
- Use **`loguru`** for all logging. Do NOT use the standard `logging` module.
  - Example: `from loguru import logger`

### 3.6. Imports
- Use absolute imports instead of relative imports where possible.
- Group imports logically:
  1. Standard library imports
  2. Third-party imports (e.g., `fastapi`, `langgraph`, `sqlmodel`, `loguru`)
  3. Local application imports (e.g., `from dingent.core.paths import paths`)

## 4. Frontend Code Style Guidelines (`ui/` directory)

- **Framework:** Next.js (Standalone mode), React, TypeScript.
- **Package Manager:** Use `bun`. Never use `npm`, `yarn`, or `pnpm` to add dependencies.
  - Install dependency: `cd ui && bun add <package>`
  - Build UI: `cd ui && bun run build`
- **Types:** Use strict TypeScript. Define interfaces or types for props and state.
- **Components:** Use functional components and React Hooks.
- Ensure any modifications to frontend logic can compile under `next build`.
- Deployment relies on the `.next/standalone` output (handled by `just assemble`).

## 5. Agent Operational Directives

When modifying this repository, Agents MUST adhere to the following workflow:

1. **Understand Before Modifying:**
   - Use `rg` or `grep` to find references.
   - Use `cat` or `read` to check exact file structures.
   - Verify assumptions against `pyproject.toml` and `uv.lock`.
2. **Implement Incrementally:**
   - Keep changes scoped. Do not rewrite unrelated files.
   - If editing frontend code, ensure `bun run build` succeeds.
3. **Verify Everything:**
   - Always run the linter: `uv run ruff check .`
   - Always run the formatter check: `uv run ruff format --check .`
   - Run a targeted test before calling the work complete: `uv run pytest tests/<modified_module>_test.py::test_name`
4. **Safety & Quality:**
   - Do not leave commented-out debug code (`print` or `logger.debug` statements that were only used for debugging).
   - Ensure secrets are never hardcoded in the repository.
   - Maintain the line-length (180) and formatting exactly as defined by the Ruff settings.
