"""
logging_config — Configuration du logging structuré pour les générateurs de devis.

Fournit un logger structuré JSON qui écrit vers stderr (compatible MCP JSON-RPC sur stdout).
Chaque entrée contient : timestamp, level, module, message, et des champs métier optionnels.

Usage :
    from generators.logging_config import get_logger
    logger = get_logger(__name__)
    logger.info("Devis généré", extra={"client": "Dupont", "type": "pergola"})
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any


class StructuredFormatter(logging.Formatter):
    """Formateur JSON structuré pour les logs de génération de devis.

    Produit des lignes JSON avec les champs :
    - timestamp (ISO 8601 UTC)
    - level (DEBUG/INFO/WARNING/ERROR/CRITICAL)
    - logger (nom du module)
    - message (texte du log)
    - Tout champ supplémentaire passé via ``extra``
    """

    def format(self, record: logging.LogRecord) -> str:
        """Formate un LogRecord en JSON structuré."""
        entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Ajouter les champs métier passés via extra (ignorer les champs internes)
        _internal = {
            "name", "msg", "args", "created", "relativeCreated",
            "exc_info", "exc_text", "stack_info", "lineno", "funcName",
            "filename", "module", "pathname", "thread", "threadName",
            "process", "processName", "levelname", "levelno", "message",
            "msecs", "taskName",
        }
        for key, value in record.__dict__.items():
            if key not in _internal and not key.startswith("_"):
                entry[key] = value

        if record.exc_info and record.exc_info[1] is not None:
            entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(entry, ensure_ascii=False, default=str)


class HumanFormatter(logging.Formatter):
    """Formateur lisible pour le développement local.

    Produit des lignes du type :
        [2025-01-15 14:30:00] INFO  generators.pergola — Devis généré
    """

    LEVEL_COLORS = {
        "DEBUG": "\033[36m",     # cyan
        "INFO": "\033[32m",      # green
        "WARNING": "\033[33m",   # yellow
        "ERROR": "\033[31m",     # red
        "CRITICAL": "\033[35m",  # magenta
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        """Formate un LogRecord en texte lisible avec couleurs."""
        ts = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
        color = self.LEVEL_COLORS.get(record.levelname, "")
        reset = self.RESET if color else ""
        msg = record.getMessage()

        line = f"[{ts}] {color}{record.levelname:<8}{reset} {record.name} — {msg}"

        if record.exc_info and record.exc_info[1] is not None:
            line += f"\n{self.formatException(record.exc_info)}"

        return line


def get_logger(
    name: str,
    *,
    level: int = logging.INFO,
    structured: bool = False,
) -> logging.Logger:
    """Crée et retourne un logger configuré pour les générateurs.

    Args:
        name: Nom du logger (typiquement ``__name__``).
        level: Niveau de log minimum (défaut : INFO).
        structured: Si True, utilise le format JSON structuré.
                    Si False (défaut), utilise le format humain lisible.

    Returns:
        Un ``logging.Logger`` configuré qui écrit vers stderr.
    """
    logger = logging.getLogger(name)

    # Éviter d'ajouter des handlers en double si le logger existe déjà
    if logger.handlers:
        return logger

    logger.setLevel(level)
    logger.propagate = False

    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)

    formatter = StructuredFormatter() if structured else HumanFormatter()
    handler.setFormatter(formatter)

    logger.addHandler(handler)

    return logger


def setup_root_logger(
    *,
    level: int = logging.INFO,
    structured: bool = False,
) -> None:
    """Configure le logger racine ``generators`` pour tout le package.

    Appeler une seule fois au démarrage (typiquement dans mcp_server_devis.py).

    Args:
        level: Niveau de log minimum.
        structured: Si True, format JSON ; sinon format humain.
    """
    get_logger("generators", level=level, structured=structured)
