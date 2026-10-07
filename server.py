"""Small local RAG API backed by Ollama and a JSON knowledge store."""
from __future__ import annotations

import json
import math
import os
import re
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("RAG_DATA_DIR", ROOT / "data"))
STORE = DATA_DIR / "knowledge.json"
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
CHAT_MODEL = os.getenv("OLLAMA_CHAT_MODEL", "llama3.2")
EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
MAX_BODY = 8 * 1024 * 1024
LOCK = threading.Lock()


def load_store() -> list[dict[str, Any]]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        return json.loads(STORE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_store(chunks: list[dict[str, Any]]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(chunks, ensure_ascii=False), encoding="utf-8")


def ollama(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{OLLAMA_URL.rstrip('/')}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.loads(response.read())
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise RuntimeError(
            f"Could not reach Ollama at {OLLAMA_URL}. Start Ollama and pull the configured models. ({reason})"
        ) from exc


def embed(texts: list[str]) -> list[list[float]]:
    result = ollama("/api/embed", {"model": EMBED_MODEL, "input": texts})
    vectors = result.get("embeddings")
    if not vectors:
        raise RuntimeError("Ollama returned no embeddings. Check that the embedding model is installed.")
    return vectors


def chunks_for(text: str, size: int = 900, overlap: int = 140) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    parts = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            boundary = text.rfind(" ", start + size // 2, end)
            if boundary > start:
                end = boundary
        parts.append(text[start:end].strip())
        if end == len(text):
            break
        start = max(end - overlap, start + 1)
    return parts


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0


class Handler(BaseHTTPRequestHandler):
    server_version = "LocalRAG/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def send_json(self, status: int, body: dict[str, Any]) -> None:
        raw = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(raw)

    def body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > MAX_BODY:
            raise ValueError("Request is too large (maximum 8 MB).")
        return json.loads(self.rfile.read(length) or b"{}")

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/health":
            try:
                with urllib.request.urlopen(f"{OLLAMA_URL.rstrip('/')}/api/tags", timeout=3) as response:
                    tags = json.loads(response.read()).get("models", [])
                models = [m.get("name", "") for m in tags]
                self.send_json(200, {"ok": True, "ollama": True, "chat_model": CHAT_MODEL, "embed_model": EMBED_MODEL,
                                     "chat_model_ready": any(m == CHAT_MODEL or m.startswith(CHAT_MODEL + ":") for m in models),
                                     "embed_model_ready": any(m == EMBED_MODEL or m.startswith(EMBED_MODEL + ":") for m in models)})
            except Exception:
                self.send_json(200, {"ok": True, "ollama": False, "chat_model": CHAT_MODEL, "embed_model": EMBED_MODEL,
                                     "chat_model_ready": False, "embed_model_ready": False})
        elif path == "/api/documents":
            with LOCK:
                chunks = load_store()
            docs: dict[str, int] = {}
            for chunk in chunks:
                docs[chunk["source"]] = docs.get(chunk["source"], 0) + 1
            self.send_json(200, {"documents": [{"name": name, "chunks": count} for name, count in docs.items()]})
        else:
            asset = {"/": "index.html", "/index.html": "index.html", "/styles.css": "styles.css", "/app.js": "app.js"}.get(path)
            if not asset:
                return self.send_json(404, {"error": "Not found"})
            file_path = ROOT / asset
            content = file_path.read_bytes()
            content_type = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8"}[file_path.suffix]
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            payload = self.body()
            if path == "/api/documents":
                name = Path(str(payload.get("name", "document.txt"))).name[:180]
                content = str(payload.get("content", ""))
                if not content.strip():
                    return self.send_json(400, {"error": "This file has no readable text."})
                if len(content) > 1_000_000:
                    return self.send_json(400, {"error": "A document must be under 1 MB of text."})
                texts = chunks_for(content)
                vectors = embed(texts)
                items = [{"source": name, "text": text, "embedding": vector} for text, vector in zip(texts, vectors)]
                with LOCK:
                    store = [item for item in load_store() if item["source"] != name] + items
                    save_store(store)
                return self.send_json(200, {"ok": True, "name": name, "chunks": len(items)})
            if path == "/api/chat":
                question = str(payload.get("message", "")).strip()
                if not question:
                    return self.send_json(400, {"error": "Enter a question first."})
                with LOCK:
                    store = load_store()
                if not store:
                    return self.send_json(400, {"error": "Add a document to your knowledge base first."})
                query_vector = embed([question])[0]
                matches = sorted(store, key=lambda c: cosine(query_vector, c["embedding"]), reverse=True)[:4]
                context = "\n\n".join(f"[{item['source']}] {item['text']}" for item in matches)
                messages = [{"role": "system", "content": "Answer using only the supplied knowledge base context. If the context does not contain the answer, say you could not find it in the knowledge base. Keep answers clear and concise. Cite supporting files by their bracketed filename."}]
                for message in payload.get("history", [])[-8:]:
                    role = "assistant" if message.get("role") == "assistant" else "user"
                    messages.append({"role": role, "content": str(message.get("content", ""))[:3000]})
                messages.append({"role": "user", "content": f"Knowledge base context:\n{context}\n\nQuestion: {question}"})
                response = ollama("/api/chat", {"model": CHAT_MODEL, "messages": messages, "stream": False})
                answer = response.get("message", {}).get("content", "").strip()
                sources = []
                seen = set()
                for item in matches:
                    if item["source"] not in seen:
                        seen.add(item["source"])
                        sources.append({"name": item["source"], "excerpt": item["text"][:240]})
                return self.send_json(200, {"answer": answer, "sources": sources})
            self.send_json(404, {"error": "Not found"})
        except (ValueError, json.JSONDecodeError) as exc:
            self.send_json(400, {"error": str(exc)})
        except Exception as exc:
            self.send_json(502, {"error": str(exc)})

    def do_DELETE(self) -> None:
        path = urlparse(self.path).path
        if not path.startswith("/api/documents/"):
            return self.send_json(404, {"error": "Not found"})
        name = unquote(path.rsplit("/", 1)[-1])
        with LOCK:
            store = [item for item in load_store() if item["source"] != name]
            save_store(store)
        self.send_json(200, {"ok": True})


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    print(f"Knowledge chat is ready at http://localhost:{port}")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
