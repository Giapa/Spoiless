# Spoiless

A local-first reading companion in development. Spoiless is intended to answer questions about books using only chapters the reader has completed.

The current task is the project foundation; book upload, sign-in, retrieval, and answers are not implemented yet. See [TASKS.md](TASKS.md) for the reviewable roadmap and [HANDOFF.md](HANDOFF.md) for the agreed product scope.

## Backend

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```sh
uv sync --group dev
uv run uvicorn spoiless.main:app --reload
```

The health endpoint is available at `http://127.0.0.1:8000/api/health`.

```sh
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

## Frontend

Requires Node.js 22.12+ and npm. With the backend running, open a second terminal:

```sh
cd frontend
npm ci
npm run dev
```

Open the local URL shown by Vite. Run `npm run build` to check types and create a production build, `npm run lint` for Oxlint, and `npm run format:check` for Oxfmt.
