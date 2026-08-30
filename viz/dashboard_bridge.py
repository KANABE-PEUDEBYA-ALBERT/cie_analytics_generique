"""
Déclaration du pont Streamlit Components pour le Tableau de bord.

`components.declare_component()` DOIT être appelé une seule fois, au niveau
module, dans un module importé normalement (`import ...`) — jamais dans le
code d'une page exécutée via `st.navigation()` / `page.run()`, qui utilise
`exec(code, module.__dict__)` en interne. Cet `exec` casse l'introspection
de frame que `declare_component()` utilise pour deviner le nom du module
appelant, provoquant un crash :

    RuntimeError: module is None. This should never happen.
    File ".../streamlit/components/v1/component_registry.py", line 38,
    in _get_module_name

Isoler la déclaration ici, dans un module chargé via un `import` classique
(voir 11_Tableau_de_Bord.py), contourne le problème : Python peuple
correctement `__name__`/`__spec__` pour un module importé normalement,
contrairement au code exec'd d'une page Streamlit multi-pages.
"""
from __future__ import annotations

from pathlib import Path

import streamlit.components.v1 as components

COMPONENT_DIR = Path(__file__).resolve().parent.parent / "assets" / "dashboard_component"
COMPONENT_DIR.mkdir(exist_ok=True)

dashboard_bridge = components.declare_component("cie_dashboard_bridge", path=str(COMPONENT_DIR))
