import sys
from pathlib import Path

# Permite `from src.api...` ao rodar pytest a partir de qualquer diretório.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
