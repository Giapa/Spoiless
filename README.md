# Spoiless

A local-first reading companion in development. Spoiless is intended to answer questions about books using only chapters the reader has completed.

You can import and delete EPUBs in a local library. Readers can confirm chapters and record their progress. Sign-in and AI answers are not implemented yet. The EPUB importer is conservative and may reject some valid files, including those with encryption metadata. See [TASKS.md](TASKS.md) for the reviewable roadmap and [HANDOFF.md](HANDOFF.md) for the agreed product scope.

The library is stored in `$XDG_DATA_HOME/spoiless/library.sqlite3`, or `~/.local/share/spoiless/library.sqlite3` if `XDG_DATA_HOME` is unset.

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

The frontend follows Feature-Sliced Design. `src/App.vue` provides the app shell; `src/pages/library` groups the library page's `ui`, `model`, and `api` code. Import the needed file directly; slices may only depend on lower layers. Add layers and slices when the application needs them.

## Reading progress

After confirming a book's chapters, choose your current chapter and save it in the library. The current chapter is treated as unread; select **Finished book** to include all chapters. Changing chapter boundaries clears the saved progress, so choose it again. Chapter review can show unread text when you explicitly open the manual review.

Questions, recaps, conversations, and AI retrieval are not implemented yet. The eligible-text boundary is tested locally but is not a guarantee against future model-generated spoilers.

## Retrieval in progress

An offline keyword-search API builds a temporary index from eligible text only, after applying saved progress. This is a first step toward hybrid retrieval, not AI answering. The experimental hybrid-search API combines keyword and semantic rankings using a local model. It stores embeddings for previously eligible passages in the local library database and reuses them only when the passage and model version match. It still rebuilds the keyword index each search. Tests use a fake model; real hybrid retrieval quality and CPU use have not yet been evaluated. After saving progress, open “Search completed chapters” to search by words or, after model setup, by words and meaning. Search results are local book passages, not AI answers. Deleting a book deletes its stored embeddings. Results are discarded if eligible text changes during retrieval, but future answer generation must also guard against changes after retrieval.

## Sample and evaluation

The [sample EPUB](examples/the-inland-compass.epub) is a short fictional story that can be redistributed. Run `uv run python scripts/evaluate_retrieval.py` for offline keyword and boundary checks. Add `--hybrid` only after downloading the model in the app. See [the evaluation notes](docs/retrieval-evaluation.md) for results and limitations. EPUBs imported before the document-head fix may need to be deleted and reimported to remove metadata from their stored text.

## ChatGPT connection

The sign-in request, local callback listener, token exchange and identity verification are tested offline with a simulated server. Linux secure credential storage has passed a temporary save/read/delete check on the development machine, and a local registry can remember and reauthorize verified account registrations through backend controls. The sign-in interface, token refresh, and real-account verification are not yet available. See [the sign-in notes](docs/chatgpt-auth.md) for the remaining work.
