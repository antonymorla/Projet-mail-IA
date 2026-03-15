"""Tests pour les utilitaires Playwright (fermer_popups, appliquer_code_promo)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from utils_playwright import appliquer_code_promo, fermer_popups


@pytest.mark.asyncio
class TestFermerPopups:
    """Tests pour la fermeture des popups GDPR/cookies."""

    async def test_clic_bouton_accepter(self) -> None:
        """Clique sur le bouton d'acceptation si visible."""
        page = AsyncMock()
        locator = AsyncMock()
        locator.first = locator
        locator.is_visible = AsyncMock(return_value=True)
        locator.click = AsyncMock()
        page.locator = MagicMock(return_value=locator)
        page.evaluate = AsyncMock(return_value=None)
        page.wait_for_timeout = AsyncMock()
        page.add_style_tag = AsyncMock()

        await fermer_popups(page)

        assert page.evaluate.called

    async def test_pas_de_popup(self) -> None:
        """Pas de popup visible — continue sans erreur."""
        page = AsyncMock()
        locator = AsyncMock()
        locator.first = locator
        locator.is_visible = AsyncMock(return_value=False)
        page.locator = MagicMock(return_value=locator)
        page.evaluate = AsyncMock(return_value=None)
        page.add_style_tag = AsyncMock()

        await fermer_popups(page)


@pytest.mark.asyncio
class TestAppliquerCodePromo:
    """Tests pour l'application des codes promo."""

    async def test_code_vide(self) -> None:
        """Code promo vide → retour immédiat."""
        page = AsyncMock()
        await appliquer_code_promo(page, "")
        page.evaluate.assert_not_called()

    async def test_code_none(self) -> None:
        """Code promo None → retour immédiat."""
        page = AsyncMock()
        await appliquer_code_promo(page, None)
        page.evaluate.assert_not_called()

    async def test_ajax_success(self) -> None:
        """Application AJAX réussie."""
        page = AsyncMock()
        page.evaluate = AsyncMock(return_value={"ok": True})

        await appliquer_code_promo(page, "LEROYMERLIN10")

        page.evaluate.assert_called_once()

    async def test_ajax_error_fallback_formulaire(self) -> None:
        """AJAX échoue → fallback sur le formulaire HTML."""
        page = AsyncMock()
        page.evaluate = AsyncMock(
            return_value={"ok": False, "msg": "nonce_absent"}
        )

        locator = AsyncMock()
        locator.first = locator
        locator.is_visible = AsyncMock(return_value=True)
        locator.fill = AsyncMock()
        locator.click = AsyncMock()
        page.locator = MagicMock(return_value=locator)
        page.wait_for_timeout = AsyncMock()

        await appliquer_code_promo(page, "TEST123")
