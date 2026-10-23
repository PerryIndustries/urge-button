# Urge Button

Press it when an urge hits. The screen locks for a few minutes, you pick something better to do (walk, music, Sudoku, text a friend), and every urge is tracked so you can see the trend.

Beside it is a smaller **Bored** button for the mindless kind of restlessness: no lock, just three quick ideas (Sudoku, a stretch, a glass of water, a few pages, music...), one tap to pick one, and the idea then runs right there in the panel (on the phone, in the sheet): a box for what's on your mind, with everything you've saved under Your notes (delete any of them); a guided two-minute stretch, six stretches of twenty seconds with Pause; five-minute timers for stepping outside (then a line for what you noticed), tidying one surface (it suggests one, or a different one) and any idea of your own; ten minutes for reading (how many pages?) and for practising (it remembers what); the lock screen's text-a-friend flow; a glass of water, with today's count. Sudoku and music still just open. Each ends with Done or Stop, and the timers read the clock rather than counting ticks, so putting the window or the app away loses no time. The press is tracked on its own - Progress has a Boredom section (today, this week, finished of picked, time on it, 30 days, when it hits, what you picked and how often you finished it, your notes, and how often an urge followed within the hour) and nothing about urges counts it. The ideas are yours to edit in Settings, one per line.

## Windows

Needs Python 3.10+ from python.org (tkinter comes with it). Nothing else to install.

```
git clone https://github.com/PerryIndustries/urge-button.git
cd urge-button
python urge_button.py --install
```

`--install` puts an "Urge Button" shortcut on the desktop, sets it to start with Windows, and starts it now. Right-click the floating button for Progress, Sudoku, "I'm bored", Settings and Quit; Ctrl+Alt+U triggers the lock from anywhere and Ctrl+Alt+B opens the Bored ideas.

**Food timer:** the orange Food button starts a 5-minute timer (it survives a restart). Press it again to see what is left, add 5/15/30 minutes or 1 hour, or cancel; the mouse wheel over Food adds or takes off 5 minutes. When it runs out a big silent "Your order is here" note fills the middle of the button's monitor, with +5/+10/+15 min if the order is late and Got it to clear it.

**Alarm:** when the Wake Alarm is installed in `~/Alarm` (PerryIndustries/wake-alarm), a purple Alarm button sits after Food. It shows when the alarm next rings (`9am` today, `Sat 11am` later, `off` with none set, refreshed every 5 minutes) and opens the alarm panel: alarms, typing speed and the night screen timer.

**Updates:** the app keeps itself up to date from this repo (on start and every 30 minutes, like Rift Pen). New versions download in the background and install themselves the first time nothing is open (no lock, no Sudoku, Settings or Progress window) and the keyboard and mouse have been quiet for two minutes - or right away from "Restart to update" in the right-click menu, or at the next start. It only updates a clean checkout of `main`, so local edits are never overwritten.

Your history and settings live in `%APPDATA%\UrgeButton\` (`events.json`, `sudoku.json`, `config.json`), not in the repo. To bring your history to another computer, copy that folder across.

Tests: `python -m pytest tests`. Screenshots of any screen without locking (needs Pillow): `python urge_button.py --preview <dir> <options|sudoku|friend|walk|spotify|finish|progress|logged|settings|button|sudokuwin|sudokusolved|sudokunew|bored|boredwrite|boredstretch|boredtimer|boredtidy|boredread|boredpractice|boredfriend|boredwater|boredcustom|borednotes|borednoticed|boredpages|boredpicked|headsup|cluster>`.

## Sudoku

Sudoku is there during a lock and on its own: right-click the button on the PC, or the Sudoku tab on the phone. It plays like sudoku.com: tap a cell and its row, column, box and every matching digit light up; the number pad shows how many of each digit are left and drops a digit once all nine are placed; Notes pencils small candidates into a cell (a correct digit clears it from the cells around it); Undo, Erase and Hint do what they say; a wrong digit turns red and counts as a mistake; a finished row, column or box flashes; the clock only runs while the board is in front of you, with Pause. Keyboard on the PC: 1-9 place, 0 or Backspace erases, N toggles notes, Ctrl+Z undoes, arrows move.

Four difficulties - Easy, Medium, Hard, Expert (38, 32, 27, 23 clues) - and every puzzle has exactly one answer. The puzzle in progress is saved after every move, so unlocking, closing the window or restarting never loses it, and picking Sudoku during a lock carries on where you were (or starts a new one at your last difficulty). Every finished or abandoned game goes on your record: solved totals, this week, the daily streak, best and average times per difficulty, perfect games (no mistakes, no hints) and the last ten games, marked when they were played during an urge.

## iPhone

Open https://perryindustries.github.io/urge-button/ in Safari, then Share, Add to Home Screen. Settings has backup and restore.

## One history on PC and phone

Both apps sync through two files in the private repo `PerryIndustries/urge-data`: `events.json` for urges and Bored presses (`kind: "bored"`, same file, same merge; how the activity went rides on the same event as `done`, `seconds`, `note` and `amount`, written only when set, so an older copy of either app reads the file as before) and `sudoku.json` for Sudoku (the record of games, plus the puzzle in progress). Records merge as a union by id with the latest edit winning; the puzzle in progress is whichever copy was saved last, so you can start on the PC and finish on the phone. A PC with the GitHub CLI logged in (`gh auth login`) needs nothing else. The phone, or a PC without `gh`, needs a token:

1. Open https://github.com/settings/personal-access-tokens/new
2. Name it "Urge Button", pick an expiry, Repository access: **Only select repositories** → `urge-data`
3. Permissions → Repository permissions → **Contents: Read and write**. Generate, copy.
4. Paste it into Settings → Sync on the phone (or the PC's "GitHub token" box) and save.

The phone app is built from `phone/urge-button.html` by `python phone/build_pwa.py` into `docs/`, which GitHub Pages serves. Edit the source, rebuild, commit, push.
