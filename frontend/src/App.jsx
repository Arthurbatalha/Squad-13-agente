import { useEffect, useRef, useState } from "react";
import CharacterPicker from "./components/CharacterPicker.jsx";
import ChatReply, { Preview } from "./components/ChatReply.jsx";
import { useConversation } from "./useConversation.js";

export default function App() {
  const chat = useConversation();
  const [choosing, setChoosing] = useState(false);
  const endRef = useRef(null);
  const inputRef = useRef(null);
  const blocked =
    chat.busy || chat.switching || chat.needsRecovery || chat.expired;
  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "nearest" });
  }, [chat.items, chat.busy]);
  useEffect(() => {
    if (chat.session && !blocked) inputRef.current?.focus();
  }, [chat.session?.thread_id, blocked]);
  async function select(characterId) {
    if (await chat.start(characterId)) setChoosing(false);
  }
  function chooseOption(option) {
    chat.setDraft(option);
    inputRef.current?.focus();
  }
  function submit(event) {
    event.preventDefault();
    chat.submit();
  }

  return (
    <div className="workspace">
      <aside className="sidebar">
        <a className="brand" href="#conversation">
          <span className="brand-icon" aria-hidden="true">
            13
          </span>
          <span>
            Central de serviços<small>Squad 13 · Assistente GLPI</small>
          </span>
        </a>
        <div className="sidebar-intro">
          <span className="eyebrow">Atendimento técnico</span>
          <h1>
            Uma conversa.
            <br />O próximo passo.
          </h1>
          <p>Consulte orientações e confira cada ação antes de confirmar.</p>
        </div>
        {chat.session && (
          <section className="active-character" aria-label="Técnico ativo">
            <span className="eyebrow">Técnico ativo</span>
            <h2>{chat.session.character.name}</h2>
            <p>Perspectiva: técnico (staff)</p>
            {chat.session.adapter === "mock" && (
              <span className="badge">Simulação · adapter="mock"</span>
            )}
            <button
              className="secondary"
              disabled={chat.switching || chat.restoring}
              onClick={() => setChoosing((value) => !value)}
            >
              {choosing ? "Manter conversa atual" : "Trocar personagem"}
            </button>
          </section>
        )}
        {!chat.restoring && (!chat.session || choosing || chat.expired) && (
          <CharacterPicker
            onSelect={select}
            disabled={chat.switching}
            activeId={chat.session?.character.id}
          />
        )}
        <p className="sidebar-note">
          Você escolhe o personagem. O servidor define a perspectiva e valida as
          ações.
        </p>
      </aside>
      <main className="conversation" id="conversation">
        <header className="conversation-header">
          <div>
            <p className="eyebrow">Assistente GLPI</p>
            <h2>
              {chat.session
                ? "Conversa de atendimento"
                : "Seu espaço de atendimento"}
            </h2>
          </div>
          {chat.session && (
            <button
              className="secondary"
              onClick={chat.recover}
              disabled={chat.busy || chat.switching || chat.expired}
            >
              Atualizar sessão
            </button>
          )}
        </header>
        {chat.session?.adapter === "mock" && (
          <p className="simulation-banner">
            Ambiente simulado: respostas e ações de demonstração, sem gravações
            no GLPI.
          </p>
        )}
        {chat.restoring && (
          <p role="status" className="notice">
            Recuperando a sessão disponível…
          </p>
        )}
        {chat.switching && (
          <p role="status" className="notice">
            Iniciando outro contexto…
          </p>
        )}
        {chat.error && (
          <p role="alert" className="error">
            {chat.error}
          </p>
        )}
        {chat.notice && (
          <p role="status" className="notice">
            {chat.notice}
          </p>
        )}
        {chat.needsRecovery && !chat.expired && (
          <div className="recovery">
            <p>
              O estado precisa ser consultado antes de enviar outra mensagem ou
              decisão.
            </p>
            <button
              disabled={chat.busy || chat.switching}
              onClick={chat.recover}
            >
              Consultar estado
            </button>
          </div>
        )}
        <section
          role="log"
          aria-label="Mensagens da conversa"
          aria-live="polite"
          aria-relevant="additions"
          className="log"
        >
          {!chat.items.length && (
            <div className="empty-chat">
              <span className="welcome-icon" aria-hidden="true">
                ↗
              </span>
              <h2>
                {chat.session
                  ? "Como posso ajudar?"
                  : "Comece pelo seu técnico"}
              </h2>
              <p>
                {chat.session
                  ? "Descreva o problema ou peça uma orientação para continuar."
                  : "Escolha um personagem fictício ao lado para iniciar uma conversa."}
              </p>
              {chat.session?.adapter === "mock" && (
                <p className="muted">
                  Para explorar a simulação: pergunte sobre VPN, impressora ou
                  peça para abrir um chamado.
                </p>
              )}
            </div>
          )}
          {chat.items.map((item, index) => (
            <article key={index} className={`message ${item.from}`}>
              <p className="message-author">
                {item.from === "user" ? "Você" : "Assistente"}
              </p>
              {item.from === "user" ? (
                <>
                  <p className="message-text">{item.text}</p>
                  {item.status === "failed" && (
                    <p className="attempt-failed">
                      A resposta não foi recebida. Confira o estado disponível.
                    </p>
                  )}
                </>
              ) : (
                <ChatReply
                  reply={item.reply}
                  onOption={chooseOption}
                  disabled={blocked}
                  pending={chat.session?.pending_action}
                />
              )}
            </article>
          ))}
          {chat.busy && (
            <p role="status" className="waiting">
              Aguardando resposta do servidor…
            </p>
          )}
          <div ref={endRef} />
        </section>
        {chat.session?.pending_action && !chat.expired && (
          <section className="pending-panel" aria-label="Ação pendente">
            <h2>Ação pendente de decisão</h2>
            <Preview action={chat.session.pending_action} />
            <p>
              Confira esta prévia. Digite <strong>sim</strong> para confirmar,{" "}
              <strong>não</strong> para cancelar ou{" "}
              <strong>editar: texto corrigido</strong> para receber uma nova
              prévia.
            </p>
          </section>
        )}
        {chat.session && (
          <form className="composer" onSubmit={submit}>
            <label htmlFor="message">Sua mensagem</label>
            <div className="composer-input">
              <textarea
                id="message"
                ref={inputRef}
                value={chat.draft}
                onChange={(event) => chat.setDraft(event.target.value)}
                disabled={blocked}
                maxLength={4000}
                rows={3}
                aria-describedby="composer-help"
                placeholder="Descreva o que você precisa…"
                onKeyDown={(event) => {
                  if (
                    event.key === "Enter" &&
                    !event.shiftKey &&
                    !event.nativeEvent.isComposing
                  ) {
                    event.preventDefault();
                    event.currentTarget.form.requestSubmit();
                  }
                }}
              />
              <button type="submit" disabled={blocked || !chat.draft.trim()}>
                Enviar <span aria-hidden="true">↑</span>
              </button>
            </div>
            <p id="composer-help" className="muted">
              Enter envia · Shift + Enter quebra a linha · {chat.draft.length}
              /4000
            </p>
          </form>
        )}
      </main>
    </div>
  );
}
