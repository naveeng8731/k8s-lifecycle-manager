# ☸ Kubernetes Lifecycle Manager

> Discover, analyse, and upgrade Kubernetes clusters — automatically.
> Run directly on your server **or** from your Windows / Linux / Mac laptop.

---

## What Does This Tool Do?

You run **one command**. The tool does everything else:

1. Detects if a Kubernetes cluster exists on your server
2. If no cluster → installs a fresh one automatically
3. Discovers everything running inside the cluster
4. Compares your current version with the latest stable release
5. Builds a safe upgrade plan (one minor version at a time — Kubernetes rule)
6. Asks for your confirmation before making any changes
7. Executes the upgrade step by step with full logging
8. Shows a complete summary — what succeeded and what failed

---

## Two Ways to Run It

| Mode | Command | When to Use |
|---|---|---|
| **Local** | `python3 run.py` | Run directly on the Kubernetes server |
| **Remote** | `python3 run.py --mode remote` | Run from your Windows / Linux / Mac laptop |

---

## Quick Start

### Local Mode — on the Kubernetes server

```bash
git clone https://github.com/naveeng8731/k8s-lifecycle-manager.git
cd k8s-lifecycle-manager
pip3 install -r requirements.txt
python3 run.py
```

### Remote Mode — from your laptop

```bash
git clone https://github.com/naveeng8731/k8s-lifecycle-manager.git
cd k8s-lifecycle-manager
pip3 install -r requirements.txt

# 1. Edit config/settings.yaml  → set your server IP, SSH user, SSH key
# 2. Edit inventory/hosts.ini   → set your server IP and SSH details
# 3. Run
python3 run.py --mode remote
```

---

## What You Need on Your Local Machine (Remote Mode)

> **Important:** `kubectl`, `kubeadm`, and `kubelet` run on the **remote server** — NOT on your laptop.
> Ansible sends all commands to the server via SSH. Your laptop only needs Python + Ansible.

### Windows

```powershell
# Step 1: Install Python 3.8+
# Download from: https://www.python.org/downloads/
# ✔ Check "Add Python to PATH" during install

# Step 2: Install all required packages — ONE command
pip install ansible requests pyyaml

# Step 3: SSH Client — already built into Windows 10/11
# If missing: Settings → Apps → Optional Features → OpenSSH Client

# Step 4: Generate SSH key and copy to your server
ssh-keygen -t rsa -b 4096
ssh-copy-id ubuntu@<your-server-ip>
```

> **That's it for Windows.** No kubectl. No kubeadm. No other tools.

### Linux (Ubuntu / Debian)

```bash
sudo apt update
sudo apt install python3 python3-pip ansible -y
pip3 install requests pyyaml
ssh-keygen -t rsa -b 4096
ssh-copy-id ubuntu@<your-server-ip>
```

### Mac

```bash
brew install python3 ansible
pip3 install requests pyyaml
ssh-keygen -t rsa -b 4096
ssh-copy-id ubuntu@<your-server-ip>
```

### What Goes Where

| Tool | Your Laptop | Remote Server |
|---|---|---|
| Python 3.8+ | ✔ Required | ✔ Required |
| Ansible | ✔ Required | — |
| requests (pip) | ✔ Required | — |
| pyyaml (pip) | ✔ Required | — |
| SSH Client | ✔ Required (built-in) | — |
| kubectl | ✘ **NOT needed** | ✔ Required |
| kubeadm | ✘ **NOT needed** | ✔ Required |
| kubelet | ✘ **NOT needed** | ✔ Required |

---

## Why pyyaml?

`pyyaml` is a small Python library that lets Python **read `.yaml` files**.
Without it, Python cannot parse `config/settings.yaml` and the tool crashes on startup.
It is not a Kubernetes tool — it just reads config files.

---

## Configuration

### 1. Edit `config/settings.yaml`

```yaml
remote:
  host: 192.168.115.3        # IP address of your Kubernetes server
  user: ubuntu               # SSH username on the server
  ssh_key: ~/.ssh/id_rsa     # path to your SSH private key on your laptop
  port: 22                   # SSH port (default: 22)
  remote_kubeconfig: /home/ubuntu/.kube/config
```

### 2. Edit `inventory/hosts.ini`

```ini
[k8s_cluster]
devdc3 ansible_host=192.168.115.3 ansible_user=ubuntu ansible_ssh_private_key_file=~/.ssh/id_rsa
```

---

## How Remote Mode Works

```
Your Laptop (Windows / Linux / Mac)       Remote Linux Server
───────────────────────────────────       ──────────────────────────────
python3 run.py --mode remote
  reads config/settings.yaml
  tests SSH connection           ──SSH──► ubuntu@192.168.115.3
  runs Ansible playbooks         ──SSH──► kubectl get nodes   ← runs HERE
                                 ──SSH──► kubectl version     ← runs HERE
                                 ──SSH──► kubeadm upgrade     ← runs HERE
                                 ──SSH──► apt-get install     ← runs HERE
  receives results               ◄──────
  shows you the output
```

---

## How the Upgrade Flow Works

```
python3 run.py
       │
       ▼
Phase 0 ── Detect cluster state
       │    HEALTHY / DEGRADED / NOT_INSTALLED / UNREACHABLE
       ▼
Phase 1 ── No cluster? → Offer fresh kubeadm install (local mode only)
       ▼
Phase 2 ── Run Ansible discovery playbooks on server
       ▼
Phase 3 ── Analyse versions, risks, compatibility, dependencies
       ▼
Phase 4 ── Fetch current version (kubectl) + stable version (internet)
       ▼
Phase 5 ── Build upgrade plan (one minor version at a time)
            e.g. v1.34.8 → v1.35.0 → v1.36.0 → v1.36.2
       ▼
Phase 6 ── Show plan + ask for CONFIRM before touching anything
       ▼
Phase 7 ── Execute each phase:
            1. Update apt repo to new minor version
            2. Upgrade kubeadm
            3. Cordon node
            4. Drain node (auto-bypass PDB on single-node)
            5. kubeadm upgrade apply
            6. Upgrade kubelet + kubectl
            7. Restart kubelet
            8. Uncordon node
            9. Wait 30s for cluster to stabilise
       ▼
Phase 8 ── Show upgrade summary (completed steps / failed at / next steps)
```

---

## Upgrade Summary (example output)

```
╔══════════════════════════════════════════════╗
║           UPGRADE SUMMARY                    ║
╠══════════════════════════════════════════════╣
║  Original Version : v1.34.8                  ║
║  Target Version   : v1.36.2                  ║
║  Total Phases     : 3                        ║
║  Completed        : 3                        ║
╠══════════════════════════════════════════════╣
║  ✔ Completed Steps:                          ║
║      → v1.35.0                               ║
║      → v1.36.0                               ║
║      → v1.36.2                               ║
╠══════════════════════════════════════════════╣
║  ✔ STATUS : FULLY UPGRADED                   ║
║  Current  : v1.36.2                          ║
╚══════════════════════════════════════════════╝
```

---

## Project Structure

```
k8s-lifecycle-manager/
│
├── run.py                          ← Start here. One command runs everything.
├── requirements.txt                ← pip install -r requirements.txt
├── README.md                       ← This file
│
├── config/
│   └── settings.yaml               ← Edit this: server IP, SSH user, SSH key
│
├── inventory/
│   └── hosts.ini                   ← Edit this: Ansible server connection
│
├── modules/
│   ├── cluster_detector.py         ← Is cluster healthy / missing / unreachable?
│   ├── cluster_installer.py        ← Install fresh cluster with kubeadm
│   ├── remote_connection.py        ← SSH connection from laptop to server
│   ├── version_manager.py          ← Current version + stable version from internet
│   ├── application_inventory.py    ← Scan all workloads and image versions
│   ├── compatibility_engine.py     ← App compatibility with target k8s version
│   ├── component_detector.py       ← Detect Calico, Ingress, Metrics Server, etcd
│   ├── dependency_engine.py        ← Which components need attention before upgrade
│   ├── risk_analyzer.py            ← Risk score based on cluster config
│   ├── upgrade_engine.py           ← Build step-by-step upgrade plan
│   ├── upgrade_executor.py         ← Execute upgrade with safety checks
│   ├── backup_manager.py           ← etcd snapshot before each upgrade phase
│   ├── validation.py               ← Check node Ready status
│   ├── discovery.py                ← Load Ansible-collected discovery data
│   └── report_generator.py         ← Save inventory as JSON files
│
├── playbooks/
│   ├── discovery.yaml              ← Collect all cluster data via kubectl
│   ├── precheck.yaml               ← Pre-upgrade health checks
│   └── backup.yaml                 ← etcd backup playbook
│
└── output/
    ├── discovery_raw.json           ← Raw data from discovery playbook
    ├── cluster_inventory.json       ← Processed cluster inventory
    ├── component_inventory.json     ← All workloads with versions
    └── backups/                     ← etcd snapshots (.db + .json metadata)
```

---

## Branch Structure

| Branch | Purpose |
|---|---|
| `main` | Stable — local mode, runs on the cluster server |
| `dev` | Development — remote mode added (Windows / Linux / Mac) |

### Create the dev branch

```bash
git checkout -b dev
git add .
git commit -m "feat: add remote mode support (Windows/Linux/Mac)"
git push origin dev
```

---

## etcd Backup

Before every upgrade phase, the tool automatically takes an etcd snapshot.

**Backup location:** `output/backups/etcd-backup-v1.34.8-20260616-183000.db`

**Prerequisites:** `etcdctl` must be installed on the server.

```bash
ETCD_VER=v3.5.0
curl -LO https://github.com/etcd-io/etcd/releases/download/${ETCD_VER}/etcd-${ETCD_VER}-linux-amd64.tar.gz
tar -xf etcd-*.tar.gz
sudo mv etcd-*/etcdctl /usr/local/bin/
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `ModuleNotFoundError: cluster_installer` | Rename file: `mv modules/Cluster_installer.py modules/cluster_installer.py` |
| `ImportError: build_upgrade_plan` | Run: `pip3 install packaging` |
| `kubectl drain` retrying forever | Single-node cluster — fixed in `upgrade_executor.py` (auto-uses `--force --disable-eviction`) |
| `kubeadm: version 35 > 34` | Fixed — tool now upgrades kubeadm before running `kubeadm upgrade apply` |
| Package not found in apt | Fixed — tool auto-updates apt repo per minor version before each phase |
| SSH connection failed | Run: `ssh-copy-id -i ~/.ssh/id_rsa.pub user@host` then check `config/settings.yaml` |
| `pyyaml` import error | Run: `pip install pyyaml` |
| Node stuck as cordoned | Run on server: `kubectl uncordon <nodename>` |
| Cluster state UNREACHABLE | Run on server: `sudo systemctl restart kubelet` |

---

## All Commands

```bash
python3 run.py                    # local mode (default)
python3 run.py --mode remote      # remote mode from your laptop
python3 run.py --setup            # show OS-specific setup instructions

pip install -r requirements.txt   # install all dependencies
pip install ansible requests pyyaml  # install individually

git checkout -b dev               # create dev branch
git push origin dev               # push to GitHub

kubectl get nodes                 # verify nodes after upgrade
kubectl get pods -A               # verify pods after upgrade
kubectl uncordon <node>           # fix cordoned node
```

---

## License

MIT
