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
- [Offres](offres.html) : détail des trois axes datapredict ;
- [Méthode](methode.html) : clarifier, diagnostiquer, arbitrer et transmettre ;
- [Réalisations](cas-clients.html) : sélection de contextes et d’interventions anonymisés ;
- [Contact](contact.html) : qualification d’un besoin et prise de contact.

Le nom de fichier historique `cas-clients.html` est conservé ; son libellé public est « Réalisations ».

## Socle technique

- HTML5 et CSS natifs, sans framework, JavaScript, dépendance ni étape de compilation ;
- publication statique avec GitHub Pages ;
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
└── assets/
    ├── css/site.css
    └── img/logo-datapredict.png
```

`CNAME` configure le domaine public, `.nojekyll` assure la publication directe des fichiers statiques et `robots.txt` déclare le sitemap des cinq pages canoniques.

## Principes éditoriaux et de publication

- écrire `datapredict` en minuscules ;
- préserver l’anonymat des organisations et des missions ;
- ne publier ni nom client non autorisé, ni chiffre inventé ou non validé, ni livrable client brut ;
- exclure tout visuel, média ou métadonnée confidentiels ;
- vérifier les liens, les métadonnées, la navigation au clavier et le rendu responsive avant publication ;
- n’introduire du JavaScript que pour répondre à un besoin fonctionnel démontré.
