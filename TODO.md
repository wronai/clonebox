# CloneBox TODO List

## 🚀 High Priority

### Core Features
- [x] Add `clonebox exec` command for executing commands in VM via QEMU Guest Agent ✅ v1.1.2
- [ ] Implement VM snapshot functionality (save/restore state)
- [ ] Add support for multiple VMs in single project (docker-compose style)
- [x] Create web-based dashboard for VM management ✅ v1.1.0
- [ ] Add automatic port forwarding configuration
- [x] P2P secure transfer with AES-256 encryption ✅ v1.1.2

### Monitoring & Diagnostics
- [x] Add real-time resource usage monitoring (CPU, RAM, disk) ✅ v1.1.2 (`clonebox monitor`)
- [ ] Implement alert system for failed services/apps
- [ ] Create health check API endpoint
- [ ] Add performance benchmarks for VM operations
- [ ] Implement log rotation for monitor logs

## 🔧 Medium Priority

### Usability
- [ ] Add progress bars for long operations (clone, export, import)
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
- [ ] Plugin system for custom providers
- [ ] Multi-user support with permissions
- [ ] Audit logging for all operations
- [ ] Backup/restore automation

### Performance
- [ ] Differential disk images to save space
- [ ] RAM disk for temporary files
- [ ] Optimized network configuration
- [ ] GPU passthrough support
- [ ] Live migration between hosts

## 🐛 Known Issues

### Bugs to Fix
- [ ] Chromium headless test fails on some systems
- [ ] Display auto-detection doesn't work for all setups
- [ ] Mount points sometimes empty after reboot
- [ ] Snap interfaces need manual reconnection sometimes
- [ ] Keyring password mismatch on first login

### Improvements
- [ ] Better error messages for failed operations
- [ ] Retry mechanism for network operations
- [ ] Graceful handling of missing dependencies
- [ ] Validation of configuration before VM creation
- [ ] Automatic cleanup of temporary files

## 📚 Documentation

### User Documentation
- [ ] Video tutorials for common workflows
- [ ] Troubleshooting guide with common issues
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
- [ ] Refactor cloud-init script generation
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

### Current Version: 1.1.2

### Completed in v1.1.x:
- [x] `clonebox exec` command ✅
- [x] Web dashboard MVP (FastAPI + HTMX + Tailwind) ✅
- [x] Container runtime (Podman/Docker) ✅
- [x] Configuration profiles ✅
- [x] P2P secure transfer (AES-256) ✅
- [x] Real-time resource monitoring ✅
- [x] Bash/Zsh auto-completion ✅

### Next Release (1.2.0) Goals:
- [ ] VM snapshots (save/restore state)
- [ ] Progress bars for long operations
- [ ] Health check API endpoint
- [ ] Improved error handling
- [ ] Alert system for failed services

### Roadmap
- **v1.2.0**: VM snapshots, progress bars, health API
- **v1.3.0**: Multi-VM orchestration, cluster mode
- **v2.0.0**: Cloud provider support (AWS, GCP, Azure), Windows WSL2

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
