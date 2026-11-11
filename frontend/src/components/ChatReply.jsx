function safeUrl(reference) {
  try {
    const url = new URL(reference);
    return ["http:", "https:"].includes(url.protocol) ? url.href : null;
  } catch {
    return null;
  }
}

export function Sources({ sources }) {
  if (!sources?.length) return null;
  return (
    <section className="sources" aria-label="Fontes da resposta">
      <h3>Fontes consultadas</h3>
      <ul>
        {sources.map((source, index) => {
          const href = safeUrl(source.reference);
          return (
            <li
              key={`${source.source_type}-${source.source_id}-${source.chunk_id ?? index}`}
            >
              <strong>{source.title}</strong>
              <p className="source-meta">
                {source.source_type === "article" ? "Artigo" : "Caso"} · ID{" "}
                {source.source_id}
                {source.chunk_id && <> · Trecho {source.chunk_id}</>}
              </p>
              <p>
                {href ? (
                  <a href={href} target="_blank" rel="noopener noreferrer">
                    {source.reference}
                  </a>
                ) : (
                  source.reference
                )}
              </p>
              {source.excerpt && <blockquote>{source.excerpt}</blockquote>}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

const resultLabels = {
  succeeded: "Ação concluída",
  partial: "Conclusão parcial",
  uncertain: "Resultado incerto",
  cancelled: "Ação cancelada",
};
export function Preview({ action }) {
  return (
    <>
      <p className="eyebrow">Prévia · versão {action.version}</p>
      <pre className="preview">{action.preview_text}</pre>
    </>
  );
}
export default function ChatReply({ reply, onOption, disabled, pending }) {
  switch (reply.type) {
    case "text":
      return (
        <>
          <p className="message-text">{reply.text}</p>
          {reply.answer_status === "no_evidence" && (
            <p className="answer-state">Sem evidência suficiente nas fontes.</p>
          )}
          {reply.answer_status === "index_unavailable" && (
            <p className="answer-state warning">
              Índice indisponível. Tente consultar novamente mais tarde.
            </p>
          )}
          <Sources sources={reply.sources} />
        </>
      );
    case "clarification":
      return (
        <>
          <h3>Vamos esclarecer</h3>
          <p className="message-text">{reply.question}</p>
          <div className="options">
            {reply.options.map((option, i) => (
              <button
                className="secondary"
                key={i}
                disabled={disabled || Boolean(pending)}
                onClick={() => onOption(option)}
              >
                {option}
              </button>
            ))}
          </div>
          <p className="muted">
            Escolha uma opção para preencher sua mensagem ou escreva sua
            resposta.
          </p>
        </>
      );
    case "preview":
      return (
        <>
          <Preview action={reply.action} />
          <p className="muted">
            Use a prévia atual no painel de ação pendente para decidir.
          </p>
        </>
      );
    case "write_result":
      return (
        <section
          className={`write-result ${reply.status}`}
          aria-label={resultLabels[reply.status]}
        >
          <h3>{resultLabels[reply.status]}</h3>
          <p className="message-text">{reply.message}</p>
          {reply.ticket_id != null && (
            <p>
              <strong>Chamado #{reply.ticket_id}</strong>
            </p>
          )}
          {["partial", "uncertain"].includes(reply.status) && (
            <p>Confira o estado do chamado antes de repetir a operação.</p>
          )}
        </section>
      );
    default:
      return (
        <p>
          Resposta não reconhecida. Atualize a sessão para conferir o estado
          disponível.
        </p>
      );
  }
}
