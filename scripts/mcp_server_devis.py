#!/usr/bin/env python3
"""
MCP Server — Générateur de Devis Abri Français

Expose le générateur de devis comme outil MCP pour Claude Desktop.
Le commercial colle les données Odoo dans Claude, Claude analyse et
appelle ces outils pour configurer + générer les devis PDF.

Lancement :
    python3 mcp_server_devis.py
"""

import asyncio
import datetime
import json
import os
import sys
import time as _time
import urllib.request
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# Ajouter le répertoire courant au path pour importer generateur_devis_auto
sys.path.insert(0, str(Path(__file__).parent))


# Le protocole MCP utilise stdout pour JSON-RPC — tout print() non-JSON corrompt le flux.
# Les générateurs Playwright affichent ~100 logs (========, ✓, ➜...) via print().
# FastMCP écrit le JSON-RPC directement dans le buffer de sys.stdout, pas via print(),
# donc on peut sans risque rediriger tous les print() vers stderr.
import builtins as _builtins
_original_print = _builtins.print


def _print_to_stderr(*args, **kwargs):
    kwargs.setdefault("file", sys.stderr)
    _original_print(*args, **kwargs)


_builtins.print = _print_to_stderr


# ═══════════════════════════════════════════════════════════════
# IMPORT DIRECT DES GÉNÉRATEURS (remplace subprocess)
# ═══════════════════════════════════════════════════════════════
# Les générateurs héritent automatiquement du print→stderr ci-dessus.
# Chrome reste visible : même processus = même session macOS WindowServer.

try:
    from generateur_devis_3sites import (
        generer_devis_pergola, generer_devis_terrasse,
        generer_devis_cloture, generer_devis_terrasse_detail,
    )
    from generateur_devis_auto import generer_devis_abri, generer_devis_studio
    _GENERATORS_AVAILABLE = True
    _GENERATORS_IMPORT_ERR = None
except Exception as _import_exc:
    _GENERATORS_AVAILABLE = False
    _GENERATORS_IMPORT_ERR = str(_import_exc)


# Background tasks — référence pour éviter le GC avant la fin de génération
_background_tasks: dict = {}
_bg_task_counter = 0

# Log structuré des devis générés
_DEVIS_LOG_FILE = os.path.expanduser("~/Downloads/devis_log.json")


def _log_devis(filepath: str, type_devis: str, client_prenom: str, client_nom: str) -> None:
    """Enregistre un devis généré dans ~/Downloads/devis_log.json (non-bloquant)."""
    try:
        log = []
        if os.path.exists(_DEVIS_LOG_FILE):
            with open(_DEVIS_LOG_FILE, "r", encoding="utf-8") as f:
                log = json.load(f)
        size_kb = round(os.path.getsize(filepath) / 1024, 1) if os.path.exists(filepath) else 0
        log.insert(0, {
            "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "type": type_devis,
            "client": f"{client_prenom} {client_nom}".strip(),
            "filepath": filepath,
            "filename": os.path.basename(filepath),
            "size_kb": size_kb,
        })
        with open(_DEVIS_LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(log[:100], f, ensure_ascii=False, indent=2)
    except Exception:
        pass  # log non-bloquant


async def _run_generator(type_devis: str, params: dict) -> str:
    """Appelle directement la fonction de génération appropriée."""
    if type_devis == "pergola":
        fp, _ = await generer_devis_pergola(**params)
    elif type_devis == "terrasse":
        fp, _ = await generer_devis_terrasse(**params)
    elif type_devis == "cloture":
        fp, _ = await generer_devis_cloture(**params)
    elif type_devis == "terrasse_detail":
        fp, _ = await generer_devis_terrasse_detail(**params)
    elif type_devis == "abri":
        fp = await generer_devis_abri(**params)
    elif type_devis == "studio":
        fp = await generer_devis_studio(**params)
    else:
        raise ValueError(f"Type de devis inconnu: {type_devis}")
    return fp


async def _generer_direct(type_devis: str, params: dict,
                           client_prenom: str, client_nom: str) -> str:
    """Génère un devis en appelant directement les fonctions de génération.

    Avantages vs subprocess :
    - Pas de délai de démarrage de processus Python
    - Pas de sérialisation/parsing stdout
    - Pas de retry FS pour le fichier (filepath retourné directement)
    - Chrome visible : même session macOS WindowServer
    - asyncio.shield : le task continue en arrière-plan si timeout 55s
    """
    global _bg_task_counter

    if not _GENERATORS_AVAILABLE:
        return json.dumps({
            "success": False,
            "error": f"Générateurs non importés : {_GENERATORS_IMPORT_ERR}",
        })

    task = asyncio.create_task(_run_generator(type_devis, params))

    # Stocker la référence pour éviter le GC si timeout
    _bg_task_counter += 1
    task_id = f"{type_devis}_{client_prenom}_{client_nom}_{_bg_task_counter}"
    _background_tasks[task_id] = task
    task.add_done_callback(lambda t: _background_tasks.pop(task_id, None))

    try:
        # asyncio.shield empêche l'annulation du task interne quand wait_for expire
        filepath = await asyncio.wait_for(asyncio.shield(task), timeout=55)

        if filepath and str(filepath).endswith(".pdf") and os.path.exists(filepath):
            size_kb = os.path.getsize(filepath) / 1024
            _log_devis(filepath, type_devis, client_prenom, client_nom)
            return json.dumps({
                "success": True,
                "filepath": filepath,
                "filename": os.path.basename(filepath),
                "size_kb": round(size_kb, 1),
                "message": f"Devis {type_devis} généré pour {client_prenom} {client_nom}",
            })
        return json.dumps({"success": False, "error": f"PDF non trouvé : {filepath!r}"})

    except asyncio.TimeoutError:
        # Le task continue en arrière-plan — retourner "en_cours"
        nom = f"{client_prenom}_{client_nom}".replace(" ", "_")
        return json.dumps({
            "success": True,
            "status": "en_cours",
            "message": (
                f"Génération démarrée en arrière-plan (prend ~2 min). "
                f"Appelez lister_devis_generes dans 1-2 minutes pour récupérer le PDF de {nom}."
            ),
        })
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


mcp = FastMCP(
    "devis-abri-francais",
    instructions="""Tu es l'assistant commercial du Groupe Abri Français.
Tu utilises les outils ci-dessous pour générer des devis PDF à partir
des demandes clients extraites des opportunités Odoo.

Workflow typique :
1. Le commercial colle les données d'une opportunité Odoo
2. Tu analyses le besoin client (produit, dimensions, options)
3. Tu appelles generer_devis pour créer le PDF
4. Tu rédiges la réponse email au client avec le devis en PJ

Pour les demandes multi-produits (ex: abri + pergola), génère
chaque devis séparément puis propose une réponse globale.""",
)


# ═══════════════════════════════════════════════════════════════
# CONFIGURATION : URLs des sites WooCommerce
# ═══════════════════════════════════════════════════════════════

SITES_BASE_URL = {
    "abri":    "https://www.xn--abri-franais-sdb.fr",   # abri-francais.fr (punycode)
    "studio":  "https://xn--studio-franais-qjb.fr",     # studio-francais.fr (punycode) ⚠ PAS de www. !
    "pergola": "https://www.mapergolabois.fr",
    "terrasse":"https://www.terrasseenbois.fr",
    "cloture": "https://www.cloturebois.fr",
    # ⚠ www.studio-francais.fr redirige vers la homepage (HTML) — toujours utiliser le punycode sans www
}

# Cache API WooCommerce — évite les appels répétés lors d'une même session
_API_CACHE: dict = {}   # {(site, recherche, max_results): (timestamp, result_str)}
_API_CACHE_TTL = 300    # 5 minutes


def _woo_api_get(base_url: str, path: str, params: dict = None) -> list | dict:
    """Appel GET à l'API WooCommerce Store v1 (pas d'auth requise pour produits publics)."""
    url = f"{base_url}/wp-json/wc/store/v1/{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; DevisBot/1.0)"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


# ═══════════════════════════════════════════════════════════════
# OUTIL : RECHERCHER DES PRODUITS AU DÉTAIL (API LIVE)
# ═══════════════════════════════════════════════════════════════

@mcp.tool()
def rechercher_produits_detail(
    site: str,
    recherche: str = "",
    max_results: int = 10,
) -> str:
    """Recherche des produits complémentaires / au détail sur un site du groupe.

    Interroge l'API WooCommerce en temps réel — toujours à jour avec le catalogue en ligne.
    Utilise cet outil pour trouver le bon product_id, variation_id et URL d'un produit
    avant de l'ajouter comme produit complémentaire dans generer_devis.

    Args:
        site       : "abri" | "studio" | "pergola" | "terrasse" | "cloture"
                     Cas d'usage par site :
                     - "abri"    : bois au détail (planches, lames, bac acier…) + Gamme Essentiel préconçue
                                  rechercher "essentiel" pour trouver les abris Essentiel (1190-2120€)
                     - "studio"  : cloison intérieure (ID=5766, 60€/ml) + bois au détail
                     - "pergola" : accessoires pergola (visserie, protections…)
                     - "terrasse": kits préconçus (surfaces 10/20/40/60/80m², types lame/kit/kit-complet)
                                  rechercher "[essence]" ex: "pin autoclave" ou "cumaru"
                     - "cloture" : aucun produit au détail (kit classique et moderne uniquement)
        recherche  : Terme de recherche libre (ex: "planche 27x130", "polycarbonate", "cloison", "essentiel")
                     Laisser vide "" pour lister TOUS les produits du site.
        max_results: Nombre maximum de résultats (défaut 10, max 50)

    Returns:
        JSON array de produits avec pour chaque produit :
        - id            : product_id WooCommerce
        - name          : nom du produit
        - prix_min      : prix minimum en euros (variation la moins chère)
        - en_stock      : True si le produit est disponible
        - stock_status  : "instock" | "outofstock" | "onbackorder"
        - url           : URL de la page produit
        - variations    : liste des variations disponibles avec leur id, attributs, prix et stock
        - note          : conseils d'utilisation pour le paramètre attribut_selects

    Exemple d'utilisation du résultat dans generer_devis :
        produits_complementaires='[{"url": "https://...produit/planche.../", "variation_id": 53609,
         "quantite": 16, "attribut_selects": {"attribute_pa_longueur": "2"},
         "description": "16 planches 27×130mm 2m"}]'
    """
    if site not in SITES_BASE_URL:
        return json.dumps({
            "error": f"Site '{site}' inconnu. Valeurs : {list(SITES_BASE_URL.keys())}",
        })

    base_url = SITES_BASE_URL[site]

    # Vérifier le cache (TTL 5 min)
    cache_key = (site, recherche.strip(), min(max_results, 50))
    cached = _API_CACHE.get(cache_key)
    if cached and (_time.time() - cached[0]) < _API_CACHE_TTL:
        return cached[1]

    try:
        params = {"per_page": min(max_results, 50)}
        recherche_clean = recherche.strip()
        fallback_mot = None

        if recherche_clean:
            params["search"] = recherche_clean

        products = _woo_api_get(base_url, "products", params)

        # ── Fallback : si 0 résultats avec recherche multi-mots, réessayer
        #    avec le mot le plus long (généralement le plus distinctif).
        #    WordPress full-text search ne gère pas bien "planche 27x130" car
        #    "27x130" contient le signe × (U+00D7) dans la BDD, pas "x" ASCII.
        if not products and recherche_clean and " " in recherche_clean:
            mots = recherche_clean.split()
            fallback_mot = max(mots, key=len)   # mot le plus long = plus distinctif
            params["search"] = fallback_mot
            products = _woo_api_get(base_url, "products", params)

        import html as _html
        import re as _re

        def _clean_name(raw: str) -> str:
            """Décode entités HTML et retire les balises HTML."""
            return _re.sub(r"<[^>]+>", "", _html.unescape(raw)).strip()

        def _build_url(p: dict) -> str:
            """Reconstruit une URL propre depuis le slug (évite les entités &#215; etc.)"""
            return f"{base_url}/produit/{p['slug']}/"

        def _clean_attr_value(v: str) -> str:
            """Décode les valeurs d'attributs URL-encodées (ex: '1-m%c2%b2' → '1-m²')."""
            return urllib.parse.unquote(v)

        results = []
        for p in products:
            minor = int(p.get("prices", {}).get("currency_minor_unit", 2))
            divisor = 10 ** minor
            prix_brut = int(p.get("prices", {}).get("price", 0) or 0)
            prix_euros = prix_brut / divisor

            variations_out = []
            for v in p.get("variations", []):
                # Les variations inline n'ont pas toujours de prix → fallback sur le prix produit
                if "prices" in v:
                    var_prix = int(v["prices"].get("price", prix_brut)) / divisor
                else:
                    var_prix = prix_euros

                attrs = {a["name"]: _clean_attr_value(a["value"]) for a in v.get("attributes", [])}
                # Construire le dict attribut_selects compatible avec ajouter_produit_woo
                # Les valeurs WooCommerce utilisent "-" à la place de "." (ex: "2-5" = 2.5m)
                # ⚠ On garde la valeur RAW (encodée) pour attribut_selects car c'est ce que WC attend
                attr_selects = {}
                for a in v.get("attributes", []):
                    attr_slug = "attribute_pa_" + a["name"].lower().replace(" ", "_").replace("-", "_")
                    attr_selects[attr_slug] = a["value"]  # valeur brute WooCommerce (non décodée)

                var_en_stock = v.get("is_in_stock", True)
                var_stock_status = v.get("stock_status", "instock" if var_en_stock else "outofstock")
                variations_out.append({
                    "variation_id": v["id"],
                    "attributs": attrs,                  # lisible (décodé)
                    "attribut_selects": attr_selects,    # brut (pour le script)
                    "prix": round(var_prix, 2),
                    "en_stock": var_en_stock,
                    "stock_status": var_stock_status,
                })

            product_link = _build_url(p)

            prod_en_stock = p.get("is_in_stock", True)
            prod_stock_status = p.get("stock_status", "instock" if prod_en_stock else "outofstock")
            results.append({
                "id": p["id"],
                "name": _clean_name(p["name"]),
                "prix_min": round(prix_euros, 2),
                "en_stock": prod_en_stock,
                "stock_status": prod_stock_status,
                "url": product_link,
                "variations": variations_out,
                "note": (
                    "Pour ajouter ce produit dans generer_devis, utilise : "
                    f"\"url\": \"{product_link}\", "
                    f"\"variation_id\": <id_variation>, "
                    "\"quantite\": N, "
                    "\"attribut_selects\": <attribut_selects de la variation choisie>"
                ),
            })

        result_str = json.dumps({
            "site": site,
            "base_url": base_url,
            "recherche": recherche,
            "fallback_mot_utilise": fallback_mot,
            "nb_resultats": len(results),
            "produits": results,
        }, ensure_ascii=False, indent=2)
        # Mettre en cache (TTL 5 min)
        _API_CACHE[cache_key] = (_time.time(), result_str)
        return result_str

    except Exception as e:
        return json.dumps({
            "error": str(e),
            "site": site,
            "recherche": recherche,
            "conseil": "Vérifier que le site est accessible et que l'API WooCommerce Store est active."
        })


# ═══════════════════════════════════════════════════════════════
# OUTIL : VÉRIFIER LES PROMOTIONS ACTIVES
# ═══════════════════════════════════════════════════════════════

@mcp.tool()
def verifier_promotions_actives() -> str:
    """Scrappe les 5 sites du groupe pour détecter les promotions en cours.

    Lit le bandeau supérieur (#topbar) de chaque site — rendu côté serveur,
    donc toujours à jour sans JavaScript. Utile pour :
    - Proposer le bon code promo dans la réponse email au client
    - Passer le code_promo au bon outil generer_devis* pour l'appliquer dans le panier

    Appeler cet outil EN PREMIER lors de chaque session commerciale, ou dès
    qu'un client mentionne une remise / promotion.

    Returns:
        JSON avec les promotions par site, les codes détectés et un résumé global.
        Champs : promotions (par site), codes_uniques (dict code→remise),
                 resume (texte court), aucune_promo (bool).
    """
    import html as _html_mod
    import re as _re

    def _extraire_texte_topbar(html_str: str) -> str:
        """Extrait le texte du bandeau promo depuis .topbar-text ou #topbar."""
        # Stratégie 1 : class="topbar-text" (fonctionne sur tous les sites)
        matches = _re.findall(
            r'class=["\']topbar-text["\'][^>]*>(.*?)</div>',
            html_str, _re.DOTALL
        )
        for m in matches:
            text = _re.sub(r"<[^>]+>", "", m).strip()
            text = _html_mod.unescape(text)
            if text and len(text) > 10:
                return text
        # Stratégie 2 : id="topbar" (fallback)
        idx = html_str.find('id="topbar"')
        if idx == -1:
            idx = html_str.find("id='topbar'")
        if idx != -1:
            chunk = html_str[idx:idx + 2000]
            text = _re.sub(r"<[^>]+>", "", chunk)
            text = _re.sub(r"\s+", " ", text).strip()
            if text:
                return text[:300]
        return ""

    def _parse_codes(text: str) -> list:
        """Extrait (code, remise) depuis un texte de bandeau promo.
        Fonctionne avec tous les formats : '(code X)', 'avec le code X', 'code promo : X'.
        """
        pairs = []
        for m in _re.finditer(
            r'(?:code\s+(?:promo\s*:?)?\s*)([A-Z][A-Z0-9]{4,})',
            text, _re.IGNORECASE
        ):
            code = m.group(1).upper()
            # Chercher le pourcentage dans les 200 chars avant ce code
            before = text[max(0, m.start() - 200):m.start()]
            pct_matches = _re.findall(r'(-\d+)\s*%', before)
            remise = (pct_matches[-1] + "%") if pct_matches else ""
            pairs.append({"code": code, "remise": remise})
        return pairs

    promotions = []
    erreurs = []

    def _fetch_site_promo(site_url_pair):
        """Scrape un site pour les promos — exécuté en thread (urlopen est bloquant)."""
        site, base_url = site_url_pair
        try:
            req = urllib.request.Request(
                base_url + "/",
                headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                html_bytes = resp.read(700_000)  # 700 Ko — nécessaire pour studio/pergola
            html_str = html_bytes.decode("utf-8", errors="replace")

            topbar_text = _extraire_texte_topbar(html_str)
            code_remise_pairs = _parse_codes(topbar_text)

            periode_match = _re.search(
                r'(?:du\s+\d+\s+au\s+\d+\s+\w+|\d+\s+au\s+\d+\s+\w+(?:\s+\d{4})?|jusqu\'au\s+\d+\s+\w+)',
                topbar_text, _re.IGNORECASE
            )
            periode = periode_match.group(0) if periode_match else ""

            return ("ok", {
                "site": site,
                "url": base_url,
                "promo_active": bool(code_remise_pairs),
                "topbar_text": topbar_text,
                "codes_detectes": code_remise_pairs,
                "periode": periode,
            })
        except Exception as e:
            return ("err", {"site": site, "erreur": str(e)})

    # Requêtes en parallèle (5 sites simultanés → gain ~4× vs séquentiel)
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(_fetch_site_promo, pair): pair
                   for pair in SITES_BASE_URL.items()}
        for future in as_completed(futures):
            status, data = future.result()
            if status == "ok":
                promotions.append(data)
            else:
                erreurs.append(data)

    # Résumé global — dédupliquer les codes
    codes_uniques = {}
    for p in promotions:
        for c in p.get("codes_detectes", []):
            code = c.get("code")
            if code and code not in codes_uniques:
                codes_uniques[code] = c.get("remise", "")

    if codes_uniques:
        parts = [
            f"{remise} avec le code {code}" if remise else f"code {code}"
            for code, remise in codes_uniques.items()
        ]
        resume = "Promotions en cours : " + " | ".join(parts)
        periode_global = next((p["periode"] for p in promotions if p.get("periode")), "")
        if periode_global:
            resume += f" ({periode_global})"
    else:
        resume = "Aucune promotion détectée sur les sites du groupe."

    return json.dumps({
        "promotions": promotions,
        "codes_uniques": codes_uniques,
        "resume": resume,
        "erreurs": erreurs,
        "aucune_promo": len(codes_uniques) == 0,
        "conseil": (
            "Passer le code approprié dans code_promo de generer_devis / "
            "generer_devis_pergola_bois / generer_devis_terrasse_bois / "
            "generer_devis_cloture_bois pour l'appliquer automatiquement dans le panier."
        ),
    }, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════
# OUTIL PRINCIPAL : GÉNÉRER UN DEVIS
# ═══════════════════════════════════════════════════════════════

@mcp.tool()
async def generer_devis_pergola_bois(
    largeur: str,
    profondeur: str,
    fixation: str,
    ventelle: str,
    option: str = "non",
    poteau_lamelle_colle: bool = False,
    nb_poteaux_lamelle_colle: int = 0,
    claustra_type: str = "",
    nb_claustra: int = 0,
    sur_mesure: bool = False,
    largeur_hors_tout: str = "",
    profondeur_hors_tout: str = "",
    hauteur_hors_tout: str = "",
    client_nom: str = "",
    client_prenom: str = "",
    client_email: str = "",
    client_telephone: str = "",
    client_adresse: str = "",
    code_promo: str = "",
    mode_livraison: str = "",
    produits_complementaires: str = "[]",
    configurations_supplementaires: str = "[]",
) -> str:
    """Génère un devis pergola bois sur mapergolabois.fr.

    Args:
        largeur              : "2m","3m","4m","5m","6m","7m","8m","9m","10m"
        profondeur           : "2m","3m","4m","5m"
        fixation             : "adossee" | "independante"
        ventelle             : "largeur" | "profondeur" | "retro" | "sans"
        option               : "non" | "platelage" | "voilage" | "bioclimatique" |
                               "carport" | "lattage" | "polycarbonate"
                               ⚠ platelage nécessite ventelle="largeur" ou "profondeur"
        poteau_lamelle_colle : True pour ajouter des poteaux en bois lamellé-collé
        nb_poteaux_lamelle_colle : Nombre de poteaux lamellé-collé (0 = auto-calculé depuis
                               la description de variation). Fournir si auto-calcul échoue.
        claustra_type        : Type de claustra : "" (aucun) | "vertical" | "horizontal" |
                               "lattage". Option native du configurateur WAPF (field-5219ffc).
                               ⚠ NE PAS ajouter les claustras en produits_complementaires.
                               Le bardage (panneau plein) est un produit séparé → utiliser produits_complementaires.
        nb_claustra          : Nombre de modules claustra (1 module = 1m de large).
                               Ex : pergola 4m → nb_claustra=4 pour remplir un côté.
        sur_mesure           : True pour activer la configuration sur-mesure (+199,90€)
                               Choisir largeur/profondeur = variation standard >= dimensions souhaitées
        largeur_hors_tout    : Largeur réelle hors-tout en mètres (ex: "7.60")
                               Obligatoire si sur_mesure=True
        profondeur_hors_tout : Profondeur réelle hors-tout en mètres (ex: "3.42")
        hauteur_hors_tout    : Hauteur hors-tout en mètres (max 3.07m, ex: "2.50")
        client_*             : coordonnées client
        mode_livraison       : "" (ne pas changer) | "retrait" (retrait atelier Illies)
                               | "livraison" (livraison à domicile, ~99€)
        produits_complementaires : JSON array de produits supplémentaires à ajouter au même panier.
                               Utiliser d'abord rechercher_produits_detail pour obtenir url/variation_id.
                               Format : [{"url": "...", "variation_id": 123, "quantite": 2,
                                          "attribut_selects": {}, "description": "..."}]
        configurations_supplementaires : JSON array de configs supplémentaires. Chaque élément
                               est un dict avec les mêmes clés : {"largeur": "5m", "profondeur": "3m",
                               "fixation": "independante", "ventelle": "largeur", "option": "non", ...}
                               Permet de mettre plusieurs pergolas sur le même devis PDF.

    Returns:
        JSON avec chemin du PDF et métadonnées.
    """
    return await _generer_direct("pergola", {
        "largeur": largeur, "profondeur": profondeur, "fixation": fixation,
        "ventelle": ventelle, "option": option,
        "poteau_lamelle_colle": poteau_lamelle_colle,
        "nb_poteaux_lamelle_colle": nb_poteaux_lamelle_colle,
        "claustra_type": claustra_type, "nb_claustra": nb_claustra,
        "sur_mesure": sur_mesure, "largeur_hors_tout": largeur_hors_tout,
        "profondeur_hors_tout": profondeur_hors_tout, "hauteur_hors_tout": hauteur_hors_tout,
        "client_nom": client_nom, "client_prenom": client_prenom,
        "client_email": client_email, "client_telephone": client_telephone,
        "client_adresse": client_adresse, "code_promo": code_promo,
        "mode_livraison": mode_livraison, "produits_complementaires": produits_complementaires,
        "configurations_supplementaires": configurations_supplementaires,
    }, client_prenom, client_nom)


@mcp.tool()
async def generer_devis_terrasse_bois(
    essence: str,
    longueur: str,
    quantite: int = 1,
    lambourdes: str = "",
    lambourdes_longueur: str = "",
    plots: str = "NON",
    visserie: str = "",
    densite_lambourdes: str = "simple",
    nb_lames: int = 0,
    nb_lambourdes: int = 0,
    client_nom: str = "",
    client_prenom: str = "",
    client_email: str = "",
    client_telephone: str = "",
    client_adresse: str = "",
    code_promo: str = "",
    mode_livraison: str = "",
    produits_complementaires: str = "[]",
    configurations_supplementaires: str = "[]",
) -> str:
    """Génère un devis terrasse bois sur terrasseenbois.fr (formulaire WAPF).

    Args:
        essence  : Type de bois. Valeurs :
            "PIN 21mm Autoclave Vert" | "PIN 27mm Autoclave Vert" |
            "PIN 27mm Autoclave Marron" | "PIN 27mm Autoclave Gris" |
            "PIN 27mm Thermotraité" | "FRAKE" | "JATOBA" | "CUMARU" |
            "PADOUK" | "IPE"
        longueur : Longueur des lames (selon essence) :
            IPE/PADOUK  : "0.95", "1.25"
            CUMARU/JATOBA/FRAKE: "1.25", "1.85", "2.15", "3.05", "3.65"
            PIN 21mm Vert  : "3.3", "4.2", "5.1"
            PIN 27mm Vert  : "2.4", "2.75", "3.3", "3.9", "4.2", "4.5", "4.8", "5.1"
            PIN 27mm Marron: "3", "3.3", "3.6", "4.2", "4.8", "5.1", "5.4"
        quantite         : Nombre de m² (défaut 1). Ignoré si nb_lames ou nb_lambourdes fournis.
        lambourdes       : "" (aucune) | "Pin autoclave Vert 45x70" |
                           "Pin autoclave Vert 45x145" | "Bois exotique Niove 40x60"
        lambourdes_longueur : Longueur des lambourdes (dépend du type) :
            Pin 45x70/45x145 : "3", "4.2", "4.8", "5.1"
            Niove 40x60      : "1.55", "1.85", "2.15", "3.05", "3.65"
        plots            : Hauteur des plots réglables :
            "2 à 4 cm" | "4 à 6 cm" | "6 à 9 cm" | "9 à 15 cm" |
            "15 à 26 cm" | "NON" (défaut)
        visserie         : "" (aucune) | "Vis Inox 5x50mm" | "Vis Inox 5x60mm" |
                           "Fixations invisible Hapax"
        densite_lambourdes : "simple" (défaut) | "double"
        nb_lames         : Nombre exact de lames souhaité (ex: 70). Si fourni avec
                           nb_lambourdes, calcule automatiquement le split en 2 lignes
                           de panier (item1 = lambourdes+plots, item2 = lames seules).
        nb_lambourdes    : Nombre exact de lambourdes souhaité (ex: 25). Calcule
                           automatiquement le m² correspondant.
        client_*         : coordonnées client
        mode_livraison   : "" (ne pas changer) | "retrait" (retrait atelier Illies)
                           | "livraison" (livraison à domicile, ~99€)
        produits_complementaires : JSON array de produits supplémentaires à ajouter au même panier.
                           Utiliser d'abord rechercher_produits_detail pour obtenir url/variation_id.
                           Format : [{"url": "...", "variation_id": 123, "quantite": 2,
                                      "attribut_selects": {}, "description": "..."}]
        configurations_supplementaires : JSON array de configs supplémentaires. Chaque élément
                           est un dict avec les mêmes clés : {"essence": "...", "longueur": "...",
                           "quantite": N, "lambourdes": "...", ...}
                           Permet de mettre plusieurs terrasses sur le même devis PDF.

    Returns:
        JSON avec chemin du PDF et métadonnées.
    """
    return await _generer_direct("terrasse", {
        "essence": essence, "longueur": longueur, "quantite": quantite,
        "lambourdes": lambourdes, "lambourdes_longueur": lambourdes_longueur,
        "plots": plots, "visserie": visserie, "densite_lambourdes": densite_lambourdes,
        "nb_lames": nb_lames, "nb_lambourdes": nb_lambourdes,
        "client_nom": client_nom, "client_prenom": client_prenom,
        "client_email": client_email, "client_telephone": client_telephone,
        "client_adresse": client_adresse, "code_promo": code_promo,
        "mode_livraison": mode_livraison, "produits_complementaires": produits_complementaires,
        "configurations_supplementaires": configurations_supplementaires,
    }, client_prenom, client_nom)


@mcp.tool()
async def generer_devis_terrasse_bois_detail(
    produits: str,
    client_nom: str = "",
    client_prenom: str = "",
    client_email: str = "",
    client_telephone: str = "",
    client_adresse: str = "",
    code_promo: str = "",
    mode_livraison: str = "",
) -> str:
    """Génère un devis terrasse bois en ajoutant des produits au détail SANS configurateur WAPF.

    Utile pour commander des quantités exactes de lames, lambourdes, plots et visserie
    directement depuis le catalogue au détail de terrasseenbois.fr.

    Args:
        produits : JSON array de produits à ajouter au panier.
                   Utiliser d'abord rechercher_produits_detail(site="terrasse") pour obtenir
                   url, variation_id et attribut_selects.
                   Format : [
                     {"url": "https://www.terrasseenbois.fr/produit/choisissez-vos-lames-de-terrasse-en-cumaru/",
                      "variation_id": 89495, "quantite": 70,
                      "attribut_selects": {"attribute_pa_longueur_de_lame": "3-05-m"},
                      "description": "70 lames Cumaru 3,05m"},
                     {"url": "https://www.terrasseenbois.fr/produit/choisissez-vos-lambourdes-de-terrasse-exotique-niove-40x60-mm/",
                      "variation_id": 89624, "quantite": 25,
                      "attribut_selects": {"attribute_pa_longueur_de_lambourdes": "3-05-m"},
                      "description": "25 lambourdes Niove 40x60 3,05m"},
                     {"url": "https://www.terrasseenbois.fr/produit/choisissez-vos-plots-plastiques-reglables/",
                      "variation_id": 89681, "quantite": 150,
                      "attribut_selects": {"attribute_pa_hauteur_de_plots": "6-a-9-cm"},
                      "description": "150 plots réglables 6-9cm"}
                   ]
        client_*       : coordonnées client
        code_promo     : ex "LEROYMERLIN10" (-10% terrasse)
        mode_livraison : "" (ne pas changer) | "retrait" | "livraison" (~99€)

    Returns:
        JSON avec chemin du PDF et métadonnées.
    """
    return await _generer_direct("terrasse_detail", {
        "produits": json.loads(produits) if isinstance(produits, str) else produits,
        "client_nom": client_nom, "client_prenom": client_prenom,
        "client_email": client_email, "client_telephone": client_telephone,
        "client_adresse": client_adresse, "code_promo": code_promo,
        "mode_livraison": mode_livraison,
    }, client_prenom, client_nom)


@mcp.tool()
async def generer_devis_cloture_bois(
    modele: str,
    longeur: str,
    hauteur: str,
    bardage: str,
    fixation_sol: str,
    type_poteaux: str = "",
    longueur_lames: str = "",
    sens_bardage: str = "vertical",
    recto_verso: str = "non",
    client_nom: str = "",
    client_prenom: str = "",
    client_email: str = "",
    client_telephone: str = "",
    client_adresse: str = "",
    code_promo: str = "",
    mode_livraison: str = "",
    produits_complementaires: str = "[]",
    configurations_supplementaires: str = "[]",
) -> str:
    """Génère un devis kit clôture bois sur cloturebois.fr.

    Args:
        modele  : "classique" | "moderne"

        Kit classique (productId=18393) :
            longeur      : "4" | "10" | "20" | "30" | "40" (mètres linéaires)
            hauteur      : "1-9" (= 1.9m, seule option disponible)
            bardage      : "27x130" | "27x130-gris"
            fixation_sol : "plots-beton"
            type_poteaux : "90x90-h" | "metal7016"
            longueur_lames: "2-m"

        Kit moderne (productId=17434) :
            longeur      : "5" | "10" | "20" | "30" | "40"
            hauteur      : "0-9" (0.9m) | "1-9" (1.9m) | "2-3" (2.3m)
            bardage      : "20x60" | "20x70-brun" | "20x70-gris" | "20x70-noir" |
                           "21x130" | "21x145" | "45x45-esp0-015m" | "45x45-esp0-045m"
            fixation_sol : "plots-beton" | "pieds-galvanises-en-h"
            sens_bardage : "horizontal" | "vertical"
            recto_verso  : "non" | "oui"

        client_* : coordonnées client
        mode_livraison : "" (ne pas changer) | "retrait" (retrait atelier Illies)
                         | "livraison" (livraison à domicile, ~99€)
        produits_complementaires : JSON array de produits supplémentaires à ajouter au même panier.
                         Utiliser d'abord rechercher_produits_detail pour obtenir url/variation_id.
                         Format : [{"url": "...", "variation_id": 123, "quantite": 2,
                                    "attribut_selects": {}, "description": "..."}]
        configurations_supplementaires : JSON array de configs supplémentaires. Chaque élément
                         est un dict avec les mêmes clés : {"modele": "moderne", "longeur": "10",
                         "hauteur": "1-9", "bardage": "21x145", ...}
                         Permet de mettre plusieurs clôtures sur le même devis PDF.

    Returns:
        JSON avec chemin du PDF et métadonnées.
    """
    return await _generer_direct("cloture", {
        "modele": modele, "longeur": longeur, "hauteur": hauteur,
        "bardage": bardage, "fixation_sol": fixation_sol,
        "type_poteaux": type_poteaux, "longueur_lames": longueur_lames,
        "sens_bardage": sens_bardage, "recto_verso": recto_verso,
        "client_nom": client_nom, "client_prenom": client_prenom,
        "client_email": client_email, "client_telephone": client_telephone,
        "client_adresse": client_adresse, "code_promo": code_promo,
        "mode_livraison": mode_livraison, "produits_complementaires": produits_complementaires,
        "configurations_supplementaires": configurations_supplementaires,
    }, client_prenom, client_nom)


@mcp.tool()
async def generer_devis(
    site: str,
    largeur: str,
    profondeur: str,
    client_nom: str,
    client_prenom: str,
    client_email: str,
    client_telephone: str,
    client_adresse: str,
    ouvertures: str = "[]",
    extension_toiture: str = "",
    plancher: str = "",
    bac_acier: bool = False,
    menuiseries: str = "[]",
    bardage_exterieur: str = "",
    isolation: str = "",
    rehausse: bool = False,
    bardage_interieur: str = "",
    finition_plancher: bool = False,
    terrasse: str = "",
    pergola: str = "",
    produits_complementaires: str = "[]",
    code_promo: str = "",
    produits_uniquement: bool = False,
    configurations_supplementaires: str = "[]",
) -> str:
    """Génère un devis PDF complet pour un produit configuré sur le site web.

    Le script Playwright ouvre un navigateur Chrome, configure le produit
    sur le configurateur web, ajoute au panier avec les images de configuration,
    puis génère et télécharge le devis PDF.

    Args:
        site: Site configurateur. Valeurs :
            - "abri" — Abri de jardin bois (abri-français.fr)
            - "studio" — Studio de jardin (studio-français.fr)
        largeur: Largeur du produit.
            Abri : "4,35M", "5,50M", etc. (texte après "Largeur ")
            Studio : "4,4", "5,5", "6,6", etc. (mètres sans unité)
        profondeur: Profondeur du produit.
            Abri : "4,35m", "2,15m", etc. (texte après "Profondeur ", m minuscule)
            Studio : "3,5", "4,6", "5,7", etc. (mètres sans unité)
        client_nom: Nom de famille du client
        client_prenom: Prénom du client
        client_email: Adresse email du client
        client_telephone: Numéro de téléphone du client
        client_adresse: Adresse postale complète du client
        ouvertures: (ABRI uniquement) JSON array des ouvertures. Chaque élément :
            {"type": "...", "face": "...", "position": "..."}
            Types : "Porte Vitrée", "Porte Pleine", "Porte double Vitrée",
                    "Porte double Pleine", "Fenêtre Horizontale", "Fenêtre Verticale"
            Faces : "Face 1", "Face 2", "Droite", "Gauche", "Fond 1", "Fond 2"
            Positions : "Centre", "Gauche", "Droite"
            IMPORTANT : ne pas superposer plusieurs ouvertures sur le même mur.
        extension_toiture: (ABRI) "" ou "Droite 1 M", "Gauche 2 M", etc.
        plancher: (ABRI) "true"/"false" pour plancher. (STUDIO) "Sans plancher",
            "Plancher standard", "Plancher RE2020", "Plancher porteur"
        bac_acier: (ABRI) True pour bac acier anti-condensation
        menuiseries: (STUDIO uniquement) JSON array des menuiseries. Chaque élément :
            {"type": "...", "materiau": "...", "mur": "...", "position": "..."}
            Types : "PORTE VITREE", "FENETRE SIMPLE", "FENETRE DOUBLE",
                    "BAIE VITREE", "PORTE DOUBLE VITREE"
            Matériaux : "PVC", "ALU"
            Murs : "MUR DE FACE", "MUR DE GAUCHE", "MUR DE DROITE", "MUR DU FOND"
            Positions : valeurs numériques d'offset (ex: "0,24", "1,1", "2,2", "3,3")
        bardage_exterieur: (STUDIO) "Gris", "Brun", "Noir", "Vert"
        isolation: (STUDIO) "60mm" ou "100 mm (RE2020)"
        rehausse: (STUDIO) True pour rehausse hauteur 3,20m
        bardage_interieur: (STUDIO) "OSB" ou "Panneaux bois massif (3 plis épicéa)"
        finition_plancher: (STUDIO) True pour finition plancher
        terrasse: (STUDIO) "" (aucune), "2m (11m2)", "4m (22m2)"
        pergola: (STUDIO) "" (aucune), "4x2m (8m2)", "4x4m (16m2)"
        produits_complementaires: JSON array de produits supplémentaires à ajouter au MÊME panier.
            Utilise d'abord rechercher_produits_detail pour trouver les ids et urls.
            Format : [
                {
                    "url": "https://www.xn--abri-franais-sdb.fr/produit/planche.../",
                    "variation_id": 53609,
                    "quantite": 16,
                    "attribut_selects": {"attribute_pa_longueur": "2"},
                    "description": "16 planches 27×130mm 2m"
                }
            ]
            Les produits sont ajoutés après le configurateur principal (abri/studio).
            ⚠ Les "url" doivent correspondre au même domaine que "site" (ex: abri → abri-francais.fr).

            CAS FRÉQUENTS :
            - Cloison studio     : rechercher_produits_detail(site="studio", recherche="cloison") → ID=5766, 60€/ml
            - Bac acier abri     : option directe bac_acier=True (pas besoin de produits_complementaires)
            - 2 abris accolés    : configurer le 1er abri normalement, puis rechercher_produits_detail(site="abri",
                                   recherche="[dimensions 2ème abri]") pour trouver le modèle préconçu du 2ème
                                   et l'ajouter ici → les 2 abris apparaissent sur le même devis PDF
            - Gamme Essentiel    : utiliser produits_uniquement=True + rechercher_produits_detail(site="abri",
                                   recherche="essentiel [options]") → trouver url + variation_id → passer
                                   en produits_complementaires. Le PDF ne contiendra QUE le modèle préconçu.
        produits_uniquement: (ABRI uniquement) True pour générer un devis avec UNIQUEMENT les
            produits_complementaires, SANS passer par le configurateur WPC. Utilisé pour les
            modèles préconçus (Gamme Essentiel, Haut de Gamme) qui sont des produits WooCommerce
            simples. Les paramètres largeur/profondeur/ouvertures sont ignorés dans ce mode.
            ⚠ Nécessite au moins 1 produit dans produits_complementaires.
        configurations_supplementaires: JSON array de configurations supplémentaires à ajouter
            au MÊME devis PDF. Chaque élément est un dict avec les mêmes clés que la config
            principale. Permet de mettre plusieurs produits personnalisés (ex: 2 abris Gamme Origine)
            sur le même devis.

            ABRI : [{"largeur": "4,70M", "profondeur": "3,45m",
                     "ouvertures": [{"type": "...", "face": "...", "position": "..."}],
                     "extension_toiture": "Gauche 3,5 M", "plancher": false, "bac_acier": true}]
            STUDIO : [{"largeur": "3,3", "profondeur": "3,5",
                       "menuiseries": [...], "bardage_exterieur": "Gris", ...}]

            Le script configure le premier produit, l'ajoute au panier, puis navigue à nouveau
            vers le configurateur pour chaque config supplémentaire. Les produits_complementaires
            sont ajoutés après tous les produits configurés.

    Returns:
        JSON avec le chemin du PDF généré et les métadonnées.
    """
    # Parser produits_complementaires
    try:
        produits_list = json.loads(produits_complementaires) if isinstance(produits_complementaires, str) else produits_complementaires
        if not isinstance(produits_list, list):
            produits_list = []
    except (json.JSONDecodeError, TypeError):
        produits_list = []

    # Parser configurations_supplementaires
    try:
        configs_sup = json.loads(configurations_supplementaires) if isinstance(configurations_supplementaires, str) else configurations_supplementaires
        if not isinstance(configs_sup, list):
            configs_sup = []
    except (json.JSONDecodeError, TypeError):
        configs_sup = []

    try:
        if site == "studio":
            # Parser les menuiseries
            try:
                menuiseries_list = json.loads(menuiseries) if isinstance(menuiseries, str) else menuiseries
            except json.JSONDecodeError:
                return json.dumps({
                    "success": False,
                    "error": f"Format menuiseries invalide. Attendu : JSON array. Reçu : {menuiseries[:100]}"
                })

            params = {
                "largeur": largeur,
                "profondeur": profondeur,
                "menuiseries": menuiseries_list,
                "client_nom": client_nom,
                "client_prenom": client_prenom,
                "client_email": client_email,
                "client_telephone": client_telephone,
                "client_adresse": client_adresse,
                "bardage_exterieur": bardage_exterieur or "Gris",
                "isolation": isolation or "60mm",
                "rehausse": rehausse,
                "bardage_interieur": bardage_interieur or "OSB",
                "plancher": plancher or "Sans plancher",
                "finition_plancher": finition_plancher,
                "terrasse": terrasse,
                "pergola": pergola,
                "produits_complementaires": produits_list,
                "code_promo": code_promo,
                "configurations_supplementaires": configs_sup,
            }

        else:  # abri
            # Parser les ouvertures (JSON string → list)
            try:
                ouvertures_list = json.loads(ouvertures) if isinstance(ouvertures, str) else ouvertures
            except json.JSONDecodeError:
                return json.dumps({
                    "success": False,
                    "error": f"Format ouvertures invalide. Attendu : JSON array. Reçu : {ouvertures[:100]}"
                })

            # Convertir plancher string → bool pour abri
            plancher_bool = plancher.lower() in ("true", "oui", "1") if isinstance(plancher, str) else bool(plancher)

            params = {
                "largeur": largeur,
                "profondeur": profondeur,
                "ouvertures": ouvertures_list,
                "client_nom": client_nom,
                "client_prenom": client_prenom,
                "client_email": client_email,
                "client_telephone": client_telephone,
                "client_adresse": client_adresse,
                "extension_toiture": extension_toiture,
                "plancher": plancher_bool,
                "bac_acier": bac_acier,
                "produits_complementaires": produits_list,
                "code_promo": code_promo,
                "produits_uniquement": produits_uniquement,
                "configurations_supplementaires": configs_sup,
            }

        return await _generer_direct(site, params, client_prenom, client_nom)

    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e),
            "message": f"Échec de la génération du devis : {e}",
        })


# ═══════════════════════════════════════════════════════════════
# OUTIL : LISTER LES SITES DISPONIBLES
# ═══════════════════════════════════════════════════════════════

@mcp.tool()
def lister_sites() -> str:
    """Liste les sites configurateurs disponibles et leurs options.

    Retourne un JSON avec tous les sites, les dimensions disponibles,
    les types d'ouvertures, et les options pour chaque produit.
    Utilise cet outil au début pour connaître les options disponibles
    avant de configurer un devis.
    """
    sites = {
        "abri": {
            "nom": "Abri de jardin bois — Gamme Origine (toit plat)",
            "url": "https://www.xn--abri-franais-sdb.fr",
            "statut": "fonctionnel",
            "note_gammes": "Ce configurateur génère la Gamme Origine (toit plat, 1600-6120€, promo LEROYMERLIN10 -10%). Pour la Gamme Essentiel (toit 2 pentes, 1190-2120€, promo LEROYMERLIN5 -5%) : utiliser produits_uniquement=True + rechercher_produits_detail(site='abri', recherche='essentiel [options]') → passer le résultat en produits_complementaires. Le PDF ne contiendra que le modèle préconçu.",
            "dimensions": {
                "largeurs": ["2,15M", "2,65M", "3,45M", "4,20M", "4,35M",
                             "4,70M", "5,20M", "5,50M", "6,00M", "6,80M",
                             "6,40M", "6,90M", "7,70M", "8,60M"],
                "profondeurs": ["2,15m", "2,65m", "3,45m", "4,35m"],
                "note": "Toutes les combinaisons largeur × profondeur ne sont pas disponibles."
            },
            "ouvertures": [
                {"type": "Porte Vitrée", "description": "Porte simple vitrée, vitrage polycarbonate"},
                {"type": "Porte Pleine", "description": "Porte simple pleine bois"},
                {"type": "Porte double Vitrée", "description": "Porte 2 vantaux vitrée, vitrage polycarbonate"},
                {"type": "Porte double Pleine", "description": "Porte 2 vantaux pleine bois"},
                {"type": "Fenêtre Horizontale", "description": "Fenêtre bandeau horizontale"},
                {"type": "Fenêtre Verticale", "description": "Fenêtre haute verticale"},
            ],
            "faces": ["Face 1 (façade)", "Face 2 (façade multi-pan)", "Droite", "Gauche", "Fond 1", "Fond 2 (fond multi-pan)"],
            "positions": ["Centre", "Gauche", "Droite"],
            "regles_positions": "Les positions Gauche/Droite ne sont disponibles que si le mur est assez large. Sur un mur étroit (ex: profondeur 2,15m), seul Centre est disponible. Les portes doubles prennent plus de place et n'ont souvent que Centre sur les murs latéraux.",
            "options": {
                "extension_toiture": "Droite/Gauche + 1 M / 1,5 M / 2 M / 3,5 M",
                "plancher": "OUI/NON",
                "bac_acier": "Bac acier anti-condensation (recommandé)",
            },
        },
        "pergola": {
            "nom": "Pergola Bois En Kit",
            "url": "https://mapergolabois.fr",
            "configurateur": "https://mapergolabois.fr/produit/pergola-bois-en-kit",
            "statut": "fonctionnel",
            "outil_mcp": "generer_devis_pergola_bois",
            "type": "WooCommerce variable product (productId=16046)",
            "attributs": {
                "largeur":    ["2m","3m","4m","5m","6m","7m","8m","9m","10m"],
                "profondeur": ["2m","3m","4m","5m"],
                "fixation":   ["adossee","independante"],
                "ventelle":   ["largeur","profondeur","retro","sans"],
                "option":     ["non","platelage","voilage","bioclimatique","carport","lattage","polycarbonate"],
            },
            "options_wapf": {
                "sur_mesure": "True pour dimensions intermédiaires (+199,90€). Sélectionner variation standard >= dimensions souhaitées.",
                "largeur_hors_tout": "Largeur réelle en m (ex: '7.60'). Obligatoire si sur_mesure=True.",
                "profondeur_hors_tout": "Profondeur réelle en m (ex: '3.42').",
                "hauteur_hors_tout": "Hauteur réelle en m (max 3.07m).",
                "poteau_lamelle_colle": "True pour poteaux bois lamellé-collé. Quantité calculée automatiquement depuis la description de la variation.",
            },
            "prix_depart": "1 180 € (+ 199,90€ pour sur-mesure)",
            "pieds_reglables": "Ajustables de 12 à 18 cm pour s'adapter au terrain",
            "portee_max": "5m sans poteau intermédiaire — au-delà, poteau central livré avec le kit",
        },
        "studio": {
            "nom": "Studio de jardin — Studio Français",
            "url": "https://studio-français.fr",
            "statut": "fonctionnel",
            "dimensions": {
                "combinaisons": [
                    "2,2x2,4", "3,3x2,4", "2,2x3,5", "4,4x2,4", "2,2x4,6",
                    "3,3x3,5", "5,5x2,4", "3,3x4,6", "2,2x5,7", "4,4x3,5",
                    "6,6x2,4", "5,5x3,5", "3,3x5,7", "7,7x2,4", "4,4x4,6",
                    "5,5x4,6", "6,6x3,5", "8,8x2,4", "4,4x5,7", "7,7x3,5",
                    "5,5x5,7", "6,6x4,6", "8,8x3,5", "7,7x4,6", "6,6x5,7",
                    "8,8x4,6", "7,7x5,7", "8,8x5,7",
                ],
                "format": "largeur,profondeur en mètres (ex: 4,4x3,5 = 4,4m x 3,5m)",
                "note": "1 URL produit par dimension. Le configurateur s'ouvre directement avec le modèle."
            },
            "menuiseries": [
                {"type": "PORTE VITREE", "description": "Porte vitrée simple"},
                {"type": "FENETRE SIMPLE", "description": "Fenêtre simple"},
                {"type": "FENETRE DOUBLE", "description": "Fenêtre double"},
                {"type": "BAIE VITREE", "description": "Baie vitrée coulissante"},
                {"type": "PORTE DOUBLE VITREE", "description": "Porte double vitrée"},
            ],
            "materiaux": ["PVC", "ALU"],
            "murs": ["MUR DE FACE", "MUR DE GAUCHE", "MUR DE DROITE", "MUR DU FOND"],
            "positions_note": "Chaque menuiserie occupe un module de 1,10 m. position: 'gauche'/'auto' (1er module libre depuis l'angle), 'droite' (dernier libre), 'centre' (module central libre), ou offset exact ex: '1,29'. Anti-chevauchement automatique.",
            "materiaux_note": "BAIE VITREE et PORTE DOUBLE VITREE = ALU uniquement.",
            "options": {
                "bardage_exterieur": ["Gris", "Brun", "Noir", "Vert"],
                "isolation": ["60mm", "100 mm (RE2020)"],
                "rehausse": "OUI/NON (hauteur 3,20m au lieu de 2,50m)",
                "bardage_interieur": ["OSB", "Panneaux bois massif (3 plis épicéa)"],
                "plancher": ["Sans plancher", "Plancher standard", "Plancher RE2020", "Plancher porteur"],
                "finition_plancher": "OUI/NON",
                "terrasse": ["(aucune)", "2m (11m2)", "4m (22m2)"],
                "pergola": ["(aucune)", "4x2m (8m2)", "4x4m (16m2)"],
            },
        },
        "terrasse": {
            "nom": "Configurateur Terrasse Bois",
            "url": "https://terrasseenbois.fr",
            "configurateur": "https://terrasseenbois.fr/produit/configurateur-terrasse/",
            "statut": "fonctionnel",
            "outil_mcp": "generer_devis_terrasse_bois",
            "type": "WooCommerce simple + WAPF (productId=57595)",
            "essences": [
                "PIN 21mm Autoclave Vert",
                "PIN 27mm Autoclave Vert",
                "PIN 27mm Autoclave Marron",
                "PIN 27mm Autoclave Gris",
                "PIN 27mm Thermotraité",
                "FRAKE", "JATOBA", "CUMARU", "PADOUK", "IPE",
            ],
            "longueurs_par_essence": {
                "IPE": ["0.95", "1.25"],
                "PADOUK": ["0.95", "1.25"],
                "CUMARU": ["1.25", "1.85", "2.15", "3.05", "3.65"],
                "JATOBA": ["1.25", "1.85", "2.15", "3.05", "3.65"],
                "FRAKE": ["1.25", "1.85", "2.15", "3.05", "3.65"],
                "PIN 21mm Autoclave Vert": ["3.3", "4.2", "5.1"],
                "PIN 27mm Autoclave Vert": ["2.4", "2.75", "3.3", "3.9", "4.2", "4.5", "4.8", "5.1"],
                "PIN 27mm Autoclave Marron": ["3", "3.3", "3.6", "4.2", "4.8", "5.1", "5.4"],
            },
            "lambourdes": [
                "Pin autoclave Vert 45x70",
                "Pin autoclave Vert 45x145",
                "Bois exotique Niove 40x60",
            ],
            "lambourdes_longueurs": {
                "Pin 45x70 / Pin 45x145": ["3", "4.2", "4.8", "5.1"],
                "Bois exotique Niove 40x60": ["1.55", "1.85", "2.15", "3.05", "3.65"],
            },
            "plots": ["2 à 4 cm", "4 à 6 cm", "6 à 9 cm", "9 à 15 cm", "15 à 26 cm", "NON"],
            "visserie": ["Vis Inox 5x50mm", "Vis Inox 5x60mm", "Fixations invisible Hapax", "Non"],
            "densite_lambourdes": ["simple", "double"],
            "kits_preconçus": "En plus du configurateur WAPF, des kits préconçus WooCommerce sont disponibles (surfaces fixes : 10/20/40/60/80 m²). Types : lame / kit (lames+lambourdes) / kit-complet (avec visserie). Utiliser rechercher_produits_detail(site='terrasse', recherche='[essence]') pour les trouver.",
        },
        "cloture_classique": {
            "nom": "Kit Clôture Bois Classique",
            "url": "https://cloturebois.fr",
            "configurateur": "https://cloturebois.fr/produit/kit-cloture-bois-classique/",
            "statut": "fonctionnel",
            "outil_mcp": "generer_devis_cloture_bois",
            "modele": "classique",
            "type": "WooCommerce variable product (productId=18393)",
            "attributs": {
                "longeur":       ["4","10","20","30","40"],
                "hauteur":       ["1-9 (=1.9m)"],
                "bardage":       ["27x130","27x130-gris"],
                "type_poteaux":  ["90x90-h","metal7016"],
                "longueur_lames":["2-m"],
                "fixation_sol":  ["plots-beton"],
            },
            "prix_depart": "729,90 €",
        },
        "cloture_moderne": {
            "nom": "Kit Clôture Bois Moderne",
            "url": "https://cloturebois.fr",
            "configurateur": "https://cloturebois.fr/produit/kit-cloture-bois-moderne/",
            "statut": "fonctionnel",
            "outil_mcp": "generer_devis_cloture_bois",
            "modele": "moderne",
            "type": "WooCommerce variable product (productId=17434, 959 variations)",
            "attributs": {
                "longeur":       ["5","10","20","30","40"],
                "hauteur":       ["0-9 (0.9m)","1-9 (1.9m)","2-3 (2.3m)"],
                "bardage":       ["20x60","20x70-brun","20x70-gris","20x70-noir",
                                  "21x130","21x145","45x45-esp0-015m","45x45-esp0-045m"],
                "sens_bardage":  ["horizontal","vertical"],
                "recto_verso":   ["non","oui"],
                "fixation_sol":  ["plots-beton","pieds-galvanises-en-h"],
            },
            "prix_depart": "639,90 €",
        },
    }
    return json.dumps(sites, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════
# OUTIL : LISTER LES DEVIS GÉNÉRÉS
# ═══════════════════════════════════════════════════════════════

@mcp.tool()
def lister_devis_generes() -> str:
    """Liste les devis PDF déjà générés dans le dossier de téléchargement.

    Combine deux sources :
    1. Le log JSON (~/Downloads/devis_log.json) — métadonnées riches (client, type, date)
    2. Scan ~/Downloads/devis_*.pdf — pour les devis non loggés ou anciens

    Utile pour retrouver un devis récemment généré ou vérifier les devis existants.
    """
    download_dir = os.path.expanduser("~/Downloads")
    devis = []

    # Source 1 : log JSON (métadonnées riches)
    if os.path.exists(_DEVIS_LOG_FILE):
        try:
            with open(_DEVIS_LOG_FILE, "r", encoding="utf-8") as f:
                log = json.load(f)
            for entry in log[:20]:
                if os.path.exists(entry.get("filepath", "")):
                    devis.append(entry)
        except Exception:
            pass

    # Source 2 : scan ~/Downloads pour les devis non loggés
    logged_filenames = {d.get("filename") for d in devis}
    for f in sorted(Path(download_dir).glob("devis_*.pdf"), reverse=True):
        if f.name not in logged_filenames:
            stat = f.stat()
            devis.append({
                "date": datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                "type": "inconnu",
                "client": "",
                "filepath": str(f),
                "filename": f.name,
                "size_kb": round(stat.st_size / 1024, 1),
            })
        if len(devis) >= 30:
            break

    return json.dumps({
        "devis": devis[:20],
        "total": len(devis),
        "dossier": download_dir,
        "log_json": _DEVIS_LOG_FILE,
    }, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════════
# POINT D'ENTRÉE
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    mcp.run(transport="stdio")
