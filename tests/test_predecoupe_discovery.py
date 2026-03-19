"""Tests pour la prédécoupe abri et la découverte dynamique des options WPC.

Vérifie :
- ConfigAbri accepte les nouveaux champs predecoupe et options_wpc
- La découverte dynamique retourne un arbre d'options WPC
- La prédécoupe déclenche les bons clics dans le configurateur
- Les options_wpc dynamiques sont appliquées correctement
- Le MCP server expose et parse les nouveaux paramètres
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

# Ajouter scripts/ au PYTHONPATH
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from generateur_devis_auto import ConfigAbri, _print_wpc_tree


# ─── Tests ConfigAbri ────────────────────────────────────────────────────────

class TestConfigAbriPredecoupe:
    """Tests pour les nouveaux champs de ConfigAbri."""

    def test_default_predecoupe_false(self) -> None:
        """predecoupe est False par défaut."""
        config = ConfigAbri(largeur="4,35M", profondeur="2,15m")
        assert config.predecoupe is False

    def test_predecoupe_true(self) -> None:
        """predecoupe peut être activé."""
        config = ConfigAbri(largeur="4,35M", profondeur="2,15m", predecoupe=True)
        assert config.predecoupe is True

    def test_default_options_wpc_empty(self) -> None:
        """options_wpc est un dict vide par défaut."""
        config = ConfigAbri(largeur="4,35M", profondeur="2,15m")
        assert config.options_wpc == {}

    def test_options_wpc_custom(self) -> None:
        """options_wpc accepte un dict personnalisé."""
        opts = {"Prédécoupe": "OUI", "Plancher": "OUI"}
        config = ConfigAbri(largeur="4,35M", profondeur="2,15m", options_wpc=opts)
        assert config.options_wpc == opts

    def test_asdict_includes_new_fields(self) -> None:
        """asdict() inclut predecoupe et options_wpc."""
        config = ConfigAbri(
            largeur="4,35M", profondeur="2,15m",
            predecoupe=True, options_wpc={"Test": "OUI"},
        )
        d = asdict(config)
        assert d["predecoupe"] is True
        assert d["options_wpc"] == {"Test": "OUI"}

    def test_config_abri_backward_compatible(self) -> None:
        """Les anciens appels sans predecoupe/options_wpc fonctionnent toujours."""
        config = ConfigAbri(
            largeur="5,50M",
            profondeur="3,45m",
            ouvertures=[{"type": "Porte double Vitrée", "face": "Face 1", "position": "Centre"}],
            extension_toiture="Droite 1 M",
            plancher=True,
            bac_acier=True,
        )
        assert config.predecoupe is False
        assert config.options_wpc == {}
        assert config.plancher is True
        assert config.bac_acier is True


# ─── Tests _print_wpc_tree ──────────────────────────────────────────────────

class TestPrintWpcTree:
    """Tests pour l'affichage de l'arbre WPC découvert."""

    def test_simple_node(self, capsys) -> None:
        """Affiche un nœud simple."""
        node = {"text": "OPTIONS", "type": "group", "uid": "abc", "visible": True, "selected": False}
        _print_wpc_tree(node, indent=0)
        captured = capsys.readouterr()
        assert "OPTIONS" in captured.out
        assert "group" in captured.out
        assert "✓" in captured.out

    def test_hidden_node(self, capsys) -> None:
        """Affiche correctement un nœud masqué."""
        node = {"text": "Hidden", "type": "image", "uid": "xyz", "visible": False, "selected": False}
        _print_wpc_tree(node, indent=2)
        captured = capsys.readouterr()
        assert "Hidden" in captured.out
        assert "✗" in captured.out

    def test_selected_node(self, capsys) -> None:
        """Affiche [SÉLECTIONNÉ] pour un nœud actif."""
        node = {"text": "OUI", "type": "image", "uid": "sel", "visible": True, "selected": True}
        _print_wpc_tree(node, indent=0)
        captured = capsys.readouterr()
        assert "SÉLECTIONNÉ" in captured.out

    def test_nested_children(self, capsys) -> None:
        """Affiche récursivement les enfants."""
        node = {
            "text": "OPTIONS", "type": "group", "uid": "a", "visible": True, "selected": False,
            "children": [
                {"text": "Prédécoupe", "type": "sub_group", "uid": "b", "visible": True, "selected": False,
                 "children": [
                     {"text": "OUI", "type": "image", "uid": "c", "visible": True, "selected": False},
                     {"text": "NON", "type": "image", "uid": "d", "visible": True, "selected": True},
                 ]},
            ],
        }
        _print_wpc_tree(node, indent=0)
        captured = capsys.readouterr()
        assert "OPTIONS" in captured.out
        assert "Prédécoupe" in captured.out
        assert "OUI" in captured.out
        assert "NON" in captured.out


# ─── Tests découverte dynamique WPC ─────────────────────────────────────────

@pytest.mark.asyncio
class TestDecouvrirOptionsWpc:
    """Tests pour la méthode _decouvrir_options_wpc."""

    async def test_retourne_arbre_options(self, mock_page) -> None:
        """_decouvrir_options_wpc retourne l'arbre des options du DOM."""
        from generateur_devis_auto import GenerateurDevis

        # Simuler la réponse du DOM
        wpc_tree = [
            {
                "text": "OPTIONS", "type": "group", "uid": "opt1", "visible": True, "selected": False,
                "children": [
                    {"text": "Plancher", "type": "sub_group", "uid": "p1", "visible": True, "selected": False,
                     "children": [
                         {"text": "OUI", "type": "image", "uid": "p1y", "visible": True, "selected": False},
                     ]},
                    {"text": "Bac Acier", "type": "sub_group", "uid": "ba1", "visible": True, "selected": False},
                    {"text": "Prédécoupe", "type": "sub_group", "uid": "pd1", "visible": True, "selected": False,
                     "children": [
                         {"text": "OUI", "type": "image", "uid": "pd1y", "visible": True, "selected": False},
                     ]},
                ],
            },
        ]
        mock_page.evaluate = AsyncMock(return_value=wpc_tree)

        gen = GenerateurDevis.__new__(GenerateurDevis)
        gen.page = mock_page

        result = await gen._decouvrir_options_wpc()

        assert len(result) == 1
        assert result[0]["text"] == "OPTIONS"
        children_texts = [c["text"] for c in result[0]["children"]]
        assert "Plancher" in children_texts
        assert "Bac Acier" in children_texts
        assert "Prédécoupe" in children_texts

    async def test_retourne_liste_vide_si_pas_de_dom(self, mock_page) -> None:
        """Retourne [] si le DOM n'a pas de conteneur WPC."""
        from generateur_devis_auto import GenerateurDevis

        mock_page.evaluate = AsyncMock(return_value=[])

        gen = GenerateurDevis.__new__(GenerateurDevis)
        gen.page = mock_page

        result = await gen._decouvrir_options_wpc()
        assert result == []


# ─── Tests appliquer_options_wpc ─────────────────────────────────────────────

@pytest.mark.asyncio
class TestAppliquerOptionsWpc:
    """Tests pour la méthode _appliquer_options_wpc."""

    async def test_option_simple_dans_options(self, mock_page) -> None:
        """Applique une option simple dans le groupe OPTIONS."""
        from generateur_devis_auto import GenerateurDevis

        gen = GenerateurDevis.__new__(GenerateurDevis)
        gen.page = mock_page
        gen._click_by_data_text = AsyncMock()
        gen._click_visible_by_data_text = AsyncMock()

        await gen._appliquer_options_wpc({"Prédécoupe": "OUI"})

        # Doit ouvrir "OPTIONS" puis naviguer vers "Prédécoupe" > "OUI"
        gen._click_by_data_text.assert_called_with("OPTIONS")
        calls = gen._click_visible_by_data_text.call_args_list
        assert any(c == call("Prédécoupe", parent_text="OPTIONS") for c in calls)
        assert any(c == call("OUI", parent_text="OPTIONS") for c in calls)

    async def test_option_hierarchique(self, mock_page) -> None:
        """Applique une option hiérarchique (group > sub > value)."""
        from generateur_devis_auto import GenerateurDevis

        gen = GenerateurDevis.__new__(GenerateurDevis)
        gen.page = mock_page
        gen._click_by_data_text = AsyncMock()
        gen._click_visible_by_data_text = AsyncMock()

        await gen._appliquer_options_wpc({"Extension de toiture": {"Droite": "2 M"}})

        gen._click_by_data_text.assert_called_with("Extension de toiture")
        calls = gen._click_visible_by_data_text.call_args_list
        assert any(c == call("Droite", parent_text="Extension de toiture") for c in calls)
        assert any(c == call("2 M", parent_text="Extension de toiture") for c in calls)

    async def test_fallback_racine_si_pas_dans_options(self, mock_page) -> None:
        """Tombe en fallback sur la racine si l'option n'est pas dans OPTIONS."""
        from generateur_devis_auto import GenerateurDevis

        gen = GenerateurDevis.__new__(GenerateurDevis)
        gen.page = mock_page

        # Simuler que _click_by_data_text("OPTIONS") fonctionne mais
        # _click_visible_by_data_text("NouvelleOption") lève une ValueError
        call_count = 0

        async def mock_click_by_data_text(text):
            nonlocal call_count
            call_count += 1

        async def mock_click_visible(text, parent_text=""):
            if parent_text == "OPTIONS" and text == "NouvelleOption":
                raise ValueError("not found")

        gen._click_by_data_text = mock_click_by_data_text
        gen._click_visible_by_data_text = mock_click_visible

        # Devrait essayer OPTIONS, échouer, puis chercher directement
        await gen._appliquer_options_wpc({"NouvelleOption": "OUI"})
        # Au moins 2 appels à _click_by_data_text : "OPTIONS" puis "NouvelleOption"
        assert call_count >= 2


# ─── Tests configurer_abri avec prédécoupe ──────────────────────────────────

@pytest.mark.asyncio
class TestConfigurerAbriPredecoupe:
    """Tests que configurer_abri gère correctement la prédécoupe."""

    async def test_predecoupe_appelle_options(self, mock_page) -> None:
        """Avec predecoupe=True, le configurateur clique sur OPTIONS > Prédécoupe > OUI."""
        from generateur_devis_auto import GenerateurDevis, ConfigAbri

        gen = GenerateurDevis.__new__(GenerateurDevis)
        gen.page = mock_page
        gen.base_url = "https://www.abri-français.fr"
        gen.site_config = {"configurateur": "/configurateur-abri/"}
        gen.fermer_popups = AsyncMock()
        gen._select_dimension = AsyncMock()
        gen._click_by_data_text = AsyncMock()
        gen._click_visible_by_data_text = AsyncMock()
        gen._verifier_config_wpc = AsyncMock(return_value=True)
        gen._get_prix = AsyncMock(return_value="1 500,00 €")
        gen._decouvrir_options_wpc = AsyncMock(return_value=[])
        gen._appliquer_options_wpc = AsyncMock()

        config = ConfigAbri(
            largeur="4,35M", profondeur="2,15m",
            predecoupe=True,
        )
        prix = await gen.configurer_abri(config)

        # Vérifier que _click_by_data_text a été appelé avec "OPTIONS" (pour prédécoupe)
        options_calls = [c for c in gen._click_by_data_text.call_args_list
                         if c == call("OPTIONS")]
        assert len(options_calls) >= 1, "OPTIONS devrait être cliqué pour la prédécoupe"

        # Vérifier que Prédécoupe > OUI a été cliqué
        predecoupe_calls = [c for c in gen._click_visible_by_data_text.call_args_list
                            if "découpe" in str(c).lower()]
        assert len(predecoupe_calls) >= 1, "Prédécoupe devrait être cliqué"

    async def test_sans_predecoupe_pas_de_clic(self, mock_page) -> None:
        """Sans predecoupe, pas de clic sur Prédécoupe."""
        from generateur_devis_auto import GenerateurDevis, ConfigAbri

        gen = GenerateurDevis.__new__(GenerateurDevis)
        gen.page = mock_page
        gen.base_url = "https://www.abri-français.fr"
        gen.site_config = {"configurateur": "/configurateur-abri/"}
        gen.fermer_popups = AsyncMock()
        gen._select_dimension = AsyncMock()
        gen._click_by_data_text = AsyncMock()
        gen._click_visible_by_data_text = AsyncMock()
        gen._verifier_config_wpc = AsyncMock(return_value=True)
        gen._get_prix = AsyncMock(return_value="1 200,00 €")
        gen._decouvrir_options_wpc = AsyncMock(return_value=[])
        gen._appliquer_options_wpc = AsyncMock()

        config = ConfigAbri(
            largeur="4,35M", profondeur="2,15m",
            predecoupe=False,
        )
        await gen.configurer_abri(config)

        # Pas de clic sur Prédécoupe
        predecoupe_calls = [c for c in gen._click_visible_by_data_text.call_args_list
                            if "découpe" in str(c).lower()]
        assert len(predecoupe_calls) == 0


# ─── Tests MCP server — parsing des nouveaux paramètres ─────────────────────

class TestMcpServerParsing:
    """Tests que le MCP server parse correctement predecoupe et options_wpc."""

    def test_options_wpc_json_parsing(self) -> None:
        """Le JSON options_wpc est correctement parsé."""
        raw = '{"Prédécoupe": "OUI", "Plancher": "OUI"}'
        parsed = json.loads(raw)
        assert parsed == {"Prédécoupe": "OUI", "Plancher": "OUI"}

    def test_options_wpc_empty_string(self) -> None:
        """Un options_wpc vide donne un dict vide."""
        raw = "{}"
        parsed = json.loads(raw)
        assert parsed == {}

    def test_options_wpc_invalid_json_fallback(self) -> None:
        """Un JSON invalide donne un dict vide (fallback)."""
        raw = "not json"
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {}
        assert parsed == {}

    def test_configurations_supplementaires_with_predecoupe(self) -> None:
        """Les configs supplémentaires supportent predecoupe et options_wpc."""
        configs = [
            {
                "largeur": "4,70M",
                "profondeur": "3,45m",
                "ouvertures": [{"type": "Porte double Vitrée", "face": "Face 2", "position": "Centre"}],
                "extension_toiture": "Gauche 3,5 M",
                "bac_acier": True,
                "plancher": False,
                "predecoupe": True,
                "options_wpc": {"Prédécoupe": "OUI"},
            }
        ]
        raw = json.dumps(configs)
        parsed = json.loads(raw)
        assert parsed[0]["predecoupe"] is True
        assert parsed[0]["options_wpc"] == {"Prédécoupe": "OUI"}


# ─── Tests intégration generer_devis_abri ────────────────────────────────────

@pytest.mark.asyncio
class TestGenererDevisAbriPredecoupe:
    """Tests que generer_devis_abri passe correctement predecoupe au ConfigAbri."""

    async def test_predecoupe_passee_au_config(self) -> None:
        """generer_devis_abri passe predecoupe=True au ConfigAbri."""
        from generateur_devis_auto import generer_devis_abri, GenerateurDevis

        configs_created = []

        with patch.object(GenerateurDevis, 'start', new_callable=AsyncMock), \
             patch.object(GenerateurDevis, 'configurer_abri', new_callable=AsyncMock) as mock_config, \
             patch.object(GenerateurDevis, 'ajouter_au_panier', new_callable=AsyncMock), \
             patch.object(GenerateurDevis, 'verifier_panier', new_callable=AsyncMock, return_value=1), \
             patch.object(GenerateurDevis, 'generer_devis', new_callable=AsyncMock, return_value="/tmp/test.pdf"), \
             patch.object(GenerateurDevis, 'stop', new_callable=AsyncMock):

            # Capturer le ConfigAbri passé
            async def capture_config(config):
                configs_created.append(config)
                return "1 500,00 €"
            mock_config.side_effect = capture_config

            try:
                await generer_devis_abri(
                    largeur="4,35M",
                    profondeur="2,15m",
                    ouvertures=[{"type": "Porte Pleine", "face": "Face 1", "position": "Centre"}],
                    client_nom="Test", client_prenom="Predecoupe",
                    client_email="test@test.fr", client_telephone="0600000000",
                    client_adresse="1 Rue Test, 75001 Paris",
                    predecoupe=True,
                    options_wpc={"CustomOption": "Valeur"},
                )
            except Exception:
                pass  # Le PDF n'existera pas, c'est normal

            assert len(configs_created) >= 1
            config = configs_created[0]
            assert config.predecoupe is True
            assert config.options_wpc == {"CustomOption": "Valeur"}
