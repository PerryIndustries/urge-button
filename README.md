# Urge Button

Press it when an urge hits. The screen locks for a few minutes, you pick something better to do (walk, music, Sudoku, text a friend), and every urge is tracked so you can see the trend.

## Windows

Needs Python 3.10+ from python.org (tkinter comes with it). Nothing else to install.

```
git clone https://github.com/PerryIndustries/urge-button.git
cd urge-button
python urge_button.py --install
```

`--install` puts an "Urge Button" shortcut on the desktop, sets it to start with Windows, and starts it now. Right-click the floating button for Progress, Sudoku, Settings and Quit; Ctrl+Alt+U triggers the lock from anywhere.

**Updates:** the app keeps itself up to date from this repo (on start and every 30 minutes, like Rift Pen). New versions download in the background and install themselves the first time nothing is open (no lock, no Sudoku, Settings or Progress window) and the keyboard and mouse have been quiet for two minutes - or right away from "Restart to update" in the right-click menu, or at the next start. It only updates a clean checkout of `main`, so local edits are never overwritten.

Your history and settings live in `%APPDATA%\UrgeButton\` (`events.json`, `sudoku.json`, `config.json`), not in the repo. To bring your history to another computer, copy that folder across.

Tests: `python -m pytest tests`. Screenshots of any screen without locking (needs Pillow): `python urge_button.py --preview <dir> <options|sudoku|friend|walk|spotify|finish|progress|logged|settings|button|sudokuwin|sudokusolved|sudokunew>`.

## Sudoku

Sudoku is there during a lock and on its own: right-click the button on the PC, or the Sudoku tab on the phone. It plays like sudoku.com: tap a cell and its row, column, box and every matching digit light up; the number pad shows how many of each digit are left and drops a digit once all nine are placed; Notes pencils small candidates into a cell (a correct digit clears it from the cells around it); Undo, Erase and Hint do what they say; a wrong digit turns red and counts as a mistake; a finished row, column or box flashes; the clock only runs while the board is in front of you, with Pause. Keyboard on the PC: 1-9 place, 0 or Backspace erases, N toggles notes, Ctrl+Z undoes, arrows move.

Four difficulties - Easy, Medium, Hard, Expert (38, 32, 27, 23 clues) - and every puzzle has exactly one answer. The puzzle in progress is saved after every move, so unlocking, closing the window or restarting never loses it, and picking Sudoku during a lock carries on where you were (or starts a new one at your last difficulty). Every finished or abandoned game goes on your record: solved totals, this week, the daily streak, best and average times per difficulty, perfect games (no mistakes, no hints) and the last ten games, marked when they were played during an urge.

## iPhone

Open https://perryindustries.github.io/urge-button/ in Safari, then Share, Add to Home Screen. Settings has backup and restore.

## One history on PC and phone

Both apps sync through two files in the private repo `PerryIndustries/urge-data`: `events.json` for urges and `sudoku.json` for Sudoku (the record of games, plus the puzzle in progress). Records merge as a union by id with the latest edit winning; the puzzle in progress is whichever copy was saved last, so you can start on the PC and finish on the phone. A PC with the GitHub CLI logged in (`gh auth login`) needs nothing else. The phone, or a PC without `gh`, needs a token:

1. Open https://github.com/settings/personal-access-tokens/new
2. Name it "Urge Button", pick an expiry, Repository access: **Only select repositories** → `urge-data`
3. Permissions → Repository permissions → **Contents: Read and write**. Generate, copy.
4. Paste it into Settings → Sync on the phone (or the PC's "GitHub token" box) and save.

The phone app is built from `phone/urge-button.html` by `python phone/build_pwa.py` into `docs/`, which GitHub Pages serves. Edit the source, rebuild, commit, push.
