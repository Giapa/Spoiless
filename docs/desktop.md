# Desktop app

The desktop app uses Tauri 2 for its window and a PyInstaller bundle for the
existing Python backend. The backend serves both the production Vue frontend and
API from a random `127.0.0.1` port. No public server is needed. The window has no
Tauri IPC permissions and cannot navigate to remote websites. ChatGPT sign-in
opens the system browser. Closing the app stops its backend; a pipe also stops
the backend if the desktop process crashes.

## Build on Linux

Install Python 3.12+, uv, Node.js 22.12+, and the stable Rust toolchain. On
Debian/Ubuntu, install the native build dependencies:

```sh
sudo apt-get update
sudo apt-get install -y libwebkit2gtk-4.1-dev build-essential libayatana-appindicator3-dev librsvg2-dev patchelf
```

From the repository root:

```sh
python3 scripts/build-desktop.py --bundles deb,appimage
```

The script builds the frontend, freezes Python and its dependencies, then builds
local installers in `desktop/target/release/bundle/`. Users do not need Node,
Python, uv, or Rust installed. Linux still needs a graphical session, WebKitGTK
runtime libraries, and an unlocked Secret Service keyring. The `.deb` declares
Tauri's native runtime dependencies. If FUSE is unavailable, run the AppImage
with `--appimage-extract-and-run`. AppImage compatibility depends on the target
distribution; test it before sharing.

Build on the oldest Linux distribution you intend to support. In particular, a
backend frozen on Ubuntu 26.04 is not a compatibility-tested Ubuntu 22.04 build.
A successful build on this workstation alone is insufficient to claim support
for older distributions.

For backend-only packaging and testing:

```sh
python3 scripts/build-desktop.py --backend-only
```

The directory `backend/dist/spoiless-backend/` contains the complete standalone
backend, including its built frontend. Keep the whole directory together; the
executable alone is insufficient. It expects a parent stdin pipe kept open and
prints `SPOILESS_READY <port>` after startup. Closing that pipe stops the process.

## Other desktop platforms

The shell, data paths, native credential-store selection, and sign-in lock have
Windows and macOS implementations. Build each package on its own OS; PyInstaller
does not cross-compile the backend. These targets need native testing before
being advertised as supported downloads.

- Windows: install Microsoft's C++ Build Tools, WebView2, Rust, Python, uv and
  Node.js. Run `python scripts/build-desktop.py --bundles nsis`.
- macOS: install Xcode Command Line Tools, Rust, Python, uv and Node.js. Run
  `python3 scripts/build-desktop.py --bundles dmg`. Distributing a trusted macOS
  download requires signing and notarization.

Linux uses Secret Service, macOS uses Keychain, and Windows uses Credential
Manager. There is no plaintext fallback. Windows Credential Manager limits the
size of individual credentials; account token payload sizes must be checked on
Windows before its first release.

Linux keeps the existing `~/.local/share/spoiless` library, macOS defaults to
`~/Library/Application Support/spoiless`, and Windows defaults to
`%LOCALAPPDATA%/spoiless`. `XDG_DATA_HOME` continues to override the base directory.
The search model is downloaded only when requested in the app, and stays beside
the library. Internet access is still needed for sign-in and AI answers.

## Manual distribution

There are no publishing workflows, automatic releases or updater in this change.
After building, launch the installer on a clean target system and verify EPUB
import, progress, search-model setup, keyring access, sign-in, questions, restart,
and shutdown. Real-account model access and inference remain experimental.
Upload the tested installer manually wherever you distribute the app. Update the
version in `desktop/tauri.conf.json`, `desktop/Cargo.toml`, and
`desktop/package.json` before building another version. User data lives outside
the install directory so reinstalling does not intentionally delete the library.

## Current verification

On Ubuntu 26.04 x86_64, the desktop shell compiles and the extracted Debian
package starts its bundled backend. Terminating the desktop also stops that
backend. The final AppImage also passes this startup/shutdown check when
extracted and launched through AppRun. Frozen-backend checks cover the built JS/CSS, EPUB import, detected
chapters, model status, and library persistence across restart. The focused
desktop/account/sign-in checks pass (34 tests), as do backend Ruff checks and
the frontend build, unit test, and lint check.

The full backend suite has four failing answer API tests, reproduced on the
unchanged committed code. The frontend formatting check also reports three
unchanged Vue files. Neither is caused by desktop packaging. Real-account AI
inference, Windows/macOS runtime behavior, and older Linux distributions remain
unverified.
