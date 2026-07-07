# datapredict

Site vitrine statique de datapredict, publié avec GitHub Pages.

## Positionnement

datapredict intervient sur les projets Data, BI, reporting et IA qui doivent être recadrés, sécurisés, documentés et transmis au RUN.

## Architecture du dépôt

- CNAME : configuration du domaine.
- .nojekyll : publication statique directe par GitHub Pages.
- index.html : page d'accueil.
- offres.html : offres d'intervention.
- methode.html : méthode de travail.
- cas-clients.html : références anonymisées et reformulées.
- contact.html : page de contact.
- assets/css/site.css : feuille de style commune.
- assets/img/logo-datapredict.png : logo principal.
- assets/img/logo-datapredict.svg : fallback du logo.

## Architecture retenue

Le site reste volontairement statique : HTML et CSS uniquement. Ce choix limite les points de rupture, accélère la publication et garde un dépôt lisible par un prospect technique.

## Règles de publication

- Toujours écrire datapredict en minuscules.
- Utiliser les couleurs de marque : turquoise #11b3bf et gris bleu #40647c.
- Ne jamais publier de données client nominatives.
- Ne jamais publier de livrable client brut.
- Anonymiser les contextes et reformuler les résultats.
- Garder le site compatible mobile.
- Éviter tout framework inutile tant que le contenu commercial n'est pas stabilisé.

## Vérification avant publication

1. Vérifier que tous les liens internes pointent vers une page existante.
2. Vérifier que le nom de marque est toujours en minuscules.
3. Vérifier que CNAME et .nojekyll sont conservés.
4. Vérifier que le rendu mobile reste lisible.
