import sys
import os
import re
import json
import unicodedata
from pathlib import Path
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QFileDialog, QLabel, QProgressBar, 
                             QMessageBox, QTextEdit)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

def to_slug(text):
    """
    Normalise une chaîne de caractères selon les règles strictes TDG :
    1. Remplacement des points '.' par des tirets bas '_'.
    2. Remplacement des résidus [' ( ) - @ %] par des espaces.
    3. Enlever les accents et passer en minuscules.
    4. Remplacer les espaces par des tirets bas.
    5. Fusionner les underscores multiples (e.g., '__' -> '_').
    """
    if not text:
        return ""
    
    # 1. Remplacement spécifique du point par un tiret bas
    cleaned = text.replace(".", "_")
    
    # 2. Remplacement des autres résidus spécifiés par des espaces
    cleaned = re.sub(r"['\(\)\-@%]", " ", cleaned)
    
    # 3. Suppression des accents (Normalisation Unicode)
    cleaned = unicodedata.normalize('NFD', cleaned)
    cleaned = "".join([c for c in cleaned if unicodedata.category(c) != 'Mn'])
    
    # 4. Passage en minuscules et nettoyage des espaces aux extrémités
    cleaned = cleaned.lower().strip()
    
    # 5. Remplacement de tout groupe d'espaces par un tiret bas
    cleaned = re.sub(r"\s+", "_", cleaned)
    
    # 6. REGLE CRITIQUE : Fusion de tous les underscores consécutifs
    slug = re.sub(r"_+", "_", cleaned)
    
    return slug

def format_folder_name(name):
    """
    Retourne le nom du dossier capitalisé.
    Si le nom est déjà un slug normalisé (ex: s_sam_mbaye), il le dé-normalise
    (ex: s_sam_mbaye -> S Sam Mbaye) avant de le capitaliser.
    """
    if not name:
        return ""
    
    # Vérification si le nom ressemble à un slug purement normalisé (minuscules, chiffres et underscores)
    if re.match(r'^[a-z0-9_]+$', name):
        # Remplacement des underscores par des espaces
        name = name.replace("_", " ")
        
    # Capitalisation de chaque mot (ex: "histoire du prophete" -> "Histoire Du Prophete")
    return name.title().strip()


class CatalogProcessingThread(QThread):
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int)
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, root_folder):
        super().__init__()
        self.root_folder = Path(root_folder)

    def run(self):
        try:
            # -----------------------------------------------------------------
            # ÉTAPE 1 : GÉNÉRATION DU JSON AVEC STRATÉGIE DE CAPITALISATION / SLUG
            # -----------------------------------------------------------------
            self.log_signal.emit("📝 Étape 1 : Analyse de l'arborescence et génération du JSON...")
            bibliotheque = {}

            # Extraction des dossiers Profs au premier niveau
            profs = sorted([d for d in os.listdir(self.root_folder) if (self.root_folder / d).is_dir()])
            
            for prof in profs:
                prof_path = self.root_folder / prof
                prof_display_name = format_folder_name(prof)
                bibliotheque[prof_display_name] = {}
                
                # Extraction des dossiers Thèmes au deuxième niveau
                themes = sorted([t for t in os.listdir(prof_path) if (prof_path / t).is_dir()])
                for theme in themes:
                    theme_path = prof_path / theme
                    theme_display_name = format_folder_name(theme)
                    
                    pistes_normalisees = []
                    # Extraction et tri des fichiers du thème
                    fichiers = sorted([f for f in os.listdir(theme_path) if (theme_path / f).is_file()])
                    
                    for f in fichiers:
                        name, ext = os.path.splitext(f)
                        # Stockage du fichier au format normalisé + extension en minuscules
                        new_filename = to_slug(name) + ext.lower()
                        pistes_normalisees.append(new_filename)
                        
                    bibliotheque[prof_display_name][theme_display_name] = pistes_normalisees

            # Sauvegarde du fichier JSON à la racine du répertoire sélectionné
            json_output_path = self.root_folder / 'bibliotheque.json'
            with open(json_output_path, 'w', encoding='utf-8') as f:
                json.dump(bibliotheque, f, indent=4, ensure_ascii=False)
                
            self.log_signal.emit(f"💾 Fichier '{json_output_path.name}' créé avec succès.")

            # -----------------------------------------------------------------
            # ÉTAPE 2 : NORMALISATION ET REMPLACEMENT EFFECTIF DES FICHIERS/DOSSIERS
            # -----------------------------------------------------------------
            self.log_signal.emit("🔄 Étape 2 : Application physique de la normalisation sur le disque...")
            
            all_dirs = []
            all_files = []
            
            # Collecte récursive pour le calcul de la barre de progression
            for root, dirs, files in os.walk(self.root_folder, topdown=False):
                for file in files:
                    # On évite de renommer le fichier de configuration JSON qu'on vient de créer
                    if file != 'bibliotheque.json':
                        all_files.append((root, file))
                for d in dirs:
                    all_dirs.append((root, d))
                    
            total_elements = len(all_files) + len(all_dirs)
            if total_elements == 0:
                self.finished_signal.emit(True, "JSON généré, mais aucun fichier/dossier à renommer.")
                return

            processed_count = 0

            # Renommage des fichiers d'abord
            for root, file in all_files:
                name, ext = os.path.splitext(file)
                new_name = to_slug(name) + ext.lower()
                
                old_path = os.path.join(root, file)
                new_path = os.path.join(root, new_name)
                
                if old_path != new_path:
                    os.rename(old_path, new_path)
                    self.log_signal.emit(f"📄 Fichier renommé : {file} ➡️ {new_name}")
                    
                processed_count += 1
                self.progress_signal.emit(int((processed_count / total_elements) * 100))

            # Renommage des dossiers (en remontant l'arborescence grâce à topdown=False)
            for root, d in all_dirs:
                new_dir_name = to_slug(d)
                
                old_path = os.path.join(root, d)
                new_path = os.path.join(root, new_dir_name)
                
                if old_path != new_path:
                    os.rename(old_path, new_path)
                    self.log_signal.emit(f"📁 Dossier renommé : {d} ➡️ {new_dir_name}")
                    
                processed_count += 1
                self.progress_signal.emit(int((processed_count / total_elements) * 100))

            self.finished_signal.emit(True, f"Processus complet terminé.\nJSON sauvegardé et {processed_count} éléments normalisés.")
            
        except Exception as e:
            self.finished_signal.emit(False, str(e))


class AudioRenamerApp(QWidget):
    def __init__(self):
        super().__init__()
        self.selected_folder = ""
        self.initUI()

    def initUI(self):
        self.setWindowTitle("TDG Catalog Engine - JSON & Slug Normalizer")
        self.setMinimumSize(650, 450)
        
        layout = QVBoxLayout()
        layout.setSpacing(12)

        # Section 1 : Sélection du dossier racine
        folder_layout = QHBoxLayout()
        self.lbl_folder = QLabel("Aucun dossier sélectionné")
        self.lbl_folder.setStyleSheet("color: #555; font-style: italic; font-weight: bold;")
        btn_browse = QPushButton("Sélectionner le répertoire")
        btn_browse.clicked.connect(self.browse_folder)
        folder_layout.addWidget(self.lbl_folder, stretch=3)
        folder_layout.addWidget(btn_browse, stretch=1)
        layout.addLayout(folder_layout)

        # Section 2 : Zone de Logs en temps réel
        layout.addWidget(QLabel("Console d'exécution :"))
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setStyleSheet("background-color: #1E1E1E; color: #A9FFB2; font-family: monospace;")
        layout.addWidget(self.log_box)

        # Section 3 : Progression
        self.progress_bar = QProgressBar()
        self.progress_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        # Section 4 : Bouton d'action principal
        self.btn_start = QPushButton("Générer le JSON & Lancer la normalisation")
        self.btn_start.setStyleSheet("background-color: #28A745; color: white; font-weight: bold; padding: 14px;")
        self.btn_start.clicked.connect(self.start_processing)
        layout.addWidget(self.btn_start)

        self.setLayout(layout)

    def browse_folder(self):
        folder_path = QFileDialog.getExistingDirectory(self, "Choisir le répertoire de la bibliothèque")
        if folder_path:
            self.selected_folder = folder_path
            self.lbl_folder.setText(folder_path)
            self.log_box.clear()
            self.progress_bar.setValue(0)

    def start_processing(self):
        if not self.selected_folder:
            QMessageBox.warning(self, "Erreur", "Veuillez d'abord sélectionner un répertoire racine.")
            return

        confirm = QMessageBox.question(
            self, "Confirmation requise", 
            "Cette action va générer la cartographie 'bibliotheque.json' PUIS modifier "
            "définitivement l'arborescence des dossiers et fichiers sur le stockage.\n\n"
            "Voulez-vous exécuter le pipeline ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if confirm == QMessageBox.StandardButton.No:
            return

        self.btn_start.setEnabled(False)
        self.log_box.clear()
        
        # Lancement du traitement unifié
        self.thread = CatalogProcessingThread(self.selected_folder)
        self.thread.log_signal.connect(self.append_log)
        self.thread.progress_signal.connect(self.progress_bar.setValue)
        self.thread.finished_signal.connect(self.on_finished)
        self.thread.start()

    def append_log(self, text):
        self.log_box.append(text)

    def on_finished(self, success, message):
        self.btn_start.setEnabled(True)
        if success:
            self.progress_bar.setValue(100)
            QMessageBox.information(self, "Pipeline Réussi", message)
        else:
            QMessageBox.critical(self, "Erreur Critique", f"Le processus a échoué :\n{message}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = AudioRenamerApp()
    window.show()
    sys.exit(app.exec())
