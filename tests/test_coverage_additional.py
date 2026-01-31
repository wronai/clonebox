"""Additional tests to increase overall coverage."""

import pytest
from unittest.mock import Mock, patch


def test_cloner_imports():
    """Test cloner module imports."""
    try:
        from clonebox.cloner import SelectiveVMCloner, VMConfig

        assert SelectiveVMCloner is not None
        assert VMConfig is not None
    except ImportError:
        pytest.skip("libvirt not available")


def test_dashboard_import():
    """Test dashboard module import."""
    try:
        from clonebox import dashboard

        assert dashboard is not None
    except ImportError:
        pytest.skip("streamlit not available")


def test_main_module():
    """Test __main__ module exists."""
    from clonebox import __main__

    assert __main__ is not None


def test_init_module():
    """Test __init__ module exports."""
    from clonebox import SelectiveVMCloner, SystemDetector, __version__

    assert SelectiveVMCloner is not None
    assert SystemDetector is not None
    assert __version__ is not None
