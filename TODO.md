# CloneBox TODO List

## 🚀 High Priority

### Core Features
- [ ] Add `clonebox exec` command for executing commands in VM via QEMU Guest Agent
- [ ] Implement VM snapshot functionality (save/restore state)
- [ ] Add support for multiple VMs in single project (docker-compose style)
- [ ] Create web-based dashboard for VM management
- [ ] Add automatic port forwarding configuration

### Monitoring & Diagnostics
- [ ] Add real-time resource usage monitoring (CPU, RAM, disk)
- [ ] Implement alert system for failed services/apps
- [ ] Create health check API endpoint
- [ ] Add performance benchmarks for VM operations
- [ ] Implement log rotation for monitor logs

## 🔧 Medium Priority

### Usability
- [ ] Add progress bars for long operations (clone, export, import)
- [ ] Implement configuration profiles (dev, test, production)
- [ ] Add auto-completion for bash/zsh
- [ ] Create GUI configuration wizard
- [ ] Add dark mode for terminal output

### Integration
- [ ] Docker/Podman integration (run containers inside VM)
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

### Current Version: 0.1.23

### Next Release (0.2.0) Goals:
- [ ] `clonebox exec` command
- [ ] VM snapshots
- [ ] Web dashboard MVP
- [ ] Improved error handling
- [ ] Windows WSL2 support

### Roadmap
- **Q1 2024**: Core improvements and Windows support
- **Q2 2024**: Web dashboard and advanced monitoring
- **Q3 2024**: Cloud provider integrations
- **Q4 2024**: Multi-VM orchestration

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
