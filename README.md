# Spoiless

A local-first reading companion for EPUB books. Tell Spoiless where you are in a book, then ask questions or request a recap about the chapters you have finished.

Spoiless is an **experimental project in development**. It is designed to limit the book text used for answers to completed chapters, but it cannot guarantee a spoiler-free or accurate response. Chapter detection can also miss or misidentify boundaries, so check them against your EPUB before relying on them.

## What you can do

- Import EPUB books into a local library and choose your current chapter.
- Ask questions and follow up in a conversation about completed chapters.
- Request a recap of a completed chapter or the story through a completed chapter.
- See quotes from the book alongside supported answers.
- Use a local search model to find relevant passages by words and meaning.

Your current chapter is treated as **unread**. Select **Finished book** when you have completed it. Changing your selection saves progress automatically and starts a new conversation; older conversations are hidden, not deleted, until you delete the book.

## Desktop app

The Tauri desktop wrapper bundles the existing Vue interface and Python backend.
See [desktop build instructions](docs/desktop.md) for building a Linux installer
for manual distribution, and the requirements for later Windows/macOS builds.
Windows/macOS builds and real-account AI behavior still need platform testing
before sharing those releases.

## Getting started

### Requirements

- Python 3.12 or newer and [uv](https://docs.astral.sh/uv/)
- Node.js 22.12 or newer and npm
- An internet connection for setup and AI responses
- A ChatGPT account with access to a supported model, and an available operating-system credential store

The ChatGPT connection and answer flow are experimental. Sign-in has been exercised with a real account, while real-account model access and inference have not yet been verified. Account eligibility and availability may vary. On Linux, unlock your system keyring before connecting.

### 1. Start the backend

From the project root:

```sh
cd backend
uv sync --group dev
uv run uvicorn src.main:app --reload
```

Leave this terminal running. The backend health check is at <http://127.0.0.1:8000/api/health>.

### 2. Start the frontend

Open a second terminal in the project root:

```sh
cd frontend
npm ci
npm run dev
```

Open the local URL printed by Vite. Keep both terminals running while using the app.

### 3. Add a book and start a conversation

1. Add an EPUB using the library sidebar. You can try the included [sample book](examples/the-inland-compass.epub). EPUB uploads are limited to 25 MB; the importer may reject some files, including files with encryption metadata.
2. Select the chapter you are currently reading. The app uses the chapters before it as completed text. If chapters cannot be detected, the app offers an AI-assisted analysis; read its warning before proceeding.
3. Under **Local search settings**, download the English search model. This is a one-time download of approximately 90 MB and runs locally.
4. Under **Account and model**, connect your ChatGPT account, load the available models, and select one.
5. Ask a question, such as “Who found the key?” or “Summarize chapter 1.” You can ask follow-up questions in the same conversation.

The local search setup does not send book text when downloading the model. Answer and recap requests send information to OpenAI as described below.

## How Spoiless handles your book

Your library, reading progress, cached search embeddings, and conversations are stored in a local SQLite database at `$XDG_DATA_HOME/spoiless/library.sqlite3`, or `~/.local/share/spoiless/library.sqlite3` when `XDG_DATA_HOME` is unset. ChatGPT credentials are stored separately in the operating system credential store.

For a question, Spoiless searches completed text locally using keyword and semantic retrieval. It may send your question, relevant completed passages, and up to four recent conversation turns to OpenAI. A recap can send the selected completed text in multiple requests. AI-assisted chapter analysis can send short passages around uncertain boundaries, including unread text.

Before displaying a generated answer, Spoiless checks that cited quotes match the supplied text and checks reading progress around generation. These checks reduce risk but do not prove that every claim is supported or prevent model-generated spoilers. If progress changes after a request has started, text already sent cannot be recalled.

Search quality, resource use, and real-account model behavior still need further evaluation. Recap intent detection may miss some phrasings, especially when a question has no matching passages.

## Development

### Backend checks

From `backend`:

```sh
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

### Frontend checks

From `frontend`:

```sh
npm test
npm run lint
npm run format:check
npm run build
```

For browser tests, install Chromium once with `npx playwright install chromium`, then run `npm run test:browser`. Run `npm run test:integration` for browser tests against an isolated local API with simulated OpenAI and credential services. Install the backend development dependencies first.

### Project layout

| Path | Purpose |
| --- | --- |
| `backend/src/library/` | EPUB import, chapters, reading progress, and library storage |
| `backend/src/retrieval/` | Passage retrieval and local search model setup |
| `backend/src/book_assistant/` | Questions, recaps, conversation history, and citations |
| `backend/src/chatgpt/` | ChatGPT sign-in, accounts, models, and inference |
| `frontend/src/pages/library/` | Vue library and conversation interface |
| `examples/` | Sample EPUB for trying the app |
| `showcase/` | Separate static product showcase |

The frontend uses Feature-Sliced Design. The static showcase can be previewed with `python3 -m http.server 8001 --directory showcase` and opened at <http://localhost:8001>; it does not host the local backend.

## More information

- [Retrieval evaluation](docs/retrieval-evaluation.md) — test methods and limitations.
- [ChatGPT connection notes](docs/chatgpt-auth.md) — sign-in and account implementation details.
- [Architecture](docs/architecture.md) and [answer safety](docs/answer-safety.md) — background on data flow and safeguards. Some details in these notes describe earlier iterations and may lag behind the current code.
- [Sample book notes](examples/README.md) — information about the included EPUB.
