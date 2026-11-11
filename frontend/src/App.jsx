import { useEffect, useRef, useState } from "react";
import { ApiError, createSession, getCharacters, sendMessage } from "./api.js";

// UI-01: tela mínima que percorre o contrato. Visual e estados completos: UI-02 / ACO-03.

function Sources({ sources }) {
  if (!sources?.length) return null;
  return (
    <ul className="sources">
      {sources.map((s) => (
        <li key={`${s.source_type}-${s.source_id}-${s.chunk_id ?? ""}`}>
          {s.title} <span className="muted">({s.reference})</span>
        </li>
      ))}
    </ul>
  );
}

function Reply({ reply }) {
  switch (reply.type) {
    case "text":
      return (
        <>
          <p>{reply.text}</p>
          {reply.answer_status !== "answered" && (
            <p className="muted">Situação: {reply.answer_status}</p>
          )}
          <Sources sources={reply.sources} />
        </>
      );
    case "clarification":
      return (
        <>
          <p>{reply.question}</p>
          {reply.options.length > 0 && <p className="muted">{reply.options.join(" · ")}</p>}
        </>
      );
    case "preview":
      return <pre className="preview">{reply.action.preview_text}</pre>;
    case "write_result":
      return (
        <p>
          {reply.message}
          {reply.ticket_id != null && <strong> Chamado #{reply.ticket_id}</strong>}
        </p>
      );
    default:
      return <p className="muted">Tipo de resposta desconhecido: {String(reply.type)}</p>;
  }
}

export default function App() {
  const [characters, setCharacters] = useState([]);
  const [session, setSession] = useState(null);
  const [items, setItems] = useState([]); // {from: "user"|"bot"|"error", ...}
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const endRef = useRef(null);

  useEffect(() => {
    getCharacters()
      .then((r) => setCharacters(r.characters))
      .catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [items]);

  async function start(characterId) {
    setError(null);
    try {
      setSession(await createSession(characterId));
      setItems([]);
    } catch (e) {
      setError(e.message);
    }
  }

  async function submit(event) {
    event.preventDefault();
    const message = text.trim();
    if (!message || busy) return;
    setText("");
    setBusy(true);
    setItems((prev) => [...prev, { from: "user", text: message }]);
    try {
      const { reply } = await sendMessage(session.thread_id, message);
      setItems((prev) => [...prev, { from: "bot", reply }]);
    } catch (e) {
      const text = e instanceof ApiError ? e.message : "Erro inesperado.";
      setItems((prev) => [...prev, { from: "error", text }]);
    } finally {
      setBusy(false);
    }
  }

  if (!session) {
    return (
      <main className="shell">
        <h1>Assistente GLPI</h1>
        <p className="muted">Escolha o técnico fictício desta sessão.</p>
        {error && <p role="alert" className="error">{error}</p>}
        <div className="characters">
          {characters.map((c) => (
            <button key={c.id} onClick={() => start(c.id)}>{c.name}</button>
          ))}
        </div>
      </main>
    );
  }

  return (
    <main className="shell">
      <header className="bar">
        <h1>Assistente GLPI</h1>
        <span className="muted">
          {session.character.name}
          {session.adapter === "mock" && <span className="badge">simulado</span>}
        </span>
      </header>

      <section className="log" aria-live="polite">
        {items.map((item, i) => (
          <div key={i} className={`msg ${item.from}`}>
            {item.from === "bot" ? <Reply reply={item.reply} /> : <p>{item.text}</p>}
          </div>
        ))}
        <div ref={endRef} />
      </section>

      <form className="composer" onSubmit={submit}>
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Digite sua mensagem (ao ver uma prévia, responda sim ou não)"
          aria-label="Mensagem"
          disabled={busy}
          maxLength={4000}
        />
        <button type="submit" disabled={busy || !text.trim()}>Enviar</button>
      </form>
    </main>
  );
}
