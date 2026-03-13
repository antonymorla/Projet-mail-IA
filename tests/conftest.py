"""
conftest — Fixtures pytest partagées pour les tests des générateurs de devis.

Fournit des mocks Playwright réutilisables et des données de test.
"""

from __future__ import annotations

import asyncio
import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─── Fixtures de données client ──────────────────────────────────────────────

@pytest.fixture
def client_info() -> dict[str, str]:
    """Retourne des coordonnées client de test."""
    return {
        "client_nom": "Dupont",
        "client_prenom": "Jean",
        "client_email": "jean.dupont@test.fr",
        "client_telephone": "0600000000",
        "client_adresse": "1 Rue de Test, 75001 Paris",
    }


# ─── Fixtures Playwright mockées ─────────────────────────────────────────────

@pytest.fixture
def mock_page() -> AsyncMock:
    """Crée une page Playwright mockée avec les méthodes courantes."""
    page = AsyncMock()
    page.url = "https://example.com"

    # Configurer les retours par défaut
    page.evaluate = AsyncMock(return_value=None)
    page.wait_for_timeout = AsyncMock()
    page.wait_for_selector = AsyncMock()
    page.wait_for_function = AsyncMock()
    page.goto = AsyncMock()
    page.click = AsyncMock()
    page.locator = MagicMock()

    # Locator mock
    locator = AsyncMock()
    locator.first = locator
    locator.fill = AsyncMock()
    locator.click = AsyncMock()
    locator.is_visible = AsyncMock(return_value=True)
    locator.dispatch_event = AsyncMock()
    locator.scroll_into_view_if_needed = AsyncMock()
    page.locator.return_value = locator

    # PDF generation
    page.pdf = AsyncMock(return_value=b"%PDF-1.4 mock content")

    # Download mock
    download = AsyncMock()
    download.save_as = AsyncMock()
    page.expect_download = MagicMock()

    # Event listeners
    page.on = MagicMock()
    page.remove_listener = MagicMock()

    return page


@pytest.fixture
def mock_browser(mock_page: AsyncMock) -> AsyncMock:
    """Crée un navigateur Playwright mocké."""
    browser = AsyncMock()
    context = AsyncMock()
    context.new_page = AsyncMock(return_value=mock_page)
    browser.new_context = AsyncMock(return_value=context)
    browser.close = AsyncMock()
    return browser


@pytest.fixture
def mock_playwright(mock_browser: AsyncMock) -> AsyncMock:
    """Crée une instance async_playwright mockée."""
    pw = AsyncMock()
    pw.chromium.launch = AsyncMock(return_value=mock_browser)
    return pw


# ─── Fixtures de fichiers temporaires ────────────────────────────────────────

@pytest.fixture
def tmp_download_dir(tmp_path):
    """Crée un répertoire de téléchargement temporaire."""
    dl_dir = tmp_path / "Downloads"
    dl_dir.mkdir()
    return str(dl_dir)


@pytest.fixture
def sample_devis_log(tmp_path) -> str:
    """Crée un fichier devis_log.json de test."""
    log_file = tmp_path / "devis_log.json"
    log_data = [
        {
            "date": "2025-01-15 14:30",
            "type": "pergola",
            "client": "Jean Dupont",
            "filepath": "/tmp/devis_Dupont_Jean_20250115.pdf",
            "filename": "devis_Dupont_Jean_20250115.pdf",
            "size_kb": 245.3,
        },
    ]
    log_file.write_text(json.dumps(log_data, ensure_ascii=False))
    return str(log_file)
