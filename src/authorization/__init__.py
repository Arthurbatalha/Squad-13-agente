"""Políticas de acesso e projeção de dados (ver docs/AUTH-01.md)."""

from src.authorization.policies import (
    AccessDenied, EmptyAuthorizedSet, Principal, ToolDenied,
)
from src.authorization.service import AuthorizationService, as_model_data

__all__ = [
    "AccessDenied", "AuthorizationService", "EmptyAuthorizedSet", "Principal",
    "ToolDenied", "as_model_data",
]
