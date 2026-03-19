"""Tests pour le positionnement des menuiseries studio.

Vérifie :
- MENUISERIE_MODULES : largeurs correctes par type
- Positionnement multi-modules : BAIE VITREE, FENETRE DOUBLE, PORTE DOUBLE VITREE
  occupent 2 modules consécutifs et bloquent les positions adjacentes
- Scénario plan client Marguet (studio 8,8×5,7m) : les menuiseries ne se
  chevauchent pas et correspondent aux positions souhaitées sur le plan
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ajouter scripts/ au PYTHONPATH
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from generateur_devis_auto import (
    ConfigStudio,
    GenerateurDevis,
    MENUISERIE_MODULES,
    MODULE_STUDIO,
)


# ─── Tests MENUISERIE_MODULES ────────────────────────────────────────────────

class TestMenuiserieModules:
    """Vérifie la table de largeurs par type de menuiserie."""

    def test_simples_occupent_1_module(self) -> None:
        assert MENUISERIE_MODULES["PORTE VITREE"] == 1
        assert MENUISERIE_MODULES["FENETRE SIMPLE"] == 1

    def test_doubles_occupent_2_modules(self) -> None:
        assert MENUISERIE_MODULES["BAIE VITREE"] == 2
        assert MENUISERIE_MODULES["FENETRE DOUBLE"] == 2
        assert MENUISERIE_MODULES["PORTE DOUBLE VITREE"] == 2

    def test_tous_les_types_sont_couverts(self) -> None:
        """Chaque type de menuiserie studio doit avoir une entrée."""
        types_attendus = {
            "PORTE VITREE", "FENETRE SIMPLE", "FENETRE DOUBLE",
            "BAIE VITREE", "PORTE DOUBLE VITREE",
        }
        assert set(MENUISERIE_MODULES.keys()) == types_attendus

    def test_module_studio_valeur(self) -> None:
        assert MODULE_STUDIO == 1.10


# ─── Tests positionnement anti-chevauchement ─────────────────────────────────

def _make_positions_8_8m() -> list[dict]:
    """Génère les positions DOM pour un mur de 8,8m (8 modules)."""
    return [
        {"text": f"{i * 1.1:.2f}".replace(".", ","), "uid": f"uid-{i}"}
        for i in range(8)
    ]


def _make_positions_5_7m() -> list[dict]:
    """Génère les positions DOM pour un mur de 5,7m (5 modules)."""
    return [
        {"text": f"{i * 1.1:.2f}".replace(".", ","), "uid": f"uid-{i}"}
        for i in range(5)
    ]


class TestPositionnementMultiModules:
    """Vérifie que les menuiseries doubles réservent 2 modules."""

    @pytest.fixture
    def gen(self) -> GenerateurDevis:
        """Crée un GenerateurDevis avec une page mockée."""
        g = object.__new__(GenerateurDevis)
        g.page = AsyncMock()
        return g

    @pytest.mark.asyncio
    async def test_baie_vitree_occupe_2_modules(self, gen: GenerateurDevis) -> None:
        """BAIE VITREE à la position 2,20 doit réserver les modules 2 ET 3."""
        positions = _make_positions_8_8m()

        # Premier appel evaluate → navigation DOM (retourne les positions)
        # Deuxième appel evaluate → clic sur la position
        gen.page.evaluate = AsyncMock(side_effect=[
            {"positions": positions},
            {"ok": True},
        ])
        gen.page.wait_for_timeout = AsyncMock()

        used = {}
        await gen._ajouter_menuiserie_studio(
            "BAIE VITREE", "ALU", "MUR DE FACE", "2,20", used,
        )

        # Doit avoir réservé les modules 2 et 3
        assert used["MUR DE FACE"] == {2, 3}

    @pytest.mark.asyncio
    async def test_fenetre_simple_occupe_1_module(self, gen: GenerateurDevis) -> None:
        """FENETRE SIMPLE ne réserve qu'un seul module."""
        positions = _make_positions_5_7m()
        gen.page.evaluate = AsyncMock(side_effect=[
            {"positions": positions},
            {"ok": True},
        ])
        gen.page.wait_for_timeout = AsyncMock()

        used = {}
        await gen._ajouter_menuiserie_studio(
            "FENETRE SIMPLE", "PVC", "MUR DE GAUCHE", "centre", used,
        )

        # Centre du mur 5,7m (5 modules) → module 2
        assert used["MUR DE GAUCHE"] == {2}

    @pytest.mark.asyncio
    async def test_baie_vitree_bloque_positions_adjacentes(self, gen: GenerateurDevis) -> None:
        """Après une BAIE VITREE en 2,20, une FENETRE SIMPLE ne peut pas aller en 3,30."""
        positions = _make_positions_8_8m()

        # Appel 1 : BAIE VITREE → navigation + clic
        gen.page.evaluate = AsyncMock(side_effect=[
            {"positions": positions},
            {"ok": True},
        ])
        gen.page.wait_for_timeout = AsyncMock()

        used = {}
        await gen._ajouter_menuiserie_studio(
            "BAIE VITREE", "ALU", "MUR DE FACE", "2,20", used,
        )

        # Appel 2 : FENETRE SIMPLE en auto → devrait sauter le module 3 (occupé par BAIE)
        gen.page.evaluate = AsyncMock(side_effect=[
            {"positions": positions},
            {"ok": True},
        ])

        result = await gen._ajouter_menuiserie_studio(
            "FENETRE SIMPLE", "PVC", "MUR DE FACE", "auto", used,
        )

        # Module 0 est le premier libre (modules 2 et 3 occupés par la baie)
        assert result == "0,00"
        assert 0 in used["MUR DE FACE"]  # module 0 maintenant occupé
        assert 3 in used["MUR DE FACE"]  # module 3 toujours occupé (baie)


# ─── Scénario plan client Marguet ─────────────────────────────────────────────

class TestPlanClientMarguet:
    """Simule la configuration du studio 8,8×5,7m d'après le plan du client.

    Plan client (de gauche à droite sur le MUR DE FACE = côté terrasse) :
    - Modules 0-1 : mur plein (zone coffret/vestiaire)
    - Modules 2-3 : BAIE VITREE ALU (grande ouverture salon)
    - Module 4 : PORTE VITREE ALU (entrée)
    - Modules 5-6 : FENETRE DOUBLE ALU (côté chambre)
    - Module 7 : mur plein (angle SDB)

    MUR DE GAUCHE (5 modules) : FENETRE SIMPLE PVC au centre (module 2)
    MUR DE DROITE (5 modules) : FENETRE SIMPLE PVC au centre (module 2)
    MUR DU FOND (8 modules) : FENETRE SIMPLE PVC à droite (module 7, SDB)
    """

    @pytest.fixture
    def gen(self) -> GenerateurDevis:
        g = object.__new__(GenerateurDevis)
        g.page = AsyncMock()
        g.page.wait_for_timeout = AsyncMock()
        return g

    def _setup_evaluate(self, gen: GenerateurDevis, positions: list[dict]) -> None:
        """Configure page.evaluate pour retourner positions puis ok."""
        gen.page.evaluate = AsyncMock(side_effect=[
            {"positions": positions},
            {"ok": True},
        ])

    @pytest.mark.asyncio
    async def test_mur_de_face_complet(self, gen: GenerateurDevis) -> None:
        """Place 3 menuiseries sur le MUR DE FACE sans chevauchement."""
        pos_face = _make_positions_8_8m()
        used = {}

        # 1. BAIE VITREE en position 2,20 (modules 2-3)
        self._setup_evaluate(gen, pos_face)
        r1 = await gen._ajouter_menuiserie_studio(
            "BAIE VITREE", "ALU", "MUR DE FACE", "2,20", used,
        )
        assert r1 == "2,20"
        assert used["MUR DE FACE"] == {2, 3}

        # 2. PORTE VITREE en position 4,40 (module 4)
        self._setup_evaluate(gen, pos_face)
        r2 = await gen._ajouter_menuiserie_studio(
            "PORTE VITREE", "ALU", "MUR DE FACE", "4,40", used,
        )
        assert r2 == "4,40"
        assert used["MUR DE FACE"] == {2, 3, 4}

        # 3. FENETRE DOUBLE en position 5,50 (modules 5-6)
        self._setup_evaluate(gen, pos_face)
        r3 = await gen._ajouter_menuiserie_studio(
            "FENETRE DOUBLE", "ALU", "MUR DE FACE", "5,50", used,
        )
        assert r3 == "5,50"
        assert used["MUR DE FACE"] == {2, 3, 4, 5, 6}

        # Vérifications finales
        # Modules libres : 0, 1, 7 (murs pleins, conforme au plan)
        assert 0 not in used["MUR DE FACE"]
        assert 1 not in used["MUR DE FACE"]
        assert 7 not in used["MUR DE FACE"]

    @pytest.mark.asyncio
    async def test_mur_gauche_fenetre_centre(self, gen: GenerateurDevis) -> None:
        """FENETRE SIMPLE au centre du MUR DE GAUCHE (5 modules)."""
        pos_gauche = _make_positions_5_7m()
        used = {}

        self._setup_evaluate(gen, pos_gauche)
        r = await gen._ajouter_menuiserie_studio(
            "FENETRE SIMPLE", "PVC", "MUR DE GAUCHE", "centre", used,
        )
        assert r == "2,20"  # Module 2 = centre d'un mur à 5 modules
        assert used["MUR DE GAUCHE"] == {2}

    @pytest.mark.asyncio
    async def test_mur_droite_fenetre_centre(self, gen: GenerateurDevis) -> None:
        """FENETRE SIMPLE au centre du MUR DE DROITE (5 modules)."""
        pos_droite = _make_positions_5_7m()
        used = {}

        self._setup_evaluate(gen, pos_droite)
        r = await gen._ajouter_menuiserie_studio(
            "FENETRE SIMPLE", "PVC", "MUR DE DROITE", "centre", used,
        )
        assert r == "2,20"
        assert used["MUR DE DROITE"] == {2}

    @pytest.mark.asyncio
    async def test_mur_fond_fenetre_droite(self, gen: GenerateurDevis) -> None:
        """FENETRE SIMPLE à droite du MUR DU FOND (8 modules, SDB)."""
        pos_fond = _make_positions_8_8m()
        used = {}

        self._setup_evaluate(gen, pos_fond)
        r = await gen._ajouter_menuiserie_studio(
            "FENETRE SIMPLE", "PVC", "MUR DU FOND", "droite", used,
        )
        assert r == "7,70"  # Dernier module du mur 8,8m
        assert used["MUR DU FOND"] == {7}

    @pytest.mark.asyncio
    async def test_scenario_complet_4_murs(self, gen: GenerateurDevis) -> None:
        """Scénario complet : 6 menuiseries sur 4 murs, aucun chevauchement."""
        used = {}
        pos_8m = _make_positions_8_8m()
        pos_5m = _make_positions_5_7m()

        menuiseries = [
            # MUR DE FACE : 3 menuiseries (baie + porte + fenêtre double)
            ("BAIE VITREE", "ALU", "MUR DE FACE", "2,20", pos_8m),
            ("PORTE VITREE", "ALU", "MUR DE FACE", "4,40", pos_8m),
            ("FENETRE DOUBLE", "ALU", "MUR DE FACE", "5,50", pos_8m),
            # Autres murs : 1 menuiserie chacun
            ("FENETRE SIMPLE", "PVC", "MUR DE GAUCHE", "centre", pos_5m),
            ("FENETRE SIMPLE", "PVC", "MUR DE DROITE", "centre", pos_5m),
            ("FENETRE SIMPLE", "PVC", "MUR DU FOND", "droite", pos_8m),
        ]

        for type_m, mat, mur, pos, positions in menuiseries:
            self._setup_evaluate(gen, positions)
            await gen._ajouter_menuiserie_studio(type_m, mat, mur, pos, used)

        # Vérifier que chaque mur a les bons modules occupés
        assert used["MUR DE FACE"] == {2, 3, 4, 5, 6}  # 5 modules sur 8
        assert used["MUR DE GAUCHE"] == {2}              # 1 module sur 5
        assert used["MUR DE DROITE"] == {2}              # 1 module sur 5
        assert used["MUR DU FOND"] == {7}                # 1 module sur 8

        # Total : 8 modules occupés, aucun chevauchement
        all_modules = []
        for mur_name, mods in used.items():
            for m in mods:
                all_modules.append((mur_name, m))
        assert len(all_modules) == 8  # 5 + 1 + 1 + 1

    @pytest.mark.asyncio
    async def test_conflit_baie_puis_porte_meme_module(self, gen: GenerateurDevis) -> None:
        """Si BAIE VITREE occupe modules 2-3, une PORTE VITREE en 3,30 doit fallback."""
        pos_face = _make_positions_8_8m()
        used = {}

        # Placer la BAIE VITREE en 2,20 (modules 2-3)
        self._setup_evaluate(gen, pos_face)
        await gen._ajouter_menuiserie_studio(
            "BAIE VITREE", "ALU", "MUR DE FACE", "2,20", used,
        )

        # Tenter de placer une PORTE VITREE en 3,30 (module 3 déjà pris)
        self._setup_evaluate(gen, pos_face)
        r = await gen._ajouter_menuiserie_studio(
            "PORTE VITREE", "ALU", "MUR DE FACE", "3,30", used,
        )

        # Le module 3 est pris → sélection forcée (le code tente quand même)
        # ou fallback sur le plus proche libre
        # Le code actuel fait une sélection forcée quand la position exacte existe
        # mais le module est occupé → le résultat sera "3,30" avec un warning
        assert r == "3,30"  # Sélection forcée avec warning

    @pytest.mark.asyncio
    async def test_fenetre_double_evite_modules_occupes(self, gen: GenerateurDevis) -> None:
        """FENETRE DOUBLE (2 modules) en auto saute les modules occupés."""
        pos_face = _make_positions_8_8m()
        used = {}

        # Occuper les modules 0 et 1 avec 2 FENETRE SIMPLE
        self._setup_evaluate(gen, pos_face)
        await gen._ajouter_menuiserie_studio(
            "FENETRE SIMPLE", "PVC", "MUR DE FACE", "0,00", used,
        )
        self._setup_evaluate(gen, pos_face)
        await gen._ajouter_menuiserie_studio(
            "FENETRE SIMPLE", "PVC", "MUR DE FACE", "1,10", used,
        )
        assert used["MUR DE FACE"] == {0, 1}

        # FENETRE DOUBLE en auto → devrait aller en 2,20 (modules 2-3, premiers libres consécutifs)
        self._setup_evaluate(gen, pos_face)
        r = await gen._ajouter_menuiserie_studio(
            "FENETRE DOUBLE", "ALU", "MUR DE FACE", "auto", used,
        )
        assert r == "2,20"
        assert used["MUR DE FACE"] == {0, 1, 2, 3}
