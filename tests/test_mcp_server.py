"""Tests pour le serveur MCP de génération de devis."""

from __future__ import annotations

import json
import os
import sys
from unittest.mock import MagicMock, AsyncMock

import pytest

# Mock playwright et mcp avant tout import de mcp_server_devis
# (ces modules ne sont pas installés dans l'env de test CI)
_mock_pw = MagicMock()
_mock_pw.async_api.async_playwright = MagicMock()
_mock_pw.async_api.TimeoutError = TimeoutError
sys.modules.setdefault("playwright", _mock_pw)
sys.modules.setdefault("playwright.async_api", _mock_pw.async_api)

_mock_mcp = MagicMock()
_mock_fastmcp = MagicMock()
_mock_fastmcp.tool = MagicMock(return_value=lambda f: f)
_mock_mcp.server.fastmcp.FastMCP = MagicMock(return_value=_mock_fastmcp)
sys.modules.setdefault("mcp", _mock_mcp)
sys.modules.setdefault("mcp.server", _mock_mcp.server)
sys.modules.setdefault("mcp.server.fastmcp", _mock_mcp.server.fastmcp)

# Mock les générateurs
_mock_gen3 = MagicMock()
_mock_gen3.generer_devis_pergola = AsyncMock(return_value=("/tmp/test.pdf", "", []))
_mock_gen3.generer_devis_terrasse = AsyncMock(return_value=("/tmp/test.pdf", "", []))
_mock_gen3.generer_devis_cloture = AsyncMock(return_value=("/tmp/test.pdf", "", []))
_mock_gen3.generer_devis_terrasse_detail = AsyncMock(return_value=("/tmp/test.pdf", "", []))
sys.modules.setdefault("generateur_devis_3sites", _mock_gen3)

_mock_gen_auto = MagicMock()
_mock_gen_auto.generer_devis_abri = AsyncMock(return_value="/tmp/test.pdf")
_mock_gen_auto.generer_devis_studio = AsyncMock(return_value="/tmp/test.pdf")
sys.modules.setdefault("generateur_devis_auto", _mock_gen_auto)

# utils_playwright est disponible via scripts/ (ajouté au path dans conftest.py)
# Ne PAS le mocker — il est importable directement.


class TestLogDevis:
    """Tests pour la fonction _log_devis."""

    def test_log_creates_file(self, tmp_path) -> None:
        """_log_devis crée le fichier log s'il n'existe pas."""
        log_file = str(tmp_path / "devis_log.json")
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 test")

        import mcp_server_devis as mcp
        original = mcp._DEVIS_LOG_FILE
        mcp._DEVIS_LOG_FILE = log_file

        try:
            mcp._log_devis(str(pdf_file), "pergola", "Jean", "Dupont")

            assert os.path.exists(log_file)
            with open(log_file) as f:
                data = json.load(f)
            assert len(data) == 1
            assert data[0]["type"] == "pergola"
            assert data[0]["client"] == "Jean Dupont"
        finally:
            mcp._DEVIS_LOG_FILE = original

    def test_log_appends_to_existing(self, tmp_path) -> None:
        """_log_devis ajoute en tête d'un log existant."""
        log_file = str(tmp_path / "devis_log.json")
        existing = [{"date": "2025-01-01", "type": "ancien", "client": "Old"}]
        with open(log_file, "w") as f:
            json.dump(existing, f)

        pdf_file = tmp_path / "test2.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 test2")

        import mcp_server_devis as mcp
        original = mcp._DEVIS_LOG_FILE
        mcp._DEVIS_LOG_FILE = log_file

        try:
            mcp._log_devis(str(pdf_file), "terrasse", "Marie", "Martin")

            with open(log_file) as f:
                data = json.load(f)
            assert len(data) == 2
            assert data[0]["type"] == "terrasse"
            assert data[1]["type"] == "ancien"
        finally:
            mcp._DEVIS_LOG_FILE = original


class TestGenererDirect:
    """Tests pour _generer_direct (retour immédiat)."""

    @pytest.mark.asyncio
    async def test_retour_pdf_non_existant(self) -> None:
        """_generer_direct retourne une erreur si le PDF n'existe pas."""
        import mcp_server_devis as mcp
        import asyncio

        orig_available = mcp._GENERATORS_AVAILABLE
        mcp._GENERATORS_AVAILABLE = True

        try:
            result_str = await asyncio.wait_for(
                mcp._generer_direct("pergola", {
                    "largeur": "4m", "profondeur": "3m",
                    "fixation": "adossee", "ventelle": "largeur",
                }, "Jean", "Dupont"),
                timeout=2.0,
            )
            data = json.loads(result_str)

            # Le mock retourne /tmp/test.pdf qui n'existe pas → PDF non trouvé
            assert data["success"] is False
            assert "PDF non trouvé" in data.get("error", "")
        finally:
            mcp._GENERATORS_AVAILABLE = orig_available

    @pytest.mark.asyncio
    async def test_retour_pdf_existant(self, tmp_path) -> None:
        """_generer_direct retourne le PDF si le fichier existe."""
        import mcp_server_devis as mcp
        import asyncio

        pdf = tmp_path / "devis_test.pdf"
        pdf.write_bytes(b"%PDF-1.4 test content")

        orig_available = mcp._GENERATORS_AVAILABLE
        mcp._GENERATORS_AVAILABLE = True

        # Patch the imported generer_devis_pergola to return the existing PDF
        orig_gen = mcp.generer_devis_pergola
        mcp.generer_devis_pergola = AsyncMock(return_value=(str(pdf), "", []))

        try:
            result_str = await asyncio.wait_for(
                mcp._generer_direct("pergola", {}, "Jean", "Dupont"),
                timeout=2.0,
            )
            data = json.loads(result_str)

            assert data["success"] is True
            assert data["filepath"] == str(pdf)
            assert "size_kb" in data
        finally:
            mcp._GENERATORS_AVAILABLE = orig_available
            mcp.generer_devis_pergola = orig_gen

    @pytest.mark.asyncio
    async def test_generateurs_non_disponibles(self) -> None:
        """Retourne une erreur si les générateurs ne sont pas importés."""
        import mcp_server_devis as mcp

        orig = mcp._GENERATORS_AVAILABLE
        mcp._GENERATORS_AVAILABLE = False
        mcp._GENERATORS_IMPORT_ERR = "Module not found"

        try:
            result_str = await mcp._generer_direct("pergola", {}, "J", "D")
            data = json.loads(result_str)

            assert data["success"] is False
            assert "non importés" in data["error"]
        finally:
            mcp._GENERATORS_AVAILABLE = orig
