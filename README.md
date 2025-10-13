# Page GitHub Pages — Bonjour Matthieu + S&P 500 (5m)

Cette page affiche « bonjour je m'appelle matthieu » au premier plan, avec en arrière‑plan un graphique TradingView du S&P 500 en bougies 5 minutes (intraday).

Fichier principal : `index.html`

## Déploiement sur GitHub Pages

Deux options simples :

1) Dépôt `USERNAME.github.io`
- Créez un dépôt public nommé `VOTRE_UTILISATEUR.github.io`.
- Ajoutez `index.html` (et ce README si vous voulez) à la racine.
- Poussez sur `main`. Votre site sera accessible à `https://VOTRE_UTILISATEUR.github.io`.

2) Dépôt classique + Pages
- Créez un dépôt public, par ex. `bonjour-matthieu`.
- Ajoutez `index.html` à la racine et poussez sur `main`.
- Dans GitHub : Settings → Pages → Build and deployment → Source : `Deploy from a branch`, Branch : `main` (root).
- L’URL sera du type `https://VOTRE_UTILISATEUR.github.io/bonjour-matthieu/`.

## Personnalisation

- Texte : modifiez le `<h1>` dans `index.html`.
- Thème : changez `theme: 'dark'` en `'light'`.
- Fuseau horaire : remplacez `timezone: 'Europe/Paris'`.
- Symbole TradingView : la config utilise `SP:SPX`. Si le chargement échoue suivant votre région, essayez `TVC:SPX`, `SPCFD:SPX` ou `OANDA:SPX500USD` dans `SYMBOL`.

## Note

Le widget TradingView se met à jour en temps quasi‑réel côté client et ne nécessite aucun backend. L’arrière‑plan est non interactif (`pointer-events: none`) pour rester décoratif, mais vous pouvez rendre le graphique interactif en supprimant cette règle CSS.

