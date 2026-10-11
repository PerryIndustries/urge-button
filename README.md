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

**Updates:** the app keeps itself up to date from this repo (on start and every 6 hours, like Rift Pen). New versions download in the background and run the next time it starts, or right away from "Restart to update" in the right-click menu. It only updates a clean checkout of `main`, so local edits are never overwritten.

Your history and settings live in `%APPDATA%\UrgeButton\` (`events.json`, `config.json`), not in the repo. To bring your history to another computer, copy that folder across.

Tests: `python -m pytest tests`. Screenshots of any screen without locking (needs Pillow): `python urge_button.py --preview <dir> <options|sudoku|friend|walk|spotify|finish|progress|logged|settings|button>`.

## iPhone

Open https://perryindustries.github.io/urge-button/ in Safari, then Share, Add to Home Screen. Settings has backup and restore.

## One history on PC and phone

Both apps sync through `events.json` in the private repo `PerryIndustries/urge-data` (union by event id; the latest edit wins). A PC with the GitHub CLI logged in (`gh auth login`) needs nothing else. The phone, or a PC without `gh`, needs a token:

1. Open https://github.com/settings/personal-access-tokens/new
2. Name it "Urge Button", pick an expiry, Repository access: **Only select repositories** → `urge-data`
3. Permissions → Repository permissions → **Contents: Read and write**. Generate, copy.
4. Paste it into Settings → Sync on the phone (or the PC's "GitHub token" box) and save.

The phone app is built from `phone/urge-button.html` by `python phone/build_pwa.py` into `docs/`, which GitHub Pages serves. Edit the source, rebuild, commit, push.
