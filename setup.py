from setuptools import setup

APP = ['app.py']
OPTIONS = {
    'argv_emulation': False,
    'iconfile': 'GhostGauge.icns',
    'plist': {
        'CFBundleName': 'GhostGauge',
        'CFBundleDisplayName': 'GhostGauge',
        'CFBundleIdentifier': 'tech.ghostshift.ghostgauge',
        'CFBundleVersion': '1.0.0',
        'CFBundleShortVersionString': '1.0.0',
        'LSUIElement': True,  # menubar-only, no Dock icon
    },
    'resources': ['assets/claude-color.svg'],
    'packages': ['rumps', 'httpx', 'keyring', 'certifi'],
    'includes': ['core', 'keyring.backends.macOS', 'keyring.backends.SecretService',
                 'keyring.backends.chainer', 'keyring.backends.fail'],
}
setup(
    app=APP,
    name='GhostGauge',
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)
