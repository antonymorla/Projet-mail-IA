"""Tests pour le module de logging structuré."""

from __future__ import annotations

import json
import logging
import sys
from io import StringIO

import pytest

from generators.logging_config import (
    HumanFormatter,
    StructuredFormatter,
    get_logger,
    setup_root_logger,
)


class TestStructuredFormatter:
    """Tests pour le formateur JSON structuré."""

    def test_basic_format(self) -> None:
        """Un log basique produit du JSON valide avec les champs attendus."""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Hello %s",
            args=("world",),
            exc_info=None,
        )
        output = formatter.format(record)
        data = json.loads(output)

        assert data["level"] == "INFO"
        assert data["logger"] == "test"
        assert data["message"] == "Hello world"
        assert "timestamp" in data

    def test_extra_fields(self) -> None:
        """Les champs extra sont inclus dans la sortie JSON."""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO,
            pathname="test.py", lineno=1,
            msg="Devis généré", args=(), exc_info=None,
        )
        record.client = "Dupont"  # type: ignore[attr-defined]
        record.type_devis = "pergola"  # type: ignore[attr-defined]

        output = formatter.format(record)
        data = json.loads(output)

        assert data["client"] == "Dupont"
        assert data["type_devis"] == "pergola"

    def test_exception_info(self) -> None:
        """Les exceptions sont incluses dans la sortie JSON."""
        formatter = StructuredFormatter()
        try:
            raise ValueError("test error")
        except ValueError:
            record = logging.LogRecord(
                name="test", level=logging.ERROR,
                pathname="test.py", lineno=1,
                msg="Échec", args=(), exc_info=sys.exc_info(),
            )

        output = formatter.format(record)
        data = json.loads(output)

        assert "exception" in data
        assert "ValueError" in data["exception"]


class TestHumanFormatter:
    """Tests pour le formateur humain lisible."""

    def test_basic_format(self) -> None:
        """Le format humain contient le timestamp, le niveau et le message."""
        formatter = HumanFormatter()
        record = logging.LogRecord(
            name="generators.pergola", level=logging.INFO,
            pathname="pergola.py", lineno=1,
            msg="Devis OK", args=(), exc_info=None,
        )
        output = formatter.format(record)

        assert "INFO" in output
        assert "generators.pergola" in output
        assert "Devis OK" in output


class TestGetLogger:
    """Tests pour la factory de loggers."""

    def test_creates_logger_with_handler(self) -> None:
        """get_logger crée un logger avec un handler stderr."""
        # Utiliser un nom unique pour éviter les conflits entre tests
        logger = get_logger("test_unique_123")
        assert len(logger.handlers) == 1
        assert logger.level == logging.INFO

    def test_no_duplicate_handlers(self) -> None:
        """Appeler get_logger deux fois ne duplique pas les handlers."""
        logger1 = get_logger("test_no_dup_456")
        logger2 = get_logger("test_no_dup_456")
        assert logger1 is logger2
        assert len(logger1.handlers) == 1

    def test_structured_mode(self) -> None:
        """Le mode structuré utilise le StructuredFormatter."""
        logger = get_logger("test_structured_789", structured=True)
        handler = logger.handlers[0]
        assert isinstance(handler.formatter, StructuredFormatter)
