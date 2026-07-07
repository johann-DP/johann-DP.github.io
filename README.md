# datapredict — site public

Site vitrine statique de `datapredict`, publié avec GitHub Pages depuis le dépôt `johann-DP/.github.io`.

## Positionnement

`datapredict` intervient sur les projets data, BI, reporting et IA qui doivent être recadrés, sécurisés, documentés et transmis au RUN.

Le site présente des offres courtes, des preuves anonymisées et une méthode d’intervention opérationnelle. Il ne publie aucun nom de client, aucune donnée source et aucun livrable client brut.

## Règles de marque

- Graphie publique : `datapredict`, toujours en minuscules.
- Couleurs sources : turquoise `#11b3bf` et gris bleu `#40647c`.
- Les variantes graphiques doivent dériver de ces deux couleurs.
- Logo principal : `assets/img/logo-datapredict.png`.
- Fallback : `assets/img/logo-datapredict.svg`.

## Architecture

- `.nojekyll` : publication statique directe.
- `CNAME` : domaine GitHub Pages.
- `index.html` : accueil et positionnement.
- `offres.html` : offres d’intervention.
- `methode.html` : méthode de travail.
- `cas-clients.html` : cas reformulés et anonymisés.
- `contact.html` : contact et qualification.
- `assets/css/site.css` : feuille de style commune.
- `assets/img/` : logo et fallback.

## Choix techniques

- HTML statique.
- CSS statique.
- Compatible GitHub Pages.
- Aucun build step obligatoire.
- Aucun framework lourd tant que le contenu n’est pas stabilisé.

## Prévisualisation locale

Depuis la racine du dépôt :

```bash
python3 -m http.server 8000
```

## Liste de contrôle avant push

1. Vérifier la graphie `datapredict` en minuscules dans les contenus publics.
2. Relire toutes les pages pour confirmer l’absence de noms clients et de données source.
3. Contrôler les liens internes et le rendu mobile.
4. Vérifier que `CNAME`, `.nojekyll`, le PNG et le SVG sont présents.
5. Vérifier `git status --short` avant commit.

## Proposition de commit atomique

```text
refactor: refondre le site vitrine datapredict
```
