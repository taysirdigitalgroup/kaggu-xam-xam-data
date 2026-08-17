# kaggu-xam-xam-data

---

## Pour ajouter un Nouveau Prof
1. ***Ajouter ses infos sur professors/profs_infos.json***
2. ***Ajouter sa photo de profil sur professors/profils*** (en jpg et même que le nom en lowercase collé par _)
    Ex: S Sam Mbaye => s_sam_mbaye.jpg
3. ***Ajouter son dossier et ses audios*** sur audios/         
Note : Nom de dossier = nom Prof exacte - Sera auto formatté par catalogue_processor.py
4. ***Lancer catalogue_processor.py et choisissez audios/ comme cyble***
5. ***Récupérer le nouveau bibiotheque.json dans audios/ à déplacer sur la racine (écraser l'ancien)***
6. ***Faire le git add . && git commit -m "Notations ici" && git push -u origin main***
Note: ajouter --force sur le push s'il le faut.'
---
