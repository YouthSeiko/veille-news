# Veille — Tech & Cybersécurité

Site de veille informationnelle mise à jour automatiquement chaque jour à 12h (10h UTC).

## Fonctionnement

- **Collecte** : `collector/veille.py` interroge 14 flux RSS (cybersécurité + tech, EN/FR), filtre les 48 dernières heures et écrit les JSON dans `data/`.
- **Publication** : GitHub Actions (`.github/workflows/daily.yml`) lance la collecte, archive le JSON du jour, puis déploie le site via GitHub Pages.
- **Interactions** : likes, section « À la une » (épinglage) et commentaires sont stockés sur Supabase (RLS : lecture publique, écriture réservée au compte connecté).

## Automatisations

| Quand | Quoi |
|---|---|
| Chaque jour 10h00 UTC | Collecte RSS + déploiement Pages |
| Push sur `main` | Redéploiement (sans nouvelle collecte) |
| Manuellement | `gh workflow run daily.yml` |

## Composants

- `index.html` + `assets/` — le site (vanilla HTML/CSS/JS, SDK Supabase via CDN)
- `collector/veille.py` — collecteur RSS (Python standard, sans dépendance)
- `data/latest.json` — dernière veille ; `data/archive_AAAA-MM-JJ.json` — historique (60 jours)

## Compte

Connexion réservée au propriétaire du site (identifiant + mot de passe). Les inscriptions publiques sont désactivées côté Supabase.
