#!/usr/bin/env python3
"""
Post-install diagnostic and auto-repair for CloneBox VMs.

Runs immediately after VM installation (cloud-init done, profiles copied)
to detect and fix known issues before the user touches the VM.

Each repair is idempotent — safe to re-run on already-healthy VMs.

Usage (standalone):
    python -m clonebox.post_install_repair <vm-name>

Programmatic (from cloner.py):
    from clonebox.post_install_repair import run_post_install_repairs
    report = run_post_install_repairs(ssh_port, ssh_key, vm_username, browsers)
"""

import logging
import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

from clonebox.ssh import ssh_exec as _ssh_exec

log = logging.getLogger(__name__)


# ─── data types ──────────────────────────────────────────────────────────────

@dataclass
class RepairResult:
    """Outcome of a single repair check."""
    name: str
    detected: bool
    repaired: bool
    detail: str = ""
    error: str = ""


@dataclass
class RepairReport:
    """Aggregate report from all repairs."""
    results: List[RepairResult] = field(default_factory=list)

    @property
    def detected_count(self) -> int:
        return sum(1 for r in self.results if r.detected)

    @property
    def repaired_count(self) -> int:
        return sum(1 for r in self.results if r.repaired)

    @property
    def failed_count(self) -> int:
        return sum(1 for r in self.results if r.detected and not r.repaired)

    def log_summary(self) -> None:
        log.info("=" * 60)
        log.info("POST-INSTALL REPAIR REPORT")
        log.info("=" * 60)
        for r in self.results:
            if r.detected and r.repaired:
                log.info(f"  ✅ {r.name}: FIXED — {r.detail}")
            elif r.detected and not r.repaired:
                log.warning(f"  ❌ {r.name}: NOT FIXED — {r.error or r.detail}")
            else:
                log.info(f"  ✓  {r.name}: OK")
        log.info("-" * 60)
        log.info(
            f"  Total: {len(self.results)} checks, "
            f"{self.detected_count} issues detected, "
            f"{self.repaired_count} fixed, "
            f"{self.failed_count} remaining"
        )
        log.info("=" * 60)


# ─── repair context (SSH helper) ────────────────────────────────────────────

class _RepairCtx:
    """Thin wrapper around SSH exec with logging."""

    def __init__(
        self,
        ssh_port: int,
        ssh_key: Optional[Path],
        vm_username: str = "ubuntu",
        timeout: int = 30,
    ):
        self.port = ssh_port
        self.key = ssh_key
        self.user = vm_username
        self.timeout = timeout

    def run(self, cmd: str, timeout: int = None) -> Optional[str]:
        return _ssh_exec(
            port=self.port,
            key=self.key,
            command=cmd,
            username=self.user,
            timeout=timeout or self.timeout,
        )


# ═════════════════════════════════════════════════════════════════════════════
#  INDIVIDUAL REPAIRS — each returns a RepairResult
# ═════════════════════════════════════════════════════════════════════════════


def _repair_snap_dir_ownership(ctx: _RepairCtx, browsers: List[str]) -> List[RepairResult]:
    """
    BUG: sudo mkdir -p creates /home/<user>/snap/<app> owned by root.
    Snap runtime refuses to create per-revision dirs (e.g. snap/firefox/7766).
    FIX: chown -R <user>:<user> /home/<user>/snap/<app>
    """
    results = []
    snap_apps = list(browsers) + ["pycharm-community"]

    for app in snap_apps:
        snap_dir = f"/home/{ctx.user}/snap/{app}"
        owner = ctx.run(f"stat -c '%U' {shlex.quote(snap_dir)} 2>/dev/null || echo MISSING")
        if owner == "MISSING" or owner is None:
            continue  # app not installed via snap or dir doesn't exist

        detected = owner != ctx.user
        repaired = False
        detail = ""

        if detected:
            ctx.run(f"sudo chown -R {ctx.user}:{ctx.user} {shlex.quote(snap_dir)}")
            new_owner = ctx.run(f"stat -c '%U' {shlex.quote(snap_dir)} 2>/dev/null")
            repaired = new_owner == ctx.user
            detail = f"{snap_dir} was owned by {owner}, now {new_owner}"

        results.append(RepairResult(
            name=f"snap-dir-ownership:{app}",
            detected=detected,
            repaired=repaired,
            detail=detail or f"{snap_dir} owned by {owner}",
        ))

    return results


def _repair_browser_profile_ownership(ctx: _RepairCtx) -> List[RepairResult]:
    """
    BUG: tar extract via sudo leaves browser profile dirs owned by root.
    FIX: chown -R <user> on profile directories.
    """
    results = []
    profile_dirs = [
        f"/home/{ctx.user}/.mozilla",
        f"/home/{ctx.user}/.config/google-chrome",
        f"/home/{ctx.user}/.config/chromium",
        f"/home/{ctx.user}/snap/firefox/common/.mozilla",
        f"/home/{ctx.user}/snap/chromium/common/chromium",
    ]

    bad = []
    for d in profile_dirs:
        owner = ctx.run(f"stat -c '%U' {shlex.quote(d)} 2>/dev/null || echo MISSING")
        if owner and owner != "MISSING" and owner != ctx.user:
            bad.append((d, owner))

    detected = len(bad) > 0
    repaired = False
    detail = ""

    if detected:
        for d, _ in bad:
            ctx.run(f"sudo chown -R {ctx.user}:{ctx.user} {shlex.quote(d)}")
        # verify
        still_bad = 0
        for d, _ in bad:
            owner = ctx.run(f"stat -c '%U' {shlex.quote(d)} 2>/dev/null")
            if owner != ctx.user:
                still_bad += 1
        repaired = still_bad == 0
        detail = f"Fixed ownership on {len(bad)} dirs" + (
            f" ({still_bad} still broken)" if still_bad else ""
        )

    results.append(RepairResult(
        name="browser-profile-ownership",
        detected=detected,
        repaired=repaired,
        detail=detail or "All profile dirs owned correctly",
    ))
    return results


def _repair_browser_lock_files(ctx: _RepairCtx) -> List[RepairResult]:
    """
    BUG: Lock files copied from running browser on host prevent VM browser launch.
    FIX: Remove lock files.
    """
    lock_cmd = (
        f"find /home/{ctx.user}/.mozilla /home/{ctx.user}/snap/firefox "
        f"/home/{ctx.user}/.config/google-chrome /home/{ctx.user}/.config/chromium "
        f"/home/{ctx.user}/snap/chromium "
        "-maxdepth 4 -type f "
        "\\( -name 'parent.lock' -o -name '.parentlock' -o -name 'lock' "
        "-o -name 'lockfile' -o -name 'SingletonLock' "
        "-o -name 'SingletonSocket' -o -name 'SingletonCookie' \\) "
        "2>/dev/null"
    )
    locks_raw = ctx.run(lock_cmd) or ""
    locks = [l for l in locks_raw.strip().splitlines() if l.strip()]

    detected = len(locks) > 0
    repaired = False
    detail = ""

    if detected:
        for lf in locks:
            ctx.run(f"sudo rm -f {shlex.quote(lf)}")
        # verify
        remaining = ctx.run(lock_cmd) or ""
        remaining_count = len([l for l in remaining.strip().splitlines() if l.strip()])
        repaired = remaining_count == 0
        detail = f"Removed {len(locks)} lock file(s)"

    return [RepairResult(
        name="browser-lock-files",
        detected=detected,
        repaired=repaired,
        detail=detail or "No lock files found",
    )]


def _repair_browser_crash_reports(ctx: _RepairCtx) -> List[RepairResult]:
    """
    BUG: Stale crash dumps copied from host confuse browsers on first launch.
    FIX: Remove .dmp and .extra files from Crash Reports dirs.
    """
    crash_dirs = [
        f"/home/{ctx.user}/snap/firefox/common/.mozilla/firefox/Crash Reports",
        f"/home/{ctx.user}/.mozilla/firefox/Crash Reports",
        f"/home/{ctx.user}/.config/google-chrome/Crash Reports",
        f"/home/{ctx.user}/.config/chromium/Crash Reports",
        f"/home/{ctx.user}/snap/chromium/common/chromium/Crash Reports",
    ]
    count = 0
    for d in crash_dirs:
        n = ctx.run(
            f"find {shlex.quote(d)} -maxdepth 2 -type f "
            f"\\( -name '*.dmp' -o -name '*.extra' \\) 2>/dev/null | wc -l"
        )
        try:
            count += int((n or "0").strip())
        except ValueError:
            pass

    detected = count > 0
    repaired = False

    if detected:
        for d in crash_dirs:
            ctx.run(
                f"find {shlex.quote(d)} -maxdepth 2 -type f "
                f"\\( -name '*.dmp' -o -name '*.extra' \\) -delete 2>/dev/null || true"
            )
        repaired = True

    return [RepairResult(
        name="browser-crash-reports",
        detected=detected,
        repaired=repaired,
        detail=f"Removed {count} crash dump(s)" if detected else "No crash dumps",
    )]


def _repair_snap_interfaces(ctx: _RepairCtx, browsers: List[str]) -> List[RepairResult]:
    """
    BUG: Snap browser interfaces may not be auto-connected after snap install.
    FIX: snap connect <snap>:<interface>.
    """
    required = ["desktop", "desktop-legacy", "x11", "wayland", "home", "network"]
    results = []

    snap_map = {"firefox": "firefox", "chromium": "chromium"}

    for browser in browsers:
        snap_name = snap_map.get(browser)
        if not snap_name:
            continue

        installed = ctx.run(f"snap list {snap_name} >/dev/null 2>&1 && echo y || echo n")
        if installed != "y":
            continue

        conns_raw = ctx.run(f"snap connections {snap_name} 2>/dev/null") or ""
        connected = set()
        for line in conns_raw.splitlines()[1:]:  # skip header
            parts = line.split()
            if len(parts) >= 3 and parts[2] != "-":
                iface = parts[0].split(":")[-1] if ":" in parts[0] else parts[0]
                connected.add(iface)

        missing = [i for i in required if i not in connected]
        detected = len(missing) > 0
        repaired = False
        detail = ""

        if detected:
            fixed = []
            for iface in missing:
                rc = ctx.run(
                    f"sudo snap connect {snap_name}:{iface} 2>&1 && echo OK || echo FAIL"
                )
                if rc and "OK" in rc:
                    fixed.append(iface)
            repaired = len(fixed) == len(missing)
            detail = f"Connected: {', '.join(fixed)}" if fixed else f"Failed to connect: {', '.join(missing)}"

        results.append(RepairResult(
            name=f"snap-interfaces:{snap_name}",
            detected=detected,
            repaired=repaired,
            detail=detail or "All interfaces connected",
        ))

    return results


def _repair_xdg_runtime_dir(ctx: _RepairCtx) -> List[RepairResult]:
    """
    BUG: /run/user/<uid> may not exist if user hasn't logged in via GDM yet.
    Browsers and other apps need XDG_RUNTIME_DIR.
    FIX: Create the directory with correct ownership.
    """
    uid = ctx.run(f"id -u {ctx.user} 2>/dev/null") or "1000"
    runtime_dir = f"/run/user/{uid.strip()}"

    exists = ctx.run(f"test -d {runtime_dir} && echo y || echo n")
    detected = exists != "y"
    repaired = False

    if detected:
        ctx.run(
            f"sudo mkdir -p {runtime_dir} && "
            f"sudo chown {uid.strip()}:{uid.strip()} {runtime_dir} && "
            f"sudo chmod 700 {runtime_dir}"
        )
        exists2 = ctx.run(f"test -d {runtime_dir} && echo y || echo n")
        repaired = exists2 == "y"

    return [RepairResult(
        name="xdg-runtime-dir",
        detected=detected,
        repaired=repaired,
        detail=f"{runtime_dir} created" if detected and repaired else f"{runtime_dir} exists",
    )]


def _repair_fontconfig_cache(ctx: _RepairCtx) -> List[RepairResult]:
    """
    BUG: Missing font cache after fresh install causes slow first browser launch.
    FIX: Rebuild fontconfig cache.
    """
    has_cache = ctx.run(
        f"test -d /home/{ctx.user}/.cache/fontconfig && "
        f"[ $(ls /home/{ctx.user}/.cache/fontconfig 2>/dev/null | wc -l) -gt 0 ] && echo y || echo n"
    )
    detected = has_cache != "y"
    repaired = False

    if detected:
        ctx.run(
            f"sudo -u {ctx.user} fc-cache -f 2>/dev/null || true",
            timeout=60,
        )
        has_cache2 = ctx.run(
            f"test -d /home/{ctx.user}/.cache/fontconfig && echo y || echo n"
        )
        repaired = has_cache2 == "y"

    return [RepairResult(
        name="fontconfig-cache",
        detected=detected,
        repaired=repaired,
        detail="Font cache rebuilt" if repaired else "Font cache present",
    )]


def _repair_machine_id(ctx: _RepairCtx) -> List[RepairResult]:
    """
    BUG: Cloned VMs may have the same /etc/machine-id as the base image,
    causing dbus, browser telemetry, and session issues.
    FIX: Regenerate machine-id if it matches a known base image pattern or is empty.
    """
    mid = ctx.run("cat /etc/machine-id 2>/dev/null") or ""
    mid = mid.strip()

    # Detect: empty, all zeros, or suspiciously short
    detected = (
        not mid
        or mid == "0" * 32
        or len(mid) < 32
    )
    repaired = False

    if detected:
        ctx.run(
            "sudo rm -f /etc/machine-id && "
            "sudo systemd-machine-id-setup 2>/dev/null && "
            "sudo dbus-uuidgen --ensure=/etc/machine-id 2>/dev/null || true"
        )
        new_mid = ctx.run("cat /etc/machine-id 2>/dev/null") or ""
        repaired = len(new_mid.strip()) == 32 and new_mid.strip() != "0" * 32

    return [RepairResult(
        name="machine-id",
        detected=detected,
        repaired=repaired,
        detail="Regenerated /etc/machine-id" if repaired else f"machine-id OK ({mid[:8]}...)",
    )]


def _repair_dbus_session(ctx: _RepairCtx) -> List[RepairResult]:
    """
    BUG: Snap browsers need a running dbus session. Without it they fail silently.
    FIX: Ensure dbus-user-session is installed and the socket exists.
    """
    has_dbus = ctx.run(
        "dpkg -l dbus-user-session 2>/dev/null | grep -q '^ii' && echo y || echo n"
    )
    detected = has_dbus != "y"
    repaired = False

    if detected:
        ctx.run(
            "sudo apt-get install -y dbus-user-session >/dev/null 2>&1 || true",
            timeout=60,
        )
        has_dbus2 = ctx.run(
            "dpkg -l dbus-user-session 2>/dev/null | grep -q '^ii' && echo y || echo n"
        )
        repaired = has_dbus2 == "y"

    return [RepairResult(
        name="dbus-user-session",
        detected=detected,
        repaired=repaired,
        detail="Installed dbus-user-session" if repaired else "dbus-user-session present",
    )]


def _repair_home_dir_permissions(ctx: _RepairCtx) -> List[RepairResult]:
    """
    BUG: /home/<user> or subdirs may be owned by root after copy operations.
    FIX: Fix ownership of key directories.
    """
    dirs_to_check = [
        f"/home/{ctx.user}/.config",
        f"/home/{ctx.user}/.local",
        f"/home/{ctx.user}/.mozilla",
    ]
    bad = []
    for d in dirs_to_check:
        owner = ctx.run(f"stat -c '%U' {shlex.quote(d)} 2>/dev/null || echo MISSING")
        if owner and owner != "MISSING" and owner != ctx.user:
            bad.append(d)

    detected = len(bad) > 0
    repaired = False

    if detected:
        for d in bad:
            ctx.run(f"sudo chown -R {ctx.user}:{ctx.user} {shlex.quote(d)}")
        still_bad = 0
        for d in bad:
            owner = ctx.run(f"stat -c '%U' {shlex.quote(d)} 2>/dev/null")
            if owner != ctx.user:
                still_bad += 1
        repaired = still_bad == 0

    return [RepairResult(
        name="home-dir-permissions",
        detected=detected,
        repaired=repaired,
        detail=f"Fixed {len(bad)} dirs" if detected else "Home dir permissions OK",
    )]


def _repair_gdm_running(ctx: _RepairCtx, gui_mode: bool) -> List[RepairResult]:
    """
    BUG: GDM may not start after cloud-init desktop install until reboot.
    FIX: Start or restart gdm3.
    """
    if not gui_mode:
        return []

    status = ctx.run("systemctl is-active gdm3 2>/dev/null") or "inactive"
    detected = status.strip() != "active"
    repaired = False

    if detected:
        ctx.run("sudo systemctl restart gdm3 2>/dev/null || sudo systemctl start gdm3 2>/dev/null || true")
        import time
        time.sleep(3)
        status2 = ctx.run("systemctl is-active gdm3 2>/dev/null") or "inactive"
        repaired = status2.strip() == "active"

    return [RepairResult(
        name="gdm-running",
        detected=detected,
        repaired=repaired,
        detail=f"GDM status: {status.strip()}" + (f" → active" if repaired else ""),
    )]


def _repair_dns_resolution(ctx: _RepairCtx) -> List[RepairResult]:
    """
    BUG: DNS may not work right after boot (systemd-resolved not ready).
    FIX: Restart systemd-resolved and verify.
    """
    dns_ok = ctx.run("getent hosts archive.ubuntu.com >/dev/null 2>&1 && echo y || echo n")
    detected = dns_ok != "y"
    repaired = False

    if detected:
        ctx.run("sudo systemctl restart systemd-resolved 2>/dev/null || true")
        import time
        time.sleep(2)
        dns_ok2 = ctx.run("getent hosts archive.ubuntu.com >/dev/null 2>&1 && echo y || echo n")
        repaired = dns_ok2 == "y"

    return [RepairResult(
        name="dns-resolution",
        detected=detected,
        repaired=repaired,
        detail="DNS fixed" if repaired else ("DNS not working" if detected else "DNS OK"),
    )]


def _repair_apt_lock(ctx: _RepairCtx) -> List[RepairResult]:
    """
    BUG: dpkg/apt may still hold locks after cloud-init finishes.
    FIX: Wait for locks to release (up to 60s).
    """
    busy = ctx.run("fuser /var/lib/dpkg/lock-frontend 2>/dev/null && echo busy || echo idle")
    detected = busy == "busy"
    repaired = False

    if detected:
        import time
        for _ in range(12):
            time.sleep(5)
            busy2 = ctx.run("fuser /var/lib/dpkg/lock-frontend 2>/dev/null && echo busy || echo idle")
            if busy2 != "busy":
                repaired = True
                break

    return [RepairResult(
        name="apt-lock",
        detected=detected,
        repaired=repaired if detected else False,
        detail="apt lock released" if repaired else ("apt lock held" if detected and not repaired else "No apt lock"),
    )]


def _repair_firefox_profiles_ini(ctx: _RepairCtx) -> List[RepairResult]:
    """
    BUG: Firefox profiles.ini may reference wrong absolute paths after copy
    from host to VM (different home path or snap revision).
    FIX: Rewrite profiles.ini to use relative paths.
    """
    ini_paths = [
        f"/home/{ctx.user}/snap/firefox/common/.mozilla/firefox/profiles.ini",
        f"/home/{ctx.user}/.mozilla/firefox/profiles.ini",
    ]

    for ini_path in ini_paths:
        content = ctx.run(f"cat {shlex.quote(ini_path)} 2>/dev/null") or ""
        if not content or "[Profile" not in content:
            continue

        # Check for absolute paths that don't match VM user home
        # e.g. Path=/home/tom/.mozilla/firefox/xxx.default instead of relative
        if re.search(r'Path=/home/(?!' + re.escape(ctx.user) + r'/)', content):
            detected = True
            # Fix: convert absolute paths to relative
            lines = content.splitlines()
            fixed_lines = []
            for line in lines:
                if line.startswith("Path=/home/"):
                    # Extract just the profile directory name
                    parts = line.split("/")
                    profile_dir = parts[-1] if parts[-1] else parts[-2]
                    fixed_lines.append(f"Path={profile_dir}")
                elif line.strip() == "IsRelative=0":
                    fixed_lines.append("IsRelative=1")
                else:
                    fixed_lines.append(line)

            new_content = "\n".join(fixed_lines) + "\n"
            escaped = shlex.quote(new_content)
            ctx.run(f"echo {escaped} | sudo tee {shlex.quote(ini_path)} >/dev/null")
            ctx.run(f"sudo chown {ctx.user}:{ctx.user} {shlex.quote(ini_path)}")

            return [RepairResult(
                name="firefox-profiles-ini",
                detected=True,
                repaired=True,
                detail=f"Rewrote absolute paths to relative in {ini_path}",
            )]

    return [RepairResult(
        name="firefox-profiles-ini",
        detected=False,
        repaired=False,
        detail="profiles.ini paths OK or not present",
    )]


def _verify_headless_browsers(ctx: _RepairCtx, browsers: List[str]) -> List[RepairResult]:
    """
    VERIFY: Run headless smoke test for each browser after all repairs.
    This doesn't repair — it validates the repairs worked.
    """
    results = []
    uid = ctx.run(f"id -u {ctx.user} 2>/dev/null") or "1000"
    runtime_dir = f"/run/user/{uid.strip()}"
    user_env = (
        f"sudo -u {ctx.user} env HOME=/home/{ctx.user} "
        f"USER={ctx.user} LOGNAME={ctx.user} XDG_RUNTIME_DIR={runtime_dir}"
    )

    tests = {
        "firefox": f"timeout 25 {user_env} firefox --headless --version >/dev/null 2>&1 && echo y || echo n",
        "chrome": (
            f"timeout 15 {user_env} sh -c '"
            f"(google-chrome --headless=new --no-sandbox --disable-gpu --dump-dom about:blank || "
            f"google-chrome-stable --headless=new --no-sandbox --disable-gpu --dump-dom about:blank) "
            f">/dev/null 2>&1' && echo y || echo n"
        ),
        "chromium": (
            f"timeout 15 {user_env} chromium --headless=new --no-sandbox --disable-gpu "
            f"--dump-dom about:blank >/dev/null 2>&1 && echo y || echo n"
        ),
    }

    for browser in browsers:
        cmd = tests.get(browser)
        if not cmd:
            continue

        has_browser = ctx.run(
            f"command -v {browser if browser != 'chrome' else 'google-chrome'} >/dev/null 2>&1 && echo y || echo n"
        )
        if has_browser != "y":
            continue

        out = ctx.run(cmd, timeout=40)
        ok = out == "y"

        results.append(RepairResult(
            name=f"headless-verify:{browser}",
            detected=not ok,
            repaired=False,  # this is a verify step, not a repair
            detail="headless OK" if ok else "headless FAILED after repairs",
        ))

    return results


# ═════════════════════════════════════════════════════════════════════════════
#  MAIN ENTRY POINT
# ═════════════════════════════════════════════════════════════════════════════

def run_post_install_repairs(
    ssh_port: int,
    ssh_key: Optional[Path],
    vm_username: str = "ubuntu",
    browsers: Optional[List[str]] = None,
    gui_mode: bool = False,
) -> RepairReport:
    """Run all post-install diagnostics and auto-repairs.

    Args:
        ssh_port: SSH port to the VM.
        ssh_key: Path to SSH private key.
        vm_username: Username inside the VM.
        browsers: List of browser names to check (e.g. ["firefox", "chrome", "chromium"]).
        gui_mode: Whether the VM was configured with GUI.

    Returns:
        RepairReport with all results.
    """
    browsers = browsers or []
    ctx = _RepairCtx(ssh_port, ssh_key, vm_username)
    report = RepairReport()

    log.info("=" * 60)
    log.info("POST-INSTALL DIAGNOSTICS & AUTO-REPAIR")
    log.info("=" * 60)

    # Phase 1: System-level repairs
    log.info("[Phase 1/4] System checks...")
    report.results.extend(_repair_dns_resolution(ctx))
    report.results.extend(_repair_apt_lock(ctx))
    report.results.extend(_repair_xdg_runtime_dir(ctx))
    report.results.extend(_repair_machine_id(ctx))
    report.results.extend(_repair_dbus_session(ctx))
    report.results.extend(_repair_gdm_running(ctx, gui_mode))

    # Phase 2: File ownership and permissions
    log.info("[Phase 2/4] File ownership & permissions...")
    report.results.extend(_repair_home_dir_permissions(ctx))
    report.results.extend(_repair_snap_dir_ownership(ctx, browsers))
    report.results.extend(_repair_browser_profile_ownership(ctx))

    # Phase 3: Browser-specific repairs
    log.info("[Phase 3/4] Browser profile repairs...")
    report.results.extend(_repair_browser_lock_files(ctx))
    report.results.extend(_repair_browser_crash_reports(ctx))
    report.results.extend(_repair_firefox_profiles_ini(ctx))
    report.results.extend(_repair_snap_interfaces(ctx, browsers))
    report.results.extend(_repair_fontconfig_cache(ctx))

    # Phase 4: Verification
    log.info("[Phase 4/4] Headless verification...")
    report.results.extend(_verify_headless_browsers(ctx, browsers))

    report.log_summary()
    return report


# ── CLI entrypoint ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if len(sys.argv) < 2:
        print(f"Usage: python -m clonebox.post_install_repair <vm-name> [browsers...]")
        sys.exit(1)

    vm_name = sys.argv[1]
    browsers_arg = sys.argv[2:] if len(sys.argv) > 2 else ["firefox", "chrome", "chromium"]

    from clonebox.paths import resolve_ssh_port, ssh_key_path
    port = resolve_ssh_port(vm_name, user_session=True)
    key = ssh_key_path(vm_name, user_session=True)

    if not port:
        print(f"Cannot resolve SSH port for '{vm_name}'")
        sys.exit(1)

    report = run_post_install_repairs(
        ssh_port=port,
        ssh_key=key,
        browsers=browsers_arg,
        gui_mode=True,
    )
    sys.exit(report.failed_count)
