#!/usr/bin/env python3
"""Tests for network mode functionality."""

from pathlib import Path
from unittest.mock import MagicMock, patch, Mock
import pytest

from clonebox.cloner import SelectiveVMCloner, VMConfig
from clonebox.di import DependencyContainer, set_container
from clonebox.interfaces.hypervisor import HypervisorBackend
from clonebox.interfaces.disk import DiskManager
from clonebox.secrets import SecretsManager

@pytest.fixture(autouse=True)
def mock_container():
    """Setup a mock container for all tests to avoid libvirt requirement."""
    container = DependencyContainer()
    container.register(HypervisorBackend, instance=MagicMock(spec=HypervisorBackend))
    container.register(DiskManager, instance=MagicMock(spec=DiskManager))
    container.register(SecretsManager, instance=MagicMock(spec=SecretsManager))
    set_container(container)
    yield container
    set_container(None)

class TestNetworkMode:
    """Test network mode resolution and fallback."""

    @patch("clonebox.cloner.libvirt")
    def test_vm_config_network_mode_default(self, mock_libvirt):
        config = VMConfig()
        assert config.network_mode == "auto"

    @patch("clonebox.cloner.libvirt")
    def test_vm_config_network_mode_custom(self, mock_libvirt):
        config = VMConfig(network_mode="user")
        assert config.network_mode == "user"

    @patch("clonebox.cloner.libvirt")
    def test_resolve_network_mode_auto_system(self, mock_libvirt):
        """Test auto mode with system session uses default network."""
        mock_conn = MagicMock()
        mock_libvirt.open.return_value = mock_conn
        mock_libvirt.openAuth.return_value = mock_conn

        cloner = SelectiveVMCloner(user_session=False)
        config = VMConfig(network_mode="auto")

        mode = cloner.resolve_network_mode(config)
        assert mode == "default"

    @patch("clonebox.cloner.libvirt")
    def test_resolve_network_mode_auto_user_with_default(self, mock_libvirt):
        """Test auto mode with user session and default network available."""
        mock_conn = MagicMock()
        mock_libvirt.open.return_value = mock_conn
        mock_libvirt.openAuth.return_value = mock_conn
        mock_conn.listNetworks.return_value = ["default"]
        mock_conn.listDefinedNetworks.return_value = []

        cloner = SelectiveVMCloner(user_session=True)
        config = VMConfig(network_mode="auto")

        mode = cloner.resolve_network_mode(config)
        assert mode == "default"

    @patch("clonebox.cloner.libvirt")
    def test_resolve_network_mode_auto_user_no_default(self, mock_libvirt):
        """Test auto mode with user session and no default network falls back to user."""
        mock_conn = MagicMock()
        mock_conn.listNetworks.return_value = []
        mock_conn.listDefinedNetworks.return_value = []
        mock_libvirt.open.return_value = mock_conn
        mock_libvirt.openAuth.return_value = mock_conn

        cloner = SelectiveVMCloner(user_session=True)
        config = VMConfig(network_mode="auto")

        mode = cloner.resolve_network_mode(config)
        assert mode == "user"

    @patch("clonebox.cloner.libvirt")
    def test_resolve_network_mode_explicit_default(self, mock_libvirt):
        """Test explicit default mode."""
        mock_conn = MagicMock()
        mock_libvirt.open.return_value = mock_conn
        mock_libvirt.openAuth.return_value = mock_conn

        cloner = SelectiveVMCloner(user_session=True)
        config = VMConfig(network_mode="default")

        mode = cloner.resolve_network_mode(config)
        assert mode == "default"

    @patch("clonebox.cloner.libvirt")
    def test_resolve_network_mode_explicit_user(self, mock_libvirt):
        """Test explicit user mode."""
        mock_conn = MagicMock()
        mock_libvirt.open.return_value = mock_conn
        mock_libvirt.openAuth.return_value = mock_conn

        cloner = SelectiveVMCloner(user_session=False)
        config = VMConfig(network_mode="user")

        mode = cloner.resolve_network_mode(config)
        assert mode == "user"

    @patch("clonebox.cloner.libvirt")
    def test_resolve_network_mode_invalid(self, mock_libvirt):
        """Test invalid network mode falls back to default."""
        mock_conn = MagicMock()
        mock_libvirt.open.return_value = mock_conn
        mock_libvirt.openAuth.return_value = mock_conn

        cloner = SelectiveVMCloner()
        config = VMConfig(network_mode="invalid")

        mode = cloner.resolve_network_mode(config)
        assert mode == "default"

    @patch("clonebox.cloner.libvirt")
    def test_default_network_active_true(self, mock_libvirt):
        """Test _default_network_active returns True when network is active."""
        mock_conn = MagicMock()
        mock_libvirt.open.return_value = mock_conn
        mock_libvirt.openAuth.return_value = mock_conn
        mock_conn.listNetworks.return_value = ["default"]
        mock_conn.listDefinedNetworks.return_value = []

        cloner = SelectiveVMCloner()
        assert cloner._default_network_active() is True

    @patch("clonebox.cloner.libvirt")
    def test_default_network_active_false(self, mock_libvirt):
        """Test _default_network_active returns False when network is inactive."""

        mock_conn = MagicMock()
        mock_libvirt.open.return_value = mock_conn
        mock_libvirt.openAuth.return_value = mock_conn
        mock_conn.listNetworks.return_value = []
        mock_conn.listDefinedNetworks.return_value = ["default"]

        cloner = SelectiveVMCloner()
        assert cloner._default_network_active() is False

    @patch("clonebox.cloner.libvirt")
    def test_default_network_active_not_found(self, mock_libvirt):
        """Test _default_network_active returns False when network not found."""
        mock_conn = MagicMock()
        mock_conn.listNetworks.return_value = []
        mock_conn.listDefinedNetworks.return_value = []
        mock_libvirt.open.return_value = mock_conn
        mock_libvirt.openAuth.return_value = mock_conn

        cloner = SelectiveVMCloner()
        assert cloner._default_network_active() is False

    @patch("clonebox.cloner.libvirt")
    def test_generate_vm_xml_user_network(self, mock_libvirt):
        """Test VM XML generation with user network."""
        mock_conn = MagicMock()
        mock_libvirt.open.return_value = mock_conn
        mock_libvirt.openAuth.return_value = mock_conn

        cloner = SelectiveVMCloner()
        config = VMConfig(name="test-vm", network_mode="user")

        xml = cloner._generate_vm_xml(config, Path("/tmp/root.qcow2"), None)

        assert '<interface type="user">' in xml
        assert '<interface type="network">' not in xml

    @patch("clonebox.cloner.libvirt")
    def test_generate_vm_xml_default_network(self, mock_libvirt):
        """Test VM XML generation with default network."""
        mock_conn = MagicMock()
        mock_libvirt.open.return_value = mock_conn
        mock_libvirt.openAuth.return_value = mock_conn

        cloner = SelectiveVMCloner()
        config = VMConfig(name="test-vm", network_mode="default")

        xml = cloner._generate_vm_xml(config, Path("/tmp/root.qcow2"), None)

        assert '<interface type="network">' in xml
        assert '<source network="default"' in xml
        assert '<interface type="user">' not in xml
