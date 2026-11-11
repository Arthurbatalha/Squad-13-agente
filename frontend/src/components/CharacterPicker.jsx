import { useEffect, useState } from "react";
import { getCharacters } from "../api.js";

export default function CharacterPicker({ onSelect, disabled, activeId }) {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState({ status: "loading", characters: [] });
  useEffect(() => {
    let active = true;
    setState({ status: "loading", characters: [] });
    getCharacters()
      .then((result) => {
        if (!Array.isArray(result.characters))
          throw new Error("Lista inválida.");
        if (active)
          setState({ status: "ready", characters: result.characters });
      })
      .catch(() => {
        if (active) setState({ status: "error", characters: [] });
      });
    return () => {
      active = false;
    };
  }, [attempt]);
  return (
    <section aria-labelledby="character-title" className="character-picker">
      <h2 id="character-title">Escolha um técnico</h2>
      <p className="muted">Personagens fictícios para a demonstração.</p>
      {state.status === "loading" && (
        <p role="status">Carregando personagens…</p>
      )}
      {state.status === "error" && (
        <p role="alert">Não foi possível carregar os personagens.</p>
      )}
      {state.status === "ready" && !state.characters.length && (
        <p>Nenhum personagem disponível.</p>
      )}
      {state.characters.map((character) => (
        <button
          className="character"
          key={character.id}
          disabled={disabled}
          onClick={() => onSelect(character.id)}
        >
          <span className="avatar" aria-hidden="true">
            {character.name.charAt(0)}
          </span>
          <span>
            {character.name}
            {activeId === character.id && (
              <small>Contexto atual · iniciar outro</small>
            )}
          </span>
          <span aria-hidden="true">→</span>
        </button>
      ))}
      {state.status !== "loading" && (
        <button
          className="secondary"
          disabled={disabled}
          onClick={() => setAttempt((value) => value + 1)}
        >
          Tentar novamente a leitura
        </button>
      )}
    </section>
  );
}
