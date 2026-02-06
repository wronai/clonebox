#!/usr/bin/env python3
"""
CloneBox VM State Diagnostic Suite
===================================
Comprehensive diagnostic tests that work like a decision tree.
If a test fails, dependent tests are skipped with explanation.
Generates Q&A format report to identify issues.

Usage:
    python scripts/vm_state_diagnostic.py [vm_name] [--json] [--verbose]
"""

import subprocess
import json
import time
import socket
import base64
import os
import sys
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime

# Allow importing from the clonebox package
_src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")
if os.path.isdir(_src):
    sys.path.insert(0, _src)

try:
    from clonebox.ssh import ssh_exec as _pkg_ssh_exec
    from clonebox.paths import resolve_ssh_port, ssh_key_path as _ssh_key_path, vm_dir as _vm_dir
    _HAS_PKG = True
except ImportError:
    _HAS_PKG = False

from vm_state_diagnostic_models import DiagnosticContext, TestResult, TestStatus

class VMDiagnostic:
    """Diagnostic test suite for CloneBox VMs."""
    
    def __init__(self, vm_name: str, conn_uri: str = "qemu:///session", verbose: bool = False):
        self.ctx = DiagnosticContext(vm_name=vm_name, conn_uri=conn_uri)
        self.verbose = verbose
        
    def run_cmd(self, cmd: List[str], timeout: int = 10) -> tuple[int, str, str]:
        """Run command and return (returncode, stdout, stderr)."""
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return result.returncode, result.stdout.strip(), result.stderr.strip()
        except subprocess.TimeoutExpired:
            return -1, "", "Command timed out"
        except Exception as e:
            return -1, "", str(e)

    def virsh(self, *args, timeout: int = 10) -> tuple[int, str, str]:
        """Run virsh command."""
        cmd = ["virsh", "--connect", self.ctx.conn_uri] + list(args)
        return self.run_cmd(cmd, timeout)

    def qga_exec(self, command: str, timeout: int = 15) -> Optional[str]:
        """Execute command via QEMU Guest Agent."""
        try:
            payload = {
                "execute": "guest-exec",
                "arguments": {
                    "path": "/bin/sh",
                    "arg": ["-c", command],
                    "capture-output": True,
                },
            }
            rc, out, _ = self.virsh("qemu-agent-command", self.ctx.vm_name, json.dumps(payload), timeout=timeout)
            if rc != 0:
                return None
            
            resp = json.loads(out)
            pid = resp.get("return", {}).get("pid")
            if not pid:
                return None
            
            deadline = time.time() + timeout
            while time.time() < deadline:
                status_payload = {"execute": "guest-exec-status", "arguments": {"pid": pid}}
                rc, out, _ = self.virsh("qemu-agent-command", self.ctx.vm_name, json.dumps(status_payload), timeout=5)
                if rc != 0:
                    return None
                
                status_resp = json.loads(out)
                ret = status_resp.get("return", {})
                if not ret.get("exited", False):
                    time.sleep(0.3)
                    continue
                
                out_data = ret.get("out-data")
                if out_data:
                    return base64.b64decode(out_data).decode().strip()
                return ""
            return None
        except Exception:
            return None

    def ssh_exec(self, command: str, timeout: int = 15) -> Optional[str]:
        """Execute command via SSH."""
        if not self.ctx.ssh_key_path or not self.ctx.ssh_port:
            return None
        if _HAS_PKG:
            return _pkg_ssh_exec(
                port=self.ctx.ssh_port, key=self.ctx.ssh_key_path,
                command=command, timeout=timeout, connect_timeout=5,
            )
        try:
            result = subprocess.run([
                "ssh", "-i", str(self.ctx.ssh_key_path),
                "-p", str(self.ctx.ssh_port),
                "-o", "StrictHostKeyChecking=no",
                "-o", "UserKnownHostsFile=/dev/null",
                "-o", "ConnectTimeout=5",
                "-o", "BatchMode=yes",
                "ubuntu@127.0.0.1", command
            ], capture_output=True, text=True, timeout=timeout)
            if result.returncode == 0:
                return result.stdout.strip()
            return None
        except Exception:
            return None

    def exec_in_vm(self, command: str, timeout: int = 15) -> Optional[str]:
        """Execute command in VM using best available method."""
        # Try QGA first (more reliable if available)
        if self.ctx.qga_responding:
            result = self.qga_exec(command, timeout)
            if result is not None:
                return result
        # Fallback to SSH
        if self.ctx.ssh_works:
            return self.ssh_exec(command, timeout)
        return None

    def add_result(self, result: TestResult):
        """Add test result to context."""
        self.ctx.results.append(result)
        if self.verbose:
            print(f"{result.status.value} {result.name}")
            print(f"   Q: {result.question}")
            print(f"   A: {result.answer}")
            if result.diagnosis:
                print(f"   Diagnosis: {result.diagnosis}")

    # ============== TEST METHODS ==============

    def test_vm_exists(self) -> TestResult:
        """Check if VM is defined in libvirt."""
        rc, out, err = self.virsh("dominfo", self.ctx.vm_name)
        
        if rc == 0:
            self.ctx.vm_exists = True
            # Parse state from dominfo
            for line in out.split('\n'):
                if line.startswith('State:'):
                    state = line.split(':', 1)[1].strip()
                    break
            return TestResult(
                name="VM Existence",
                question="Czy VM jest zdefiniowana w libvirt?",
                status=TestStatus.PASS,
                answer=f"Tak, VM '{self.ctx.vm_name}' istnieje",
                details={"state": state},
                blocking=True
            )
        else:
            return TestResult(
                name="VM Existence",
                question="Czy VM jest zdefiniowana w libvirt?",
                status=TestStatus.FAIL,
                answer=f"Nie, VM '{self.ctx.vm_name}' nie została znaleziona",
                diagnosis="VM nie istnieje lub nie została poprawnie utworzona",
                suggestion="Uruchom: clonebox clone . --user --run",
                blocking=True
            )

    def test_vm_running(self) -> TestResult:
        """Check if VM is running."""
        if not self.ctx.vm_exists:
            return TestResult(
                name="VM Running State",
                question="Czy VM jest uruchomiona?",
                status=TestStatus.SKIP,
                answer="Pominięto - VM nie istnieje",
                blocking=True
            )
        
        rc, out, _ = self.virsh("domstate", self.ctx.vm_name)
        state = out.strip() if rc == 0 else "unknown"
        
        if state == "running":
            self.ctx.vm_running = True
            return TestResult(
                name="VM Running State",
                question="Czy VM jest uruchomiona?",
                status=TestStatus.PASS,
                answer="Tak, VM jest uruchomiona",
                details={"state": state},
                blocking=True
            )
        else:
            return TestResult(
                name="VM Running State",
                question="Czy VM jest uruchomiona?",
                status=TestStatus.FAIL,
                answer=f"Nie, stan VM: {state}",
                diagnosis=f"VM jest w stanie '{state}', nie 'running'",
                suggestion="Uruchom: virsh --connect qemu:///session start " + self.ctx.vm_name,
                blocking=True
            )

    def test_vm_directory(self) -> TestResult:
        """Check VM directory and files."""
        if not self.ctx.vm_exists:
            return TestResult(
                name="VM Directory",
                question="Czy katalog VM istnieje z wymaganymi plikami?",
                status=TestStatus.SKIP,
                answer="Pominięto - VM nie istnieje"
            )
        
        details = {}
        missing = []
        
        expected_files = ["root.qcow2", "cloud-init.iso", "ssh_key", "ssh_port"]
        for f in expected_files:
            path = self.ctx.vm_dir / f
            if path.exists():
                details[f] = "exists"
                if f == "ssh_key":
                    self.ctx.ssh_key_path = path
                elif f == "ssh_port":
                    try:
                        self.ctx.ssh_port = int(path.read_text().strip())
                    except:
                        details[f] = "invalid"
                        missing.append(f"{f} (invalid content)")
            else:
                details[f] = "missing"
                missing.append(f)
        
        # Check serial.log
        serial_log = self.ctx.vm_dir / "serial.log"
        if serial_log.exists():
            size = serial_log.stat().st_size
            details["serial.log"] = f"{size} bytes"
        else:
            details["serial.log"] = "missing"
        
        if missing:
            return TestResult(
                name="VM Directory",
                question="Czy katalog VM istnieje z wymaganymi plikami?",
                status=TestStatus.WARN,
                answer=f"Brakujące pliki: {', '.join(missing)}",
                details=details,
                diagnosis="Niektóre pliki VM nie istnieją"
            )
        else:
            return TestResult(
                name="VM Directory",
                question="Czy katalog VM istnieje z wymaganymi plikami?",
                status=TestStatus.PASS,
                answer=f"Wszystkie pliki istnieją w {self.ctx.vm_dir}",
                details=details
            )

    def test_passt_process(self) -> TestResult:
        """Check if passt/QEMU port-forwarding is active for this VM."""
        if not self.ctx.vm_running:
            return TestResult(
                name="Passt Process",
                question="Czy port-forwarding SSH działa dla tej VM?",
                status=TestStatus.SKIP,
                answer="Pominięto - VM nie jest uruchomiona"
            )
        
        import re
        details = {}
        
        # 1. Check for dedicated passt process
        rc, out, _ = self.run_cmd(["pgrep", "-af", "passt"])
        passt_lines = [l for l in out.split('\n')
                       if self.ctx.vm_name in l and l.strip()
                       and "pgrep" not in l]
        
        if passt_lines:
            for line in passt_lines:
                if "--tcp-ports" in line:
                    match = re.search(r'--tcp-ports\s+[\d\.]+/(\d+):22', line)
                    if match:
                        port = int(match.group(1))
                        if self.ctx.ssh_port is None:
                            self.ctx.ssh_port = port
                        self.ctx.passt_active = True
            
            if self.ctx.passt_active:
                details["method"] = "passt"
                details["ssh_port"] = self.ctx.ssh_port
                return TestResult(
                    name="Passt Process",
                    question="Czy port-forwarding SSH działa dla tej VM?",
                    status=TestStatus.PASS,
                    answer=f"Tak, passt aktywny (port {self.ctx.ssh_port})",
                    details=details
                )
        
        # 2. Fallback: check QEMU hostfwd (built-in user-mode networking)
        rc2, qemu_out, _ = self.run_cmd(["bash", "-c",
            f"ps aux | grep '[q]emu.*{self.ctx.vm_name}' | grep -oP 'hostfwd=tcp::\\K\\d+(?=-:22)' | head -1"])
        fwd_port = qemu_out.strip()
        if fwd_port and fwd_port.isdigit():
            port = int(fwd_port)
            if self.ctx.ssh_port is None:
                self.ctx.ssh_port = port
            self.ctx.passt_active = True
            details["method"] = "qemu-hostfwd"
            details["ssh_port"] = port
            return TestResult(
                name="Passt Process",
                question="Czy port-forwarding SSH działa dla tej VM?",
                status=TestStatus.PASS,
                answer=f"Tak, QEMU hostfwd aktywny (port {port})",
                details=details
            )
        
        return TestResult(
            name="Passt Process",
            question="Czy port-forwarding SSH działa dla tej VM?",
            status=TestStatus.FAIL,
            answer="Nie znaleziono port-forwarding dla SSH",
            diagnosis="Ani passt ani QEMU hostfwd nie przekierowują portu SSH",
            suggestion="Zrestartuj VM lub sprawdź konfigurację sieci"
        )

    def test_port_listening(self) -> TestResult:
        """Check if SSH port is listening."""
        if not self.ctx.vm_running or not self.ctx.ssh_port:
            return TestResult(
                name="SSH Port Listening",
                question="Czy port SSH nasłuchuje na hoście?",
                status=TestStatus.SKIP,
                answer="Pominięto - brak informacji o porcie SSH"
            )
        
        rc, out, _ = self.run_cmd(["ss", "-tlnp"])
        
        if f":{self.ctx.ssh_port}" in out:
            return TestResult(
                name="SSH Port Listening",
                question=f"Czy port {self.ctx.ssh_port} nasłuchuje?",
                status=TestStatus.PASS,
                answer=f"Tak, port {self.ctx.ssh_port} jest aktywny (passt forwarding)",
                details={"port": self.ctx.ssh_port}
            )
        else:
            return TestResult(
                name="SSH Port Listening",
                question=f"Czy port {self.ctx.ssh_port} nasłuchuje?",
                status=TestStatus.FAIL,
                answer=f"Nie, port {self.ctx.ssh_port} nie nasłuchuje",
                diagnosis="Passt nie przekierowuje ruchu SSH",
                suggestion="Sprawdź czy passt jest uruchomiony i poprawnie skonfigurowany"
            )

    def test_tcp_connection(self) -> TestResult:
        """Test TCP connection to SSH port."""
        if not self.ctx.ssh_port:
            return TestResult(
                name="TCP Connection",
                question="Czy można nawiązać połączenie TCP do VM?",
                status=TestStatus.SKIP,
                answer="Pominięto - brak informacji o porcie SSH"
            )
        
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            result = sock.connect_ex(('127.0.0.1', self.ctx.ssh_port))
            sock.close()
            
            if result == 0:
                return TestResult(
                    name="TCP Connection",
                    question=f"Czy można połączyć się TCP z 127.0.0.1:{self.ctx.ssh_port}?",
                    status=TestStatus.PASS,
                    answer="Tak, połączenie TCP udane",
                    details={"host": "127.0.0.1", "port": self.ctx.ssh_port}
                )
            else:
                return TestResult(
                    name="TCP Connection",
                    question=f"Czy można połączyć się TCP z 127.0.0.1:{self.ctx.ssh_port}?",
                    status=TestStatus.FAIL,
                    answer=f"Nie, błąd połączenia (kod: {result})",
                    diagnosis="TCP nie może połączyć się z portem - passt może nie działać"
                )
        except socket.timeout:
            return TestResult(
                name="TCP Connection",
                question=f"Czy można połączyć się TCP z 127.0.0.1:{self.ctx.ssh_port}?",
                status=TestStatus.FAIL,
                answer="Nie, timeout połączenia",
                diagnosis="Połączenie TCP przekroczyło limit czasu"
            )
        except Exception as e:
            return TestResult(
                name="TCP Connection",
                question=f"Czy można połączyć się TCP z 127.0.0.1:{self.ctx.ssh_port}?",
                status=TestStatus.FAIL,
                answer=f"Nie, błąd: {e}"
            )

    def test_qga_ping(self) -> TestResult:
        """Test QEMU Guest Agent connectivity."""
        if not self.ctx.vm_running:
            return TestResult(
                name="QEMU Guest Agent",
                question="Czy QEMU Guest Agent odpowiada?",
                status=TestStatus.SKIP,
                answer="Pominięto - VM nie jest uruchomiona"
            )
        
        rc, out, _ = self.virsh("qemu-agent-command", self.ctx.vm_name, '{"execute":"guest-ping"}')
        
        if rc == 0:
            self.ctx.qga_responding = True
            return TestResult(
                name="QEMU Guest Agent",
                question="Czy QEMU Guest Agent odpowiada?",
                status=TestStatus.PASS,
                answer="Tak, QGA odpowiada na ping",
                details={"response": out[:100] if out else "empty"}
            )
        else:
            return TestResult(
                name="QEMU Guest Agent",
                question="Czy QEMU Guest Agent odpowiada?",
                status=TestStatus.WAIT,
                answer="Nie, QGA nie odpowiada",
                diagnosis="QGA może nie być jeszcze zainstalowany/uruchomiony (cloud-init może wciąż działać)",
                suggestion="Poczekaj 2-3 minuty na zakończenie cloud-init, lub sprawdź konsolę VM"
            )

    def test_ssh_connection(self) -> TestResult:
        """Test SSH connection to VM."""
        if not self.ctx.ssh_key_path or not self.ctx.ssh_port:
            return TestResult(
                name="SSH Connection",
                question="Czy można połączyć się przez SSH?",
                status=TestStatus.SKIP,
                answer="Pominięto - brak klucza SSH lub portu"
            )
        
        result = self.ssh_exec("echo 'SSH_OK'", timeout=10)
        
        if result and "SSH_OK" in result:
            self.ctx.ssh_works = True
            return TestResult(
                name="SSH Connection",
                question="Czy można połączyć się przez SSH?",
                status=TestStatus.PASS,
                answer="Tak, SSH działa poprawnie",
                details={"port": self.ctx.ssh_port, "key": str(self.ctx.ssh_key_path)}
            )
        else:
            # Try to get more details about the failure
            try:
                proc = subprocess.run([
                    "ssh", "-v", "-i", str(self.ctx.ssh_key_path),
                    "-p", str(self.ctx.ssh_port),
                    "-o", "StrictHostKeyChecking=no",
                    "-o", "ConnectTimeout=5",
                    "-o", "BatchMode=yes",
                    "ubuntu@127.0.0.1", "echo test"
                ], capture_output=True, text=True, timeout=10)
                debug_info = proc.stderr[-500:] if proc.stderr else "No debug info"
            except:
                debug_info = "Could not get debug info"
            
            # Determine specific failure reason
            if "Connection reset" in debug_info or "kex_exchange" in debug_info:
                diagnosis = "SSH daemon działa, ale VM nie ma adresu IPv4"
                suggestion = "VM potrzebuje konfiguracji sieci - sprawdź konsolę: virsh --connect qemu:///session console " + self.ctx.vm_name
            elif "Connection refused" in debug_info:
                diagnosis = "Port nasłuchuje, ale SSH daemon nie jest gotowy"
                suggestion = "Poczekaj na uruchomienie SSH daemon w VM"
            elif "Connection timed out" in debug_info:
                diagnosis = "Brak odpowiedzi z VM - passt może nie działać"
                suggestion = "Sprawdź proces passt i konfigurację sieci"
            else:
                diagnosis = "Nieznany błąd SSH"
                suggestion = "Sprawdź konsolę VM dla szczegółów"
            
            return TestResult(
                name="SSH Connection",
                question="Czy można połączyć się przez SSH?",
                status=TestStatus.FAIL,
                answer="Nie, SSH nie działa",
                details={"debug_snippet": debug_info[-200:]},
                diagnosis=diagnosis,
                suggestion=suggestion
            )

    def test_vm_network_via_qga(self) -> TestResult:
        """Get VM network configuration via QGA."""
        if not self.ctx.qga_responding:
            return TestResult(
                name="VM Network (QGA)",
                question="Jaka jest konfiguracja sieci w VM (via QGA)?",
                status=TestStatus.SKIP,
                answer="Pominięto - QGA nie odpowiada"
            )
        
        rc, out, _ = self.virsh("qemu-agent-command", self.ctx.vm_name, 
                                '{"execute":"guest-network-get-interfaces"}')
        
        if rc == 0:
            try:
                data = json.loads(out)
                interfaces = data.get("return", [])
                
                ipv4_found = False
                details = {}
                for iface in interfaces:
                    name = iface.get("name", "unknown")
                    addrs = [a.get("ip-address", "") for a in iface.get("ip-addresses", [])]
                    details[name] = addrs
                    for addr in addrs:
                        if addr and not addr.startswith("127.") and not addr.startswith("fe80") and ":" not in addr:
                            ipv4_found = True
                
                self.ctx.has_ipv4 = ipv4_found
                
                if ipv4_found:
                    return TestResult(
                        name="VM Network (QGA)",
                        question="Czy VM ma adres IPv4?",
                        status=TestStatus.PASS,
                        answer="Tak, VM ma skonfigurowany IPv4",
                        details=details
                    )
                else:
                    return TestResult(
                        name="VM Network (QGA)",
                        question="Czy VM ma adres IPv4?",
                        status=TestStatus.FAIL,
                        answer="Nie, VM nie ma adresu IPv4",
                        details=details,
                        diagnosis="VM nie otrzymała adresu IP od DHCP (passt) ani nie ma statycznej konfiguracji",
                        suggestion="Sprawdź cloud-init network-config lub skonfiguruj ręcznie: ip addr add 10.0.2.15/24 dev enp*s0"
                    )
            except Exception as e:
                return TestResult(
                    name="VM Network (QGA)",
                    question="Jaka jest konfiguracja sieci w VM?",
                    status=TestStatus.WARN,
                    answer=f"Nie można sparsować odpowiedzi: {e}",
                    details={"raw": out[:200]}
                )
        else:
            return TestResult(
                name="VM Network (QGA)",
                question="Jaka jest konfiguracja sieci w VM?",
                status=TestStatus.FAIL,
                answer="Nie można pobrać informacji o sieci"
            )

    def test_cloud_init_status(self) -> TestResult:
        """Check cloud-init status."""
        if not self.ctx.qga_responding and not self.ctx.ssh_works:
            # Try to read from serial log
            serial_log = self.ctx.vm_dir / "serial.log"
            if serial_log.exists():
                try:
                    content = serial_log.read_text()[-5000:]
                    if "CloneBox VM is ready" in content:
                        self.ctx.cloud_init_done = True
                        return TestResult(
                            name="Cloud-Init Status",
                            question="Czy cloud-init zakończył działanie?",
                            status=TestStatus.PASS,
                            answer="Tak (wykryto w serial.log)",
                            details={"source": "serial.log"}
                        )
                    elif "cloud-init" in content.lower():
                        # Find last cloud-init message
                        lines = [l for l in content.split('\n') if 'cloud-init' in l.lower()]
                        last_line = lines[-1] if lines else "N/A"
                        return TestResult(
                            name="Cloud-Init Status",
                            question="Czy cloud-init zakończył działanie?",
                            status=TestStatus.WAIT,
                            answer="Cloud-init wciąż działa",
                            details={"last_message": last_line[-100:]},
                            diagnosis="Cloud-init nie zakończył jeszcze pracy",
                            suggestion="Poczekaj na zakończenie (zwykle 2-5 minut)"
                        )
                except:
                    pass
            
            return TestResult(
                name="Cloud-Init Status",
                question="Czy cloud-init zakończył działanie?",
                status=TestStatus.SKIP,
                answer="Pominięto - brak dostępu do VM"
            )
        
        # Try via QGA or SSH
        result = self.exec_in_vm("cloud-init status 2>/dev/null || echo 'unknown'")
        
        if result:
            if "done" in result.lower():
                self.ctx.cloud_init_done = True
                return TestResult(
                    name="Cloud-Init Status",
                    question="Czy cloud-init zakończył działanie?",
                    status=TestStatus.PASS,
                    answer="Tak, cloud-init status: done",
                    details={"status": result}
                )
            elif "running" in result.lower():
                return TestResult(
                    name="Cloud-Init Status",
                    question="Czy cloud-init zakończył działanie?",
                    status=TestStatus.WAIT,
                    answer="Nie, cloud-init wciąż działa",
                    diagnosis="Cloud-init wykonuje konfigurację VM",
                    suggestion="Poczekaj na zakończenie"
                )
            elif "error" in result.lower():
                return TestResult(
                    name="Cloud-Init Status",
                    question="Czy cloud-init zakończył działanie?",
                    status=TestStatus.FAIL,
                    answer=f"Cloud-init zakończył z błędem: {result}",
                    diagnosis="Cloud-init napotkał błędy podczas konfiguracji",
                    suggestion="Sprawdź /var/log/cloud-init-output.log"
                )
        
        return TestResult(
            name="Cloud-Init Status",
            question="Czy cloud-init zakończył działanie?",
            status=TestStatus.WARN,
            answer="Nie można określić statusu cloud-init"
        )

    def test_serial_log_analysis(self) -> TestResult:
        """Analyze serial.log for errors and progress."""
        serial_log = self.ctx.vm_dir / "serial.log"
        
        if not serial_log.exists():
            return TestResult(
                name="Serial Log Analysis",
                question="Co pokazuje serial.log?",
                status=TestStatus.WARN,
                answer="Serial.log nie istnieje lub jest pusty",
                suggestion="Sprawdź konsolę: virsh --connect qemu:///session console " + self.ctx.vm_name
            )
        
        try:
            content = serial_log.read_text()
            size = len(content)
            
            if size == 0:
                return TestResult(
                    name="Serial Log Analysis",
                    question="Co pokazuje serial.log?",
                    status=TestStatus.WARN,
                    answer="Serial.log jest pusty",
                    diagnosis="VM może nie zapisywać do serial.log",
                    suggestion="Sprawdź konfigurację konsoli szeregowej w VM"
                )
            
            # Analyze content
            details = {"size_bytes": size}
            errors = []
            warnings = []
            progress = []
            
            lines = content.split('\n')
            for line in lines[-200:]:  # Last 200 lines
                line_lower = line.lower()
                if 'error' in line_lower or 'fail' in line_lower:
                    errors.append(line[:150])
                if 'warning' in line_lower or 'warn' in line_lower:
                    warnings.append(line[:150])
                if '[clonebox]' in line or 'cloud-init' in line_lower:
                    progress.append(line[:150])
            
            details["errors_count"] = len(errors)
            details["warnings_count"] = len(warnings)
            details["last_progress"] = progress[-5:] if progress else []
            details["last_errors"] = errors[-3:] if errors else []
            
            # Check for specific issues
            if "Temporary failure resolving" in content:
                diagnosis = "VM nie ma dostępu do DNS - problem z konfiguracją sieci"
            elif "Failed to shellify" in content:
                diagnosis = "Błąd w cloud-init - nieprawidłowy format YAML w bootcmd/runcmd"
            elif "Connection reset" in content or "no IPv4" in content.lower():
                diagnosis = "Problem z konfiguracją sieci IPv4"
            elif "CloneBox VM is ready" in content:
                diagnosis = "Cloud-init zakończył pracę pomyślnie"
            else:
                diagnosis = f"Znaleziono {len(errors)} błędów, {len(warnings)} ostrzeżeń"
            
            status = TestStatus.PASS if not errors else TestStatus.WARN
            
            return TestResult(
                name="Serial Log Analysis",
                question="Co pokazuje serial.log?",
                status=status,
                answer=f"Przeanalizowano {size} bajtów logu",
                details=details,
                diagnosis=diagnosis
            )
        except Exception as e:
            return TestResult(
                name="Serial Log Analysis",
                question="Co pokazuje serial.log?",
                status=TestStatus.FAIL,
                answer=f"Nie można odczytać serial.log: {e}"
            )

    def test_cloud_init_config(self) -> TestResult:
        """Check cloud-init configuration files."""
        cloudinit_dir = self.ctx.vm_dir / "cloud-init"
        
        if not cloudinit_dir.exists():
            return TestResult(
                name="Cloud-Init Config",
                question="Czy konfiguracja cloud-init jest poprawna?",
                status=TestStatus.WARN,
                answer="Katalog cloud-init nie istnieje"
            )
        
        details = {}
        issues = []
        
        # Check user-data
        user_data = cloudinit_dir / "user-data"
        if user_data.exists():
            content = user_data.read_text()
            details["user-data_size"] = len(content)
            
            # Check for common issues
            if "bootcmd:" in content:
                # Check for YAML issues
                import re
                if re.search(r'bootcmd:.*:\s*"', content):
                    issues.append("Potencjalny problem z YAML - dwukropek w wartości bootcmd")
            
            if "write_files:" in content:
                details["has_write_files"] = True
            
            if "network:" in content:
                details["has_network_config"] = True
        
        # Check network-config
        net_config = cloudinit_dir / "network-config"
        if net_config.exists():
            content = net_config.read_text()
            details["network-config"] = content[:200]
            
            if "dhcp4: true" in content:
                details["dhcp4_enabled"] = True
            if "10.0.2" in content:
                details["static_passt_ip"] = True
        else:
            details["network-config"] = "BRAK - używane domyślne ustawienia"
        
        if issues:
            return TestResult(
                name="Cloud-Init Config",
                question="Czy konfiguracja cloud-init jest poprawna?",
                status=TestStatus.WARN,
                answer=f"Znaleziono potencjalne problemy: {'; '.join(issues)}",
                details=details
            )
        else:
            return TestResult(
                name="Cloud-Init Config",
                question="Czy konfiguracja cloud-init jest poprawna?",
                status=TestStatus.PASS,
                answer="Konfiguracja cloud-init wygląda poprawnie",
                details=details
            )

    def test_vm_services(self) -> TestResult:
        """Check critical services in VM."""
        if not self.ctx.qga_responding and not self.ctx.ssh_works:
            return TestResult(
                name="VM Services",
                question="Czy krytyczne usługi działają w VM?",
                status=TestStatus.SKIP,
                answer="Pominięto - brak dostępu do VM"
            )
        
        services = {
            "ssh": "systemctl is-active ssh 2>/dev/null || systemctl is-active sshd 2>/dev/null",
            "qemu-guest-agent": "systemctl is-active qemu-guest-agent 2>/dev/null",
            "systemd-networkd": "systemctl is-active systemd-networkd 2>/dev/null"
        }
        
        details = {}
        failed = []
        
        for svc, cmd in services.items():
            result = self.exec_in_vm(cmd)
            status = result.strip() if result else "unknown"
            details[svc] = status
            if status != "active":
                failed.append(svc)
        
        if not failed:
            return TestResult(
                name="VM Services",
                question="Czy krytyczne usługi działają w VM?",
                status=TestStatus.PASS,
                answer="Wszystkie krytyczne usługi działają",
                details=details
            )
        else:
            return TestResult(
                name="VM Services",
                question="Czy krytyczne usługi działają w VM?",
                status=TestStatus.WARN,
                answer=f"Nieaktywne usługi: {', '.join(failed)}",
                details=details,
                diagnosis="Niektóre usługi nie są aktywne",
                suggestion="Sprawdź: systemctl status <usługa>"
            )

    # ============== BROWSER DIAGNOSTIC TESTS ==============

    def test_browser_detection(self) -> TestResult:
        """Detect installed browsers in VM."""
        if not self.ctx.qga_responding and not self.ctx.ssh_works:
            return TestResult(
                name="Browser Detection",
                question="Czy przeglądarki są zainstalowane w VM?",
                status=TestStatus.SKIP,
                answer="Pominięto - brak dostępu do VM"
            )
        
        browsers = {
            "firefox": "command -v firefox >/dev/null 2>&1 && echo yes || echo no",
            "chrome": "(command -v google-chrome >/dev/null 2>&1 || command -v google-chrome-stable >/dev/null 2>&1) && echo yes || echo no",
            "chromium": "command -v chromium >/dev/null 2>&1 && echo yes || echo no",
            "edge": "command -v microsoft-edge >/dev/null 2>&1 && echo yes || echo no",
            "brave": "command -v brave-browser >/dev/null 2>&1 && echo yes || echo no",
        }
        
        details = {}
        detected = []
        
        for browser, cmd in browsers.items():
            result = self.exec_in_vm(cmd)
            is_installed = result == "yes"
            details[browser] = "installed" if is_installed else "not found"
            if is_installed:
                detected.append(browser)
                # Get version
                version_cmd = f"{browser} --version 2>/dev/null || echo 'unknown'"
                if browser == "chrome":
                    version_cmd = "(google-chrome --version || google-chrome-stable --version) 2>/dev/null || echo 'unknown'"
                version = self.exec_in_vm(version_cmd) or "unknown"
                details[f"{browser}_version"] = version[:50]
        
        self.ctx.browsers_detected = {b: {} for b in detected}
        
        if detected:
            return TestResult(
                name="Browser Detection",
                question="Czy przeglądarki są zainstalowane w VM?",
                status=TestStatus.PASS,
                answer=f"Wykryto: {', '.join(detected)}",
                details=details
            )
        else:
            return TestResult(
                name="Browser Detection",
                question="Czy przeglądarki są zainstalowane w VM?",
                status=TestStatus.INFO,
                answer="Nie wykryto żadnych przeglądarek",
                details=details,
                suggestion="Zainstaluj przeglądarkę: snap install firefox / apt install firefox"
            )

    def test_firefox_profile(self) -> TestResult:
        """Check Firefox profile integrity."""
        if not self.ctx.qga_responding and not self.ctx.ssh_works:
            return TestResult(
                name="Firefox Profile",
                question="Czy profil Firefox jest poprawnie skonfigurowany?",
                status=TestStatus.SKIP,
                answer="Pominięto - brak dostępu do VM"
            )
        
        # Check if firefox is installed
        ff_check = self.exec_in_vm("command -v firefox >/dev/null 2>&1 && echo yes || echo no")
        if ff_check != "yes":
            return TestResult(
                name="Firefox Profile",
                question="Czy profil Firefox jest poprawnie skonfigurowany?",
                status=TestStatus.SKIP,
                answer="Firefox nie jest zainstalowany"
            )
        
        # Check profile paths
        profile_paths = [
            "/home/ubuntu/.mozilla/firefox",
            "/home/ubuntu/snap/firefox/common/.mozilla/firefox"
        ]
        
        details = {}
        found_profile = False
        profile_location = None
        
        for path in profile_paths:
            # Check if directory exists and is non-empty
            cmd = f"test -d {path} && [ $(ls -A {path} 2>/dev/null | wc -l) -gt 0 ] && echo yes || echo no"
            result = self.exec_in_vm(cmd)
            details[f"path_{path.replace('/', '_')}"] = "exists" if result == "yes" else "missing/empty"
            
            if result == "yes":
                found_profile = True
                profile_location = path
                # Get profile size
                size_cmd = f"du -sb {path} 2>/dev/null | cut -f1 || echo '0'"
                size = self.exec_in_vm(size_cmd) or "0"
                details[f"{path}_size_bytes"] = size
                
                # Check for profiles.ini
                profiles_ini = f"{path}/profiles.ini"
                ini_exists = self.exec_in_vm(f"test -f {profiles_ini} && echo yes || echo no")
                details["profiles_ini"] = "exists" if ini_exists == "yes" else "missing"
                
                # List profile directories
                profiles_cmd = f"ls -la {path}/ 2>/dev/null | grep '^d' | awk '{{print $9}}' | grep -v '^\\.$\\|^\\.\\.$' || echo ''"
                profiles = self.exec_in_vm(profiles_cmd)
                if profiles:
                    details["profile_dirs"] = profiles.replace('\n', ', ')[:100]
        
        self.ctx.firefox_profile_ok = found_profile
        
        if found_profile:
            return TestResult(
                name="Firefox Profile",
                question="Czy profil Firefox jest poprawnie skonfigurowany?",
                status=TestStatus.PASS,
                answer=f"Tak, profil znaleziony w {profile_location}",
                details=details
            )
        else:
            return TestResult(
                name="Firefox Profile",
                question="Czy profil Firefox jest poprawnie skonfigurowany?",
                status=TestStatus.WARN,
                answer="Nie znaleziono profilu Firefox",
                details=details,
                diagnosis="Profil Firefox nie istnieje lub jest pusty - przeglądarka uruchomi się z domyślnym/czystym profilem",
                suggestion="Zaimportuj profil lub uruchom Firefox ręcznie w VM aby utworzyć nowy profil"
            )

    def test_chrome_profile(self) -> TestResult:
        """Check Chrome/Chromium profile integrity."""
        if not self.ctx.qga_responding and not self.ctx.ssh_works:
            return TestResult(
                name="Chrome Profile",
                question="Czy profil Chrome/Chromium jest poprawnie skonfigurowany?",
                status=TestStatus.SKIP,
                answer="Pominięto - brak dostępu do VM"
            )
        
        # Check if chrome is installed
        chrome_check = self.exec_in_vm("(command -v google-chrome >/dev/null 2>&1 || command -v google-chrome-stable >/dev/null 2>&1) && echo yes || echo no")
        chromium_check = self.exec_in_vm("command -v chromium >/dev/null 2>&1 && echo yes || echo no")
        
        details = {}
        
        if chrome_check != "yes" and chromium_check != "yes":
            return TestResult(
                name="Chrome Profile",
                question="Czy profil Chrome/Chromium jest poprawnie skonfigurowany?",
                status=TestStatus.SKIP,
                answer="Chrome/Chromium nie jest zainstalowany"
            )
        
        # Check Chrome profile
        chrome_paths = [
            "/home/ubuntu/.config/google-chrome",
            "/home/ubuntu/snap/google-chrome/common/.config/google-chrome"
        ]
        
        # Check Chromium profile
        chromium_paths = [
            "/home/ubuntu/.config/chromium",
            "/home/ubuntu/snap/chromium/common/chromium"
        ]
        
        chrome_found = False
        chromium_found = False
        
        for path in chrome_paths:
            cmd = f"test -d {path} && [ $(ls -A {path} 2>/dev/null | wc -l) -gt 0 ] && echo yes || echo no"
            result = self.exec_in_vm(cmd)
            if result == "yes":
                chrome_found = True
                size = self.exec_in_vm(f"du -sb {path} 2>/dev/null | cut -f1 || echo '0'") or "0"
                details["chrome_profile_size"] = size
                details["chrome_profile_path"] = path
                # Check for Default directory
                default_dir = f"{path}/Default"
                default_exists = self.exec_in_vm(f"test -d {default_dir} && echo yes || echo no")
                details["chrome_default_dir"] = "exists" if default_exists == "yes" else "missing"
                break
        
        for path in chromium_paths:
            cmd = f"test -d {path} && [ $(ls -A {path} 2>/dev/null | wc -l) -gt 0 ] && echo yes || echo no"
            result = self.exec_in_vm(cmd)
            if result == "yes":
                chromium_found = True
                size = self.exec_in_vm(f"du -sb {path} 2>/dev/null | cut -f1 || echo '0'") or "0"
                details["chromium_profile_size"] = size
                details["chromium_profile_path"] = path
                break
        
        self.ctx.chrome_profile_ok = chrome_found
        self.ctx.chromium_profile_ok = chromium_found
        
        if chrome_found or chromium_found:
            browsers = []
            if chrome_found:
                browsers.append("Chrome")
            if chromium_found:
                browsers.append("Chromium")
            return TestResult(
                name="Chrome Profile",
                question="Czy profil Chrome/Chromium jest poprawnie skonfigurowany?",
                status=TestStatus.PASS,
                answer=f"Tak, profil znaleziony dla: {', '.join(browsers)}",
                details=details
            )
        else:
            return TestResult(
                name="Chrome Profile",
                question="Czy profil Chrome/Chromium jest poprawnie skonfigurowany?",
                status=TestStatus.WARN,
                answer="Nie znaleziono profilu Chrome/Chromium",
                details=details,
                diagnosis="Profil Chrome/Chromium nie istnieje - przeglądarka uruchomi się z domyślnym profilem",
                suggestion="Uruchom Chrome/Chromium ręcznie w VM aby utworzyć profil"
            )

    def test_firefox_headless(self) -> TestResult:
        """Test Firefox headless launch."""
        if not self.ctx.qga_responding and not self.ctx.ssh_works:
            return TestResult(
                name="Firefox Headless Test",
                question="Czy Firefox uruchamia się w trybie headless?",
                status=TestStatus.SKIP,
                answer="Pominięto - brak dostępu do VM"
            )
        
        # Check if firefox is installed
        ff_check = self.exec_in_vm("command -v firefox >/dev/null 2>&1 && echo yes || echo no")
        if ff_check != "yes":
            return TestResult(
                name="Firefox Headless Test",
                question="Czy Firefox uruchamia się w trybie headless?",
                status=TestStatus.SKIP,
                answer="Firefox nie jest zainstalowany"
            )
        
        # Get UID for ubuntu user
        uid_out = self.exec_in_vm("id -u ubuntu 2>/dev/null || echo '1000'")
        vm_uid = uid_out.strip() if uid_out else "1000"
        runtime_dir = f"/run/user/{vm_uid}"
        
        # Setup runtime directory
        self.exec_in_vm(f"sudo mkdir -p {runtime_dir} && sudo chown {vm_uid}:{vm_uid} {runtime_dir} && sudo chmod 700 {runtime_dir}")
        
        # Test headless launch
        user_env = f"sudo -u ubuntu env HOME=/home/ubuntu USER=ubuntu LOGNAME=ubuntu XDG_RUNTIME_DIR={runtime_dir}"
        cmd = f"{user_env} timeout 25 firefox --headless --version >/dev/null 2>&1 && echo yes || echo no"
        result = self.exec_in_vm(cmd, timeout=35)
        
        details = {
            "runtime_dir": runtime_dir,
            "headless_test": "passed" if result == "yes" else "failed"
        }
        
        if result == "yes":
            return TestResult(
                name="Firefox Headless Test",
                question="Czy Firefox uruchamia się w trybie headless?",
                status=TestStatus.PASS,
                answer="Tak, Firefox uruchamia się poprawnie w trybie headless",
                details=details
            )
        else:
            # Try to get error logs
            error_cmd = f"{user_env} timeout 25 firefox --headless --version 2>&1 | head -20 || echo ''"
            error_output = self.exec_in_vm(error_cmd, timeout=35)
            if error_output:
                details["error_output"] = error_output[:200]
            
            return TestResult(
                name="Firefox Headless Test",
                question="Czy Firefox uruchamia się w trybie headless?",
                status=TestStatus.FAIL,
                answer="Nie, Firefox nie uruchamia się w trybie headless",
                details=details,
                diagnosis="Firefox ma problem z uruchomieniem - może być uszkodzony profil lub brakujące zależności",
                suggestion="Sprawdź logi: journalctl -u firefox || snap logs firefox"
            )

    def test_browser_permissions(self) -> TestResult:
        """Check browser profile permissions."""
        if not self.ctx.qga_responding and not self.ctx.ssh_works:
            return TestResult(
                name="Browser Permissions",
                question="Czy uprawnienia do profili przeglądarek są poprawne?",
                status=TestStatus.SKIP,
                answer="Pominięto - brak dostępu do VM"
            )
        
        details = {}
        issues = []
        
        # Check Firefox permissions
        firefox_paths = [
            "/home/ubuntu/.mozilla",
            "/home/ubuntu/snap/firefox/common/.mozilla"
        ]
        
        for path in firefox_paths:
            exists = self.exec_in_vm(f"test -d {path} && echo yes || echo no")
            if exists == "yes":
                owner = self.exec_in_vm(f"stat -c '%U' {path} 2>/dev/null || echo 'unknown'")
                perms = self.exec_in_vm(f"stat -c '%a' {path} 2>/dev/null || echo 'unknown'")
                details[f"firefox_{path.replace('/', '_')}_owner"] = owner
                details[f"firefox_{path.replace('/', '_')}_perms"] = perms
                
                if owner != "ubuntu":
                    issues.append(f"{path} owned by {owner}, expected ubuntu")
        
        # Check Chrome permissions
        chrome_paths = [
            "/home/ubuntu/.config/google-chrome",
            "/home/ubuntu/.config/chromium"
        ]
        
        for path in chrome_paths:
            exists = self.exec_in_vm(f"test -d {path} && echo yes || echo no")
            if exists == "yes":
                owner = self.exec_in_vm(f"stat -c '%U' {path} 2>/dev/null || echo 'unknown'")
                perms = self.exec_in_vm(f"stat -c '%a' {path} 2>/dev/null || echo 'unknown'")
                details[f"chrome_{path.replace('/', '_')}_owner"] = owner
                details[f"chrome_{path.replace('/', '_')}_perms"] = perms
                
                if owner != "ubuntu":
                    issues.append(f"{path} owned by {owner}, expected ubuntu")
        
        if not issues:
            return TestResult(
                name="Browser Permissions",
                question="Czy uprawnienia do profili przeglądarek są poprawne?",
                status=TestStatus.PASS,
                answer="Tak, wszystkie uprawnienia są poprawne",
                details=details
            )
        else:
            return TestResult(
                name="Browser Permissions",
                question="Czy uprawnienia do profili przeglądarek są poprawne?",
                status=TestStatus.WARN,
                answer=f"Znaleziono problemy z uprawnieniami: {len(issues)}",
                details=details,
                diagnosis=f"Problemy: {'; '.join(issues[:3])}",
                suggestion="Napraw uprawnienia: sudo chown -R ubuntu:ubuntu /home/ubuntu/.mozilla /home/ubuntu/.config"
            )

    def test_browser_lock_files(self) -> TestResult:
        """Check for stale browser lock files from copied profiles."""
        if not self.ctx.qga_responding and not self.ctx.ssh_works:
            return TestResult(
                name="Browser Lock Files",
                question="Czy są pozostałe pliki blokady w profilach przeglądarek?",
                status=TestStatus.SKIP,
                answer="Pominięto - brak dostępu do VM"
            )

        lock_cmd = (
            "find /home/ubuntu/.mozilla /home/ubuntu/snap/firefox "
            "/home/ubuntu/.config/google-chrome /home/ubuntu/.config/chromium "
            "/home/ubuntu/snap/chromium "
            "-maxdepth 4 -type f "
            "\\( -name 'parent.lock' -o -name '.parentlock' -o -name 'lock' "
            "-o -name 'lockfile' -o -name 'SingletonLock' \\) "
            "2>/dev/null | head -10 || echo ''"
        )
        locks = self.exec_in_vm(lock_cmd)
        lock_list = [l for l in (locks or "").strip().splitlines() if l.strip()]

        details = {"lock_files": lock_list}

        if lock_list:
            return TestResult(
                name="Browser Lock Files",
                question="Czy są pozostałe pliki blokady w profilach przeglądarek?",
                status=TestStatus.WARN,
                answer=f"Znaleziono {len(lock_list)} plik(ów) blokady",
                details=details,
                diagnosis="Pliki blokady mogą uniemożliwiać uruchomienie przeglądarki (skopiowane z działającej instancji)",
                suggestion="Usuń pliki blokady: rm -f " + " ".join(lock_list[:3])
            )
        else:
            return TestResult(
                name="Browser Lock Files",
                question="Czy są pozostałe pliki blokady w profilach przeglądarek?",
                status=TestStatus.PASS,
                answer="Brak plików blokady",
                details=details
            )

    def test_browser_crash_reports(self) -> TestResult:
        """Check for recent browser crash dumps."""
        if not self.ctx.qga_responding and not self.ctx.ssh_works:
            return TestResult(
                name="Browser Crash Reports",
                question="Czy są ostatnie zrzuty awarii przeglądarek?",
                status=TestStatus.SKIP,
                answer="Pominięto - brak dostępu do VM"
            )

        crash_cmd = (
            "find /home/ubuntu/.mozilla /home/ubuntu/snap/firefox "
            "/home/ubuntu/.config/google-chrome /home/ubuntu/.config/chromium "
            "/home/ubuntu/snap/chromium "
            "-maxdepth 4 -type f "
            "\\( -name '*.dmp' -o -name '*.extra' \\) "
            "-newer /proc/1/status 2>/dev/null | wc -l || echo '0'"
        )
        count_str = self.exec_in_vm(crash_cmd)
        try:
            count = int((count_str or "0").strip())
        except ValueError:
            count = 0

        details = {"recent_crash_dumps": count}

        if count > 0:
            return TestResult(
                name="Browser Crash Reports",
                question="Czy są ostatnie zrzuty awarii przeglądarek?",
                status=TestStatus.WARN,
                answer=f"Znaleziono {count} zrzut(ów) awarii od ostatniego restartu VM",
                details=details,
                diagnosis="Przeglądarki się crashują - sprawdź profil i zależności",
                suggestion="Sprawdź katalogi Crash Reports w profilach przeglądarek"
            )
        else:
            return TestResult(
                name="Browser Crash Reports",
                question="Czy są ostatnie zrzuty awarii przeglądarek?",
                status=TestStatus.PASS,
                answer="Brak ostatnich zrzutów awarii",
                details=details
            )

    def test_snap_browser_interfaces(self) -> TestResult:
        """Check snap browser interface connections."""
        if not self.ctx.qga_responding and not self.ctx.ssh_works:
            return TestResult(
                name="Snap Browser Interfaces",
                question="Czy interfejsy snap przeglądarek są poprawnie podłączone?",
                status=TestStatus.SKIP,
                answer="Pominięto - brak dostępu do VM"
            )

        required_ifaces = ["desktop", "desktop-legacy", "x11", "wayland", "home", "network"]
        details = {}
        issues = []

        for snap_name in ["firefox", "chromium"]:
            installed = self.exec_in_vm(f"snap list {snap_name} >/dev/null 2>&1 && echo yes || echo no")
            if installed != "yes":
                continue

            conns = self.exec_in_vm(
                f"snap connections {snap_name} 2>/dev/null | awk 'NR>1{{print $1, $3}}'"
            )
            if conns is None:
                details[snap_name] = "cannot read connections"
                continue

            connected = set()
            for line in (conns or "").splitlines():
                parts = line.split()
                if len(parts) >= 2 and parts[1] != "-":
                    connected.add(parts[0])

            missing = [i for i in required_ifaces if i not in connected]
            details[f"{snap_name}_connected"] = sorted(connected)
            details[f"{snap_name}_missing"] = missing

            if missing:
                issues.append(f"{snap_name}: brak {', '.join(missing)}")

        if not details:
            return TestResult(
                name="Snap Browser Interfaces",
                question="Czy interfejsy snap przeglądarek są poprawnie podłączone?",
                status=TestStatus.SKIP,
                answer="Brak snap przeglądarek"
            )

        if issues:
            return TestResult(
                name="Snap Browser Interfaces",
                question="Czy interfejsy snap przeglądarek są poprawnie podłączone?",
                status=TestStatus.WARN,
                answer=f"Brakujące interfejsy: {'; '.join(issues)}",
                details=details,
                diagnosis="Brakujące interfejsy snap mogą uniemożliwiać uruchomienie przeglądarki GUI",
                suggestion="Podłącz interfejsy: snap connect <browser>:<interface>"
            )
        else:
            return TestResult(
                name="Snap Browser Interfaces",
                question="Czy interfejsy snap przeglądarek są poprawnie podłączone?",
                status=TestStatus.PASS,
                answer="Wszystkie wymagane interfejsy podłączone",
                details=details
            )

    def test_browser_logs(self) -> TestResult:
        """Check browser error logs."""
        if not self.ctx.qga_responding and not self.ctx.ssh_works:
            return TestResult(
                name="Browser Logs",
                question="Czy są błędy w logach przeglądarek?",
                status=TestStatus.SKIP,
                answer="Pominięto - brak dostępu do VM"
            )
        
        details = {}
        errors_found = []
        
        # Check Firefox snap logs
        snap_ff_logs = self.exec_in_vm("snap logs firefox -n 50 2>/dev/null || echo ''")
        if snap_ff_logs:
            details["firefox_snap_logs"] = snap_ff_logs[:300]
            if any(err in snap_ff_logs.lower() for err in ["error", "fail", "denied"]):
                errors_found.append("Firefox snap logs contain errors")
        
        # Check journal for firefox errors
        journal_ff = self.exec_in_vm("journalctl -n 100 --no-pager 2>/dev/null | grep -i firefox | tail -20 || echo ''")
        if journal_ff:
            details["firefox_journal"] = journal_ff[:300]
            if any(err in journal_ff.lower() for err in ["error", "fail", "denied", "crash"]):
                errors_found.append("Journal contains Firefox errors")
        
        # Check Chrome snap logs
        snap_chrome_logs = self.exec_in_vm("snap logs google-chrome -n 50 2>/dev/null || echo ''")
        if snap_chrome_logs:
            details["chrome_snap_logs"] = snap_chrome_logs[:300]
            if any(err in snap_chrome_logs.lower() for err in ["error", "fail", "denied"]):
                errors_found.append("Chrome snap logs contain errors")
        
        # Check Chromium snap logs
        snap_chromium_logs = self.exec_in_vm("snap logs chromium -n 50 2>/dev/null || echo ''")
        if snap_chromium_logs:
            details["chromium_snap_logs"] = snap_chromium_logs[:300]
        
        if not errors_found:
            return TestResult(
                name="Browser Logs",
                question="Czy są błędy w logach przeglądarek?",
                status=TestStatus.PASS,
                answer="Nie znaleziono błędów w logach",
                details=details
            )
        else:
            return TestResult(
                name="Browser Logs",
                question="Czy są błędy w logach przeglądarek?",
                status=TestStatus.WARN,
                answer=f"Znaleziono błędy: {'; '.join(errors_found[:2])}",
                details=details,
                diagnosis="Przeglądarki raportują błędy w logach - mogą wskazywać na problemy z profilem, uprawnieniami lub konfiguracją",
                suggestion="Przejrzyj szczegóły w logach powyżej lub sprawdź: snap logs <browser>"
            )

    def run_all_tests(self) -> List[TestResult]:
        """Run all diagnostic tests in order."""
        # Test sequence with dependencies
        tests = [
            self.test_vm_exists,
            self.test_vm_running,
            self.test_vm_directory,
            self.test_passt_process,
            self.test_port_listening,
            self.test_tcp_connection,
            self.test_qga_ping,
            self.test_ssh_connection,
            self.test_vm_network_via_qga,
            self.test_cloud_init_status,
            self.test_serial_log_analysis,
            self.test_cloud_init_config,
            self.test_vm_services,
            # Browser diagnostic tests
            self.test_browser_detection,
            self.test_firefox_profile,
            self.test_chrome_profile,
            self.test_browser_permissions,
            self.test_browser_lock_files,
            self.test_browser_crash_reports,
            self.test_snap_browser_interfaces,
            self.test_firefox_headless,
            self.test_browser_logs,
        ]
        
        for test_func in tests:
            result = test_func()
            self.add_result(result)
            
            # Stop if blocking test fails
            if result.blocking and result.status in [TestStatus.FAIL, TestStatus.SKIP]:
                break
        
        return self.ctx.results

    def generate_report(self) -> str:
        """Generate Q&A format diagnostic report."""
        report = []
        report.append("=" * 70)
        report.append("  CLONEBOX VM DIAGNOSTIC REPORT")
        report.append(f"  VM: {self.ctx.vm_name}")
        report.append(f"  Time: {datetime.now().isoformat()}")
        report.append("=" * 70)
        report.append("")
        
        # Summary
        passed = sum(1 for r in self.ctx.results if r.status == TestStatus.PASS)
        failed = sum(1 for r in self.ctx.results if r.status == TestStatus.FAIL)
        waiting = sum(1 for r in self.ctx.results if r.status == TestStatus.WAIT)
        skipped = sum(1 for r in self.ctx.results if r.status == TestStatus.SKIP)
        
        report.append(f"📊 SUMMARY: {passed} passed, {failed} failed, {waiting} waiting, {skipped} skipped")
        report.append("")
        
        # Q&A Section
        report.append("-" * 70)
        report.append("  DIAGNOSTIC Q&A")
        report.append("-" * 70)
        
        for i, result in enumerate(self.ctx.results, 1):
            report.append("")
            report.append(f"Q{i}: {result.question}")
            report.append(f"A{i}: {result.status.value} {result.answer}")
            
            if result.diagnosis:
                report.append(f"    📋 Diagnoza: {result.diagnosis}")
            if result.suggestion:
                report.append(f"    💡 Sugestia: {result.suggestion}")
            if result.details and self.verbose:
                report.append(f"    📎 Szczegóły: {json.dumps(result.details, indent=6, ensure_ascii=False)[:500]}")
        
        # Root cause analysis
        report.append("")
        report.append("-" * 70)
        report.append("  ROOT CAUSE ANALYSIS")
        report.append("-" * 70)
        
        root_causes = self._analyze_root_cause()
        for cause in root_causes:
            report.append(f"\n🔍 {cause}")
        
        # Next steps
        report.append("")
        report.append("-" * 70)
        report.append("  RECOMMENDED NEXT STEPS")
        report.append("-" * 70)
        
        steps = self._get_next_steps()
        for i, step in enumerate(steps, 1):
            report.append(f"{i}. {step}")
        
        return "\n".join(report)

    def _analyze_root_cause(self) -> List[str]:
        """Analyze results to identify root cause."""
        causes = []
        
        if not self.ctx.vm_exists:
            causes.append("VM nie istnieje - należy ją utworzyć")
            return causes
        
        if not self.ctx.vm_running:
            causes.append("VM nie jest uruchomiona")
            return causes
        
        if not self.ctx.passt_active and not self.ctx.ssh_works:
            causes.append("Port-forwarding SSH nie działa (ani passt ani QEMU hostfwd)")
        
        if not self.ctx.qga_responding and not self.ctx.ssh_works:
            causes.append("Brak dostępu do VM (ani QGA ani SSH nie działają)")
            causes.append("Możliwa przyczyna: VM wciąż bootuje lub cloud-init nie zakończył pracy")
        
        if self.ctx.qga_responding and not self.ctx.has_ipv4:
            causes.append("VM nie ma adresu IPv4 - DHCP nie działa lub brak statycznej konfiguracji")
            causes.append("To jest główna przyczyna problemów z SSH")
        
        if self.ctx.qga_responding and self.ctx.has_ipv4 and not self.ctx.ssh_works:
            causes.append("VM ma IPv4 ale SSH nie działa - sprawdź usługę SSH w VM")
        
        # Browser-specific root causes
        if "firefox" in self.ctx.browsers_detected and not self.ctx.firefox_profile_ok:
            causes.append("Firefox jest zainstalowany ale brak profilu - przeglądarka uruchomi się z czystym profilem")
        
        if ("chrome" in self.ctx.browsers_detected or "chromium" in self.ctx.browsers_detected) and \
           not self.ctx.chrome_profile_ok and not self.ctx.chromium_profile_ok:
            causes.append("Chrome/Chromium jest zainstalowany ale brak profilu - przeglądarka uruchomi się z czystym profilem")
        
        if not causes:
            causes.append("Nie zidentyfikowano krytycznych problemów")
        
        return causes

    def _get_next_steps(self) -> List[str]:
        """Get recommended next steps based on results."""
        steps = []
        
        if not self.ctx.vm_exists:
            steps.append("Utwórz VM: clonebox clone . --user --run")
            return steps
        
        if not self.ctx.vm_running:
            steps.append(f"Uruchom VM: virsh --connect qemu:///session start {self.ctx.vm_name}")
            return steps
        
        if not self.ctx.qga_responding and not self.ctx.ssh_works:
            steps.append("Poczekaj 2-3 minuty na zakończenie cloud-init")
            steps.append(f"Sprawdź konsolę VM: virsh --connect qemu:///session console {self.ctx.vm_name}")
            steps.append(f"Monitoruj logi: tail -f {self.ctx.vm_dir}/serial.log")
        
        if self.ctx.qga_responding and not self.ctx.has_ipv4:
            steps.append("Skonfiguruj sieć ręcznie w konsoli VM:")
            steps.append("  sudo ip addr add 10.0.2.15/24 dev enp17s0")
            steps.append("  sudo ip route add default via 10.0.2.2")
            steps.append("  echo 'nameserver 10.0.2.3' | sudo tee /etc/resolv.conf")
        
        if self.ctx.ssh_works:
            steps.append("SSH działa - możesz połączyć się z VM:")
            steps.append(f"  ssh -i {self.ctx.ssh_key_path} -p {self.ctx.ssh_port} ubuntu@127.0.0.1")
        
        # Browser-specific next steps
        if "firefox" in self.ctx.browsers_detected and not self.ctx.firefox_profile_ok:
            steps.append("\n🔧 Firefox bez profilu - aby zaimportować profil:")
            steps.append("  1. Uruchom Firefox w VM ręcznie przez virt-viewer")
            steps.append("  2. Lub skopiuj profil przez SSH:")
            steps.append("     scp -r -i ~/.local/share/libvirt/images/<vm>/ssh_key -P <port> ~/.mozilla/firefox/* ubuntu@127.0.0.1:/home/ubuntu/.mozilla/firefox/")
        
        if ("chrome" in self.ctx.browsers_detected or "chromium" in self.ctx.browsers_detected) and \
           not self.ctx.chrome_profile_ok and not self.ctx.chromium_profile_ok:
            steps.append("\n🔧 Chrome/Chromium bez profilu - aby zaimportować profil:")
            steps.append("  1. Uruchom Chrome w VM ręcznie przez virt-viewer")
            steps.append("  2. Lub skopiuj profil przez SSH:")
            steps.append("     scp -r -i ~/.local/share/libvirt/images/<vm>/ssh_key -P <port> ~/.config/google-chrome/* ubuntu@127.0.0.1:/home/ubuntu/.config/google-chrome/")
        
        if not steps:
            steps.append("Uruchom ponownie diagnostykę za kilka minut")
        
        return steps

    def to_json(self) -> str:
        """Export results as JSON."""
        return json.dumps({
            "vm_name": self.ctx.vm_name,
            "timestamp": datetime.now().isoformat(),
            "summary": {
                "vm_exists": self.ctx.vm_exists,
                "vm_running": self.ctx.vm_running,
                "ssh_port": self.ctx.ssh_port,
                "passt_active": self.ctx.passt_active,
                "qga_responding": self.ctx.qga_responding,
                "ssh_works": self.ctx.ssh_works,
                "has_ipv4": self.ctx.has_ipv4,
                "cloud_init_done": self.ctx.cloud_init_done,
                "browsers": {
                    "detected": list(self.ctx.browsers_detected.keys()),
                    "firefox_profile_ok": self.ctx.firefox_profile_ok,
                    "chrome_profile_ok": self.ctx.chrome_profile_ok,
                    "chromium_profile_ok": self.ctx.chromium_profile_ok,
                }
            },
            "results": [
                {
                    "name": r.name,
                    "question": r.question,
                    "status": r.status.name,
                    "answer": r.answer,
                    "diagnosis": r.diagnosis,
                    "suggestion": r.suggestion,
                    "details": r.details,
                }
                for r in self.ctx.results
            ],
            "root_causes": self._analyze_root_cause(),
            "next_steps": self._get_next_steps(),
        }, indent=2, ensure_ascii=False)


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="CloneBox VM Diagnostic Suite")
    parser.add_argument("vm_name", nargs="?", default="clone-clonebox", help="VM name to diagnose")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--conn-uri", default="qemu:///session", help="Libvirt connection URI")
    
    args = parser.parse_args()
    
    diag = VMDiagnostic(args.vm_name, args.conn_uri, args.verbose)
    diag.run_all_tests()
    
    if args.json:
        print(diag.to_json())
    else:
        print(diag.generate_report())


if __name__ == "__main__":
    main()
