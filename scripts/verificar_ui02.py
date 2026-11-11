"""Ensaio opcional no navegador, exclusivamente com o adapter mock.

Requer Playwright e Chromium, ou --browser /caminho/do/navegador.
Execute contra a API servindo frontend/dist; screenshots vão para --output.
"""

import argparse
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def verify(base_url: str, browser_path: str | None, output: Path):
    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=browser_path)
        for width, height in ((1440, 1000), (390, 844)):
            context = browser.new_context(viewport={"width": width, "height": height})
            health = context.request.get(f"{base_url}/api/health").json()
            assert health.get("adapter") == "mock", "Ensaio permitido somente contra a API mock da UI-02."
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(base_url)
            with page.expect_response(lambda r: r.url.endswith("/api/sessions") and r.request.method == "POST") as created:
                page.get_by_role("button", name="Técnico Demo A").click()
            old_thread = created.value.json()["thread_id"]
            editor = page.get_by_role("textbox", name="Sua mensagem")

            def send(text):
                expect(editor).to_be_enabled()
                editor.fill(text)
                editor.press("Enter")
                expect(editor).to_be_enabled()
                expect(editor).to_have_value("")

            send("Como configurar a VPN?")
            expect(page.get_by_role("region", name="Fontes da resposta")).to_contain_text("GLPI KB #1")
            send("problema na impressora")
            page.get_by_role("button", name="Atolamento de papel").click()
            expect(editor).to_have_value("Atolamento de papel")
            editor.press("Enter")
            expect(editor).to_have_value("")
            send("abrir chamado")
            pending = page.get_by_role("region", name="Ação pendente", exact=True)
            expect(pending).to_contain_text("versão 1")
            editor.fill("sim?")
            editor.press("Enter")
            expect(page.get_by_role("alert")).to_contain_text("Mensagens ambíguas")
            send("editar: descrição corrigida no navegador")
            expect(pending).to_contain_text("versão 2")
            page.screenshot(path=str(output / f"ui02-{width}.png"), full_page=True)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Overflow horizontal"
            send("sim")
            expect(page.get_by_role("region", name="Ação concluída", exact=True)).to_be_visible()
            send("abrir simular parcial")
            send("sim")
            expect(page.get_by_role("region", name="Conclusão parcial")).to_contain_text("Chamado #")
            send("abrir simular incerto")
            send("sim")
            expect(page.get_by_role("region", name="Resultado incerto")).to_be_visible()
            send("abrir chamado")
            page.get_by_role("button", name="Trocar personagem").click()
            page.get_by_role("button", name="Técnico Demo B").click()
            expect(page.get_by_role("region", name="Técnico ativo")).to_contain_text("Técnico Demo B")
            expect(pending).to_have_count(0)
            assert context.request.get(f"{base_url}/api/sessions/{old_thread}").status == 404
            assert not errors, errors
            print(f"UI-02 OK: {width}x{height}, teclado, fontes, prévia, edição, resultados e troca; sem overflow ou erros JS.")
            context.close()
        browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--browser", default=None)
    parser.add_argument("--output", type=Path, default=Path("/tmp/ui02-browser"))
    args = parser.parse_args()
    verify(args.url.rstrip("/"), args.browser, args.output)
