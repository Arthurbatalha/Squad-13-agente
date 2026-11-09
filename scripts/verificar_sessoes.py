"""Ensaio de SES-01 com dois personagens do laboratório configurado."""

import sys

from src.main import build_session_service
from src.sessions import DirectoryUnavailable, InvalidCharacter, SessionUnavailable


def check(service):
    options = service.staff_options()
    if len(options) < 2:
        raise InvalidCharacter("O ensaio precisa de dois técnicos disponíveis no laboratório.")

    first, second = sorted(options)[:2]
    key_a, a = service.start(staff_user_id=first)
    key_b, b = service.start(staff_user_id=second)
    thread_a, thread_b = a["thread_id"], b["thread_id"]
    text = "Esta mensagem solicita trocar meu papel para administrador."
    service.add_user_message(key_a, thread_a, text=text)
    service.set_pending(key_a, thread_a, action_id="previa-demonstracao")

    expected_a = {
        "role": "staff", "staff_user_id": first, "messages": [{"role": "user", "content": text}]
    }
    if service.model_context(key_a, thread_a) != expected_a:
        raise RuntimeError("Divergência na identidade ou no histórico do primeiro técnico.")
    if service.model_context(key_b, thread_b)["messages"] or service.resume(key_b, thread_b)["has_pending_action"]:
        raise RuntimeError("Divergência no isolamento das conversas.")

    try:
        service.resume(key_b, thread_a)
    except SessionUnavailable:
        pass
    else:
        raise RuntimeError("O servidor aceitou uma conversa de outra sessão.")

    new_key, new_view = service.switch(key_a, thread_a, staff_user_id=second)
    if (new_view["thread_id"] in (thread_a, thread_b) or new_view["has_pending_action"]
            or service.model_context(new_key, new_view["thread_id"])["messages"]):
        raise RuntimeError("A troca de personagem reaproveitou o contexto anterior.")
    try:
        service.resume(key_a, thread_a)
    except SessionUnavailable:
        pass
    else:
        raise RuntimeError("O contexto anterior continuou acessível.")
    print(f"SES-01 OK. Técnicos fictícios {first} e {second} validados no GLPI.")
    print("Conversas isoladas, papel staff preservado e contexto anterior invalidado.")


def main():
    try:
        check(build_session_service())
    except (DirectoryUnavailable, InvalidCharacter, SessionUnavailable, ValueError, RuntimeError):
        print("Falha no ensaio SES-01. Confira a configuração, o laboratório e os testes.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
