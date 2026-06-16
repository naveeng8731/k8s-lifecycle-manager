# ☸ Kubernetes Lifecycle Manager

> Discover, analyse, and upgrade Kubernetes clusters — automatically.
> Run directly on your server **or** from your Windows / Linux / Mac laptop.

---

## Step 1 — Install Python and Git First

> You must install Python and Git before anything else.
> If you already have them, skip to Step 2.

### Windows

**Install Python:**
1. Go to → https://www.python.org/downloads/
2. Click **Download Python 3.x.x**
3. Run the installer
4. ✔️ **IMPORTANT: Check "Add Python to PATH"** before clicking Install

   ![Add to PATH](https://www.python.org/static/img/python-logo.png)

5. Click **Install Now**

**Verify Python installed — open PowerShell and run:**
```powershell
python --version
```
Should show: `Python 3.x.x`

> If you see `python is not recognized` — Python is not installed or PATH was not checked.
> Uninstall Python and reinstall with "Add Python to PATH" checked.

**Install Git:**
1. Go to → https://git-scm.com/download/win
2. Download and run the installer
3. Use all default options → click Next through everything

**Verify Git installed:**
```powershell
git --version
```
Should show: `git version 2.x.x`

---

### Linux (Ubuntu / Debian)

```bash
sudo apt update
sudo apt install python3 python3-pip git -y

# Verify
python3 --version
git --version
```

---

### Mac

```bash
# Install Homebrew first (if not installed)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Then install Python and Git
brew install python3 git

# Verify
python3 --version
git --version
```

---

## Step 2 — Clone and Run

### Windows (PowerShell or Command Prompt)

```powershell
git clone https://github.com/naveeng8731/k8s-lifecycle-manager.git
cd k8s-lifecycle-manager
python -m pip install -r requirements.txt
python run.py
```

> On Windows use `python` and `python -m pip` — NOT `python3` or `pip3`

### Linux

```bash
git clone https://github.com/naveeng8731/k8s-lifecycle-manager.git
cd k8s-lifecycle-manager
pip3 install -r requirements.txt
python3 run.py
```

### Mac

```bash
git clone https://github.com/naveeng8731/k8s-lifecycle-manager.git
cd k8s-lifecycle-manager
pip3 install -r requirements.txt
python3 run.py
```

---

## Common Errors and Fixes

| Error | Cause | Fix |
|---|---|---|
| `pip is not recognized` | Python not installed or not in PATH | Reinstall Python — ✔ check **"Add Python to PATH"** |
| `python is not recognized` | Python not installed or not in PATH | Reinstall Python — ✔ check **"Add Python to PATH"** |
| `git is not recognized` | Git not installed | Install Git from git-scm.com |
| `python3 is not recognized` | On Windows use `python` not `python3` | Use `python run.py` instead of `python3 run.py` |
| `pip3 is not recognized` | On Windows use `python -m pip` | Use `python -m pip install -r requirements.txt` |
| `ModuleNotFoundError` | pip install not run yet | Run `python -m pip install -r requirements.txt` first |

---

## What Happens After `python run.py`

The script does everything else automatically — no config editing needed:

```
1. Checks if ansible, ssh, pip packages are installed
   → tells you exactly what to install if anything is missing

2. Detects your OS:
   Windows       → REMOTE mode (connects to your Linux server)
   Linux / Mac   → checks if local cluster exists
                   yes → LOCAL mode
                   no  → REMOTE mode

3. Connection wizard (remote mode):
   → Where is your server? (AWS / Azure / GCP / Intranet / Other)
   → Enter server IP address
   → Tests if server is reachable on port 22
   → Enter SSH username
   → SSH key or password?
   → Tests SSH connection — shows server hostname and OS
   → Saves connection for future runs

4. Checks cluster on the server:
   → No cluster  → asks: single-node or multi-node?
                   → installs Kubernetes automatically via SSH
   → Has cluster → checks current version vs stable version
                   → upgrades if needed
```

---

## Two Ways to Run It

| Mode | Command | When to Use |
|---|---|---|
| **Local** | `python3 run.py` | Run directly on the Kubernetes server |
| **Remote** | `python run.py` (Windows) | Run from your laptop — wizard handles connection |

---

## What You Need on Your Laptop (Remote Mode)

> `kubectl`, `kubeadm`, and `kubelet` are **NOT needed** on your laptop.
> They run on the remote server. Ansible sends all commands via SSH.

| Software | Required on Laptop | Purpose |
|---|---|---|
| Python 3.8+ | ✔ Yes | Runs the tool |
| Git | ✔ Yes | Downloads the code |
| Ansible (auto-installed via pip) | ✔ Yes | Sends commands to server via SSH |
| requests (pip) | ✔ Yes | Fetches stable k8s version |
| pyyaml (pip) | ✔ Yes | Reads config files |
| SSH Client | ✔ Yes (built-in on all OS) | Connects to server |
| kubectl | ✘ Not needed | Runs on remote server |
| kubeadm | ✘ Not needed | Runs on remote server |
| kubelet | ✘ Not needed | Runs on remote server |

---

## Why pyyaml?

`pyyaml` lets Python read `.yaml` config files. Without it, the tool
cannot read `config/settings.yaml` and crashes on startup.
It is not a Kubernetes tool — just a file reader.

---

## How Remote Mode Works

```
Your Laptop (Windows / Linux / Mac)       Remote Linux Server
───────────────────────────────────       ──────────────────────────────
python run.py
  wizard asks: platform / IP / user
  tests SSH connection          ──SSH──►  ubuntu@your-server-ip
  runs Ansible playbooks        ──SSH──►  kubectl get nodes  ← HERE
                                ──SSH──►  kubeadm upgrade    ← HERE
                                ──SSH──►  apt-get install    ← HERE
  shows results on your screen  ◄───────
```

---

## Project Structure

```
k8s-lifecycle-manager/
│
├── run.py                         ← Start here. One command runs everything.
├── requirements.txt               ← pip packages: ansible, requests, pyyaml
├── readme.md                      ← This file
│
├── config/
│   └── settings.yaml              ← Auto-filled by wizard (no manual editing)
│
├── inventory/
│   └── hosts.ini                  ← Auto-updated by wizard
│
├── modules/
│   ├── cluster_detector.py        ← Is cluster healthy / missing / unreachable?
│   ├── cluster_installer.py       ← Install fresh cluster (single or multi-node)
│   ├── remote_connection.py       ← SSH wizard — IP, auth, platform detection
│   ├── version_manager.py         ← Current version + stable version
│   ├── upgrade_engine.py          ← Build step-by-step upgrade plan
│   ├── upgrade_executor.py        ← Execute upgrade with safety checks
│   ├── backup_manager.py          ← etcd snapshot before each upgrade phase
│   └── ...other modules
│
├── playbooks/
│   ├── discovery.yaml             ← Collect cluster data via kubectl
│   └── precheck.yaml              ← Pre-upgrade health checks
│
└── output/
    ├── discovery_raw.json          ← Raw cluster data
    ├── cluster_inventory.json      ← Processed inventory
    └── backups/                    ← etcd snapshots
```

---

## Branch Structure

| Branch | Purpose |
|---|---|
| `main` | Stable — local mode on the cluster server |
| `dev` | Development — remote mode (Windows / Linux / Mac) |

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `pip is not recognized` (Windows) | Reinstall Python with "Add Python to PATH" checked |
| `python3 is not recognized` (Windows) | Use `python` instead of `python3` on Windows |
| `pip3 is not recognized` (Windows) | Use `python -m pip install -r requirements.txt` |
| SSH connection failed | Check server firewall allows port 22. Run: `ssh user@server-ip` to test |
| `ModuleNotFoundError` | Run `python -m pip install -r requirements.txt` first |
| Node stuck as cordoned | Run on server: `kubectl uncordon <nodename>` |
| Cluster state UNREACHABLE | Run on server: `sudo systemctl restart kubelet` |

---

## All Commands

```bash
# Windows
python run.py
python -m pip install -r requirements.txt

# Linux / Mac
python3 run.py
pip3 install -r requirements.txt

# Git
git clone https://github.com/naveeng8731/k8s-lifecycle-manager.git
git checkout -b dev
git push origin dev
```

---

## License

MIT
