# Contributing to STL Inventory

Thanks for your interest in contributing!

## Before You Start

- Check [open issues](https://github.com/RBStephenson/STL-Inventory/issues) to avoid duplicate work.
- For significant changes, open an issue first to discuss the approach.
- All PRs must target the `main` branch.

## Development Setup

**Backend (Python 3.12 + FastAPI)**

```bash
cd backend
pip install -r requirements-test.txt
pytest          # run the test suite
```

**Frontend (React + TypeScript)**

```bash
cd frontend
npm ci
npm run dev     # starts Vite dev server on :3000
```

**Full stack via Docker**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

The dev overlay bind-mounts the source and runs `uvicorn --reload`, so Python
edits take effect without a rebuild.

## Pull Request Checklist

- [ ] Tests pass (`pytest` in `backend/`)
- [ ] New backend logic has corresponding tests
- [ ] No secrets, credentials, or local paths committed
- [ ] PR description explains *why*, not just *what*

## Code Style

- **Python**: standard PEP 8; type hints on public functions.
- **TypeScript**: strict mode; no `any` without a comment explaining why.
- Comments only when the *why* is non-obvious — well-named identifiers should
  speak for themselves.

## Licensing

By submitting a pull request you agree that your contributions will be licensed
under the [MIT License](LICENSE).
