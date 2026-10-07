# Chatbot

Simple RAG chatbot.

## Groundwork — local knowledge chat

A small retrieval-augmented generation (RAG) chatbot with a browser UI, a Python backend, and local open models served by [Ollama](https://ollama.com). Documents are chunked, embedded locally, and stored in `data/knowledge.json`. Questions retrieve the four closest chunks before the model writes an answer with file sources.

## Requirements

- Python 3.10+
- [Ollama](https://ollama.com/download) running locally
- `llama3.2` for chat and `nomic-embed-text` for embeddings (both open models)

## Start

Pull the models once:

```sh
ollama pull llama3.2
ollama pull nomic-embed-text
```

Start the app:

```sh
python3 server.py
```

Open [http://localhost:8000](http://localhost:8000). The server serves the app UI and its API from the same port.

## Use

Choose **Add documents** and select `.txt` or `.md` files (up to 1 MB each). Ask a question in the composer. Answers include the source filenames, and the UI lets you remove a file from the knowledge base. Indexing and answers run through Ollama on your machine.

## Configuration

Override defaults with environment variables:

```sh
OLLAMA_URL=http://localhost:11434 \
OLLAMA_CHAT_MODEL=llama3.2 \
OLLAMA_EMBED_MODEL=nomic-embed-text \
RAG_DATA_DIR=./data \
PORT=8000 \
python3 server.py
```

The browser UI and API are served from the same port, including when `PORT` is changed.

## API

- `GET /api/health` — app and model readiness
- `GET /api/documents` — indexed files
- `POST /api/documents` — JSON `{ "name": "notes.md", "content": "..." }`
- `DELETE /api/documents/{filename}` — remove a file
- `POST /api/chat` — JSON `{ "message": "...", "history": [] }`

This is a simple single-user local app. Do not expose the server directly to the public internet without adding authentication and request protections.
