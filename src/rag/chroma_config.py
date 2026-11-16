"""ING-03: configuração de persistência e identidade de um índice vetorial."""

from dataclasses import asdict, dataclass
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from src.config import PROJECT_ROOT
CHROMA_DIR_ENV = "CHROMA_PERSIST_DIR"
DEFAULT_PERSIST_DIR = PROJECT_ROOT / "data" / "chroma"
METRIC = "cosine"


@dataclass(frozen=True)
class IndexConfig:
    """Tudo que precisa coincidir para que vetores de gerações diferentes sejam comparáveis.

    Os embeddings (E5 ou outro modelo) são produzidos fora do armazenamento; aqui só se
    registra e se compara a configuração. Prefixos E5 ("query: "/"passage: ") fazem parte
    de `input_format`, pois mudá-los muda o espaço vetorial.
    """

    model: str
    revision: str
    dimension: int
    normalize: bool = True
    input_format: str = "e5:query/passage"
    metric: str = METRIC

    def __post_init__(self):
        for name in ("model", "revision", "input_format"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} deve ser texto não vazio.")
        if type(self.dimension) is not int or self.dimension <= 0:
            raise ValueError("dimension deve ser inteiro positivo.")
        if self.normalize is not True:
            raise ValueError("O índice exige embeddings normalizados (norma L2 = 1).")
        if self.metric != METRIC:
            raise ValueError("A métrica do índice é cosseno; outras métricas não são suportadas.")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "IndexConfig":
        return cls(**data)


def persist_dir_from_env(environ=os.environ) -> Path:
    """Diretório de persistência: CHROMA_PERSIST_DIR ou data/chroma na raiz do projeto."""
    value = environ.get(CHROMA_DIR_ENV, "").strip()
    return Path(value) if value else DEFAULT_PERSIST_DIR
