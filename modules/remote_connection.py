import subprocess
import os
import platform
import socket
import yaml
import getpass


# ─────────────────────────────────────────────────────────
# REMOTE CONNECTION MANAGER
# ─────────────────────────────────────────────────────────

def get_platform():
    s = platform.system().lower()
    if s == "windows": return "windows"
    elif s == "darwin": return "mac"
    else:               return "linux"

def expand_path(path):
    return os.path.normpath(os.path.expandvars(os.path.expanduser(path)))

def load_remote_config():
    config_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "config", "settings.yaml"
    )
    with open(config_path) as f:
        config = yaml.safe_load(f)
    return config.get("remote", {})

def _default_settings():
    """Return clean default settings if file is missing or corrupted"""
    return {
        "report_path": "reports",
        "output_path": "output",
        "backup_path": "backups",
        "log_path": "logs",
        "cluster_inventory_file": "output/cluster_inventory.json",
        "health_threshold": {"pod_restart_limit": 10},
        "discovery": {
            "detect_crds": True,
            "detect_helm": True,
            "detect_ingress": True,
            "detect_storage": True,
        },
        "remote": {}
    }


def save_remote_config(data):
    config_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "config", "settings.yaml"
    )

    # Read existing config safely.
    # If file is corrupted (e.g. contains Python code instead of YAML),
    # yaml.safe_load returns a string. Detect this and reset to defaults.
    try:
        with open(config_path) as f:
            full = yaml.safe_load(f)
        if not isinstance(full, dict):
            print(f"\n  [WARN] settings.yaml was corrupted — resetting to defaults")
            full = _default_settings()
    except Exception:
        full = _default_settings()

    # Update only the remote section
    full["remote"] = data

    with open(config_path, "w") as f:
        yaml.dump(full, f, default_flow_style=False, allow_unicode=True)

    print(f"\n  [INFO] Connection details saved to config/settings.yaml")


# ─────────────────────────────────────────────────────────
# PLATFORM SELECTION
# Ask the user where their server lives.
# We cannot reliably detect cloud vs intranet from IP alone
# because AWS/Azure/GCP all use private IPs (10.x, 172.x)
# that look identical to office networks.
# ─────────────────────────────────────────────────────────
PLATFORMS = {
    "1": {
        "name":  "AWS (Amazon Web Services)",
        "notes": [
            "Use the PUBLIC IP or Elastic IP of your EC2 instance",
            "Make sure Security Group allows inbound TCP port 22 (SSH)",
            "Make sure Security Group allows inbound TCP port 6443 (Kubernetes API)",
            "Default username is usually: ubuntu (Ubuntu AMI) or ec2-user (Amazon Linux)",
            "Use the .pem key file downloaded when you created the EC2 instance",
        ]
    },
    "2": {
        "name":  "Azure (Microsoft Azure)",
        "notes": [
            "Use the PUBLIC IP of your Virtual Machine",
            "Make sure NSG (Network Security Group) allows inbound port 22 and 6443",
            "Default username is what you set during VM creation (e.g. azureuser)",
            "Use the SSH key or password you set during VM creation",
        ]
    },
    "3": {
        "name":  "GCP (Google Cloud Platform)",
        "notes": [
            "Use the EXTERNAL IP of your Compute Engine VM",
            "Make sure Firewall Rules allow inbound port 22 and 6443",
            "Default username is your Google account username or what you configured",
            "Use the SSH key from GCP Console → Metadata → SSH Keys",
        ]
    },
    "4": {
        "name":  "On-premise / Intranet / Office Network",
        "notes": [
            "Use the private IP of the server (e.g. 192.168.x.x or 10.x.x.x)",
            "Your laptop must be on the same network (office WiFi / VPN)",
            "Make sure the server firewall allows port 22 (SSH) and 6443 (k8s API)",
            "Username is whatever was set when the server was created",
        ]
    },
    "5": {
        "name":  "Other / VPS / Bare Metal (Hetzner, DigitalOcean, Linode, etc.)",
        "notes": [
            "Use the PUBLIC IP of your server",
            "Make sure firewall allows port 22 (SSH) and 6443 (Kubernetes API)",
            "Username is usually: root or ubuntu depending on your provider",
            "Check your provider's dashboard for the server IP and credentials",
        ]
    },
}

def ask_platform():
    """
    Ask user where their server is.
    Show helpful notes for each platform (firewall, username, key format).
    Returns platform key string.
    """
    print("\n" + "="*55)
    print("  WHERE IS YOUR SERVER?")
    print("="*55)
    print()
    print("  Select the platform where your server is running:\n")

    for key, val in PLATFORMS.items():
        print(f"  {key}) {val['name']}")

    print()
    while True:
        choice = input("  Choose [1-5]: ").strip()
        if choice in PLATFORMS:
            break
        print("  Please enter a number between 1 and 5")

    selected = PLATFORMS[choice]
    print(f"\n  ✔ Selected: {selected['name']}")
    print(f"\n  ── Notes for {selected['name']} ──────────────────────")
    for note in selected["notes"]:
        print(f"    • {note}")

    return choice, selected["name"]


# ─────────────────────────────────────────────────────────
# TCP CONNECTIVITY TEST
# Checks if host:port is reachable before SSH attempt
# ─────────────────────────────────────────────────────────
def test_tcp(host, port=22, timeout=5):
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
        return True
    except Exception:
        return False


# ─────────────────────────────────────────────────────────
# SSH RUNNER
# Supports key-based and password-based auth
# ─────────────────────────────────────────────────────────
def ssh_run(host, user, cmd, port=22, ssh_key=None, password=None, timeout=30):
    if ssh_key:
        ssh_cmd = [
            "ssh",
            "-i", expand_path(ssh_key),
            "-p", str(port),
            "-o", "StrictHostKeyChecking=no",
            "-o", "ConnectTimeout=10",
            "-o", "BatchMode=yes",
            f"{user}@{host}", cmd
        ]
    else:
        if not _sshpass_available():
            raise Exception(
                "sshpass is required for password auth.\n"
                "  Linux : sudo apt install sshpass\n"
                "  Mac   : brew install sshpass\n"
                "  Windows: use SSH key instead (recommended)"
            )
        ssh_cmd = [
            "sshpass", "-p", password,
            "ssh",
            "-p", str(port),
            "-o", "StrictHostKeyChecking=no",
            "-o", "ConnectTimeout=10",
            f"{user}@{host}", cmd
        ]
    return subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=timeout)


def _sshpass_available():
    import shutil
    return shutil.which("sshpass") is not None


# ─────────────────────────────────────────────────────────
# INTERACTIVE CONNECTION WIZARD
# Collects all connection info step by step
# ─────────────────────────────────────────────────────────
def interactive_connection_wizard():

    print("\n" + "="*55)
    print("  REMOTE SERVER CONNECTION WIZARD")
    print("="*55)
    print()
    print("  Answer a few questions to connect to your server.")
    print("  No need to edit any config files manually.\n")

    # ── Step 1: Where is the server? ──────────────────────
    platform_key, platform_name = ask_platform()

    # ── Step 2: IP / Hostname ─────────────────────────────
    print()
    while True:
        host = input("  Enter server IP address or hostname: ").strip()
        if host:
            break
        print("  ⚠ Cannot be empty.")

    # ── Step 3: Test TCP reachability ─────────────────────
    port_input = input(f"\n  SSH port [default: 22]: ").strip()
    port = int(port_input) if port_input.isdigit() else 22

    print(f"\n  [INFO] Testing TCP connection to {host}:{port}...")
    if test_tcp(host, port):
        print(f"  ✔ {host}:{port} is reachable")
    else:
        print(f"  ❌ Cannot reach {host}:{port}")
        print(f"\n  Possible reasons:")

        if platform_key == "1":   # AWS
            print(f"    • EC2 Security Group does not allow inbound port {port}")
            print(f"    • Make sure you are using the PUBLIC/Elastic IP, not private IP")
            print(f"    • Check EC2 instance is in 'running' state")
        elif platform_key == "2": # Azure
            print(f"    • NSG (Network Security Group) blocking port {port}")
            print(f"    • Check VM is running in Azure Portal")
            print(f"    • Make sure you are using the Public IP Address")
        elif platform_key == "3": # GCP
            print(f"    • GCP Firewall rule missing for port {port}")
            print(f"    • Check Compute Engine → VM is running")
            print(f"    • Make sure you are using the External IP")
        elif platform_key == "4": # Intranet
            print(f"    • Your laptop must be on the same network or connected via VPN")
            print(f"    • Check server firewall: sudo ufw status")
            print(f"    • Try: ping {host}")
        else:
            print(f"    • Check your provider's firewall/security settings for port {port}")

        retry = input(f"\n  Continue anyway? (yes/no): ").strip().lower()
        if retry != "yes":
            raise Exception(f"Cannot reach {host}:{port}. Connection aborted.")

    # ── Step 4: Username ───────────────────────────────────
    print()
    # Suggest default username based on platform
    default_users = {
        "1": "ubuntu",     # AWS Ubuntu AMI
        "2": "azureuser",  # Azure default
        "3": "ubuntu",     # GCP Ubuntu
        "4": "ubuntu",     # Intranet — common default
        "5": "root",       # VPS — often root
    }
    suggested_user = default_users.get(platform_key, "ubuntu")
    user_input = input(f"  SSH username [default: {suggested_user}]: ").strip()
    user = user_input if user_input else suggested_user

    # ── Step 5: Auth method ────────────────────────────────
    print(f"\n  Authentication method:")
    print(f"    1) SSH key  — recommended (more secure, no password needed)")
    print(f"    2) Password — simpler but less secure")

    # Suggest key for cloud platforms
    if platform_key in ["1", "2", "3"]:
        print(f"\n  ℹ  Cloud platforms ({platform_name}) typically use SSH keys.")
        print(f"     Password auth may not be enabled by default.")

    auth_input = input(f"\n  Choose [1/2]: ").strip()

    ssh_key  = None
    password = None

    if auth_input == "2":
        password = getpass.getpass(f"\n  Password for {user}@{host}: ")
        auth_method = "password"

        # Warn if cloud platform
        if platform_key in ["1", "2", "3"]:
            print(f"\n  ⚠ Cloud VMs often have password auth disabled by default.")
            print(f"     If connection fails, use SSH key auth instead.")
    else:
        # SSH key auth
        # Suggest .pem for AWS
        if platform_key == "1":
            default_key = "~/.ssh/my-key.pem"
            print(f"\n  ℹ  AWS uses .pem key files downloaded from EC2 console.")
            print(f"     Make sure permissions are set: chmod 400 ~/.ssh/my-key.pem")
        else:
            default_key = "~/.ssh/id_rsa"

        key_input = input(f"\n  Path to SSH private key [default: {default_key}]: ").strip()
        ssh_key = key_input if key_input else default_key

        key_expanded = expand_path(ssh_key)
        if not os.path.exists(key_expanded):
            print(f"\n  ⚠ Key file not found: {key_expanded}")
            if platform_key == "1":
                print(f"     Download it from: AWS Console → EC2 → Key Pairs")
                print(f"     Then run: chmod 400 {key_expanded}")
            elif platform_key == "2":
                print(f"     Download from: Azure Portal → VM → Connect → SSH")
            elif platform_key == "3":
                print(f"     Add via: GCP Console → Compute Engine → Metadata → SSH Keys")
            else:
                print(f"     Generate: ssh-keygen -t rsa -b 4096 -f ~/.ssh/id_rsa")
                print(f"     Copy to server: ssh-copy-id -i ~/.ssh/id_rsa.pub {user}@{host}")

            cont = input(f"\n  Continue anyway? (yes/no): ").strip().lower()
            if cont != "yes":
                raise Exception("SSH key not found. Aborted.")

        auth_method = "key"

        # Fix permissions on the key file if it exists
        if os.path.exists(expand_path(ssh_key)) and get_platform() != "windows":
            subprocess.run(f"chmod 600 {expand_path(ssh_key)}", shell=True)

    # ── Step 6: Test SSH connection ────────────────────────
    print(f"\n  [INFO] Testing SSH connection to {user}@{host}...")

    result = ssh_run(
        host, user,
        "echo SSH_OK && hostname && cat /etc/os-release | grep PRETTY_NAME | cut -d= -f2",
        port=port, ssh_key=ssh_key, password=password
    )

    if result.returncode != 0 or "SSH_OK" not in result.stdout:
        error = result.stderr.strip() or "Connection failed"
        msg = f"SSH connection failed to {user}@{host}:{port}\n  Error: {error}\n"

        if auth_method == "password":
            msg += "  Check your username and password are correct."
        else:
            if platform_key == "1":
                msg += f"  AWS: Check Security Group allows port {port} and you are using the correct .pem key."
            elif platform_key == "2":
                msg += f"  Azure: Check NSG allows port {port} and the username matches your VM config."
            elif platform_key == "3":
                msg += f"  GCP: Check Firewall Rules allow port {port} and the SSH key is added to VM metadata."
            else:
                msg += f"  Check the server firewall allows port {port}."

        raise Exception(msg)

    lines = result.stdout.strip().split("\n")
    server_hostname = lines[1].strip() if len(lines) > 1 else host
    server_os = lines[2].strip().strip('"') if len(lines) > 2 else "Unknown OS"

    print(f"\n  ✔ Connected successfully!")
    print(f"    Hostname : {server_hostname}")
    print(f"    Platform : {platform_name}")
    print(f"    OS       : {server_os}")
    print(f"    IP       : {host}")

    # ── Step 7: Save config ────────────────────────────────
    config = {
        "host":              host,
        "user":              user,
        "port":              port,
        "platform":          platform_name,
        "auth_method":       auth_method,
        "ssh_key":           ssh_key if auth_method == "key" else None,
        "remote_kubeconfig": f"/home/{user}/.kube/config",
        "local_kubeconfig":  "~/.kube/remote-config",
    }

    save_input = input(
        "\n  Save these connection details for future runs? (yes/no): "
    ).strip().lower()
    if save_input == "yes":
        save_remote_config(config)

    return config, password


# ─────────────────────────────────────────────────────────
# CHECK REMOTE CLUSTER STATE
# ─────────────────────────────────────────────────────────
def check_remote_cluster_state(config, password=None):

    host    = config.get("host")
    user    = config.get("user")
    port    = config.get("port", 22)
    ssh_key = config.get("ssh_key")

    print(f"\n[INFO] Checking cluster state on {host}...\n")

    result = ssh_run(
        host, user,
        "which kubectl > /dev/null 2>&1 "
        "&& kubectl cluster-info --request-timeout=5s > /dev/null 2>&1 "
        "&& kubectl get nodes --no-headers 2>/dev/null | wc -l "
        "|| echo NOT_INSTALLED",
        port=port, ssh_key=ssh_key, password=password
    )

    output = result.stdout.strip()

    if "NOT_INSTALLED" in output or result.returncode != 0:
        return "NOT_INSTALLED", 0

    try:
        node_count = int(output.split("\n")[-1].strip())
        if node_count > 0:
            return "HEALTHY", node_count
        return "NO_NODES", 0
    except Exception:
        return "UNKNOWN", 0


# ─────────────────────────────────────────────────────────
# GET REMOTE NODES
# ─────────────────────────────────────────────────────────
def get_remote_nodes(config, password=None):

    host    = config.get("host")
    user    = config.get("user")
    port    = config.get("port", 22)
    ssh_key = config.get("ssh_key")

    print(f"\n[INFO] Node list on {host}:\n")
    result = ssh_run(
        host, user, "kubectl get nodes -o wide",
        port=port, ssh_key=ssh_key, password=password
    )
    if result.stdout:
        print(result.stdout)


# ─────────────────────────────────────────────────────────
# FULL REMOTE SETUP — called from run.py
# ─────────────────────────────────────────────────────────
def setup_remote_connection():

    password = None

    # Check if a real saved config exists
    # Empty string "" counts as NOT saved — wizard will always run on first use
    try:
        config = load_remote_config()
        host_saved = config.get("host", "").strip()
        user_saved = config.get("user", "").strip()
        has_saved  = bool(host_saved and user_saved)
    except Exception:
        config    = {}
        has_saved = False

    if has_saved:
        # A previous connection was saved — ask if user wants to reuse it
        print("\n======================================")
        print(" Remote Connection")
        print("======================================\n")
        print(f"  Found saved connection from last run:")
        print(f"    Host     : {config.get('host')}")
        print(f"    User     : {config.get('user')}")
        print(f"    Platform : {config.get('platform', 'not set')}")
        print(f"    Auth     : {config.get('auth_method', 'key')}")
        print()
        print(f"  Press Enter to use this, or type 'new' to connect to a different server.")
        use_saved = input("  [Enter / new]: ").strip().lower()

        if use_saved == "new":
            # Run wizard for a new server
            config, password = interactive_connection_wizard()
        else:
            # Reuse saved — only ask for password if password auth
            if config.get("auth_method") == "password":
                password = getpass.getpass(
                    f"  SSH password for {config.get('user')}@{config.get('host')}: "
                )
    else:
        # No saved config — run the full wizard
        # Wizard will ask: platform, IP, port, username, SSH key or password
        config, password = interactive_connection_wizard()

    # Final SSH verify
    print(f"\n  [INFO] Verifying connection to {config['host']}...")
    result = ssh_run(
        config["host"], config["user"], "echo SSH_OK",
        port=config.get("port", 22),
        ssh_key=config.get("ssh_key"),
        password=password
    )
    if result.returncode != 0 or "SSH_OK" not in result.stdout:
        raise Exception(
            f"SSH verification failed: {result.stderr.strip()}"
        )
    print(f"  ✔ Connection verified")

    # Check cluster state
    state, node_count = check_remote_cluster_state(config, password)
    print(f"\n  Remote Cluster State : {state}")
    if node_count > 0:
        print(f"  Node Count           : {node_count}")
        get_remote_nodes(config, password)

    print(f"\n  ✔ Remote connection established\n")

    # Store password in memory for this session only — never saved to disk
    config["_session_password"] = password
    return config


# ─────────────────────────────────────────────────────────
# SETUP INSTRUCTIONS
# ─────────────────────────────────────────────────────────
def print_local_setup_instructions():

    os_type = get_platform()

    print("\n======================================")
    print(" Local Machine Setup — Remote Mode")
    print("======================================\n")
    print("  You only need these on your local machine:\n")
    print("  ┌──────────────────────────────────────────────────┐")
    print("  │  1. Python 3.8+                                   │")
    print("  │  2. Ansible                                       │")
    print("  │  3. pip: requests, pyyaml                         │")
    print("  │  4. sshpass  (only if using password auth)        │")
    print("  └──────────────────────────────────────────────────┘\n")
    print("  ✔ kubectl  → NOT needed (runs on remote server)")
    print("  ✔ kubeadm  → NOT needed (runs on remote server)")
    print("  ✔ kubelet  → NOT needed (runs on remote server)\n")

    if os_type == "windows":
        print("  ── WINDOWS ──────────────────────────────────────────")
        print("  pip install ansible requests pyyaml\n")
        print("  For password auth: use Git Bash (includes sshpass)\n")
    elif os_type == "mac":
        print("  ── MAC ──────────────────────────────────────────────")
        print("  brew install python3 ansible sshpass")
        print("  pip3 install requests pyyaml\n")
    else:
        print("  ── LINUX ────────────────────────────────────────────")
        print("  sudo apt install python3 python3-pip ansible sshpass -y")
        print("  pip3 install requests pyyaml\n")

    print("  ── THEN RUN ─────────────────────────────────────────")
    print("  python3 run.py --mode remote")
    print("  # The wizard will guide you through the connection\n")
    print("  ── SUPPORTED PLATFORMS ──────────────────────────────")
    for k, v in PLATFORMS.items():
        print(f"  {k}) {v['name']}")
    print()
