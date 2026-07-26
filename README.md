# datapredict

Dépôt du site institutionnel de [datapredict](https://www.datapredict.org/), entreprise de conseil et de réalisation Data, IA et BI.

## Positionnement

datapredict intervient de la stratégie au RUN pour cadrer les décisions, structurer les dispositifs et préparer leur exploitation selon trois axes complémentaires :

- management de transition et PMO Data / IA / BI ;
- architecture et Tech Lead Data / IA / BI ;
- expertise industrielle Seine–Paris–Normandie : instrumentation, capteurs, mesures physiques et physico-chimiques, séries temporelles, IoT industriel et procédés.

Les réalisations présentées sur le site sont anonymisées et reformulées afin de préserver la confidentialité des organisations concernées.

## Pages du site

- [Accueil](index.html) : positionnement et champs d’intervention ;
- [Offres](offres.html) : détail des trois axes, technologies, référentiels, formats et tarifs indicatifs ;
- [Méthode](methode.html) : clarifier, diagnostiquer, arbitrer et transmettre, avec une représentation visuelle de la séquence ;
- [Réalisations](cas-clients.html) : sélection de contextes et d’interventions anonymisés ;
- [Contact](contact.html) : qualification d’un besoin et prise de contact.

Le nom de fichier historique `cas-clients.html` est conservé ; son libellé public est « Réalisations ».

## Socle technique

- HTML5 et CSS natifs, sans framework ; JavaScript limité à la mesure d’audience agrégée ;
- publication statique avec GitHub Pages ;
- mesure d’audience propriétaire agrégée, sans identifiant ni suivi individuel, exécutée sur Cloudflare Workers et D1 en offre gratuite ;
- interface fluide conçue pour les largeurs de référence de 320 à 1 920 pixels ;
- dispositions d’accessibilité intégrées : structure sémantique, navigation au clavier, contrastes et réduction des animations ;
- logo officiel datapredict au format PNG uniquement ;
- couleurs principales `#11b3bf` et `#40647c`.

## Structure du dépôt

```text
.
├── .nojekyll
├── CNAME
├── README.md
├── robots.txt
├── sitemap.xml
├── index.html
├── offres.html
├── methode.html
├── cas-clients.html
├── contact.html
├── assets/
    ├── css/
    │   └── site.css
    ├── js/
    │   └── audience-counter.js
    └── img/
        ├── case-immobilier-typologie-panel.jpg
        ├── case-sante-pilotage-capacitaire.png
        ├── case-sante-previsions-hospitalieres.png
        ├── favicon-datapredict.png
        ├── illustration-*.webp
        ├── logo-datapredict.png
        ├── portrait-johann-grisel.webp
        ├── social-datapredict.png
        └── tech-*.webp
└── analytics-counter/
    ├── migrations/
    ├── src/
    └── test/
```

`CNAME` configure le domaine public, `.nojekyll` assure la publication directe des fichiers statiques et `robots.txt` déclare le sitemap des cinq pages canoniques.

## Mesure d’audience agrégée

Le système est développé dans `analytics-counter/`. Le script du site envoie au même endpoint `/hit` un payload fermé contenant :

- le chemin canonique de la page ;
- un événement parmi `pageview`, `engaged_30s` et `scroll_75` ;
- un booléen de nouvelle visite estimée ;
- une provenance parmi `direct`, `search`, `linkedin`, `other-social`, `other-site` et `internal` ;
- un appareil parmi `mobile`, `tablet` et `desktop`.

Une visite est comptée au plus une fois par session d’onglet grâce à un booléen `sessionStorage`, sans création d’identifiant. `engaged_30s` mesure trente secondes cumulées pendant lesquelles la page est visible ; `scroll_75` signale que le bas de la fenêtre a atteint 75 % de la hauteur du document. La provenance est classée dans le navigateur : aucune URL référente ni aucun paramètre UTM ne sont envoyés. L’appareil est également classé localement ; le User-Agent n’est pas stocké. Le pays approximatif est dérivé côté Worker à partir des informations Cloudflare.

Le Worker conserve pendant vingt-quatre mois des agrégats séparés par jour et par dimension, puis expose une page `/stats` protégée par authentification HTTP. Il ne stocke aucun événement brut, identifiant, adresse IP, User-Agent, URL complète, paramètre UTM ou donnée de formulaire. Ses journaux applicatifs sont désactivés. Les chiffres restent indicatifs : ils ne cherchent ni à identifier une personne, ni à distinguer un visiteur d’un robot.

Le script respecte le cookie d’opposition propre au site, Global Privacy Control et Do Not Track. Si `sessionStorage` est indisponible, la page vue reste mesurée mais n’est pas comptée comme une nouvelle visite, afin de ne pas surévaluer les visites.

Le déploiement utilise l’offre gratuite Cloudflare Workers/D1. La base
`datapredict-audience-counter` est limitée à la juridiction UE. L’environnement
GitHub `production`, réservé à `main`, contient uniquement les secrets
`CLOUDFLARE_API_TOKEN` et `COUNTER_ADMIN_PASSWORD`. Le jeton Cloudflare est
limité au compte concerné, avec les droits d’écriture `Workers Scripts` et
`D1` ; le mot de passe est une valeur aléatoire d’au moins 32 caractères.

Les pushes sur `main` et `codex/**`, ainsi que les PR vers `main`, testent le
Worker sans le déployer. Le workflow `Déploiement du compteur` ne s’exécute que
manuellement sur `main`. Le collecteur public est
`https://datapredict-audience-counter.johann-grisel.workers.dev/hit` et le
tableau privé est exposé sous `/stats`.

## Principes éditoriaux et de publication

- écrire `datapredict` en minuscules ;
- préserver l’anonymat des organisations et des missions ;
- ne publier ni nom client non autorisé, ni chiffre inventé ou non validé, ni livrable client brut ;
- exclure tout visuel, média ou métadonnée confidentiels ;
- vérifier les liens, les métadonnées, la navigation au clavier et le rendu responsive avant publication ;
- n’introduire du JavaScript que pour répondre à un besoin fonctionnel démontré.
