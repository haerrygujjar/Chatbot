const API = `${location.origin}/api`;
const $ = (selector) => document.querySelector(selector);

const welcome = $('#welcome');
const conversation = $('#conversation');
const form = $('#chat-form');
const input = $('#message');
const sendButton = $('#send');
const fileInput = $('#file-input');

let history = [];
let toastTimer;

async function request(path, options = {}) {
  const response = await fetch(`${API}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  const data = await response.json();

  if (!response.ok) {
    throw new Error(data.error || 'Something went wrong.');
  }

  return data;
}

function notify(message) {
  const toast = $('#toast');
  toast.textContent = message;
  toast.classList.add('show');

  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove('show'), 3300);
}

async function refreshStatus() {
  const badge = $('#model-status');

  try {
    const status = await request('/health');
    const ready = status.ollama && status.chat_model_ready && status.embed_model_ready;

    badge.className = `model-status ${ready ? 'ready' : 'offline'}`;
    badge.lastElementChild.textContent = ready
      ? `Local · ${status.chat_model}`
      : status.ollama
        ? 'Models need setup'
        : 'Ollama not running';
    badge.title = `Chat: ${status.chat_model} · Embeddings: ${status.embed_model}`;
  } catch {
    badge.className = 'model-status offline';
    badge.lastElementChild.textContent = 'Backend unavailable';
  }
}

async function refreshDocuments() {
  try {
    const { documents } = await request('/documents');
    const list = $('#document-list');

    $('#doc-count').textContent = documents.length;
    list.replaceChildren();

    documents.forEach((doc) => {
      const row = document.createElement('div');
      const icon = document.createElement('span');
      const name = document.createElement('span');
      const remove = document.createElement('button');

      row.className = 'doc-item';
      row.title = `${doc.name} · ${doc.chunks} chunks`;
      icon.className = 'doc-icon';
      icon.textContent = '▤';
      name.className = 'doc-name';
      name.textContent = doc.name;
      remove.className = 'remove-doc';
      remove.textContent = '×';
      remove.title = `Remove ${doc.name}`;
      remove.onclick = async () => {
        try {
          await request(`/documents/${encodeURIComponent(doc.name)}`, {
            method: 'DELETE',
          });
          await refreshDocuments();
          notify('Document removed');
        } catch (error) {
          notify(error.message);
        }
      };

      row.append(icon, name, remove);
      list.append(row);
    });

    const welcomeUpload = $('#welcome-upload');
    if (welcomeUpload) {
      welcomeUpload.textContent = documents.length
        ? '＋ Add more documents'
        : '＋ Add your first document';
      welcomeUpload.onclick = () => fileInput.click();
    }
  } catch {
    // The API may still be starting.
  }
}

function appendMessage(role, content, sources = []) {
  const node = document.createElement('div');
  const text = document.createElement('p');

  node.className = `message ${role}`;
  text.textContent = content;

  if (role === 'assistant') {
    const label = document.createElement('div');
    label.className = 'assistant-label';
    label.textContent = '✳  GROUNDWORK';
    node.append(label);
  }

  node.append(text);

  if (sources.length) {
    const sourceRow = document.createElement('div');
    sourceRow.className = 'sources';

    sources.forEach((source) => {
      const chip = document.createElement('span');
      chip.className = 'source-chip';
      chip.textContent = `▤ ${source.name}`;
      chip.title = source.excerpt;
      sourceRow.append(chip);
    });

    node.append(sourceRow);
  }

  conversation.append(node);
  conversation.scrollTop = conversation.scrollHeight;
  return node;
}

async function sendMessage(message) {
  if (!message.trim() || sendButton.disabled) return;

  welcome.classList.add('hidden');
  conversation.classList.remove('hidden');
  appendMessage('user', message);
  input.value = '';
  input.style.height = 'auto';
  sendButton.disabled = true;

  const pending = appendMessage('assistant', 'Searching your knowledge base…');
  pending.classList.add('typing');

  try {
    const result = await request('/chat', {
      method: 'POST',
      body: JSON.stringify({ message, history }),
    });

    pending.remove();
    appendMessage('assistant', result.answer, result.sources);
    history.push(
      { role: 'user', content: message },
      { role: 'assistant', content: result.answer },
    );
    history = history.slice(-10);
  } catch (error) {
    pending.remove();
    appendMessage('assistant', error.message);
  } finally {
    sendButton.disabled = false;
    input.focus();
  }
}

form.addEventListener('submit', (event) => {
  event.preventDefault();
  sendMessage(input.value);
});

input.addEventListener('input', () => {
  input.style.height = 'auto';
  input.style.height = `${Math.min(input.scrollHeight, 140)}px`;
});

input.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

$('#upload-trigger').onclick = () => fileInput.click();
$('#welcome-upload').onclick = () => fileInput.click();

document.querySelectorAll('.suggestion').forEach((button) => {
  button.onclick = () => {
    input.value = button.firstChild.textContent.trim();
    input.focus();
  };
});

fileInput.addEventListener('change', async () => {
  const files = [...fileInput.files];
  fileInput.value = '';

  for (const file of files) {
    try {
      const content = await file.text();
      const result = await request('/documents', {
        method: 'POST',
        body: JSON.stringify({ name: file.name, content }),
      });

      notify(`${result.name} added · ${result.chunks} chunks`);
      await refreshDocuments();
      await refreshStatus();
    } catch (error) {
      notify(error.message);
    }
  }
});

refreshStatus();
refreshDocuments();
