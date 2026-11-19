# Install FolioLib on Windows or macOS

No Python, no Docker, no terminal. FolioLib runs on your computer only: your data stays in the folder `.foliolib` of your user
folder, and nothing is reachable from the network.

## 1. Download

Open the [latest release](https://github.com/louispro02/foliolib/releases/latest) and download the file for your system:

| System | File |
| --- | --- |
| Windows 10 or 11 (64-bit) | `foliolib-windows-x86_64.exe` |
| macOS 12 or newer, Apple Silicon (M1, M2, M3, M4) | `foliolib-macos-arm64.zip` (open it to get `foliolib`) |
| Linux (64-bit) | `foliolib-linux-x86_64.tar.gz` |

Intel Macs have no ready-made program: use the [Docker install](../README.md#quickstart) or run it from the sources with
Python 3.11 or newer (`python3 desktop_entrypoint.py`).

## 2. Open it (the security warning is expected)

FolioLib is free software and the programs are **not code-signed** (the certificates cost several hundred euros a year). Your
system therefore shows a warning the first time. You can check the program is the one built from this repository: every file
of a release is produced by the public workflow `.github/workflows/release-binaries.yml`.

**Windows (SmartScreen: "Windows protected your PC").** Click **More info**, then **Run anyway**.

**macOS (Gatekeeper: "cannot be opened because it is from an unidentified developer").**
1. Double-click `foliolib` once, then click **Done**.
2. Open **System Settings → Privacy & Security**, scroll down to the message about `foliolib`, click **Open Anyway**, then
   confirm. This is asked only once.

If macOS says the file cannot be executed, open the Terminal once and run `chmod +x ~/Downloads/foliolib`.

**Linux.** `tar xzf foliolib-linux-x86_64.tar.gz && ./foliolib`.

## 3. First launch

A window (a black console) opens and your browser goes to `http://localhost:8080`. **Keep that window open while you use
FolioLib; close it to quit.**

1. The first time, the page asks you to **create your account**: a username and a password of 12 characters or more. They are
   kept on your computer only, the password as a hash.
2. Drop your broker's CSV exports on the page (see [Supported exports](../README.md#supported-exports)).

If the port 8080 is busy, FolioLib takes the next free one and opens the browser on it: the address is shown in the window.

## Where is my data? Backup, reset, uninstall

Everything is in `.foliolib` in your user folder (`C:\Users\<you>\.foliolib` on Windows, `~/.foliolib` on macOS): the database,
the files you dropped, and the login. Copy that folder to back it up. Delete it to start from scratch. To uninstall, delete
the program and, if you want, that folder.

**Forgot your password?** Delete the file `auth.json` in `.foliolib` and launch FolioLib again: it offers to create the account
again. Your data is not touched.
