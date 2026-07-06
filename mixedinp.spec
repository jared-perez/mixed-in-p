# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for Mixed in P

Build commands:
    Windows: pyinstaller mixedinp.spec
    macOS: pyinstaller mixedinp.spec

Output will be in dist/MixedInP/
"""

import sys
from pathlib import Path

# Determine platform-specific settings
is_windows = sys.platform == 'win32'
is_macos = sys.platform == 'darwin'

# Get the project root directory
project_root = Path(SPECPATH)

# Application metadata
APP_NAME = 'MixedInP'
APP_VERSION = '1.3.3'
APP_BUNDLE_ID = 'com.mixedinp.app'

# Entry point (must be src/main.py, not src/gui/app.py, so package imports work)
entry_point = str(project_root / 'src' / 'main.py')

# Data files to include
datas = [
    # Stylesheet template (palette tokens substituted at runtime)
    (str(project_root / 'src' / 'gui' / 'styles' / 'app.qss.template'), 'src/gui/styles'),
    # Assets (icons, panel backgrounds)
    (str(project_root / 'src' / 'gui' / 'assets'), 'src/gui/assets'),
    # Translations (.qm files; loaded at startup per the language setting)
    (str(project_root / 'src' / 'gui' / 'translations'), 'src/gui/translations'),
]

# Hidden imports that PyInstaller might miss
hiddenimports = [
    # PySide6 modules
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
    'PySide6.QtMultimedia',
    # Audio analysis
    'librosa',
    'librosa.core',
    'librosa.beat',
    'librosa.feature',
    'soundfile',
    'numpy',
    'scipy',
    'scipy.signal',
    'scipy.fft',
    # MP3 encoding
    'lameenc',
    # Audio playback (keyboard panel)
    'sounddevice',
    # Metadata
    'mutagen',
    'mutagen.mp3',
    'mutagen.flac',
    'mutagen.aiff',
    'mutagen.mp4',
    'mutagen.oggvorbis',
    'mutagen.wave',
    'mutagen.id3',
    'mutagen.easyid3',
    # Application modules
    'src.analysis',
    'src.analysis.analyzer',
    'src.analysis.bpm_detector',
    'src.analysis.key_detector',
    'src.analysis.keycode',
    'src.analysis.energy_detector',
    'src.analysis.result',
    'src.conversion',
    'src.conversion.converter',
    'src.conversion.result',
    'src.metadata',
    'src.metadata.tags',
    'src.renamer',
    'src.renamer.operations',
    'src.renamer.preview',
    'src.renamer.history',
    'src.utils',
    'src.utils.config',
    'src.utils.app_dirs',
    'src.utils.i18n',
    'src.gui',
    'src.gui.app',
    'src.gui.main_window',
    'src.gui.models',
    'src.gui.models.state',
    'src.gui.models.track_model',
    'src.gui.styles.theme',
    'src.gui.widgets',
    'src.gui.widgets.analysis_panel',
    'src.gui.widgets.linear_key_strip',
    'src.gui.widgets.loop_player',
    'src.gui.widgets.conversion_panel',
    'src.gui.widgets.drop_zone',
    'src.gui.widgets.droppable_table',
    'src.gui.widgets.header_bar',
    'src.gui.widgets.history_panel',
    'src.gui.widgets.player_panel',
    'src.gui.widgets.progress_bar',
    'src.gui.widgets.queue_panel',
    'src.gui.widgets.rename_panel',
    'src.gui.widgets.keyboard_panel',
    'src.gui.widgets.metadata_panel',
    'src.gui.widgets.range_slider',
    'src.gui.widgets.settings_panel',
    'src.gui.widgets.sidebar',
    'src.gui.widgets.slice_panel',
    'src.gui.widgets.dialogs',
    'src.gui.widgets.dialogs.about_dialog',
    'src.gui.workers',
    'src.gui.workers.analysis_worker',
    'src.gui.workers.conversion_worker',
    'src.gui.workers.rename_worker',
]

# Exclude unnecessary packages to reduce size
excludes = [
    'tkinter',
    'matplotlib',
    'PIL',
    'IPython',
    'jupyter',
    'notebook',
    'pytest',
    'sphinx',
]

# Analysis
a = Analysis(
    [entry_point],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

# Remove unnecessary Qt files to reduce size
a.binaries = [x for x in a.binaries if not x[0].startswith('libQt6Quick')]
a.binaries = [x for x in a.binaries if not x[0].startswith('libQt6Qml')]
a.binaries = [x for x in a.binaries if not x[0].startswith('libQt6Network')]

# PYZ archive
pyz = PYZ(a.pure, a.zipped_data)

# Icon paths
win_icon = str(project_root / 'resources' / 'icon.ico') if is_windows else None
mac_icon = str(project_root / 'resources' / 'icon.icns') if is_macos else None

# Executable - use onedir for all platforms (faster startup)
if is_macos:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name=APP_NAME,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=False,
        disable_windowed_traceback=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[
            # Qt / PySide6 DLLs — UPX can corrupt PE imports and AV flags them
            'Qt6*.dll',
            'PySide6*.dll',
            'shiboken6*.dll',
            # FFmpeg runtime (required by ffmpegmediaplugin.dll)
            'avcodec*.dll',
            'avformat*.dll',
            'avutil*.dll',
            'swresample*.dll',
            'swscale*.dll',
            # Qt multimedia plugins
            'ffmpegmediaplugin.dll',
            'windowsmediaplugin.dll',
            # MSVC runtime
            'vcruntime*.dll',
            'msvcp*.dll',
        ],
        name=APP_NAME,
    )
    app = BUNDLE(
        coll,
        name=f'{APP_NAME}.app',
        icon=mac_icon,
        bundle_identifier=APP_BUNDLE_ID,
        info_plist={
            'CFBundleName': APP_NAME,
            'CFBundleDisplayName': 'Mixed in P',
            'CFBundleVersion': APP_VERSION,
            'CFBundleShortVersionString': APP_VERSION,
            'NSHighResolutionCapable': True,
            'NSRequiresAquaSystemAppearance': False,
        },
    )
else:
    # Windows/Linux - onedir for faster startup
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name=APP_NAME,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,
        disable_windowed_traceback=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=win_icon,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[
            # Qt / PySide6 DLLs — UPX can corrupt PE imports and AV flags them
            'Qt6*.dll',
            'PySide6*.dll',
            'shiboken6*.dll',
            # FFmpeg runtime (required by ffmpegmediaplugin.dll)
            'avcodec*.dll',
            'avformat*.dll',
            'avutil*.dll',
            'swresample*.dll',
            'swscale*.dll',
            # Qt multimedia plugins
            'ffmpegmediaplugin.dll',
            'windowsmediaplugin.dll',
            # MSVC runtime
            'vcruntime*.dll',
            'msvcp*.dll',
        ],
        name=APP_NAME,
    )
