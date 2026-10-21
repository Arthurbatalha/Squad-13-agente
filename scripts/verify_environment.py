"""Confere os pins instalados e os imports da stack sem contatar GLPI/Gemini.

Uso (raiz do repositório): python scripts/verify_environment.py
Este script NÃO carrega modelos SentenceTransformers nem faz solicitações HTTP.
"""

from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS = ROOT / "requirements.txt"
# Nomes da distribuição pip nem sempre coincidem com os nomes de import.
IMPORTS = {
    "requests": "requests",
    "python-dotenv": "dotenv",
    "sentence-transformers": "sentence_transformers",
    "tzdata": "tzdata",
    "html2text": "html2text",
    "chromadb": "chromadb",
    "langchain": "langchain",
    "langgraph": "langgraph",
    "langchain-google-genai": "langchain_google_genai",
    "langgraph-checkpoint-sqlite": "langgraph.checkpoint.sqlite",
    "pytest": "pytest",
    "scikit-learn": "sklearn",
}


def main() -> int:
    print(f"Python: {sys.version.split()[0]} | {sys.executable}")
    if sys.version_info < (3, 11):
        print("ERRO: a versão do Python deve ser 3.11 ou mais recente.")
        return 1

    problems = 0
    for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([a-zA-Z0-9_-]+)==([a-zA-Z0-9_.+-]+)", line)
        if not match:
            print(f"ERRO: requisito não reconhecido: {line}")
            problems += 1
            continue
        package, expected = match.groups()
        try:
            installed = version(package)
        except PackageNotFoundError:
            print(f"FALTA: {package}=={expected}")
            problems += 1
            continue
        if installed != expected:
            print(f"VERSÃO DIFERENTE: {package} esperado={expected}, atual={installed}")
            problems += 1
            continue
        print(f"OK: {package}=={installed}")

    if problems:
        print(f"Falha na validação de versões: {problems} problema(s).")
        return 1

    for package, module in IMPORTS.items():
        try:
            import_module(module)
        except Exception as exc:
            print(f"ERRO AO IMPORTAR {module}: {type(exc).__name__}: {exc}")
            problems += 1
        else:
            print(f"IMPORT OK: {module}")

    if problems:
        print(f"Falha na validação de imports: {problems} problema(s).")
        return 1
    print("Ambiente validado: versões e imports presentes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
