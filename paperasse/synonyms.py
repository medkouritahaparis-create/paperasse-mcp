"""Everyday words -> official terms, for query expansion.

People say "auto-entrepreneur" or "Pôle emploi"; official fiches say
"micro-entrepreneur" and "France Travail". When a query contains a phrase on
the left, the phrases on the right are added to the search in OR: the user's
own words are always kept, never replaced. Phrases are case- and
accent-insensitive; the last word also matches its plural ("auto-entrepreneurs").

Every rule here was measured on the dev split of the eval and kept only if it
helped there: see docs/decisions.md
("Query expansion"). Add a rule the same way: measure on dev first.
"""

# One way: what people say -> the official term(s).
ONE_WAY: dict[str, list[str]] = {
    "auto-entrepreneur": ["micro-entrepreneur"],
    "chômage": ["allocation chômage", "ARE"],
    "enceinte": ["grossesse"],
}

# Both ways: each phrase of a group expands to the others. None kept so far:
# "carte de séjour <-> titre de séjour" and "APL <-> aide au logement" were
# measured and rejected (see docs/decisions.md).
TWO_WAY: list[list[str]] = []


def rules() -> list[tuple[str, list[str]]]:
    """All rules as (phrase found in the query, phrases to add)."""
    out = [(k, v) for k, v in ONE_WAY.items()]
    for group in TWO_WAY:
        out += [(p, [q for q in group if q != p]) for p in group]
    return out
