# datapredict

Site vitrine statique de datapredict, publie avec GitHub Pages.

## Positionnement

datapredict intervient sur les projets Data, BI, reporting et IA qui doivent etre recadres, securises, documentes et transmis au RUN.

## Architecture du depot

- CNAME : configuration du domaine.
- .nojekyll : publication statique directe par GitHub Pages.
- index.html : page d'accueil.
- offres.html : offres d'intervention.
- methode.html : methode de travail.
- cas-clients.html : references anonymisees et reformulees.
- contact.html : page de contact.
- assets/css/site.css : feuille de style commune.
- assets/img/logo-datapredict.png : logo principal.
- assets/img/logo-datapredict.svg : fallback du logo.

## Architecture retenue

Le site reste volontairement statique : HTML et CSS uniquement. Ce choix limite les points de rupture, accelere la publication et garde un depot lisible par un prospect technique.

## Regles de publication

- Toujours ecrire datapredict en minuscules.
- Utiliser les couleurs de marque : turquoise #11b3bf et gris bleu #40647c.
- Ne jamais publier de donnees client nominatives.
- Ne jamais publier de livrable client brut.
- Anonymiser les contextes et reformuler les resultats.
- Garder le site compatible mobile.
- Eviter tout framework inutile tant que le contenu commercial n'est pas stabilise.

## Verification avant publication

1. Verifier que tous les liens internes pointent vers une page existante.
2. Verifier que le nom de marque est toujours en minuscules.
3. Verifier que CNAME et .nojekyll sont conserves.
4. Verifier que le rendu mobile reste lisible.
