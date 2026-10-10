# Urge Button

Press it when an urge hits. The screen locks for a few minutes, you pick something better to do (walk, music, Sudoku, text a friend), and every urge is tracked so you can see the trend.

## Windows

Needs Python 3.10+ from python.org (tkinter comes with it). Nothing else to install.

```
git clone https://github.com/PerryIndustries/urge-button.git
cd urge-button
python urge_button.py --install
```

`--install` puts an "Urge Button" shortcut on the desktop, sets it to start with Windows, and starts it now. Right-click the floating button for Progress, Settings and Quit; Ctrl+Alt+U triggers the lock from anywhere.

Your history and settings live in `%APPDATA%\UrgeButton\` (`events.json`, `config.json`), not in the repo. To bring your history to another computer, copy that folder across.

Tests: `python -m pytest tests`. Screenshots of any screen without locking (needs Pillow): `python urge_button.py --preview <dir> <options|sudoku|friend|walk|spotify|finish|progress|logged|settings|button>`.

## iPhone

Open https://perryindustries.github.io/urge-button/ in Safari, then Share, Add to Home Screen. History stays on the phone; Settings has backup and restore.

The phone app is built from `phone/urge-button.html` by `python phone/build_pwa.py` into `docs/`, which GitHub Pages serves. Edit the source, rebuild, commit, push.
