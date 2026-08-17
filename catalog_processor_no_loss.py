import sys
import os
import re
import json
import unicodedata
from pathlib import Path
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QFileDialog, QLabel, QProgressBar, 
                             QMessageBox, QTextEdit, QLineEdit)
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
    
    cleaned = text.replace(".", "_")
    cleaned = re.sub(r"['\(\)\-@%]", " ", cleaned)
    cleaned = unicodedata.normalize('NFD', cleaned)
    cleaned = "".join([c for c in cleaned if unicodedata.category(c) != 'Mn'])
    cleaned = cleaned.lower().strip()
    cleaned = re.sub(r"\s+", "_", cleaned)
    slug = re.sub(r"_+", "_", cleaned)
    
    return slug

def format_folder_name(name):
    """
    Retourne le nom du dossier capitalisé.
    Si le nom est déjà un slug normalisé (ex: s_sam_mbaye), il le dé-normalise
    avant de le capitaliser.
    """
    if not name:
        return ""
    
    if re.match(r'^[a-z0-9_]+$', name):
        name = name.replace("_", " ")
        
    return name.title().strip()

def natural_sort_key(text):
    """
    Clé de tri naturel permettant de trier correctement les nombres
    ex: 'piste_1', 'piste_2', 'piste_10' au lieu de 'piste_1', 'piste_10', 'piste_2'.
    """
    return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', text)]


class CatalogProcessingThread(QThread):
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int)
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, root_folder, reference_json_path=""):
        super().__init__()
        self.root_folder = Path(root_folder)
        self.reference_json_path = Path(reference_json_path) if reference_json_path else None

    def run(self):
        try:
            # Le fichier de sortie reste TOUJOURS dans le dossier racine des audios
            json_output_path = self.root_folder / 'bibliotheque.json'
            
            # -----------------------------------------------------------------
            # ÉTAPE 0 : CHARGEMENT DU JSON DE RÉFÉRENCE SÉLECTIONNÉ
            # -----------------------------------------------------------------
            bibliotheque = {}
            if self.reference_json_path and self.reference_json_path.exists():
                try:
                    with open(self.reference_json_path, 'r', encoding='utf-8') as f:
                        bibliotheque = json.load(f)
                    self.log_signal.emit(f"📖 JSON de référence chargé : '{self.reference_json_path.name}' (conservation active).")
                except Exception as e:
                    self.log_signal.emit(f"⚠️ Impossible de lire le JSON de référence ({e}). Création d'une nouvelle structure.")
                    bibliotheque = {}
            else:
                self.log_signal.emit("ℹ️ Aucun JSON de référence fourni. Création d'un nouveau catalogue.")

            # -----------------------------------------------------------------
            # ÉTAPE 1 : MIGRATION & FUSION SANS PERTE (INCREMENTAL)
            # -----------------------------------------------------------------
            self.log_signal.emit("📝 Étape 1 : Analyse des fichiers et fusion incrémentale...")

            # Extraction et tri naturel des dossiers Profs au premier niveau
            profs = sorted([d for d in os.listdir(self.root_folder) if (self.root_folder / d).is_dir()], key=natural_sort_key)
            
            for prof in profs:
                prof_path = self.root_folder / prof
                prof_display_name = format_folder_name(prof)
                
                if prof_display_name not in bibliotheque:
                    bibliotheque[prof_display_name] = {}
                
                # Extraction et tri naturel des dossiers Thèmes au deuxième niveau
                themes = sorted([t for t in os.listdir(prof_path) if (prof_path / t).is_dir()], key=natural_sort_key)
                
                for theme in themes:
                    theme_path = prof_path / theme
                    theme_display_name = format_folder_name(theme)
                    
                    if theme_display_name not in bibliotheque[prof_display_name]:
                        bibliotheque[prof_display_name][theme_display_name] = []
                    
                    # Récupération des pistes déjà existantes dans le JSON pour ce thème
                    pistes_existantes = set(bibliotheque[prof_display_name][theme_display_name])
                    
                    # Extraction et ajout des nouveaux fichiers audio du disque
                    fichiers = sorted([f for f in os.listdir(theme_path) if (theme_path / f).is_file()], key=natural_sort_key)
                    
                    for f in fichiers:
                        name, ext = os.path.splitext(f)
                        new_filename = to_slug(name) + ext.lower()
                        pistes_existantes.add(new_filename)
                        
                    # Tri naturel de la liste fusionnée des pistes
                    pistes_triees = sorted(list(pistes_existantes), key=natural_sort_key)
                    bibliotheque[prof_display_name][theme_display_name] = pistes_triees

            # Ré-organisation globale avec tri naturel pour le fichier final
            bibliotheque_organisee = {}
            for prof_key in sorted(bibliotheque.keys(), key=natural_sort_key):
                bibliotheque_organisee[prof_key] = {}
                for theme_key in sorted(bibliotheque[prof_key].keys(), key=natural_sort_key):
                    pistes = sorted(bibliotheque[prof_key][theme_key], key=natural_sort_key)
                    bibliotheque_organisee[prof_key][theme_key] = pistes

            # Écriture du JSON dans le dossier de destination (root_folder)
            with open(json_output_path, 'w', encoding='utf-8') as f:
                json.dump(bibliotheque_organisee, f, indent=4, ensure_ascii=False)
                
            self.log_signal.emit(f"💾 Fichier de sortie '{json_output_path.name}' écrit dans : {self.root_folder}")

            # -----------------------------------------------------------------
            # ÉTAPE 2 : NORMALISATION ET REMPLACEMENT EFFECTIF DES FICHIERS/DOSSIERS
            # -----------------------------------------------------------------
            self.log_signal.emit("🔄 Étape 2 : Application physique de la normalisation sur le disque...")
            
            all_dirs = []
            all_files = []
            
            for root, dirs, files in os.walk(self.root_folder, topdown=False):
                for file in files:
                    if file != 'bibliotheque.json':
                        all_files.append((root, file))
                for d in dirs:
                    all_dirs.append((root, d))
                    
            total_elements = len(all_files) + len(all_dirs)
            if total_elements == 0:
                self.finished_signal.emit(True, "JSON mis à jour, mais aucun fichier/dossier physique à renommer.")
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

            # Renommage des dossiers (de bas en haut grâce à topdown=False)
            for root, d in all_dirs:
                new_dir_name = to_slug(d)
                
                old_path = os.path.join(root, d)
                new_path = os.path.join(root, new_dir_name)
                
                if old_path != new_path:
                    os.rename(old_path, new_path)
                    self.log_signal.emit(f"📁 Dossier renommé : {d} ➡️ {new_dir_name}")
                    
                processed_count += 1
                self.progress_signal.emit(int((processed_count / total_elements) * 100))

            self.finished_signal.emit(True, f"Traitement réussi !\nJSON fusionné et {processed_count} éléments normalisés.")
            
        except Exception as e:
            self.finished_signal.emit(False, str(e))


class AudioRenamerApp(QWidget):
    def __init__(self):
        super().__init__()
        self.selected_folder = ""
        self.selected_json_ref = ""
        self.initUI()

    def initUI(self):
        self.setWindowTitle("TDG Catalog Engine - Custom JSON Reference & Incremental Merge")
        self.setMinimumSize(700, 520)
        
        layout = QVBoxLayout()
        layout.setSpacing(12)

        # Section 1 : Sélection du JSON de référence (Existant)
        layout.addWidget(QLabel("1. Sélectionner le JSON de référence (existant / à conserver) :"))
        json_layout = QHBoxLayout()
        self.txt_json_path = QLineEdit()
        self.txt_json_path.setPlaceholderText("Optionnel - Laisser vide si aucun JSON de référence")
        self.txt_json_path.setReadOnly(True)
        btn_browse_json = QPushButton("Parcourir JSON...")
        btn_browse_json.clicked.connect(self.browse_json_file)
        json_layout.addWidget(self.txt_json_path, stretch=3)
        json_layout.addWidget(btn_browse_json, stretch=1)
        layout.addLayout(json_layout)

        # Section 2 : Sélection du dossier racine des audios (Destination du JSON final)
        layout.addWidget(QLabel("2. Sélectionner le répertoire des audios à traiter (Dossier Profs) :"))
        folder_layout = QHBoxLayout()
        self.txt_folder_path = QLineEdit()
        self.txt_folder_path.setPlaceholderText("Requis - Dossier racine contenant les professeurs")
        self.txt_folder_path.setReadOnly(True)
        btn_browse_folder = QPushButton("Sélectionner Répertoire...")
        btn_browse_folder.clicked.connect(self.browse_folder)
        folder_layout.addWidget(self.txt_folder_path, stretch=3)
        folder_layout.addWidget(btn_browse_folder, stretch=1)
        layout.addLayout(folder_layout)

        # Section 3 : Console de logs
        layout.addWidget(QLabel("Console d'exécution :"))
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setStyleSheet("background-color: #1E1E1E; color: #A9FFB2; font-family: monospace;")
        layout.addWidget(self.log_box)

        # Section 4 : Barre de progression
        self.progress_bar = QProgressBar()
        self.progress_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        # Section 5 : Bouton principal
        self.btn_start = QPushButton("Lancer la fusion incrémentale & la normalisation")
        self.btn_start.setStyleSheet("background-color: #28A745; color: white; font-weight: bold; padding: 14px;")
        self.btn_start.clicked.connect(self.start_processing)
        layout.addWidget(self.btn_start)

        self.setLayout(layout)

    def browse_json_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Choisir le fichier JSON de référence", "", "Fichiers JSON (*.json)"
        )
        if file_path:
            self.selected_json_ref = file_path
            self.txt_json_path.setText(file_path)

    def browse_folder(self):
        folder_path = QFileDialog.getExistingDirectory(self, "Choisir le répertoire des professeurs")
        if folder_path:
            self.selected_folder = folder_path
            self.txt_folder_path.setText(folder_path)
            self.log_box.clear()
            self.progress_bar.setValue(0)

    def start_processing(self):
        if not self.selected_folder:
            QMessageBox.warning(self, "Erreur", "Veuillez sélectionner le répertoire des audios à traiter.")
            return

        json_info = f"• JSON de référence : {self.selected_json_ref}\n" if self.selected_json_ref else "• Aucun JSON de référence (Nouveau catalogue)\n"
        
        confirm = QMessageBox.question(
            self, "Confirmation requise", 
            f"{json_info}"
            f"• Dossier cible : {self.selected_folder}\n\n"
            f"Le fichier 'bibliotheque.json' sera généré/mis à jour dans le dossier cible sans rien supprimer du JSON de référence.\n"
            f"Les fichiers/dossiers physiques seront normalisés en slugs.\n\n"
            f"Voulez-vous continuer ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if confirm == QMessageBox.StandardButton.No:
            return

        self.btn_start.setEnabled(False)
        self.log_box.clear()
        
        self.thread = CatalogProcessingThread(
            root_folder=self.selected_folder, 
            reference_json_path=self.selected_json_ref
        )
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
            QMessageBox.information(self, "Succès", message)
        else:
            QMessageBox.critical(self, "Erreur", f"Le processus a échoué :\n{message}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = AudioRenamerApp()
    window.show()
    sys.exit(app.exec())
