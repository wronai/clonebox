#!/usr/bin/env python3
"""
Advanced CloneBox VM Diagnostic Suite
====================================
Enhanced diagnostic with specific error detection and cloud-init monitoring.
Detects YAML parsing errors, network configuration issues, and provides targeted fixes.

Usage:
    python scripts/advanced_vm_diagnostic.py [vm_name] [--fix] [--watch]
"""

import subprocess
import json
import sys
import os
import time
import re
import signal
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Callable
from enum import Enum
from datetime import datetime
import threading


class TestStatus(Enum):
    PASS = "✅ PASS"
    FAIL = "❌ FAIL"
    SKIP = "⏭️ SKIP"
    WAIT = "⏳ WAIT"
    WARN = "⚠️ WARN"
    INFO = "ℹ️ INFO"
    FIX = "🔧 FIX"


@dataclass
class DiagnosticIssue:
    """Represents a specific diagnostic issue with potential fix."""
    name: str
    pattern: str
    description: str
    severity: str  # critical, warning, info
    fix_command: Optional[str] = None
    fix_script: Optional[str] = None
    requires_reboot: bool = False


class AdvancedVMDiagnostic:
    """Enhanced diagnostic with specific error detection and auto-fix capabilities."""
    
    def __init__(self, vm_name: str, conn_uri: str = "qemu:///session"):
        self.vm_name = vm_name
        self.conn_uri = conn_uri
        self.vm_dir = Path.home() / ".local/share/libvirt/images" / vm_name
        self.cloudinit_dir = self.vm_dir / "cloud-init"
        self.serial_log = self.vm_dir / "serial.log"
        
        # Define known issues and their patterns
        self.known_issues = [
            DiagnosticIssue(
                name="YAML Parsing Error in bootcmd",
                pattern=r"Failed loading yaml blob.*Invalid format at line.*column.*while parsing a flow sequence",
                description="Cloud-init cannot parse YAML in bootcmd due to improper list format",
                severity="critical",
                fix_script="scripts/fix_yaml_bootcmd.py"
            ),
            DiagnosticIssue(
                name="No Network Interface Found",
                pattern=r"No NIC found|Cannot find device",
                description="Network interface not detected - likely naming mismatch",
                severity="critical",
                fix_command="ip link show | grep -E 'enp|eth' | head -1 | cut -d: -f2 | tr -d ' '"
            ),
            DiagnosticIssue(
                name="SSH Keys Not Found",
                pattern=r"no authorized SSH keys fingerprints found",
                description="SSH keys not properly injected into VM",
                severity="warning",
                fix_script="scripts/fix_ssh_keys.py"
            ),
            DiagnosticIssue(
                name="Network Configuration Failed",
                pattern=r"Failed to shellify|network-config.*failed",
                description="Network configuration syntax error",
                severity="critical",
                fix_script="scripts/fix_network_config.py"
            ),
            DiagnosticIssue(
                name="Cloud-init Module Failed",
                pattern=r"Cloud-init.*failed at.*module",
                description="Specific cloud-init module failed",
                severity="warning"
            ),
            DiagnosticIssue(
                name="Service Failed to Start",
                pattern=r"Failed to start.*\.service",
                description="Systemd service failed during boot",
                severity="warning"
            )
        ]
        
        self.results = []
        self.issues_found = []
        self.watching = False
        
    def run_cmd(self, cmd: List[str], timeout: int = 10) -> tuple[int, str, str]:
        """Run command and return (returncode, stdout, stderr)."""
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return result.returncode, result.stdout.strip(), result.stderr.strip()
        except subprocess.TimeoutExpired:
            return -1, "", "Command timed out"
        except Exception as e:
            return -1, "", str(e)
    
    def analyze_serial_log(self) -> Dict[str, Any]:
        """Deep analysis of serial.log for known issues."""
        if not self.serial_log.exists():
            return {"exists": False}
        
        content = self.serial_log.read_text()
        lines = content.split('\n')
        
        analysis = {
            "exists": True,
            "size": len(content),
            "lines": len(lines),
            "issues": [],
            "boot_time": None,
            "cloud_init_stages": {},
            "network_events": [],
            "errors": [],
            "warnings": []
        }
        
        # Find boot time
        for line in lines:
            if "Cloud-init v." in line and "Up" in line:
                match = re.search(r'Up ([\d.]+) seconds', line)
                if match:
                    analysis["boot_time"] = float(match.group(1))
                    break
        
        # Track cloud-init stages
        for i, line in enumerate(lines):
            if "Cloud-init" in line and "running" in line:
                match = re.search(r"running 'modules:(\w+)'", line)
                if match:
                    stage = match.group(1)
                    analysis["cloud_init_stages"][stage] = i
        
        # Check for known issues
        for issue in self.known_issues:
            matches = []
            for i, line in enumerate(lines):
                if re.search(issue.pattern, line, re.IGNORECASE):
                    matches.append({
                        "line_number": i,
                        "content": line[:200],
                        "context": lines[max(0, i-2):i+3]
                    })
            
            if matches:
                analysis["issues"].append({
                    "issue": issue.name,
                    "severity": issue.severity,
                    "matches": matches
                })
                self.issues_found.append(issue)
        
        # Extract errors and warnings
        for line in lines:
            if "error" in line.lower() or "fail" in line.lower():
                analysis["errors"].append(line)
            if "warn" in line.lower():
                analysis["warnings"].append(line)
        
        return analysis
    
    def check_cloud_init_progress(self) -> Dict[str, Any]:
        """Check current cloud-init progress."""
        progress = {
            "stage": "unknown",
            "complete": False,
            "failed": False,
            "last_activity": None
        }
        
        if not self.serial_log.exists():
            return progress
        
        content = self.serial_log.read_text()
        
        # Check if complete
        if "Cloud-init.*finished" in content:
            progress["complete"] = True
            progress["stage"] = "complete"
        
        # Check for failures
        if "Cloud-init.*failed" in content or "ci-info: no authorized SSH keys" in content:
            progress["failed"] = True
        
        # Find current stage
        stages = ["init", "config", "final"]
        for stage in stages:
            pattern = f"running 'modules:{stage}'"
            if pattern in content:
                progress["stage"] = stage
        
        # Find last activity
        lines = content.split('\n')
        cloud_init_lines = [l for l in lines if "cloud-init" in l.lower()]
        if cloud_init_lines:
            progress["last_activity"] = cloud_init_lines[-1][:100]
        
        return progress
    
    def detect_network_interface_name(self) -> Optional[str]:
        """Try to detect the actual network interface name in VM."""
        # Check serial log for interface names
        if self.serial_log.exists():
            content = self.serial_log.read_text()
            
            # Look for interface initialization
            if_match = re.search(r'(\b(enp\d+s\d|eth\d|ens\d)\b)', content)
            if if_match:
                return if_match.group(1)
        
        # Try via QEMU guest agent if available
        try:
            rc, out, _ = self.run_cmd([
                "virsh", "--connect", self.conn_uri,
                "qemu-agent-command", self.vm_name,
                '{"execute":"guest-network-get-interfaces"}'
            ], timeout=5)
            
            if rc == 0:
                data = json.loads(out)
                for iface in data.get("return", []):
                    name = iface.get("name", "")
                    if name.startswith("enp") or name.startswith("eth") or name.startswith("ens"):
                        if name != "lo":
                            return name
        except:
            pass
        
        return None
    
    def generate_fixes(self) -> List[Dict[str, Any]]:
        """Generate specific fixes for detected issues."""
        fixes = []
        
        for issue in self.issues_found:
            if issue.severity == "critical":
                fix_info = {
                    "issue": issue.name,
                    "severity": issue.severity,
                    "description": issue.description,
                    "fix_available": bool(issue.fix_command or issue.fix_script)
                }
                
                if issue.fix_command:
                    fix_info["command"] = issue.fix_command
                elif issue.fix_script:
                    fix_info["script"] = issue.fix_script
                
                if issue.name == "YAML Parsing Error in bootcmd":
                    fix_info["fix"] = self._generate_yaml_fix()
                elif issue.name == "No Network Interface Found":
                    interface = self.detect_network_interface_name()
                    if interface:
                        fix_info["detected_interface"] = interface
                        fix_info["fix"] = f"Update bootcmd to use '{interface}' instead of pattern matching"
                
                fixes.append(fix_info)
        
        return fixes
    
    def _generate_yaml_fix(self) -> str:
        """Generate specific fix for YAML parsing error."""
        return """
Fix for YAML Parsing Error in bootcmd:
======================================

The error occurs when bootcmd contains strings with colons that YAML interprets as key-value pairs.

Current problematic format:
  bootcmd:
    - echo "message: with colon"  # ❌ YAML error

Correct format:
  bootcmd:
    - ["sh", "-c", "echo message: with colon"]  # ✅ Proper list format

To fix:
1. Edit src/clonebox/cloner.py
2. Find bootcmd_lines construction
3. Ensure all commands are in list format: ["command", "arg1", "arg2"]
4. Rebuild cloud-init ISO and restart VM
"""
    
    def watch_cloud_init(self, duration: int = 300):
        """Watch cloud-init progress in real-time."""
        print(f"\n👁️  Watching cloud-init progress for {duration}s...")
        print("   Press Ctrl+C to stop watching\n")
        
        self.watching = True
        start_time = time.time()
        last_size = 0
        
        def signal_handler(sig, frame):
            print("\n⏹️  Stopping watch...")
            self.watching = False
        
        signal.signal(signal.SIGINT, signal_handler)
        
        while self.watching and time.time() - start_time < duration:
            if self.serial_log.exists():
                current_size = self.serial_log.stat().st_size
                
                if current_size > last_size:
                    # Show new lines
                    with open(self.serial_log, 'r') as f:
                        f.seek(last_size)
                        new_content = f.read()
                        
                        # Filter for important messages
                        for line in new_content.split('\n'):
                            if any(keyword in line.lower() for keyword in ['cloud-init', 'error', 'fail', 'warn', 'ssh', 'network']):
                                print(f"   {line}")
                
                last_size = current_size
                
                # Check if complete
                progress = self.check_cloud_init_progress()
                if progress["complete"]:
                    print(f"\n✅ Cloud-init completed! Boot time: {progress.get('boot_time', 'N/A')}s")
                    break
                elif progress["failed"]:
                    print(f"\n❌ Cloud-init failed! Last stage: {progress['stage']}")
                    break
            
            time.sleep(1)
        
        self.watching = False
    
    def apply_fix(self, fix_info: Dict[str, Any]) -> bool:
        """Apply a specific fix."""
        print(f"\n🔧 Applying fix for: {fix_info['issue']}")
        
        if "command" in fix_info:
            print(f"   Running: {fix_info['command']}")
            rc, out, err = self.run_cmd(["bash", "-c", fix_info['command']])
            if rc == 0:
                print(f"   ✅ Fix applied successfully")
                return True
            else:
                print(f"   ❌ Fix failed: {err}")
                return False
        
        elif "script" in fix_info:
            script_path = Path(fix_info['script'])
            if script_path.exists():
                print(f"   Running script: {script_path}")
                rc, out, err = self.run_cmd(["python", str(script_path), self.vm_name])
                if rc == 0:
                    print(f"   ✅ Fix applied successfully")
                    return True
                else:
                    print(f"   ❌ Script failed: {err}")
                    return False
            else:
                print(f"   ❌ Script not found: {script_path}")
                return False
        
        return False
    
    def run_comprehensive_diagnostic(self) -> Dict[str, Any]:
        """Run full diagnostic analysis."""
        print(f"\n🔍 Running comprehensive diagnostic for VM: {self.vm_name}")
        print("=" * 70)
        
        # Basic VM status
        rc, out, _ = self.run_cmd(["virsh", "--connect", self.conn_uri, "dominfo", self.vm_name])
        vm_status = {"exists": rc == 0}
        if rc == 0:
            for line in out.split('\n'):
                if line.startswith('State:'):
                    vm_status["state"] = line.split(':', 1)[1].strip()
        
        # Serial log analysis
        print("\n📋 Analyzing serial.log...")
        serial_analysis = self.analyze_serial_log()
        
        # Cloud-init progress
        print("\n⏳ Checking cloud-init progress...")
        cloud_init_progress = self.check_cloud_init_progress()
        
        # Network interface detection
        print("\n🌐 Detecting network interface...")
        network_interface = self.detect_network_interface_name()
        
        # Generate fixes
        print("\n🔧 Generating fixes for detected issues...")
        fixes = self.generate_fixes()
        
        # Compile report
        report = {
            "vm_name": self.vm_name,
            "timestamp": datetime.now().isoformat(),
            "vm_status": vm_status,
            "serial_analysis": serial_analysis,
            "cloud_init_progress": cloud_init_progress,
            "network_interface": network_interface,
            "issues_found": [issue.name for issue in self.issues_found],
            "fixes": fixes,
            "recommendations": self._generate_recommendations()
        }
        
        return report
    
    def _generate_recommendations(self) -> List[str]:
        """Generate specific recommendations based on findings."""
        recommendations = []
        
        # Check for critical issues
        critical_issues = [i for i in self.issues_found if i.severity == "critical"]
        if critical_issues:
            recommendations.append("🚨 CRITICAL ISSUES FOUND:")
            for issue in critical_issues:
                recommendations.append(f"   • {issue.name}")
                if issue.fix_script:
                    recommendations.append(f"     Run: python {issue.fix_script} {self.vm_name}")
        
        # Cloud-init status
        progress = self.check_cloud_init_progress()
        if not progress["complete"] and not progress["failed"]:
            recommendations.append("\n⏳ Cloud-init still running:")
            recommendations.append(f"   • Current stage: {progress['stage']}")
            recommendations.append(f"   • Watch progress: python {__file__} {self.vm_name} --watch")
        
        # Network issues
        if "No Network Interface Found" in [i.name for i in self.issues_found]:
            interface = self.detect_network_interface_name()
            if interface:
                recommendations.append(f"\n🌐 Network Fix:")
                recommendations.append(f"   • Detected interface: {interface}")
                recommendations.append(f"   • Update cloud-init to use explicit interface name")
        
        # SSH issues
        if "SSH Keys Not Found" in [i.name for i in self.issues_found]:
            recommendations.append("\n🔑 SSH Issue:")
            recommendations.append("   • SSH keys not properly injected")
            recommendations.append("   • Check cloud-init user-data for ssh_authorized_keys")
        
        if not recommendations:
            recommendations.append("✅ No critical issues detected")
            if progress["complete"]:
                recommendations.append("   • VM should be accessible via SSH")
                port_file = self.vm_dir / "ssh_port"
                if port_file.exists():
                    port = port_file.read_text().strip()
                    recommendations.append(f"   • SSH: ssh -i {self.vm_dir}/ssh_key -p {port} ubuntu@127.0.0.1")
        
        return recommendations
    
    def print_report(self, report: Dict[str, Any]):
        """Print formatted diagnostic report."""
        print("\n" + "=" * 70)
        print("  ADVANCED VM DIAGNOSTIC REPORT")
        print("=" * 70)
        
        # VM Status
        print(f"\n📊 VM Status:")
        if report["vm_status"]["exists"]:
            print(f"   • State: {report['vm_status'].get('state', 'unknown')}")
        else:
            print(f"   • VM does not exist")
            return
        
        # Serial Log Summary
        if report["serial_analysis"]["exists"]:
            analysis = report["serial_analysis"]
            print(f"\n📋 Serial Log Analysis:")
            print(f"   • Size: {analysis['size']:,} bytes ({analysis['lines']:,} lines)")
            print(f"   • Boot time: {analysis.get('boot_time', 'N/A')} seconds")
            print(f"   • Errors found: {len(analysis['errors'])}")
            print(f"   • Warnings found: {len(analysis['warnings'])}")
            print(f"   • Issues detected: {len(analysis['issues'])}")
        
        # Cloud-init Progress
        progress = report["cloud_init_progress"]
        print(f"\n⏳ Cloud-init Status:")
        print(f"   • Stage: {progress['stage']}")
        print(f"   • Complete: {'✅ Yes' if progress['complete'] else '❌ No'}")
        print(f"   • Failed: {'❌ Yes' if progress['failed'] else '✅ No'}")
        if progress.get("last_activity"):
            print(f"   • Last: {progress['last_activity']}")
        
        # Network
        print(f"\n🌐 Network:")
        if report["network_interface"]:
            print(f"   • Detected interface: {report['network_interface']}")
        else:
            print(f"   • Interface: Not detected")
        
        # Issues Found
        if report["issues_found"]:
            print(f"\n🚨 Issues Found:")
            for issue in report["issues_found"]:
                print(f"   • {issue}")
        
        # Fixes Available
        if report["fixes"]:
            print(f"\n🔧 Available Fixes:")
            for fix in report["fixes"]:
                print(f"\n   Issue: {fix['issue']}")
                print(f"   Severity: {fix['severity']}")
                print(f"   Description: {fix['description']}")
                if fix.get("fix"):
                    print(f"   Fix: {fix['fix'][:200]}...")
        
        # Recommendations
        print(f"\n💡 Recommendations:")
        for rec in report["recommendations"]:
            print(rec)
        
        print("\n" + "=" * 70)


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Advanced CloneBox VM Diagnostic")
    parser.add_argument("vm_name", nargs="?", default="clone-clonebox", help="VM name")
    parser.add_argument("--fix", action="store_true", help="Apply automatic fixes")
    parser.add_argument("--watch", "-w", action="store_true", help="Watch cloud-init progress")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--conn-uri", default="qemu:///session", help="Libvirt connection URI")
    
    args = parser.parse_args()
    
    diag = AdvancedVMDiagnostic(args.vm_name, args.conn_uri)
    
    if args.watch:
        diag.watch_cloud_init()
        return
    
    # Run diagnostic
    report = diag.run_comprehensive_diagnostic()
    
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        diag.print_report(report)
        
        # Apply fixes if requested
        if args.fix and report["fixes"]:
            print(f"\n🔧 Applying fixes...")
            for fix in report["fixes"]:
                if fix["severity"] == "critical":
                    diag.apply_fix(fix)


if __name__ == "__main__":
    main()
