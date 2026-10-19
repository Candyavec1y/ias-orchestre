# -*- coding: utf-8 -*-
"""Planning des vacations : cycle fixe, versions datées décidées par l'administrateur, contrôles, ids stables."""
from datetime import timedelta

from aide import LUNDI, MATIN, coherent, inscription, patient
from orchestre import programme as P
from orchestre import sma_service as S

V = P.V28


def _blocs():
    return [list(b[:5]) + [list(b[5])] for b in V.BLOCS]


def _structure(lundi):
    _, vacs, _ = V.construire_semaine(lundi)
    return sorted((v.jour.weekday(), v.salle_id, v.heure_debut, v.heure_fin, v.chirurgien_id) for v in vacs.values())


def test_la_parite_des_semaines_est_deduite_de_la_date():
    t, cases = P.planning_semaine_v28(LUNDI)
    assert t == "paire" and any(c.type == "urgence" for c in cases)


def test_le_planning_d_origine_est_sans_conflit():
    assert V.verifier_blocs(_blocs()) == []


def test_le_cycle_de_4_semaines_se_repete_sur_l_annee():
    for k in range(4):
        assert _structure(LUNDI + timedelta(weeks=k)) == _structure(LUNDI + timedelta(weeks=k + 48))


def test_les_conflits_sont_detectes():
    blocs = _blocs() + [[1, 2, "CT", "9:00", "10:00", ["paire"]]]          # mardi : salle 2 = Dr JT, Dr CT en salle 4
    erreurs = V.verifier_blocs(blocs)
    assert any("Salle 2" in e and "chevauchent" in e for e in erreurs)
    assert any("CT dans deux salles" in e for e in erreurs)
    assert V.verifier_blocs([[0, 1, "CT", "13:00", "9:00", ["paire"]]])      # horaires inversés


def test_la_verification_n_enregistre_aucun_praticien():
    V.verifier_blocs(_blocs() + [[0, 1, "NOUVEAU", "8:00", "12:00", ["paire"]]])
    assert "NOUVEAU" not in V.ID_PAR_NOM


def test_une_version_ne_s_applique_qu_a_partir_de_sa_date_d_effet():
    effet = LUNDI + timedelta(weeks=4)
    avant, apres_effet = _structure(effet - timedelta(weeks=4)), _structure(effet)
    V.definir_versions([(effet, _blocs() + [[2, 1, "CT", "8:00", "12:00", ["paire", "impaire_1", "impaire_2"]]])])
    assert _structure(effet - timedelta(weeks=4)) == avant
    nouvelle = _structure(effet)
    assert len(nouvelle) == len(apres_effet) + 1
    assert any(j == 2 and s == 1 and c == S.id_chirurgien("CT") for j, s, _, _, c in nouvelle)


def test_un_nouveau_praticien_garde_son_identifiant():
    ids = V.definir_versions([(LUNDI + timedelta(weeks=4), _blocs() + [[0, 1, "ZZ", "8:00", "12:00", ["paire"]]])])
    assert ids["ZZ"] == max(i for n, i in V.ID_PAR_NOM.items() if n != "ZZ" and i < V.ID_URGENCE) + 1
    premier = ids["ZZ"]
    V.ID_PAR_NOM.pop("ZZ"); V.NOM_PAR_ID.pop(premier)                        # nouveau lancement de l'application
    assert V.definir_versions([(LUNDI + timedelta(weeks=4), _blocs() + [[0, 1, "ZZ", "8:00", "12:00", ["paire"]]])],
                              {"ZZ": premier})["ZZ"] == premier


def test_le_sma_utilise_la_nouvelle_version(prog):
    effet = LUNDI + timedelta(weeks=5)
    V.definir_versions([(effet, _blocs() + [[2, 1, "CT", "8:00", "12:00", ["paire", "impaire_1", "impaire_2"]]])])
    p = patient(1, date_min=effet + timedelta(days=2))                      # mercredi de la semaine d'effet
    sim = S.simuler(prog, [inscription(MATIN, p)], MATIN + timedelta(minutes=1))
    it = sim.intervention(p.id)
    assert it.debut.date() == effet + timedelta(days=2) and it.salle_id == 1
    assert coherent(sim) == []


def test_tous_les_praticiens_du_planning_sont_du_meme_service():
    noms = [n for n in V.ID_PAR_NOM if n not in (V.NOM_URGENCE, V.NOM_LIBRE)]
    assert {S.SMA.specialite_de(n) for n in noms} == {S.SMA.SPECIALITE_SERVICE}
    assert S.SMA.specialite_de(V.NOM_URGENCE) == ""
