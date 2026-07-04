# Contributing to STL Studio

Thanks for your interest in contributing!

## Before You Start

- Check [open issues](https://github.com/RBStephenson/STL-Inventory/issues) to avoid duplicate work.
- For significant changes, open an issue first to discuss the approach.
- All PRs must target the `main` branch.

## Development Setup

**1. Install root dependencies (required once — activates the pre-commit hook)**

```bash
npm install
```

This installs [Husky](https://typicode.github.io/husky/) at the repo root and
wires a pre-commit hook that runs the full test suite before every commit.

**2. Build the backend image (required for the pytest hook to run)**

```bash
docker compose build backend
```

If Docker is not running or the image hasn't been built, the pytest step is
skipped with a warning so offline commits aren't blocked. Build it once and
keep Docker running during development.

**3. Frontend (React + TypeScript)**

```bash
cd frontend
npm ci
npm run dev     # starts Vite dev server on :3000
```

**4. Full stack via Docker**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

The dev overlay bind-mounts the source and runs `uvicorn --reload`, so Python
edits take effect without a rebuild.

## Running Tests

**Vitest (frontend)**

```bash
npm --prefix frontend test
```

**Pytest (backend)**

The suite requires no local Python environment — it runs inside the backend
Docker image with the source mounted in:

```bash
docker run --rm --workdir /app \
  -e DATABASE_URL="sqlite:///:memory:" \
  -v "$(pwd)/backend:/app" \
  -v "$(pwd)/packaging:/packaging" \
  stl-inventory-backend:latest \
  sh -c "pip install -q pytest==9.0.3 pytest-cov==7.1.0 && pytest tests/ -q --tb=short"
```

Both suites run automatically via the pre-commit hook. To skip in an emergency:
`git commit --no-verify` (use sparingly).

## Pull Request Checklist

- [ ] Pre-commit hook passed (vitest + pytest both green)
- [ ] New backend logic has corresponding tests
- [ ] No secrets, credentials, or local paths committed
- [ ] PR description explains *why*, not just *what*

## Frontend architecture

**Server state** is managed with [TanStack Query](https://tanstack.com/query).
Fetch logic lives in `frontend/src/hooks/queries/`; components use those hooks
rather than calling `api.*` directly in effects.

**API client** (`frontend/src/api/`) is split into per-domain modules:

| Module | Covers |
|--------|--------|
| `models.ts` | Model CRUD, STL files, AI naming |
| `settings.ts` | App settings, AI APIs, credentials |
| `files.ts` | File serving, ZIP download |
| `collections.ts`, `painting.ts`, etc. | Domain modules |
| `types.ts` | All shared TypeScript interfaces |
| `client.ts` | Barrel re-export — `import { api } from "../api/client"` still works |

When adding a new endpoint, put the call in the relevant domain module and the
types in `types.ts`. The barrel re-exports everything, so call sites don't need
updating.

## Code Style

- **Python**: standard PEP 8; type hints on public functions.
- **TypeScript**: strict mode; no `any` without a comment explaining why.
- Comments only when the *why* is non-obvious — well-named identifiers should
  speak for themselves.

## Licensing

By submitting a pull request you agree that your contributions will be licensed
under the [MIT License](LICENSE).
