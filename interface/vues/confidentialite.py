# -*- coding: utf-8 -*-
"""Onglet CONFIDENTIALITÉ : mentions d'information (art. 13 RGPD) et mesures appliquées."""
from __future__ import annotations

import streamlit as st

from orchestre import stockage as DB
from vues import commun as C

NOTICE = """
### Information des patients — programmation du bloc opératoire

**Responsable du traitement** : [établissement de santé — à compléter], représenté par son directeur.
**Délégué à la protection des données (DPO)** : [adresse de contact — à compléter].

**Finalité** : organiser votre intervention chirurgicale (choix de la date, de l'heure et de la salle d'opération,
anticipation du lit ou de la place en ambulatoire), et réorganiser le programme en cas d'urgence ou d'incident.
Un outil d'aide à la décision estime la durée de l'intervention et du séjour ; **la décision reste celle de votre
chirurgien**, qui valide ou corrige ces estimations. Aucune décision n'est prise de façon entièrement automatisée.

**Base légale** : exécution d'une mission d'intérêt public / prise en charge sanitaire (art. 6.1.e et 9.2.h du RGPD).

**Données utilisées** : âge, sexe, diagnostic et acte prévus (codes CIM-10 et CCAM), type d'anesthésie, chirurgien,
date au plus tôt de l'intervention. Vous êtes identifié(e) dans l'outil par un pseudonyme ; votre nom n'y figure pas.

**Destinataires** : l'équipe du bloc opératoire (chirurgiens, cadre de bloc / régulation) habilitée.

**Durée de conservation** : {duree} jours après l'intervention, puis suppression automatique. Votre dossier médical
reste conservé dans le dossier patient de l'établissement selon les règles habituelles.

**Vos droits** : accès, rectification, effacement, limitation et opposition, auprès du DPO. Vous pouvez introduire
une réclamation auprès de la CNIL (www.cnil.fr).
"""

MESURES = """
| Principe (RGPD / CNIL) | Mise en œuvre dans OR'CHESTRE |
|---|---|
| Minimisation | Âge au lieu de la date de naissance ; ni nom ni prénom ; les CIM/CCAM associés (non utilisés par le modèle) ne sont pas collectés. |
| Pseudonymisation | Pseudonyme PAT-AA-NNNN partout ; référence de dossier facultative **chiffrée** (Fernet) avec une clé hors base. |
| Contrôle d'accès | Comptes nominatifs, rôles (chirurgien / régulation / administrateur), mots de passe robustes hachés (PBKDF2-SHA256), déconnexion après 15 min d'inactivité, blocage après 5 échecs. |
| Traçabilité | Journal des connexions, consultations, déchiffrements, exports, suppressions (conservé 6 mois). |
| Durée de conservation | Purge automatique N jours après l'intervention (paramétrable). |
| Droits des personnes | Export JSON (accès / portabilité), suppression (effacement) qui se propage au programme rejoué par le SMA. |
| Intervention humaine (art. 22) | Les prédictions et les créneaux sont des **propositions** : le chirurgien valide ou corrige ; l'écart prédiction / décision est conservé. |
| Transparence de l'IA | Qualité du modèle mesurée sur 20 % de données jamais vues affichée à chaque prédiction. |
| Données d'entraînement | Seules des métriques agrégées sont conservées ; aucune ligne de l'historique n'est affichée. |
"""

AVANT_PRODUCTION = """
- **Hébergement HDS** obligatoire pour des données de santé réelles (art. L.1111-8 CSP) et chiffrement du disque.
- **AIPD** (analyse d'impact) à réaliser : traitement de données de santé à grande échelle avec un outil innovant.
- Inscription au **registre des traitements** de l'établissement, avis du DPO.
- Authentification forte (carte CPS / Pro Santé Connect) et HTTPS.
- Jeu d'entraînement : vérifier l'anonymisation effective (le fichier historique contient dates de naissance,
  dates de séjour et noms de chirurgiens) et **ne pas le publier** dans un dépôt de code.
"""


def afficher() -> None:
    C.entete("Confidentialité et protection des données")
    duree = DB.lire_parametre("duree_conservation_jours", DB.DUREE_CONSERVATION_JOURS_DEFAUT)
    t1, t2, t3 = st.tabs(["Notice d'information patient", "Mesures appliquées", "Avant une mise en production"])
    with t1:
        texte = NOTICE.format(duree=duree)
        st.markdown(texte)
        st.download_button("Télécharger la notice (texte)", texte, file_name="notice_information_patient.md")
    with t2:
        st.markdown(MESURES)
    with t3:
        st.markdown(AVANT_PRODUCTION)
