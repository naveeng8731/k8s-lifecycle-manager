# k8s-lifecycle-manager

Kubernetes cluster lifecycle management tool — discover, analyze, and upgrade Kubernetes clusters.

Supports running **directly on the cluster node** (local mode) or **from your laptop/workstation** (remote mode) on Windows, Linux, or Mac.

---

## Modes

| Mode | Command | Use case |
|---|---|---|
| Local | `python3 run.py` | Run directly on the k8s server |
| Remote | `python3 run.py --mode remote` | Run from your laptop/workstation |

---

## Quick Start

### Local Mode (on the cluster node)
```bash
git clone https://github.com/naveeng8731/k8s-lifecycle-manager.git
cd k8s-lifecycle-manager
pip3 install -r requirements.txt
python3 run.py
```

### Remote Mode (from your laptop)
```bash
git clone https://github.com/naveeng8731/k8s-lifecycle-manager.git
cd k8s-lifecycle-manager
pip3 install -r requirements.txt

# 1. Edit config/settings.yaml → set remote host, user, ssh_key
# 2. Edit inventory/hosts.ini  → set server IP and SSH details
# 3. Run
python3 run.py --mode remote
```

---

## Local Machine Requirements (Remote Mode)

### Windows
```powershell
# 1. Install Python 3.8+
# https://www.python.org/downloads/

# 2. Install kubectl
winget install -e --id Kubernetes.kubectl

# 3. Install Ansible (via pip or WSL)
pip install ansible

# 4. Install pip packages
pip install -r requirements.txt

# 5. Ensure OpenSSH client is installed
# Settings → Apps → Optional Features → OpenSSH Client
```

### Linux
```bash
# 1. kubectl
curl -LO "https://dl.k8s.io/release/$(curl -sL https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install kubectl /usr/local/bin/

# 2. Ansible
sudo apt install ansible        # Ubuntu/Debian
sudo yum install ansible        # RHEL/CentOS

# 3. pip packages
pip3 install -r requirements.txt
```

### Mac
```bash
# 1. kubectl
brew install kubectl

# 2. Ansible
brew install ansible

# 3. pip packages
pip3 install -r requirements.txt
```

---

## Configuration

### 1. Edit `config/settings.yaml`
```yaml
remote:
  host: 192.168.115.3        # your server IP
  user: ubuntu               # SSH user
  ssh_key: ~/.ssh/id_rsa     # your SSH private key
  remote_kubeconfig: /home/ubuntu/.kube/config
  local_kubeconfig: ~/.kube/remote-config
  port: 22
```

### 2. Edit `inventory/hosts.ini`
```ini
[k8s_cluster]
devdc3 ansible_host=192.168.115.3 ansible_user=ubuntu ansible_ssh_private_key_file=~/.ssh/id_rsa
```

---

## What It Does

```
python3 run.py [--mode local|remote]
       ↓
1. Detect cluster state (HEALTHY / DEGRADED / NOT_INSTALLED / UNREACHABLE)
       ↓
2. If not installed → offer fresh kubeadm install (local mode only)
       ↓
3. Run Ansible discovery playbooks → collect cluster data
       ↓
4. Analyze versions, risks, compatibility, dependencies
       ↓
5. Build upgrade plan (one minor version at a time)
       ↓
6. Execute upgrade with safety checks:
   - Production safety warning
   - Single-node PDB auto-bypass
   - kubeadm + kubelet + kubectl upgrade per phase
   - Full upgrade summary on completion or failure
```

---

## Branch Structure

| Branch | Purpose |
|---|---|
| `main` | Stable — runs on cluster node (local mode) |
| `dev` | Development — adds remote mode support |

---

## Project Structure

```
k8s-lifecycle-manager/
├── run.py                        # Main entry point
├── config/
│   └── settings.yaml             # Configuration (incl. remote settings)
├── inventory/
│   └── hosts.ini                 # Ansible inventory (local + remote)
├── modules/
│   ├── cluster_detector.py       # Detect cluster state
│   ├── cluster_installer.py      # Fresh cluster install
│   ├── remote_connection.py      # Remote SSH + kubeconfig setup
│   ├── application_inventory.py  # Scan workloads
│   ├── backup_manager.py         # etcd backup
│   ├── compatibility_engine.py   # Version compatibility checks
│   ├── component_detector.py     # Detect CNI, ingress, etc.
│   ├── dependency_engine.py      # Dependency impact analysis
│   ├── discovery.py              # Load discovery data
│   ├── report_generator.py       # Save JSON reports
│   ├── risk_analyzer.py          # Risk scoring
│   ├── upgrade_engine.py         # Build upgrade plan
│   ├── upgrade_executor.py       # Execute upgrade phases
│   ├── validation.py             # Cluster health check
│   └── version_manager.py        # Fetch current + stable versions
├── playbooks/
│   ├── discovery.yaml            # Collect cluster data
│   ├── precheck.yaml             # Pre-upgrade checks
│   ├── backup.yaml               # etcd backup
│   └── ...
└── output/
    ├── discovery_raw.json
    ├── cluster_inventory.json
    └── component_inventory.json
```

---

## Show Setup Instructions
```bash
python3 run.py --setup
```
