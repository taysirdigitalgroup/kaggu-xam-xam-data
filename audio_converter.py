import sys
import os
import re
import subprocess
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QFileDialog, QLabel, QComboBox, 
                             QProgressBar, QMessageBox, QRadioButton, QButtonGroup, QLineEdit)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

# Extensions audio supportées lors du scan d'un dossier
SUPPORTED_EXTENSIONS = ('.mp3', '.aac', '.wav', '.m4a', '.flac', '.wma', '.ogg')

def natural_sort_key(s):
    """ Clé de tri permettant un tri alphanumérique naturel (ex: 2 avant 10) """
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]

def format_filename(name):
    """ Rend le nom en minuscule, remplace les caractères non-alphanumériques par un unique underscore """
    base_name = os.path.splitext(name)[0].lower()
    # Remplacement des caractères accentués courants pour éviter les résidus bizarres
    accent_map = str.maketrans("àâäéèêëîïôöùûüç", "aaaeeeeiioouuuc")
    base_name = base_name.translate(accent_map)
    # Remplace tout ce qui n'est pas alphanumérique par un underscore
    clean_name = re.sub(r'[^a-z0-9]+', '_', base_name)
    # Nettoie les underscores multiples ou en bordure
    clean_name = clean_name.strip('_')
    return clean_name + ".ogg"

def format_directory_path(relative_path):
    """ Capitalise chaque dossier composant le chemin relatif """
    if relative_path == ".":
        return ""
    parts = relative_path.split(os.sep)
    # Met une majuscule au début de chaque mot dans chaque nom de dossier
    formatted_parts = [title_folder(part) for part in parts]
    return os.path.join(*formatted_parts)

def title_folder(folder_name):
    """ Capitalise proprement les mots d'un dossier """
    return ' '.join([word.capitalize() for word in folder_name.split()])

class BatchConversionThread(QThread):
    file_progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(bool, str)

    def __init__(self, target_path, output_dir, is_dir, target_bitrate):
        super().__init__()
        self.target_path = target_path
        self.output_dir = output_dir
        self.is_dir = is_dir
        self.bitrate = target_bitrate

    def run(self):
        files_to_convert = []

        # 1. Collecte des fichiers à traiter
        if not self.is_dir:
            files_to_convert.append(self.target_path)
        else:
            for root, _, files in os.walk(self.target_path):
                # Application du tri naturel sur les fichiers du dossier en cours
                sorted_files = sorted(files, key=natural_sort_key)
                for file in sorted_files:
                    if file.lower().endswith(SUPPORTED_EXTENSIONS):
                        files_to_convert.append(os.path.join(root, file))

        total_files = len(files_to_convert)
        if total_files == 0:
            self.finished.emit(False, "Aucun fichier audio valide trouvé.")
            return

        success_count = 0
        skipped_count = 0

        # 2. Boucle de traitement
        for index, input_file in enumerate(files_to_convert):
            filename = os.path.basename(input_file)
            self.file_progress.emit(index + 1, total_files, filename)

            # Application des règles de formatage pour la sortie
            clean_audio_name = format_filename(filename)

            if self.is_dir:
                relative_path = os.path.relpath(os.path.dirname(input_file), self.target_path)
                formatted_rel_path = format_directory_path(relative_path)
                output_file = os.path.join(self.output_dir, formatted_rel_path, clean_audio_name)
            else:
                output_file = os.path.join(self.output_dir, clean_audio_name)

            # SKIPPED : Si l'audio formaté existe déjà dans le répertoire cible, on passe
            if os.path.exists(output_file):
                success_count += 1
                skipped_count += 1
                continue

            os.makedirs(os.path.dirname(output_file), exist_ok=True)

            # Filtre coupe-bas linéaire uniquement (Sans aucune suppression de silences)
            audio_filter = "highpass=f=85"

            cmd = [
                'ffmpeg', '-y', 
                '-i', input_file,
                '-af', audio_filter,
                '-ac', '1',
                '-c:a', 'libopus',
                '-b:a', f'{self.bitrate}k',
                '-vbr', 'on',
                '-compression_level', '10', 
                output_file
            ]

            try:
                process = subprocess.Popen(
                    cmd, 
                    stdout=subprocess.DEVNULL, 
                    stderr=subprocess.DEVNULL,
                    close_fds=True
                )
                
                # Attente maximale de 15 minutes (900 secondes) pour les longs fichiers
                process.wait(timeout=900)
                
                if process.returncode == 0:
                    success_count += 1
                else:
                    # Arrêt immédiat de l'application en cas d'erreur d'encodage brute
                    self.finished.emit(False, f"Le processus a échoué sur le fichier :\n{filename}\n\nLe traitement a été interrompu par sécurité.")
                    return

            except subprocess.TimeoutExpired:
                # Blocage ou dépassement des 15mn : on tue le processus et on stoppe tout immédiatement
                process.kill()
                process.wait()
                self.finished.emit(False, f"Temps limite dépassé (15 min) sur le fichier :\n{filename}\n\nLe traitement a été stoppé pour éviter un enregistrement tronqué.")
                return
            except Exception as e:
                self.finished.emit(False, f"Une erreur critique est survenue sur le fichier :\n{filename}\nDétails : {str(e)}")
                return

        msg = f"Traitement terminé avec succès.\n\n• Réussis ou Ignorés : {success_count}/{total_files}\n• Déjà présents (skippés) : {skipped_count}\n\nDestination : {self.output_dir}"
        self.finished.emit(True, msg)


class AudioCompressorApp(QWidget):
    def __init__(self):
        super().__init__()
        self.selected_path = ""
        self.output_path = os.path.abspath(".")
        self.initUI()

    def initUI(self):
        self.setWindowTitle("TDG Mass Audio Optimizer")
        self.setMinimumSize(550, 380)
        
        layout = QVBoxLayout()
        layout.setSpacing(12)

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

        layout.addWidget(QLabel("<b>Source :</b>"))
        file_layout = QHBoxLayout()
        self.lbl_file = QLabel("Aucune sélection effectuée")
        self.lbl_file.setStyleSheet("color: #666; font-style: italic;")
        self.btn_browse = QPushButton("Parcourir")
        self.btn_browse.clicked.connect(self.browse_target)
        file_layout.addWidget(self.lbl_file, stretch=3)
        file_layout.addWidget(self.btn_browse, stretch=1)
        layout.addLayout(file_layout)

        layout.addWidget(QLabel("<b>Dossier de destination :</b>"))
        out_layout = QHBoxLayout()
        self.txt_output = QLineEdit(self.output_path)
        self.btn_browse_out = QPushButton("Changer")
        self.btn_browse_out.clicked.connect(self.browse_output)
        out_layout.addWidget(self.txt_output, stretch=3)
        out_layout.addWidget(self.btn_browse_out, stretch=1)
        layout.addLayout(out_layout)

        bitrate_layout = QHBoxLayout()
        lbl_bitrate = QLabel("Qualité / Bitrate (Mono) :")
        self.combo_bitrate = QComboBox()
        self.combo_bitrate.addItems(["10 kbps (Compression Maximale - Voix uniquement)",
                                     "12 kbps (Ultra-Compression - Spécial Voix)", 
                                     "16 kbps (Excellent compromis Voix)", 
                                     "24 kbps (Haute qualité voix / Radio)", 
                                     "32 kbps (Qualité standard)"])
        self.combo_bitrate.setCurrentIndex(0) 
        bitrate_layout.addWidget(lbl_bitrate)
        bitrate_layout.addWidget(self.combo_bitrate)
        layout.addLayout(bitrate_layout)

        self.progress_bar = QProgressBar()
        self.progress_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.lbl_result = QLabel("")
        self.lbl_result.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_result.setWordWrap(True)
        layout.addWidget(self.lbl_result)

        self.btn_convert = QPushButton("Lancer le traitement en masse")
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

    def browse_output(self):
        path = QFileDialog.getExistingDirectory(self, "Sélectionner le dossier de destination")
        if path:
            self.output_path = path
            self.txt_output.setText(path)

    def start_conversion(self):
        if not self.selected_path:
            QMessageBox.warning(self, "Erreur", "Veuillez faire une sélection (fichier ou dossier) avant de continuer.")
            return
        
        final_output_dir = self.txt_output.text().strip()
        if not final_output_dir:
            QMessageBox.warning(self, "Erreur", "Veuillez spécifier un dossier de destination valide.")
            return

        bitrates = [10, 12, 16, 24, 32]
        target_bitrate = bitrates[self.combo_bitrate.currentIndex()]
        is_dir = self.radio_dir.isChecked()

        self.btn_convert.setEnabled(False)
        self.btn_browse.setEnabled(False)
        self.btn_browse_out.setEnabled(False)
        self.radio_file.setEnabled(False)
        self.radio_dir.setEnabled(False)
        self.lbl_result.setText("Traitement audio en cours...")

        self.thread = BatchConversionThread(self.selected_path, final_output_dir, is_dir, target_bitrate)
        self.thread.file_progress.connect(self.on_file_progress)
        self.thread.finished.connect(self.on_conversion_finished)
        self.thread.start()

    def on_file_progress(self, current, total, filename):
        percent = int((current / total) * 100)
        self.progress_bar.setValue(percent)
        self.lbl_result.setText(f"Traitement {current}/{total} :\n👉 {filename}")

    def on_conversion_finished(self, success, message):
        self.btn_convert.setEnabled(True)
        self.btn_browse.setEnabled(True)
        self.btn_browse_out.setEnabled(True)
        self.radio_file.setEnabled(True)
        self.radio_dir.setEnabled(True)

        if success:
            self.progress_bar.setValue(100)
            self.lbl_result.setText("🎉 Opération terminée !")
            QMessageBox.information(self, "Terminé !", message)
        else:
            self.progress_bar.setValue(0)
            self.lbl_result.setText("❌ Échec du processus.")
            QMessageBox.critical(self, "Erreur", message)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = AudioCompressorApp()
    window.show()
    sys.exit(app.exec())
