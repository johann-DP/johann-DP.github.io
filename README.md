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

- HTML5 et CSS natifs, sans framework ; JavaScript limité au compteur de pages vues ;
- publication statique avec GitHub Pages ;
- compteur propriétaire agrégé, sans identifiant ni suivi individuel, exécuté sur Cloudflare Workers et D1 en offre gratuite ;
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

## Compteur de pages vues

Le compteur est développé dans `analytics-counter/`. Il stocke uniquement un total journalier par page et expose une page `/stats` protégée par authentification HTTP. Il ne conserve aucun événement brut ni identifiant. Les chiffres sont indicatifs : ils ne cherchent ni à identifier une personne, ni à distinguer un visiteur d’un robot.

Le déploiement utilise l’offre gratuite Cloudflare Workers/D1. Il reste désactivé tant que la variable GitHub `COUNTER_DEPLOY_ENABLED` ne vaut pas `true`. La CI/CD requiert :

- les secrets `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN` et `COUNTER_ADMIN_PASSWORD` ;
- les variables `COUNTER_D1_DATABASE_ID` et `COUNTER_WORKER_URL` ;
- une base `datapredict-audience-counter` créée avec la juridiction `eu`.

Le jeton Cloudflare est limité au compte concerné, avec les droits d’écriture `Workers Scripts` et `D1`. `COUNTER_ADMIN_PASSWORD` est une valeur aléatoire d’au moins 32 caractères.

Après le premier déploiement, l’URL HTTPS de `/hit` remplace le marqueur `__DATAPREDICT_COUNTER_ENDPOINT__` dans `assets/js/audience-counter.js`.

## Principes éditoriaux et de publication

- écrire `datapredict` en minuscules ;
- préserver l’anonymat des organisations et des missions ;
- ne publier ni nom client non autorisé, ni chiffre inventé ou non validé, ni livrable client brut ;
- exclure tout visuel, média ou métadonnée confidentiels ;
- vérifier les liens, les métadonnées, la navigation au clavier et le rendu responsive avant publication ;
- n’introduire du JavaScript que pour répondre à un besoin fonctionnel démontré.
