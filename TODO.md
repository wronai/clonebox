# CloneBox TODO List

## 🚀 High Priority

### Core Features
- [x] Add `clonebox exec` command for executing commands in VM via QEMU Guest Agent ✅ v1.1.2
- [x] Implement VM snapshot functionality (save/restore state) ✅ v2.0.0 (`snapshots/`)
- [x] Add support for multiple VMs in single project (docker-compose style) ✅ v2.0.0 (`orchestrator.py`)
- [x] Create web-based dashboard for VM management ✅ v1.1.0
- [ ] Add automatic port forwarding configuration
- [x] P2P secure transfer with AES-256 encryption ✅ v1.1.2

### Monitoring & Diagnostics
- [x] Add real-time resource usage monitoring (CPU, RAM, disk) ✅ v1.1.2 (`clonebox monitor`)
- [x] Implement real-time installation progress monitor (10 phases) ✅ v2.0.0
- [ ] Implement alert system for failed services/apps
- [x] Create health check API endpoint ✅ v2.0.0 (`health/`)
- [ ] Add performance benchmarks for VM operations
- [ ] Implement log rotation for monitor logs

## 🔧 Medium Priority

### Usability
- [x] Add detailed progress logging for clone/setup operations ✅ v2.0.0
- [x] Implement configuration profiles (dev, test, production) ✅ v1.1.0 (`ml-dev`, `web-stack`)
- [x] Add auto-completion for bash/zsh ✅ v1.1.2 (see `scripts/clonebox-completion.*`)
- [ ] Create GUI configuration wizard
- [x] Add dark mode for terminal output ✅ v1.1.0 (rich console)

### Integration
- [x] Docker/Podman integration (run containers inside VM) ✅ v1.1.0 (container runtime)
- [ ] Kubernetes cluster mode (multiple VMs as nodes)
- [ ] CI/CD pipeline templates
- [ ] VS Code extension for CloneBox management
- [ ] Integration with Git hooks (auto-clone on branch switch)

### Platform Support
- [ ] Windows host support (WSL2 integration)
- [ ] macOS host support (UTM integration)
- [ ] ARM64 image support (Apple Silicon, ARM servers)
- [ ] Cloud provider support (AWS, GCP, Azure VMs)
- [ ] Proxmox VE integration

## 📋 Low Priority

### Advanced Features
- [ ] VM templates marketplace
- [x] Plugin system for custom providers ✅ v2.0.0 (`plugins/`)
- [ ] Multi-user support with permissions
- [x] Audit logging for all operations ✅ v2.0.0 (`audit.py`)
- [ ] Backup/restore automation

### Performance
- [x] Disk space optimization (apt clean, journal limit, snap retain) ✅ v2.0.0
- [ ] Differential disk images to save space
- [ ] RAM disk for temporary files
- [ ] Optimized network configuration
- [ ] GPU passthrough support
- [ ] Live migration between hosts

## 🐛 Known Issues

### Bugs to Fix
- [ ] Chromium headless test fails on some systems
- [ ] Display auto-detection doesn't work for all setups
- [x] Mount points sometimes empty after reboot (fixed with persistence) ✅ v2.0.0
- [x] Snap interfaces need manual reconnection sometimes (auto-fix added) ✅ v2.0.0
- [x] Keyring password mismatch on first login (repair utility added) ✅ v2.0.0

### Improvements
- [x] Better error messages for failed operations (added real-time error detection) ✅ v2.0.0
- [ ] Retry mechanism for network operations
- [x] Graceful handling of missing dependencies (host check added) ✅ v2.0.0
- [ ] Validation of configuration before VM creation
- [x] Automatic cleanup of temporary files (import mounts cleanup) ✅ v2.0.0

## 📚 Documentation

### User Documentation
- [ ] Video tutorials for common workflows
- [ ] Troubleshooting guide with common issues
- [x] Quick reference guide updated for v2.0 features ✅ v2.0.0
- [ ] Best practices guide
- [ ] FAQ section
- [ ] Migration guide from other solutions

### Developer Documentation
- [ ] API documentation
- [ ] Architecture diagrams
- [ ] Contributing guidelines
- [ ] Plugin development guide
- [ ] Performance tuning guide

## 🔍 Research & Investigation

### Technical Debt
- [x] Refactor cloud-init script generation (10-phase system) ✅ v2.0.0
- [ ] Improve test coverage (target: 80%)
- [ ] Add type hints for all functions
- [ ] Optimize memory usage
- [ ] Reduce code duplication

### Future Technologies
- [ ] Evaluate KVM/QEMU alternatives (Firecracker, gVisor)
- [ ] Research WebAssembly runtime support
- [ ] Investigate eBPF for monitoring
- [ ] Explore container-native virtualization
- [ ] Study edge computing use cases

## 🏷️ Labels

- `bug` - Bug fixes
- `enhancement` - New features
- `documentation` - Docs improvements
- `performance` - Speed/resource optimizations
- `security` - Security improvements
- `testing` - Test coverage/quality
- `ux` - User experience improvements
- `integration` - Third-party integrations

---

## 📊 Progress Tracking

### Current Version: 2.0.0

### Completed in v1.1.x:
- [x] `clonebox exec` command ✅
- [x] Web dashboard MVP (FastAPI + HTMX + Tailwind) ✅
- [x] Container runtime (Podman/Docker) ✅
- [x] Configuration profiles ✅
- [x] P2P secure transfer (AES-256) ✅
- [x] Real-time resource monitoring ✅
- [x] Bash/Zsh auto-completion ✅

### Completed in v2.0.0:
- [x] VM snapshots (save/restore state) - `snapshots/` ✅
- [x] Health check system - `health/` ✅
- [x] Multi-VM orchestration - `orchestrator.py` ✅
- [x] Plugin system - `plugins/` ✅
- [x] Audit logging - `audit.py` ✅
- [x] Secrets management - `secrets.py` ✅
- [x] Rollback on errors - `rollback.py` ✅
- [x] Remote VM management - `remote.py` ✅
- [x] Resource limits - `resources.py` ✅
- [x] Dependency injection - `di.py` ✅
- [x] Structured logging - `logging.py` ✅
- [x] Strong typing - `models.py` ✅
- [x] 10-phase detailed installation logging ✅
- [x] Real-time disk usage monitoring and warnings ✅
- [x] VM space optimizations (journal limit, snap retain, cleanup) ✅
- [x] Host-side dependency verification ✅

### Next Release (2.1.0) Goals:
- [ ] Progress bars for long operations (internal tasks)
- [ ] Alert system for failed services
- [ ] Improved error handling (automatic repair suggestions)
- [ ] Performance benchmarks
- [ ] Automatic port forwarding setup

### Roadmap
- **v2.1.0**: Progress bars, alerts, improved errors
- **v2.2.0**: Kubernetes cluster mode
- **v3.0.0**: Cloud provider support (AWS, GCP, Azure), Windows WSL2

---

## 🤝 Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on how to contribute.

### Quick Start for Contributors
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

### Good First Issues
- Add unit tests for uncovered code
- Improve error messages
- Add more examples to documentation
- Fix typos in docs
- Add more health checks
