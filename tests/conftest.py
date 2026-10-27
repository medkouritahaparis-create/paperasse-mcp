import pytest

from paperasse.store import FicheStore, build_index

PART = "https://www.service-public.gouv.fr/particuliers/vosdroits/"
PRO = "https://entreprendre.service-public.gouv.fr/vosdroits/"


def make_fiche(id: str, title: str, summary: str = "", text: str = "",
               audiences: tuple[str, ...] = ("particuliers",), **extra) -> dict:
    """A fake fiche row, shaped like ingest output. Not real service-public.fr content."""
    urls = {a: (PART if a == "particuliers" else PRO) + id for a in audiences}
    return {
        "id": id,
        "title": title,
        "type": "Fiche d'information conditionnée",
        "audiences": list(audiences),
        "summary": summary,
        "text": text,
        "url": urls[audiences[0]],
        "urls": urls,
        "updated_at": "2026-09-11",
        "important_update_at": None,
        "theme": "Test",
        "breadcrumb": ["Accueil particuliers", "Test"],
        "online_services": [],
        "sources": [],
        **extra,
    }


FICHES = [
    make_fiche("F1", "Aide au logement pour étudiant", "Les étudiants peuvent toucher une aide au logement.",
               "## Conditions\n\nÊtre étudiant et payer un loyer."),
    make_fiche("F2", "Carte de transport", "Comment obtenir une carte de transport.",
               "La carte de transport est délivrée par la mairie. Elle aide les étudiants à se déplacer."),
    make_fiche("F3", "Allocations familiales", "Montant des allocations.",
               "Les allocations sont versées chaque mois.",
               online_services=[{"id": "R1", "title": "Simulateur", "url": "https://example.gouv.fr/sim"}]),
    make_fiche("F4", "Très longue fiche", "Une fiche longue.",
               "\n\n".join(f"## Partie {i}\n\n" + "Ligne de texte officielle. " * 400 for i in range(12))),
    make_fiche("F5", "Devenir micro-entrepreneur", "Les démarches pour créer une micro-entreprise.",
               "Le micro-entrepreneur déclare son activité en ligne.", audiences=("professionnels",)),
    make_fiche("F6", "Congé de naissance", "Le congé de naissance du salarié.",
               "Le salarié prévient son employeur.", audiences=("particuliers", "professionnels")),
]


@pytest.fixture(scope="session")
def db_path(tmp_path_factory):
    path = tmp_path_factory.mktemp("db") / "test.db"
    build_index(FICHES, path)
    return path


@pytest.fixture(scope="session")
def store(db_path):
    return FicheStore(db_path)
