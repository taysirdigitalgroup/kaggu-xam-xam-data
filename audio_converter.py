import sys
import os
import subprocess
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QFileDialog, QLabel, QComboBox, 
                             QProgressBar, QMessageBox, QRadioButton, QButtonGroup)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

# Extensions audio supportées lors du scan d'un dossier
SUPPORTED_EXTENSIONS = ('.mp3', '.aac', '.wav', '.m4a', '.flac', '.wma', '.ogg')

class BatchConversionThread(QThread):
    # Émet (index_fichier_actuel, total_fichiers, nom_fichier_actuel)
    file_progress = pyqtSignal(int, int, str)
    # Émet (succès_global, message_final)
    finished = pyqtSignal(bool, str)

    def __init__(self, target_path, is_dir, target_bitrate):
        super().__init__()
        self.target_path = target_path
        self.is_dir = is_dir
        self.bitrate = target_bitrate

    def run(self):
        files_to_convert = []

        # 1. Collecte des fichiers à traiter
        if not self.is_dir:
            files_to_convert.append(self.target_path)
        else:
            # os.walk scanne récursivement le dossier et tous ses sous-dossiers
            for root, _, files in os.walk(self.target_path):
                for file in files:
                    if file.lower().endswith(SUPPORTED_EXTENSIONS):
                        files_to_convert.append(os.path.join(root, file))

        total_files = len(files_to_convert)
        if total_files == 0:
            self.finished.emit(False, "Aucun fichier audio valide trouvé.")
            return

        # 2. Définition du dossier de sortie global
        if self.is_dir:
            output_base_dir = f"{self.target_path}_Opus_{self.bitrate}k"
        else:
            output_base_dir = os.path.dirname(self.target_path)

        success_count = 0

        # 3. Boucle de conversion
        for index, input_file in enumerate(files_to_convert):
            filename = os.path.basename(input_file)
            self.file_progress.emit(index + 1, total_files, filename)

            # Déterminer le chemin de sortie en conservant l'arborescence
            if self.is_dir:
                # Récupère le chemin relatif par rapport au dossier racine sélectionné
                relative_path = os.path.relpath(input_file, self.target_path)
                output_file = os.path.join(output_base_dir, relative_path)
                # Remplace l'extension d'origine par .ogg
                output_file = os.path.splitext(output_file)[0] + ".ogg"
            else:
                base_path, _ = os.path.splitext(input_file)
                output_file = f"{base_path}_compressed_{self.bitrate}k.ogg"

            # Créer les sous-dossiers de destination s'ils n'existent pas encore
            os.makedirs(os.path.dirname(output_file), exist_ok=True)

            # Exécution de FFmpeg en mode silencieux
            cmd = [
                'ffmpeg', '-y', 
                '-i', input_file,
                '-ac', '1',
                '-c:a', 'libopus',
                '-b:a', f'{self.bitrate}k',
                '-vbr', 'on',
                output_file
            ]

            try:
                process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                process.wait()
                if process.returncode == 0:
                    success_count += 1
            except Exception:
                continue # Passe au fichier suivant si celui-ci échoue

        # Message de fin avec statistiques
        if success_count == total_files:
            msg = f"Tous les fichiers ({success_count}/{total_files}) ont été convertis avec succès.\nDestination : {output_base_dir}"
            self.finished.emit(True, msg)
        else:
            msg = f"Conversion complétée avec des erreurs.\nConvertis : {success_count}/{total_files}.\nDestination : {output_base_dir}"
            self.finished.emit(True, msg)


class AudioCompressorApp(QWidget):
    def __init__(self):
        super().__init__()
        self.selected_path = ""
        self.initUI()

    def initUI(self):
        self.setWindowTitle("TDG Mass Audio Optimizer - Opus Converter")
        self.setMinimumSize(550, 320)
        
        layout = QVBoxLayout()
        layout.setSpacing(15)

        # Section 1 : Choix Mode (Fichier ou Dossier)
        mode_layout = QHBoxLayout()
        self.radio_file = QRadioButton("Fichier unique")
        self.radio_dir = QRadioButton("Dossier complet (Inclus sous-dossiers)")
        self.radio_file.setChecked(True)
        
        self.mode_group = QButtonGroup()
        self.mode_group.addButton(self.radio_file)
        self.mode_group.addButton(self.radio_dir)
        
        self.radio_file.toggled.connect(self.reset_selection)
        
        mode_layout.addWidget(self.radio_file)
        mode_layout.addWidget(self.radio_dir)
        layout.addLayout(mode_layout)

        # Section 2 : Sélection du fichier/dossier
        file_layout = QHBoxLayout()
        self.lbl_file = QLabel("Aucune sélection effectuée")
        self.lbl_file.setStyleSheet("color: #666; font-style: italic;")
        self.btn_browse = QPushButton("Parcourir")
        self.btn_browse.clicked.connect(self.browse_target)
        file_layout.addWidget(self.lbl_file, stretch=3)
        file_layout.addWidget(self.btn_browse, stretch=1)
        layout.addLayout(file_layout)

        # Section 3 : Choix du Bitrate
        bitrate_layout = QHBoxLayout()
        lbl_bitrate = QLabel("Qualité / Bitrate (Mono) :")
        self.combo_bitrate = QComboBox()
        self.combo_bitrate.addItems(["12 kbps (Ultra-Compression - Spécial Coran/Voix)", 
                                     "16 kbps (Excellent compromis Voix)", 
                                     "24 kbps (Haute qualité voix / Radio)", 
                                     "32 kbps (Qualité standard Musique)"])
        bitrate_layout.addWidget(lbl_bitrate)
        bitrate_layout.addWidget(self.combo_bitrate)
        layout.addLayout(bitrate_layout)

        # Section 4 : Progression et statistiques
        self.progress_bar = QProgressBar()
        self.progress_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.lbl_result = QLabel("")
        self.lbl_result.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_result.setWordWrap(True)
        layout.addWidget(self.lbl_result)

        # Section 5 : Bouton d'action
        self.btn_convert = QPushButton("Lancer la conversion en masse")
        self.btn_convert.setStyleSheet("background-color: #28A745; color: white; font-weight: bold; padding: 12px;")
        self.btn_convert.clicked.connect(self.start_conversion)
        layout.addWidget(self.btn_convert)

        self.setLayout(layout)

    def reset_selection(self):
        self.selected_path = ""
        self.lbl_file.setText("Aucune sélection effectuée")
        self.progress_bar.setValue(0)
        self.lbl_result.setText("")

    def browse_target(self):
        if self.radio_file.isChecked():
            file_filter = "Fichiers Audio (*.mp3 *.aac *.wav *.m4a *.flac *.wma *.ogg)"
            path, _ = QFileDialog.getOpenFileName(self, "Sélectionner un fichier audio d'origine", "", file_filter)
        else:
            path = QFileDialog.getExistingDirectory(self, "Sélectionner le dossier racine contenant les audios")

        if path:
            self.selected_path = path
            self.lbl_file.setText(os.path.basename(path) if self.radio_file.isChecked() else path)
            self.lbl_result.setText("")
            self.progress_bar.setValue(0)

    def start_conversion(self):
        if not self.selected_path:
            QMessageBox.warning(self, "Erreur", "Veuillez faire une sélection (fichier ou dossier) avant de continuer.")
            return

        bitrates = [12, 16, 24, 32]
        target_bitrate = bitrates[self.combo_bitrate.currentIndex()]
        is_dir = self.radio_dir.isChecked()

        # Blocage de l'interface graphique
        self.btn_convert.setEnabled(False)
        self.btn_browse.setEnabled(False)
        self.radio_file.setEnabled(False)
        self.radio_dir.setEnabled(False)
        self.lbl_result.setText("Initialisation du scan des fichiers...")

        # Initialisation du thread récursif en tâche de fond
        self.thread = BatchConversionThread(self.selected_path, is_dir, target_bitrate)
        self.thread.file_progress.connect(self.on_file_progress)
        self.thread.finished.connect(self.on_conversion_finished)
        self.thread.start()

    def on_file_progress(self, current, total, filename):
        # Calcul du pourcentage d'avancement du dossier global
        percent = int((current / total) * 100)
        self.progress_bar.setValue(percent)
        self.lbl_result.setText(f"Traitement du fichier {current}/{total} :\n👉 {filename}")

    def on_conversion_finished(self, success, message):
        # Déblocage de l'interface graphique
        self.btn_convert.setEnabled(True)
        self.btn_browse.setEnabled(True)
        self.radio_file.setEnabled(True)
        self.radio_dir.setEnabled(True)

        if success:
            self.progress_bar.setValue(100)
            self.lbl_result.setText("🎉 Conversion terminée avec succès !")
            QMessageBox.information(self, "Terminé !", message)
        else:
            self.progress_bar.setValue(0)
            self.lbl_result.setText("❌ Échec de la procédure.")
            QMessageBox.critical(self, "Erreur", message)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = AudioCompressorApp()
    window.show()
    sys.exit(app.exec())
