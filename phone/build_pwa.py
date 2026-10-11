"""Build the standalone home-screen app (pwa/index.html) from the artifact page (urge-button.html).

The artifact version saves to a claude.ai database; this one keeps everything on the phone,
works offline, opens Spotify and Messages directly, and can run an iPhone Shortcut.
"""

from pathlib import Path

HERE = Path(__file__).resolve().parent
src = (HERE / "urge-button.html").read_text(encoding="utf-8")

HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#0E0F10">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Urge">
<link rel="manifest" href="manifest.webmanifest">
<link rel="apple-touch-icon" href="apple-touch-icon.png">
<link rel="icon" href="icon-192.png">
"""


def rep(old, new):
    global src
    if old not in src:
        raise SystemExit(f"anchor not found: {old[:70]!r}")
    src = src.replace(old, new, 1)


def cut(start_marker, end_marker):
    global src
    a, b = src.index(start_marker), src.index(end_marker)
    src = src[:a] + src[b:]


# System fonts, so it works offline.
rep('<link rel="preconnect" href="https://fonts.googleapis.com">\n', "")
rep('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,600;12..96,800&family=Manrope:wght@400;500;700&display=swap">\n', "")
rep('--display: "Bricolage Grotesque", "Segoe UI", system-ui, sans-serif;', '--display: -apple-system, "SF Pro Display", "Segoe UI", system-ui, sans-serif;')
rep('--body: "Manrope", "Segoe UI", system-ui, sans-serif;', '--body: -apple-system, "SF Pro Text", "Segoe UI", system-ui, sans-serif;')
rep("html, body { height: 100%; }",
    "html, body { height: 100%; margin: 0; }\nhtml { padding-top: env(safe-area-inset-top, 0px); }\n"
    "[hidden] { display: none !important; }")
rep(".btn { background: var(--panel-2); border-radius: 10px; padding: 12px 18px; font-weight: 600; }",
    ".btn { background: var(--panel-2); border-radius: 10px; padding: 12px 18px; font-weight: 600; color: var(--text); text-decoration: none; display: inline-block; cursor: pointer; }")
src = HEAD + src.replace("</style>\n", "</style>\n</head>\n<body>\n", 1) + "\n</body>\n</html>\n"

rep('<span class="chip" id="sync">Connecting...</span>', '<span class="chip" id="sync">Saved on this phone</span>')

# Settings: Shortcut name, backup/restore, iPhone notes.
rep("""    <p class="note">Add this page to your home screen so it opens like an app. In Safari, tap Share and then Add to Home Screen. In Chrome, open the menu and tap Add to Home screen.</p>
    <p class="note">A phone app can't lock the whole phone. If you leave during a lock, the timer keeps running, and the lock is still here when you come back. For a harder lock on iPhone, turn on Guided Access (Settings, then Accessibility).</p>""",
    """    <label class="f" for="setShortcut">iPhone Shortcut to run when you tap URGE (leave blank for none)
      <input type="text" id="setShortcut" placeholder="Urge Mode" autocomplete="off" autocapitalize="off">
    </label>
    <p class="note">With a Shortcut name here, tapping URGE starts the lock and then runs that Shortcut, for example to turn on a Focus and start your playlist. Swipe back to this app afterwards. The timer keeps running while you're away.</p>
    <div class="card">
      <div><h3>Backup</h3><p class="sub" id="backupSub"></p></div>
      <div class="row"><a class="btn" id="exportBtn" href="#">Save a backup</a><label class="btn" for="importFile">Restore a backup</label><input type="file" id="importFile" accept="application/json,.json" hidden></div>
      <p class="note" id="backupNote">Your history lives on this phone only. Save a backup now and then and keep it in Files or iCloud Drive.</p>
    </div>
    <p class="note">A phone app can't lock the whole phone. If you leave during a lock, the timer keeps running, and the lock is still here when you come back. For a harder lock, turn on Guided Access (Settings, Accessibility, Guided Access) and triple-click the side button when the lock starts.</p>""")
rep('$("setBored").value = boredIdeas().join("\\n");\n  }',
    '$("setBored").value = boredIdeas().join("\\n");\n    $("setShortcut").value = S.settings.shortcut || "";\n  }')
rep('S.settings = { lockMinutes: m, spotify: sp, friends:',
    'S.settings = { lockMinutes: m, spotify: sp, shortcut: $("setShortcut").value.trim(), friends:')
rep('Object.assign({ lockMinutes: 3, spotify: "", friends: [] }, ls.get("urge.settings", {}))',
    'Object.assign({ lockMinutes: 3, spotify: "", shortcut: "", friends: [] }, ls.get("urge.settings", {}))')

# Start lock, then hand off to the Shortcut.
rep("""    showLock();
  }
  function showLock() {""", """    showLock();
    if (S.settings.shortcut) setTimeout(() => { location.href = "shortcuts://run-shortcut?name=" + encodeURIComponent(S.settings.shortcut); }, 600);
  }
  function showLock() {""")

# Spotify: open the app itself (from the lock's option and from the Bored panel's "Put music on").
rep("""  function spotifyLink() { return S.settings.spotify && /^https:\\/\\/open\\.spotify\\.com\\//.test(S.settings.spotify) ? S.settings.spotify : "https://open.spotify.com/"; }
  function openSpotify() { window.open(spotifyLink(), "_blank", "noopener"); }""",
    """  function spotifyLink() { return spotifyApp(S.settings.spotify); }
  function openSpotify() { location.href = spotifyLink(); }""")
rep("""stage(`<h2>Put some music on</h2><a class="link" href="${esc(link)}" target="_blank" rel="noopener">Open Spotify</a>""",
    """stage(`<h2>Put some music on</h2><a class="link" href="${esc(link)}">Open Spotify</a>""")
rep("  function friend() {", """  function spotifyApp(url) {
    // open.spotify.com/playlist/ID?si=... -> spotify:playlist:ID, which opens the Spotify app itself
    const m = /open\\.spotify\\.com\\/(?:intl-[a-z-]+\\/)?(playlist|album|artist|track|show|episode)\\/([A-Za-z0-9]+)/.exec(url || "");
    return m ? "spotify:" + m[1] + ":" + m[2] : "spotify:";
  }
  function friend() {""")

# Friend: open Messages with the text filled in (the lock's "Reach out" and the Bored sheet's "Text a friend" share this).
rep('<div class="row" style="justify-content:center"><button class="btn primary" data-act="copy">Copy message</button>',
    '<div class="row" style="justify-content:center"><a class="btn primary" href="sms:&body=${encodeURIComponent(msg)}">Open Messages</a><button class="btn" data-act="copy">Copy</button>')
rep('const done = () => { note.textContent = "Copied. Paste it into your messages."; if (after) after(); };',
    'const done = () => { note.textContent = "Copied."; if (after) after(); };')

# Local storage only: drop the claude.ai database code.
cut("  async function connect() {", "  // ---------------------------------------------------------------- stats")
rep("    db: null,\n", "")
rep("    queue: Promise.resolve(),\n", "")
rep("""    if (!S.db) return;
    const body = { events: S.months[key] || [] };
    S.queue = S.queue.then(() => S.db.doc("urges/" + key).set(body))
      .then(() => setSync("Saved to your account"))
      .catch((e) => setSync(e && e.code === "quota_exceeded" ? "Storage full" : "Saved on this phone only", true));
""", "")
rep("""    if (!S.db) return;
    S.queue = S.queue.then(() => S.db.doc("settings/main").set(Object.assign({}, S.settings)))
      .catch(() => setSync("Saved on this phone only", true));
""", "")

# Boot: backup/restore, ?start, offline.
rep("""  connect();""", """  function backupSub() { $("backupSub").textContent = plural(urges().length, "urge") + ", " + plural(boreds().length, "Bored press") + " and " + plural(S.sdkGames.length, "Sudoku game") + " saved on this phone"; }
  $("exportBtn").addEventListener("click", () => {
    const body = JSON.stringify({ app: "urge-button", version: 1, months: S.months, settings: S.settings, sudoku: sdkShared() }, null, 2);
    $("exportBtn").href = URL.createObjectURL(new Blob([body], { type: "application/json" }));
    $("exportBtn").download = "urge-history-" + new Date().toISOString().slice(0, 10) + ".json";
  });
  $("importFile").addEventListener("change", async (e) => {
    const f = e.target.files && e.target.files[0]; if (!f) return;
    try {
      const data = JSON.parse(await f.text());
      if (!data || typeof data.months !== "object") throw new Error("not a backup");
      let added = 0;
      for (const [k, list] of Object.entries(data.months)) {
        const have = new Set((S.months[k] || []).map((x) => x.id));
        const extra = (list || []).filter((x) => x && x.id && !have.has(x.id));
        added += extra.length;
        S.months[k] = (S.months[k] || []).concat(extra);
      }
      ls.set("urge.months", S.months); render();
      const before = S.sdkGames.length;
      if (data.sudoku && typeof data.sudoku === "object") applySudoku(mergeSudokuDocs(sdkShared(), data.sudoku));
      backupSub();
      $("backupNote").textContent = "Restored " + plural(added, "urge") + " and " + plural(S.sdkGames.length - before, "Sudoku game") + ". Anything already here was kept.";
    } catch { $("backupNote").textContent = "That file isn't an Urge Button backup."; }
    e.target.value = "";
  });
  backupSub();
  document.querySelector('nav.bar button[data-tab="settings"]').addEventListener("click", backupSub);

  if (/[?&]start\\b/.test(location.search) && !active) { history.replaceState(null, "", location.pathname); startLock(); }
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});""")

assert "S.db" not in src and "claude.use" not in src and "fonts.googleapis" not in src
out = HERE.parent / "docs" / "index.html"
out.parent.mkdir(exist_ok=True)
out.write_text(src, encoding="utf-8")
print("wrote", out, len(src))
