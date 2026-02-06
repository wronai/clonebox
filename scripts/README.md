# CloneBox Scripts

Helper scripts for diagnostics, monitoring, and maintenance of CloneBox VMs.

## Main Scripts

### diagnose-vm.sh — VM Diagnostic (primary)

One-stop diagnostic for a running VM.
By default shows **only errors and warnings**; pass `--verbose` for full output.

```bash
bash scripts/diagnose-vm.sh                     # quick error scan
bash scripts/diagnose-vm.sh my-vm               # specific VM
bash scripts/diagnose-vm.sh --verbose            # full details
bash scripts/diagnose-vm.sh --quiet              # only FAIL
bash scripts/diagnose-vm.sh --help               # usage
```

Checks performed (8 sections):

1. **VM status** — exists, running
2. **Network & SSH** — passt, port resolution (file → QEMU hostfwd fallback), TCP connect, SSH auth
3. **Cloud-init** — completion, errors in serial log (filters kernel noise)
4. **QEMU Guest Agent** — ping, OS info, interfaces, users
5. **GUI & Display** — SPICE, GDM, session type, wayland sessions
6. **Browsers** — detection (`command -v`), profile presence & `profiles.ini`, permissions, lock files, crash dumps, snap interface validation, headless smoke tests (Firefox, Chrome, Chromium)
7. **Resources & filesystem** — CPU, memory, disk images (verbose)
8. **Quick actions** — SSH/SPICE/console commands (verbose)

Exit code = number of FAILs.

### vm_state_diagnostic.py — Advanced Python Diagnostic

Comprehensive Python-based diagnostic with structured Q&A output and root-cause analysis.
Runs tests as a decision tree — if a blocking test fails, dependents are skipped.

```bash
python3 scripts/vm_state_diagnostic.py <vm-name>            # text report
python3 scripts/vm_state_diagnostic.py <vm-name> --json      # JSON output
python3 scripts/vm_state_diagnostic.py <vm-name> --verbose   # show details
```

Tests performed (22 tests):
- **Infrastructure** — VM exists, running, directory, passt, SSH port, TCP, QGA, SSH, network, cloud-init, serial log, services
- **Browser detection** — Firefox, Chrome, Chromium, Edge, Brave + versions
- **Browser profiles** — Firefox (snap + classic), Chrome, Chromium — presence, `profiles.ini`, size
- **Browser permissions** — ownership validation (`ubuntu`)
- **Lock files** — detects stale `parent.lock` / `SingletonLock` from copied profiles
- **Crash reports** — recent `.dmp` / `.extra` files since last VM boot
- **Snap interfaces** — validates `desktop`, `x11`, `wayland`, `home`, `network` connections
- **Headless smoke test** — `firefox --headless --version` with proper `XDG_RUNTIME_DIR`
- **Browser logs** — snap logs and journal analysis for errors

### clonebox-logs.sh — Log Viewer

Fetches and displays VM logs via QEMU Guest Agent or SSH.
Used by `clonebox logs` CLI command.

```bash
bash scripts/clonebox-logs.sh <vm-name> [true|false] [true|false]
#                              ^name     ^user-mode   ^show-all
```

### test-user-vm.sh — VM Creation Test

End-to-end test: creates a VM from `.clonebox.yaml`, waits for boot, validates.

```bash
bash scripts/test-user-vm.sh . --base-image /path/to/image.qcow2
```

## Monitoring (runs inside VM)

### clonebox-monitor.sh + .service + .default

Systemd user service that monitors GUI apps and services inside the VM,
auto-restarts them if needed.

```bash
systemctl --user status clonebox-monitor
journalctl --user -u clonebox-monitor -f
```

Config: `clonebox-monitor.default`
- `CLONEBOX_MONITOR_INTERVAL` — check interval (default: 30s)
- `CLONEBOX_AUTO_REPAIR` — auto-restart (default: true)

## Utilities

| Script | Purpose |
|---|---|
| `fetch-logs.py` | Fetch logs from VM via QGA or SSH |
| `set-vm-password.sh` | Set/reset VM user password |
| `vm_console_interact.py` | Interactive VM console |
| `clonebox-completion.bash` | Bash tab completion |
| `clonebox-completion.zsh` | Zsh tab completion |

## Fix Scripts (one-time repairs)

| Script | Purpose |
|---|---|
| `fix_interface_name.py` | Fix network interface naming |
| `fix_network_config.py` | Fix network configuration |
| `fix_ssh_keys.py` | Fix SSH key permissions/setup |
| `fix_yaml_bootcmd.py` | Fix cloud-init bootcmd YAML |
| `fix_yaml_quotes.py` | Fix YAML quoting issues |

## Recent Fixes

Bugs found and fixed via `diagnose-vm.sh`:

- **`vm_xml.py`** — hardcoded `/home/tom/` path for serial.log → uses `Path.home()` dynamically
- **`cloud_init.py`** — classic snaps (`pycharm-community`, `code`) attempted `snap connect` which fails → skipped for classic snaps; non-classic snaps probe for plug existence before connecting
- **`diagnose-vm.sh`** — `grep` treated serial.log as binary (CR/CR/LF) → added `--text` flag; false-positive errors filtered (RAS, EXT4, GPT, snap plugs); network detection distinguishes passt vs hostfwd
- **`clonebox-logs.sh`** — missing `VM_DIR` variable, undefined `log()` function, duplicated SSH flags → added `_ssh()` helper and proper variable definitions
