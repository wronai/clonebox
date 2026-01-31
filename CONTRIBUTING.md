# CloneBox - Contributing Guidelines

## 🤝 Welcome!

Thank you for your interest in contributing to CloneBox! This document will help you get started.

## 🚀 Quick Start

1. Fork the repository
2. Clone your fork locally
3. Create a virtual environment
4. Install dependencies
5. Make your changes
6. Add tests
7. Submit a pull request

```bash
git clone https://github.com/YOUR_USERNAME/clonebox.git
cd clonebox
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -e ".[dev]"
```

## 📋 Development Setup

### Prerequisites

- Python 3.8+
- libvirt development libraries
- QEMU/KVM
- Linux (for now, Windows/macOS support planned)

### Running Tests

```bash
# Run all tests
make test

# Run with coverage
make test-cov

# Run specific test file
pytest tests/test_cloner.py

# Run with verbose output
pytest -v
```

### Code Style

We use:
- Black for formatting
- isort for import sorting
- flake8 for linting
- mypy for type checking

```bash
make format    # Format code
make lint      # Run linters
make typecheck # Run type checking
```

## 🏗️ Architecture Overview

```
clonebox/
├── src/clonebox/          # Main source code
│   ├── cli.py            # CLI commands and argument parsing
│   ├── cloner.py         # VM creation and management
│   ├── detector.py       # Auto-detection of services/apps
│   ├── models.py         # Data models
│   ├── profiles.py       # Configuration profiles
│   └── validator.py      # VM validation
├── scripts/              # Helper scripts
├── tests/               # Test suite
└── docs/                # Documentation
```

## 📝 How to Contribute

### Reporting Bugs

1. Check existing issues
2. Use the bug report template
3. Include:
   - OS and version
   - CloneBox version
   - Steps to reproduce
   - Expected vs actual behavior
   - Relevant logs

### Suggesting Features

1. Check TODO.md and existing issues
2. Use the feature request template
3. Describe the use case
4. Consider if it fits the project scope

### Submitting Changes

1. Fork and create a feature branch
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. Make your changes
   - Follow existing code style
   - Add docstrings
   - Include type hints

3. Add tests
   ```bash
   # Add new test file
   touch tests/test_your_feature.py
   
   # Write tests following existing patterns
   ```

4. Update documentation
   - README.md if needed
   - Add inline docstrings
   - Update docs/ if applicable

5. Run the test suite
   ```bash
   make test
   ```

6. Commit and push
   ```bash
   git commit -m "feat: add your feature description"
   git push origin feature/your-feature-name
   ```

7. Create a pull request
   - Use the PR template
   - Link relevant issues
   - Describe your changes

## 🎯 Good First Issues

Look for issues with the `good first issue` label:
- Adding unit tests
- Improving error messages
- Documentation updates
- Small feature enhancements

## 🔧 Development Workflow

### Adding a New Command

1. Add the command function in `cli.py`
2. Follow the naming pattern: `cmd_<command_name>`
3. Add argument parser
4. Implement the logic
5. Add tests in `tests/test_cli.py`

Example:
```python
def cmd_mycommand(args):
    """My new command."""
    # Implementation here
    pass

# In setup_argparse()
mycommand_parser = subparsers.add_parser("mycommand", help="My command")
mycommand_parser.add_argument("--option", help="Some option")
mycommand_parser.set_defaults(func=cmd_mycommand)
```

### Adding a New Feature

1. Design the API
2. Add models in `models.py`
3. Implement logic in appropriate module
4. Add CLI command if needed
5. Write comprehensive tests
6. Update documentation

### Debugging Tips

- Enable debug logging: `export CLONEBOX_DEBUG=1`
- Use `virsh` commands for low-level VM debugging
- Check cloud-init logs in VM: `/var/log/cloud-init*`
- Use the logs disk: `./scripts/clonebox-logs.sh`

## 📚 Documentation

### Types of Documentation

1. **Code Documentation**
   - Docstrings for all public functions
   - Type hints
   - Inline comments for complex logic

2. **User Documentation**
   - README.md - Main usage guide
   - docs/QUICK_REFERENCE.md - Command reference
   - Man pages for CLI commands

3. **Developer Documentation**
   - Architecture docs
   - API documentation
   - Contributing guide (this file)

### Writing Style

- Use clear, concise language
- Provide examples
- Use code blocks for commands
- Include prerequisites
- Add troubleshooting sections

## 🏷️ Release Process

1. Update version in `pyproject.toml`
2. Update CHANGELOG.md
3. Tag the release
4. Build and publish to PyPI
5. Create GitHub release

## 🤝 Community

### Code of Conduct

Be respectful, inclusive, and constructive. See CODE_OF_CONDUCT.md for details.

### Getting Help

- GitHub Issues: Bug reports and feature requests
- GitHub Discussions: General questions
- Wiki: Additional documentation

### Recognition

Contributors are recognized in:
- AUTHORS.md
- Release notes
- GitHub contributors list

## 📄 License

By contributing, you agree that your contributions will be licensed under the Apache 2.0 License.

## 🎯 Current Focus Areas

See TODO.md for current priorities. High-impact areas include:

1. **Windows/WSL2 Support** - Expand platform compatibility
2. **Web Dashboard** - GUI for VM management
3. **Enhanced Monitoring** - Better observability
4. **Performance** - Optimize resource usage
5. **Documentation** - Improve user experience

## 🙏 Thank You!

Every contribution helps make CloneBox better. Whether it's code, documentation, bug reports, or feature suggestions, we appreciate your help!
