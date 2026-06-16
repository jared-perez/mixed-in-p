# Mixed in P — macOS Signing, Notarization & DMG Checklist

A step-by-step build pipeline for distributing the macOS app without Gatekeeper
warnings. Run the whole flow **once per architecture** (Apple Silicon `arm64`
and Intel `x86_64`) — the commands are identical, you just point them at each
`.app`.

End state: a signed, notarized, stapled `.dmg` with the drag-to-Applications
window, that opens cleanly on any Mac with a normal double-click.

---

## 0. One-time setup (do this once, ever)

### 0.1 — Enroll in the Apple Developer Program
- Sign up at <https://developer.apple.com/programs/> ($99/yr).
- Approval can take a few hours to a couple of days. Nothing below works until
  you're enrolled.

### 0.2 — Install build tools
```bash
xcode-select --install        # Command Line Tools (if not already present)
brew install create-dmg       # the DMG builder
```

### 0.3 — Create your Developer ID Application certificate
This is the cert for apps distributed **outside** the App Store (your case).

- Easiest via Xcode: **Settings → Accounts → (your Apple ID) → Manage
  Certificates → + → Developer ID Application**.
- Then confirm it's installed and readable for code signing:
```bash
security find-identity -v -p codesigning
```
You should see a line like:
```
1) ABCD1234... "Developer ID Application: Your Name (TEAMID1234)"
```
Copy that full quoted string — you'll paste it into the sign command. The
`TEAMID1234` part in parentheses is your **Team ID** (also visible at
developer.apple.com → Membership).

### 0.4 — Store notarization credentials in the keychain
So you don't paste passwords into commands. Create an **app-specific password**
first at <https://appleid.apple.com> → Sign-In and Security → App-Specific
Passwords. Then:
```bash
xcrun notarytool store-credentials "notary-mixedinp" \
  --apple-id "your-appleid@email.com" \
  --team-id "TEAMID1234" \
  --password "abcd-efgh-ijkl-mnop"   # the app-specific password
```
This saves a reusable profile named `notary-mixedinp`. You reference it by name
from now on and never type the password again.

---

## 1. Create the entitlements file (one time, keep in repo)

PyInstaller apps bundle a Python interpreter, which trips the hardened runtime
unless you grant a few entitlements. Save this as `entitlements.plist` in your
project (commit it):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>com.apple.security.cs.allow-jit</key>
    <true/>
    <key>com.apple.security.cs.allow-unsigned-executable-memory</key>
    <true/>
    <key>com.apple.security.cs.disable-library-validation</key>
    <true/>
</dict>
</plist>
```

> If notarization later complains, this file is the first place to look — these
> three keys resolve the overwhelming majority of PyInstaller notarization
> rejections.

---

## 2. Sign the app

Run after each PyInstaller build, on the resulting `.app`.

```bash
codesign --deep --force --options runtime --timestamp \
  --entitlements entitlements.plist \
  --sign "Developer ID Application: Your Name (TEAMID1234)" \
  "dist/MixedInP.app"
```

What the flags mean:
- `--deep` — signs nested code (the bundled frameworks, dylibs, Python). Apple
  discourages `--deep` for complex apps in favor of signing inside-out, but for
  a standard PyInstaller bundle it's the pragmatic choice and works reliably. If
  you hit "code object is not signed at all" errors on a specific nested binary,
  that's the signal to sign that binary individually first, then re-run this.
- `--options runtime` — enables the hardened runtime (required for notarization).
- `--timestamp` — embeds a secure timestamp (required for notarization).
- `--entitlements` — applies the plist from Step 1.

### Verify the signature before going further
```bash
codesign --verify --deep --strict --verbose=2 "dist/MixedInP.app"
```
Clean output (no errors) means the signature is valid. Note: `spctl` assessment
will still *fail* at this stage — that's expected, because the app isn't
notarized yet. Don't chase that error here.

---

## 2.5 Notarize and staple the app (before building the DMG)

Stapling the **app itself** — not just the DMG — is what lets it launch cleanly
on an *offline* first run (e.g. downloaded on wifi, first opened on a plane).
Without it, the app still works for the normal online download, but a quarantined
app with no network can't verify and may refuse to open.

`notarytool` can't take a bare `.app`, so zip it first, submit the zip, then
staple the ticket onto the original `.app`:

```bash
# zip the signed app for submission (ditto preserves signing metadata)
ditto -c -k --keepParent "dist/MixedInP.app" "MixedInP-notarize.zip"

# notarize the app
xcrun notarytool submit "MixedInP-notarize.zip" \
  --keychain-profile "notary-mixedinp" --wait

# on Accepted, staple the ticket onto the .app, then confirm
xcrun stapler staple "dist/MixedInP.app"
xcrun stapler validate "dist/MixedInP.app"
```

Then build the DMG (Step 3) **from this stapled `.app`**, and notarize + staple
the DMG too (Steps 4–5). Yes, that's two notarization passes — one for the app,
one for the DMG — but the payoff is belt-and-suspenders: both the disk image
*and* the app inside carry their own offline-valid tickets.

> Skipping this section is a legitimate, common choice — the DMG-only flow still
> produces an app that reads as "Notarized Developer ID" and works for every
> normal (online) download. This step only buys the offline-first-launch case.

---

## 3. Build the DMG

This produces the drag-to-Applications window. The background is generated by
`scripts/make_dmg_background.py` (matches the app's dark theme + neon-yellow
accent, places an arrow pointing app → Applications). It writes a 600×400
`dmg-background.png` **and** a 1200×800 `dmg-background@2x.png` for Retina.

`create-dmg`'s automatic `@2x` detection is unreliable, so combine the two into
a single multi-resolution TIFF with Apple's `tiffutil` and feed *that* to
`--background` — this is the genuine macOS Retina mechanism and always works:

```bash
./venv/bin/python scripts/make_dmg_background.py        # writes the two PNGs
tiffutil -cathidpicheck dmg-background.png dmg-background@2x.png \
  -out dmg-background.tiff                               # 1x + 2x in one file
```

```bash
create-dmg \
  --volname "Mixed in P" \
  --background "dmg-background.tiff" \
  --window-pos 200 120 \
  --window-size 600 400 \
  --icon-size 100 \
  --icon "MixedInP.app" 150 200 \
  --app-drop-link 450 200 \
  --hide-extension "MixedInP.app" \
  "MixedInP-mac-arm64.dmg" \
  "dist/MixedInP.app"
```

- `--icon "MixedInP.app" 150 200` — places your app icon on the left.
- `--app-drop-link 450 200` — places the Applications shortcut on the right.
- The last two args are **output DMG name** then **source app**.
- For the Intel build, swap the output name to `MixedInP-mac-intel.dmg` and
  point at the Intel `.app`.

> `create-dmg` occasionally exits non-zero on the first run while still
> producing a valid DMG (a known quirk with its AppleScript window styling). If
> the `.dmg` exists and looks right when mounted, you're fine.

---

## 4. Notarize the DMG

Notarize the DMG itself — Apple's scan covers the app inside it.

```bash
xcrun notarytool submit "MixedInP-mac-arm64.dmg" \
  --keychain-profile "notary-mixedinp" \
  --wait
```

- `--wait` blocks until Apple finishes (usually a few minutes) and prints the
  result.
- On **Accepted**, continue to Step 5.
- On **Invalid**, pull the detailed log:
```bash
xcrun notarytool log <submission-id> --keychain-profile "notary-mixedinp"
```
  The log names the exact offending binary/issue — almost always an entitlement
  (back to Step 1) or an unsigned nested binary (back to Step 2).

---

## 5. Staple the ticket

Attaches the notarization result to the DMG so it validates even offline.

```bash
xcrun stapler staple "MixedInP-mac-arm64.dmg"
```

---

## 6. Final verification (the real test)

```bash
# 1. Confirm the staple is attached to the DMG
xcrun stapler validate "MixedInP-mac-arm64.dmg"

# 2. Confirm Gatekeeper accepts the APP inside (this is the real test)
hdiutil attach "MixedInP-mac-arm64.dmg" -nobrowse -mountpoint /tmp/mipcheck
spctl -a -t exec -vv "/tmp/mipcheck/MixedInP.app"
xcrun stapler validate "/tmp/mipcheck/MixedInP.app"   # if you stapled the app (2.5)
hdiutil detach /tmp/mipcheck
```
On the app you want to see `accepted` / `source=Notarized Developer ID`.

> **Don't** run `spctl` against the `.dmg` itself — it reports
> `rejected: no usable signature` because the disk-image *container* isn't
> code-signed (only the app inside is). That's expected and harmless; the DMG's
> notarization lives in its stapled ticket (`stapler validate`), not a signature.
> Assess the **app**, not the DMG.

**The human test that matters most:** copy the DMG to a different Mac (or a
fresh user account), download it through a browser so it gets the quarantine
flag a real user would have, mount it, drag the app to Applications, and
**double-click** it. It should open with no warning at all. That double-click —
the thing that broke for you earlier — is the whole point of this pipeline.

---

## 7. Repeat for Intel, then ship

1. Run Steps 2–6 again for the Intel `.app`, outputting `MixedInP-mac-intel.dmg`.
2. Cut a follow-up release (e.g. **v1.3.1**) and upload the two new `.dmg`
   files. Keep the Windows `.exe` as-is.
3. **Update the landing page** — your two Mac download buttons currently point at
   `.zip` filenames. Change them to the new `.dmg` names:
   - `…/releases/latest/download/MixedInP-mac-arm64.dmg`
   - `…/releases/latest/download/MixedInP-mac-intel.dmg`
   Commit and push so Pages redeploys.
4. **Update your install instructions** — once notarized, the macOS
   "right-click → Open" / "Privacy & Security → Open Anyway" caveat no longer
   applies. You can delete that note from the landing page, the release notes,
   and the docs. A notarized app just opens.

---

## Quick reference — the per-build loop

Once set up, each release is just:

```bash
# 1. sign the app
codesign --deep --force --options runtime --timestamp \
  --entitlements entitlements.plist \
  --sign "Developer ID Application: Your Name (TEAMID1234)" "dist/MixedInP.app"

# 2. notarize + staple the APP (offline-first-launch; skip if you don't need it)
ditto -c -k --keepParent "dist/MixedInP.app" "MixedInP-notarize.zip"
xcrun notarytool submit "MixedInP-notarize.zip" \
  --keychain-profile "notary-mixedinp" --wait
xcrun stapler staple "dist/MixedInP.app"

# 3. build the retina background, then the dmg (from the stapled app)
./venv/bin/python scripts/make_dmg_background.py
tiffutil -cathidpicheck dmg-background.png dmg-background@2x.png -out dmg-background.tiff
create-dmg --volname "Mixed in P" --background "dmg-background.tiff" \
  --window-size 600 400 --icon-size 100 \
  --icon "MixedInP.app" 150 200 --app-drop-link 450 200 \
  "MixedInP-mac-arm64.dmg" "dist/MixedInP.app"

# 4. notarize + staple the DMG
xcrun notarytool submit "MixedInP-mac-arm64.dmg" \
  --keychain-profile "notary-mixedinp" --wait
xcrun stapler staple "MixedInP-mac-arm64.dmg"
```

---

## Notes & gotchas

- **Certificates expire** — Developer ID Application certs are valid 5 years.
  Notarization tickets don't expire, so already-shipped apps keep working even
  after the cert lapses; you just can't sign *new* builds until you renew.
- **`--deep` caveat** — fine for PyInstaller here, but if Apple ever changes
  enforcement, the future-proof approach is signing nested binaries
  inside-out (deepest first), then the `.app` last, without `--deep`.
- **Windows is a separate battle** — SmartScreen reputation isn't solved by this
  pipeline. An EV/OV code-signing cert for Windows is a different (pricier)
  product; many indie devs simply let download reputation build over time.
- **Automate later** — once this works by hand, it's a strong candidate for a
  GitHub Actions workflow on a macOS runner, so tagging a release builds, signs,
  notarizes, and uploads all three artifacts automatically. The signing cert and
  notary credentials go in encrypted repository secrets.
