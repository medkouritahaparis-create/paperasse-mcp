# Manual search test — 2026-10-26

Roadmap step 3. 29 realistic questions, of the kind the target users ask (CAF, URSSAF, impôts, titre de séjour, santé, papiers, travail), run through `search_fiche` (top 5) on the 3,004 *Particuliers* fiches. The "right fiche" was chosen by hand by browsing fiche titles. This is a first look, not a measurement: step 4 turns it into a proper eval set.

**Result: right fiche in the top 3 for 22/29 (76%), and at rank 1 for 13/29 (45%).** 4 misses are ranking problems and 3 are missing content.

| Question | Right fiche | Rank |
|---|---|---|
| APL étudiant | F1563 Un étudiant peut-il bénéficier d'une aide au logement… | 1 |
| Comment demander l'APL quand on est étudiant ? | F1563 | 1 |
| déclarer un changement de situation à la CAF | F827 Faut-il signaler un changement de situation… | 1 |
| taxe d'habitation résidence secondaire | F42 Taxe d'habitation sur les résidences secondaires | 1 |
| avis d'imposition contester | F110 Réclamations et recours en matière d'impôt | 1 |
| prélèvement à la source changer de taux | F35894 Comment changer votre taux de prélèvement… | 1 |
| renouvellement titre de séjour étudiant | F2231 Étudiant étranger en France : visa ou titre de séjour | 1 |
| récépissé titre de séjour | F15763 Qu'est-ce qu'un récépissé… | 1 |
| changer d'adresse carte grise | F12118 Changer l'adresse sur son certificat d'immatriculation | 1 |
| passeport délai | F34757 Comment savoir où en est une demande de passeport ? | 1 |
| perte de papiers d'identité | F31421 Perte de tous ses papiers d'identité | 1 |
| chômage démission | F34991 / F89 Allocation chômage en cas de démission | 1 |
| rupture conventionnelle indemnité | F31539 Calculer l'indemnité de rupture conventionnelle | 1 |
| allocations familiales deuxième enfant | F13213 Allocations familiales (2 enfants ou plus) | 2 |
| déclaration de revenus en ligne | F358 Déclaration de revenus annuelle | 2 |
| changement de statut étudiant salarié | F2229 Étudiant étranger : travailler en France après ses études | 2 |
| carte vitale perdue | F265 Carte Vitale | 2 |
| arrêt maladie indemnités journalières | F3053 Arrêt maladie : indemnités journalières | 2 |
| demande de logement social | F35683 Faire une demande de logement social | 2 |
| regroupement familial | F11166 Regroupement familial | 3 |
| complémentaire santé solidaire | F10027 Complémentaire santé solidaire | 3 |
| inscription listes électorales | F1367 Listes électorales : première inscription | 3 |
| naturalisation française conditions | F2213 Naturalisation française par décret | **miss** |
| prime d'activité conditions | F2882 Prime d'activité : salarié ou fonctionnaire | **miss** |
| RSA montant | F19778 RSA : demandeur de 25 ans et plus | **miss** |
| payer impôt sur le revenu en plusieurs fois | F3124 Demander un délai de paiement pour payer ses impôts | **miss** |
| micro-entrepreneur déclaration chiffre d'affaires URSSAF | not in the *Particuliers* feed | **no content** |
| créer une micro-entreprise | not in the *Particuliers* feed | **no content** |
| cotisations sociales auto-entrepreneur | not in the *Particuliers* feed | **no content** |

## Findings

1. **Freelancer content is missing.** Micro-entreprise, URSSAF and cotisations guides live in the separate *Entreprendre* feed (`/vdd/3.5/pro/zip/vosdroits-latest.zip`, same schema), which isn't ingested. Freelancers are a target segment, so this gap matters most. It also gives the existing `audience` parameter a real second value.
2. **Main guides lose to short Q&A fiches.** The main guides (F2213 naturalisation, 43k characters; RSA and prime d'activité guides, 20–40k) rank below short "Question-réponse" fiches whose titles share the same words. BM25 length normalisation on the `text` column penalises long fiches. Options to test against the eval set: lower the `text` weight or its length normalisation, boost "Fiche d'information" types, or rank on title + summary first.
3. **Wording gap.** "Payer en plusieurs fois" vs "délai de paiement". Keyword search can't bridge this without synonyms or embeddings. Note it for the embeddings decision, which should only be made on eval numbers.
4. **Noise after a good first hit.** For example "avis d'imposition contester" → F110, then unrelated fiches (bourse de collège, Apa). That's harmless when the client reads rank 1, but a minimum score cutoff could be tried.

## Suggested next steps

- Step 4 eval set: start from these 29 questions with their labels, plus about 20 more, and measure top-1 / top-3 before changing any ranking.
- Ingest the *Entreprendre* feed (audience `professionnels`).
- Try the ranking options in finding 2 one at a time, and keep only what improves the eval numbers.
