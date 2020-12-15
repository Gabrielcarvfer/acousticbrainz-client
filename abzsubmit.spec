# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

import sys
project_binaries = [("streaming_extractor_music" + ("" if sys.platform != "win32" else ".exe"), "./")]


a = Analysis(['abzsubmit.py'],
             pathex=['E:/tools/source/acousticbrainz-client'],
             binaries=project_binaries,
             datas=[],
             hiddenimports=[],
             hookspath=[],
             runtime_hooks=[],
             excludes=[],
             win_no_prefer_redirects=False,
             win_private_assemblies=False,
             cipher=block_cipher,
             noarchive=False)
pyz = PYZ(a.pure, a.zipped_data,
             cipher=block_cipher)
exe = EXE(pyz,
          a.scripts,
          [],
          exclude_binaries=True,
          name='abzsubmit',
          debug=False,
          bootloader_ignore_signals=False,
          strip=False,
          upx=True,
          console=True )

coll = COLLECT(exe,
               a.binaries,
               a.zipfiles,
               a.datas,
               strip=False,
               upx=True,
               upx_exclude=[],
               name='abzsubmit')
