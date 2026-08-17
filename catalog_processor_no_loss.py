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
    Si le nom est un slug normalisé, il le dé-normalise avant de le capitaliser.
    """
    if not name:
        return ""
    
    # Nettoyage des caractères spéciaux résiduels avant formatage visuel
    cleaned = re.sub(r"['\(\)\-@%]", " ", name)
    cleaned = unicodedata.normalize('NFD', cleaned)
    cleaned = "".join([c for c in cleaned if unicodedata.category(c) != 'Mn'])
    
    if re.match(r'^[a-z0-9_]+$', cleaned.lower()):
        cleaned = cleaned.replace("_", " ")
        
    return re.sub(r'\s+', ' ', cleaned).title().strip()

def natural_sort_key(text):
    """
    Clé de tri naturel permettant de trier correctement les nombres
    ex: 'piste_1', 'piste_2', 'piste_10' au lieu de 'piste_1', 'piste_10', 'piste_2'.
    """
    return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', text)]

def consolidate_json_structure(raw_json):
    """
    Nettoie et consolide un dictionnaire JSON en fusionnant les Professeurs
    et Thèmes ayant le même slug (ex: "Irwà-Un Nadìm" et "Irwa Un Nadim").
    """
    consolidated = {}
    
    for prof_key, themes in raw_json.items():
        prof_slug = to_slug(prof_key)
        
        # Recherche si le prof existe déjà sous un autre nom équivalent
        matched_prof_key = None
        for p_key in consolidated.keys():
            if to_slug(p_key) == prof_slug:
                matched_prof_key = p_key
                break
        
        if not matched_prof_key:
            matched_prof_key = format_folder_name(prof_key)
            consolidated[matched_prof_key] = {}
            
        if isinstance(themes, dict):
            for theme_key, tracks in themes.items():
                theme_slug = to_slug(theme_key)
                
                # Recherche si le thème existe déjà sous un autre nom équivalent
                matched_theme_key = None
                for t_key in consolidated[matched_prof_key].keys():
                    if to_slug(t_key) == theme_slug:
                        matched_theme_key = t_key
                        break
                
                if not matched_theme_key:
                    matched_theme_key = format_folder_name(theme_key)
                    consolidated[matched_prof_key][matched_theme_key] = []
                
                # Fusion des pistes audio sans doublons
                existing_tracks = set(consolidated[matched_prof_key][matched_theme_key])
                if isinstance(tracks, list):
                    for track in tracks:
                        existing_tracks.add(track)
                        
                consolidated[matched_prof_key][matched_theme_key] = sorted(list(existing_tracks), key=natural_sort_key)
                
    return consolidated


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
            # ÉTAPE 0 : CHARGEMENT & CONSOLIDATION DU JSON DE RÉFÉRENCE
            # -----------------------------------------------------------------
            bibliotheque = {}
            if self.reference_json_path and self.reference_json_path.exists():
                try:
                    with open(self.reference_json_path, 'r', encoding='utf-8') as f:
                        raw_data = json.load(f)
                    # Consolidation préalable des doublons dans le fichier de référence
                    bibliotheque = consolidate_json_structure(raw_data)
                    self.log_signal.emit(f"📖 JSON de référence chargé et nettoyé des doublons : '{self.reference_json_path.name}'.")
                except Exception as e:
                    self.log_signal.emit(f"⚠️ Erreur de lecture du JSON de référence ({e}). Création d'une nouvelle structure.")
                    bibliotheque = {}
            else:
                self.log_signal.emit("ℹ️ Aucun JSON de référence fourni. Création d'un nouveau catalogue.")

            # -----------------------------------------------------------------
            # ÉTAPE 1 : SCAN ET FUSION ANTI-REDONDANCE DES AUDIOS DU DISQUE
            # -----------------------------------------------------------------
            self.log_signal.emit("📝 Étape 1 : Analyse des dossiers et fusion incrémentale par Slug...")

            profs = sorted([d for d in os.listdir(self.root_folder) if (self.root_folder / d).is_dir()], key=natural_sort_key)
            
            for prof in profs:
                prof_path = self.root_folder / prof
                target_prof_slug = to_slug(prof)
                
                # 1. Correspondance Professeur par Slug
                matched_prof_key = None
                for p_key in bibliotheque.keys():
                    if to_slug(p_key) == target_prof_slug:
                        matched_prof_key = p_key
                        break
                
                if not matched_prof_key:
                    matched_prof_key = format_folder_name(prof)
                    bibliotheque[matched_prof_key] = {}
                
                themes = sorted([t for t in os.listdir(prof_path) if (prof_path / t).is_dir()], key=natural_sort_key)
                
                for theme in themes:
                    theme_path = prof_path / theme
                    target_theme_slug = to_slug(theme)
                    
                    # 2. Correspondance Thème par Slug
                    matched_theme_key = None
                    for t_key in bibliotheque[matched_prof_key].keys():
                        if to_slug(t_key) == target_theme_slug:
                            matched_theme_key = t_key
                            break
                    
                    if not matched_theme_key:
                        matched_theme_key = format_folder_name(theme)
                        bibliotheque[matched_prof_key][matched_theme_key] = []
                    
                    # 3. Fusion des pistes du dossier
                    pistes_existantes = set(bibliotheque[matched_prof_key][matched_theme_key])
                    fichiers = sorted([f for f in os.listdir(theme_path) if (theme_path / f).is_file()], key=natural_sort_key)
                    
                    for f in fichiers:
                        name, ext = os.path.splitext(f)
                        new_filename = to_slug(name) + ext.lower()
                        pistes_existantes.add(new_filename)
                        
                    # Re-tri naturel des pistes du thème
                    bibliotheque[matched_prof_key][matched_theme_key] = sorted(list(pistes_existantes), key=natural_sort_key)

            # -----------------------------------------------------------------
            # ÉTAPE 2 : ORGANISATION FINALE ET SAUVEGARDE DU JSON
            # -----------------------------------------------------------------
            bibliotheque_organisee = {}
            for prof_key in sorted(bibliotheque.keys(), key=natural_sort_key):
                bibliotheque_organisee[prof_key] = {}
                for theme_key in sorted(bibliotheque[prof_key].keys(), key=natural_sort_key):
                    pistes = sorted(bibliotheque[prof_key][theme_key], key=natural_sort_key)
                    bibliotheque_organisee[prof_key][theme_key] = pistes

            with open(json_output_path, 'w', encoding='utf-8') as f:
                json.dump(bibliotheque_organisee, f, indent=4, ensure_ascii=False)
                
            self.log_signal.emit(f"💾 JSON nettoyé et sauvegardé dans : {json_output_path}")

            # -----------------------------------------------------------------
            # ÉTAPE 3 : NORMALISATION DES FICHIERS ET DOSSIERS PHYSIQUES
            # -----------------------------------------------------------------
            self.log_signal.emit("🔄 Étape 3 : Normalisation physique des fichiers/dossiers sur le disque...")
            
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
                self.finished_signal.emit(True, "JSON fusionné et nettoyé avec succès.")
                return

            processed_count = 0

            # Renommage des fichiers
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

            # Renommage des dossiers (de bas en haut)
            for root, d in all_dirs:
                new_dir_name = to_slug(d)
                
                old_path = os.path.join(root, d)
                new_path = os.path.join(root, new_dir_name)
                
                if old_path != new_path:
                    os.rename(old_path, new_path)
                    self.log_signal.emit(f"📁 Dossier renommé : {d} ➡️ {new_dir_name}")
                    
                processed_count += 1
                self.progress_signal.emit(int((processed_count / total_elements) * 100))

            self.finished_signal.emit(True, f"Traitement réussi !\nLes entités de thèmes/profs en doublon ont été fusionnées et {processed_count} éléments normalisés.")
            
        except Exception as e:
            self.finished_signal.emit(False, str(e))


class AudioRenamerApp(QWidget):
    def __init__(self):
        super().__init__()
        self.selected_folder = ""
        self.selected_json_ref = ""
        self.initUI()

    def initUI(self):
        self.setWindowTitle("TDG Catalog Engine - Deduplicated Incremental Merge")
        self.setMinimumSize(700, 520)
        
        layout = QVBoxLayout()
        layout.setSpacing(12)

        # Section 1 : JSON de référence
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

        # Section 2 : Dossier des audios à traiter
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
        self.btn_start = QPushButton("Lancer la déduplication & la normalisation")
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

        json_info = f"• JSON de référence : {self.selected_json_ref}\n" if self.selected_json_ref else "• Aucun JSON de référence\n"
        
        confirm = QMessageBox.question(
            self, "Confirmation requise", 
            f"{json_info}"
            f"• Dossier cible : {self.selected_folder}\n\n"
            f"Le script va fusionner les entités redondantes (ex: accents ou tirets) en se basant sur le slug unique.\n"
            f"Voulez-vous démarrer la procédure ?",
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
