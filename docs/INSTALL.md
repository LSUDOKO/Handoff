# Installing Handoff

Handoff is a Python application with a native desktop window. It installs like
any command-line tool and then runs as `handoff`.

You need **Python 3.12 or newer**. Check with `python --version` (Windows) or
`python3 --version` (Linux/macOS).

---

## The short version

```bash
# Linux / macOS
pipx install "handoff[bedrock,desktop,voice,web]"

# Windows (PowerShell)
pipx install "handoff[bedrock,desktop,voice,web]"
```

Then:

```bash
handoff credentials set groq   # prompts, hidden — nothing is echoed
handoff doctor                 # confirms it really works
handoff desktop                # opens the app window
```

If you do not have `pipx`, use `uv` instead — it is one binary and needs no
Python setup of its own:

```bash
uv tool install "handoff[bedrock,desktop,voice,web]"
```

`pipx` and `uv tool` both put Handoff in its own isolated environment, so it
cannot break other Python programs on your machine. Plain `pip install --user`
works too, but on modern Linux distributions it is often blocked by design.

---

## Linux

### 1. System packages first

The desktop window is a real native window, not a browser tab. On Linux that
means GTK and WebKit, which come from your distribution rather than from pip.
Install them before Handoff:

**Arch, Manjaro, EndeavourOS**

```bash
sudo pacman -S --needed python gobject-introspection gtk3 webkit2gtk-4.1 cairo pkgconf gcc portaudio
```

**Ubuntu, Debian, Linux Mint, Pop!_OS**

```bash
sudo apt update
sudo apt install -y python3-dev python3-venv libgirepository1.0-dev \
    libgtk-3-dev libwebkit2gtk-4.1-dev libcairo2-dev pkg-config build-essential \
    portaudio19-dev
```

**Fedora, RHEL, Rocky**

```bash
sudo dnf install -y python3-devel gobject-introspection-devel gtk3-devel \
    webkit2gtk4.1-devel cairo-devel pkgconf-pkg-config gcc portaudio-devel
```

`portaudio` is only needed if you want to talk to Handoff from the desktop
window or the terminal. Everything else works without it.

### 2. Install Handoff

```bash
pipx install "handoff[bedrock,desktop,voice,web]"
```

### 3. Run it

```bash
handoff credentials list
handoff desktop
```

> **"GTK cannot be loaded"** in the output means step 1 was skipped or the
> `webkit2gtk` package name differs on your distribution. Handoff still runs —
> it falls back to opening your browser — but the native window needs those
> system packages.

---

## Windows

### 1. Python

Install Python 3.12+ from [python.org](https://www.python.org/downloads/) or
the Microsoft Store. During the python.org installer, tick **"Add python.exe to
PATH"**.

### 2. Install Handoff

In PowerShell:

```powershell
py -m pip install --user pipx
py -m pipx ensurepath
# close and reopen PowerShell so PATH updates
pipx install "handoff[bedrock,desktop,voice,web]"
```

### 3. Run it

```powershell
handoff credentials list
handoff desktop
```

The window uses **WebView2**, which ships with Windows 10 and 11. If Handoff
reports it is missing, install the Evergreen runtime from
[Microsoft](https://developer.microsoft.com/microsoft-edge/webview2/).

---

## macOS

```bash
brew install portaudio          # only if you want voice
pipx install "handoff[bedrock,desktop,voice,web]"
handoff credentials list
handoff desktop
```

The window uses the system WebKit, so there is nothing else to install.

---

## Choosing the extras

The name in brackets picks what gets installed. Take what you need:

| Extra       | What it adds                                            |
|-------------|---------------------------------------------------------|
| `bedrock`   | AWS Bedrock models, plus Transcribe and Polly for voice |
| `groq`      | Groq as the model provider (has a free tier)            |
| `anthropic` | Claude directly, one API key, no AWS account            |
| `desktop`   | The native window                                       |
| `voice`     | Microphone capture from the window and the terminal     |
| `web`       | A credential-free page-fetch tool                       |
| `agentcore` | Deploying to Bedrock AgentCore                          |

A minimal install that still does something real:

```bash
pipx install "handoff[groq,web]"
```

That gives you a working agent on Groq's free tier reading live web pages, with
no AWS account and no credentials beyond one Groq key.

---

## After installing

```bash
handoff doctor     # checks every credential with a real API call
handoff --help     # every command
handoff desktop    # the window
handoff serve      # the same UI in your browser instead
handoff run --watch <workflow>   # stream a run in the terminal
```

`handoff doctor` is the one to trust: it does not check that a variable is set,
it makes a real call and tells you what to fix when the answer is no.

Store credentials with `handoff credentials set <provider>` (it reads the value
hidden, so nothing lands in your shell history), or connect each service from
the **Settings → Credentials** page in the app. A `.env` file in the working
directory works too.
See [SETUP.md](SETUP.md) for where each key comes from.

---

## Upgrading and removing

```bash
pipx upgrade handoff
pipx uninstall handoff
```

With `uv`, substitute `uv tool upgrade handoff` and `uv tool uninstall handoff`.

Your workflows, decisions and preferences live outside the install (in
`.handoff-state/`, or DynamoDB when you turn it on), so upgrading never touches
them.

---

## Installing from source

For development, or to run an unreleased commit:

```bash
git clone https://github.com/LSUDOKO/Handoff
cd Handoff
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev,bedrock,desktop,web,voice]"
handoff doctor
```

On Linux, the system packages from the Linux section above are still required
for the desktop window.
