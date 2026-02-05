#!/usr/bin/env python3
"""Tests for the SelectiveVMCloner module."""

from pathlib import Path
from unittest.mock import MagicMock, patch, Mock
import os
import pytest

from clonebox.cloner import SelectiveVMCloner, VMConfig
from clonebox.di import DependencyContainer, set_container
from clonebox.interfaces.hypervisor import HypervisorBackend
from clonebox.interfaces.disk import DiskManager
from clonebox.interfaces.network import NetworkManager
from clonebox.secrets import SecretsManager
from clonebox.backends.libvirt_network import LibvirtNetworkManager

@pytest.fixture(autouse=True)
def mock_container():
    """Setup a mock container for all tests to avoid libvirt requirement."""
    container = DependencyContainer()
    container.register(HypervisorBackend, instance=MagicMock(spec=HypervisorBackend))
    container.register(DiskManager, instance=MagicMock(spec=DiskManager))
    container.register(NetworkManager, LibvirtNetworkManager)
    container.register(SecretsManager, instance=MagicMock(spec=SecretsManager))
    set_container(container)
    yield container
    set_container(None)


class TestVMConfig:
    """Test VMConfig dataclass."""

    def test_default_values(self):
        with patch.dict(os.environ, {}, clear=True):
            config = VMConfig()
            assert config.name == "clonebox-vm"
            assert config.ram_mb == 8192
            assert config.vcpus == 4
        assert config.disk_size_gb == 20
        assert config.gui is True
        assert config.base_image is None
        assert config.paths == {}
        assert config.packages == []
        assert config.services == []
        assert config.user_session is False

    def test_custom_values(self):
        config = VMConfig(
            name="my-vm",
            ram_mb=8192,
            vcpus=8,
            disk_size_gb=50,
            gui=False,
            base_image="/path/to/image.qcow2",
            paths={"/home/user/project": "/mnt/project"},
            packages=["python3", "nodejs"],
            services=["docker"],
            user_session=True,
        )
        assert config.name == "my-vm"
        assert config.ram_mb == 8192
        assert config.user_session is True

    def test_to_dict(self):
        config = VMConfig(paths={"/a": "/b"}, packages=["pkg1"], services=["svc1"])
        d = config.to_dict()
        assert d["paths"] == {"/a": "/b"}
        assert d["packages"] == ["pkg1"]
        assert d["services"] == ["svc1"]


class TestSelectiveVMClonerInit:
    """Test SelectiveVMCloner initialization."""

    @patch("clonebox.cloner.libvirt")
    def test_system_images_dir(self, mock_libvirt):
        mock_libvirt.open.return_value = MagicMock()
        mock_libvirt.openAuth.return_value = MagicMock()
        cloner = SelectiveVMCloner()
        assert cloner.SYSTEM_IMAGES_DIR == Path("/var/lib/libvirt/images")

    @patch("clonebox.cloner.libvirt")
    def test_user_images_dir(self, mock_libvirt):
        mock_libvirt.open.return_value = MagicMock()
        mock_libvirt.openAuth.return_value = MagicMock()
        cloner = SelectiveVMCloner()
        expected = Path.home() / ".local/share/libvirt/images"
        assert cloner.USER_IMAGES_DIR == expected

    @pytest.mark.parametrize(
        "user_session,expected_uri",
        [
            (False, "qemu:///system"),
            (True, "qemu:///session"),
        ],
    )
    @patch("clonebox.cloner.libvirt")
    def test_init_session_type(self, mock_libvirt, user_session, expected_uri):
        mock_conn = MagicMock()
        mock_libvirt.open.return_value = mock_conn
        mock_libvirt.openAuth.return_value = mock_conn

        cloner = SelectiveVMCloner(user_session=user_session)

        assert cloner.conn_uri == expected_uri
        assert cloner.user_session is user_session
        
        # Verify open was called with expected URI
        args, _ = mock_libvirt.open.call_args
        assert args[0] == expected_uri

    @patch("clonebox.cloner.libvirt")
    def test_init_custom_uri(self, mock_libvirt):
        mock_conn = MagicMock()
        mock_libvirt.open.return_value = mock_conn
        mock_libvirt.openAuth.return_value = mock_conn

        cloner = SelectiveVMCloner(conn_uri="qemu+ssh://host/system")

        assert cloner.conn_uri == "qemu+ssh://host/system"

    @patch("clonebox.cloner.libvirt", None)
    def test_init_no_libvirt(self):
        with pytest.raises(ImportError) as exc_info:
            SelectiveVMCloner()
        assert "libvirt-python is required" in str(exc_info.value)

    @patch("clonebox.cloner.libvirt")
    def test_init_connection_failed(self, mock_libvirt):
        try:
            import libvirt as real_libvirt

            mock_libvirt.libvirtError = real_libvirt.libvirtError
            mock_libvirt.open.side_effect = real_libvirt.libvirtError("Connection refused")
            mock_libvirt.openAuth.side_effect = real_libvirt.libvirtError("Connection refused")
        except ImportError:
            # If libvirt is not installed, create a mock exception
            class MockLibvirtError(Exception):
                pass

            mock_libvirt.libvirtError = MockLibvirtError
            mock_libvirt.open.side_effect = MockLibvirtError("Connection refused")
            mock_libvirt.openAuth.side_effect = MockLibvirtError("Connection refused")

        with pytest.raises(ConnectionError) as exc_info:
            SelectiveVMCloner()
        assert "Cannot connect" in str(exc_info.value)
        assert "Troubleshooting" in str(exc_info.value)


class TestSelectiveVMClonerMethods:
    """Test SelectiveVMCloner methods."""

    @pytest.mark.parametrize(
        "user_session,expected_path",
        [
            (False, Path("/var/lib/libvirt/images")),
            (True, Path.home() / ".local/share/libvirt/images"),
        ],
    )
    @patch("clonebox.cloner.libvirt")
    def test_get_images_dir(self, mock_libvirt, user_session, expected_path):
        mock_libvirt.open.return_value = MagicMock()
        mock_libvirt.openAuth.return_value = MagicMock()

        cloner = SelectiveVMCloner(user_session=user_session)
        assert cloner.get_images_dir() == expected_path

    @patch("clonebox.cloner.libvirt")
    def test_check_prerequisites_returns_dict(self, mock_libvirt):
        mock_conn = MagicMock()
        mock_conn.isAlive.return_value = True
        mock_conn.getLibVersion.return_value = 9_000_000
        mock_conn.listNetworks.return_value = ["default"]
        mock_conn.listDefinedNetworks.return_value = []
        mock_libvirt.open.return_value = mock_conn
        mock_libvirt.openAuth.return_value = mock_conn

        cloner = SelectiveVMCloner(user_session=True)  # Use user session to avoid permission issues
        checks = cloner.check_prerequisites()

        assert "libvirt_connected" in checks
        assert "kvm_available" in checks
        assert "default_network" in checks
        assert "images_dir_writable" in checks
        assert "images_dir" in checks
        assert "session_type" in checks
        assert "passt_installed" in checks
        assert "passt_available" in checks
        assert "default_network_required" in checks

    @pytest.mark.parametrize(
        "user_session,expected_type",
        [
            (False, "system"),
            (True, "user"),
        ],
    )
    @patch("clonebox.cloner.libvirt")
    def test_check_prerequisites_session_type(self, mock_libvirt, user_session, expected_type):
        mock_conn = MagicMock()
        mock_conn.isAlive.return_value = True
        mock_conn.getLibVersion.return_value = 9_000_000
        mock_libvirt.open.return_value = mock_conn
        mock_libvirt.openAuth.return_value = mock_conn

        cloner = SelectiveVMCloner(user_session=user_session)
        assert cloner.check_prerequisites()["session_type"] == expected_type

    @patch("clonebox.cloner.libvirt")
    def test_list_vms(self, mock_libvirt):
        mock_conn = MagicMock()
        mock_conn.listDomainsID.return_value = [1]
        mock_conn.listDefinedDomains.return_value = ["stopped-vm"]

        running_vm = MagicMock()
        running_vm.name.return_value = "running-vm"
        running_vm.UUIDString.return_value = "uuid-1234"
        running_vm.info.return_value = [1, 4194304, 0, 2]  # running, 4GB mem, 0 cpu time, 2 vcpus

        stopped_vm = MagicMock()
        stopped_vm.name.return_value = "stopped-vm"
        stopped_vm.UUIDString.return_value = "uuid-5678"
        stopped_vm.info.return_value = [5, 4194304, 0, 2]  # shutoff, 4GB mem, 0 cpu time, 2 vcpus

        mock_conn.lookupByID.return_value = running_vm
        mock_conn.lookupByName.return_value = stopped_vm
        mock_libvirt.open.return_value = mock_conn
        mock_libvirt.openAuth.return_value = mock_conn

        cloner = SelectiveVMCloner()
        vms = cloner.list_vms()

        assert len(vms) == 2
        assert vms[0]["name"] == "running-vm"
        assert vms[0]["state"] == "running"
        assert vms[1]["name"] == "stopped-vm"
        assert vms[1]["state"] == "shutoff"

    @patch("clonebox.cloner.libvirt")
    def test_close(self, mock_libvirt):
        mock_conn = MagicMock()
        mock_libvirt.open.return_value = mock_conn
        mock_libvirt.openAuth.return_value = mock_conn

        cloner = SelectiveVMCloner()
        cloner.close()

        mock_conn.close.assert_called_once()


class TestVMXMLGeneration:
    """Test VM XML generation."""

    @patch("clonebox.cloner.libvirt")
    def test_generate_vm_xml_basic(self, mock_libvirt):
        mock_libvirt.open.return_value = MagicMock()
        mock_libvirt.openAuth.return_value = MagicMock()

        cloner = SelectiveVMCloner()
        config = VMConfig(name="test-vm", ram_mb=2048, vcpus=2)

        xml = cloner._generate_vm_xml(config, Path("/tmp/root.qcow2"), None)

        assert "test-vm" in xml
        # Memory is in MiB
        assert "2048" in xml
        assert "<vcpu" in xml
        assert "kvm" in xml

    @patch("clonebox.cloner.libvirt")
    def test_generate_vm_xml_with_paths(self, mock_libvirt):
        mock_libvirt.open.return_value = MagicMock()
        mock_libvirt.openAuth.return_value = MagicMock()

        cloner = SelectiveVMCloner()
        config = VMConfig(name="test-vm", paths={"/home/user/project": "/mnt/project"})

        # Need to mock Path.exists() for the paths
        with patch.object(Path, "exists", return_value=True):
            xml = cloner._generate_vm_xml(config, Path("/tmp/root.qcow2"), None)

        assert "filesystem" in xml
        assert "mount" in xml

    @patch("clonebox.cloner.libvirt")
    def test_generate_vm_xml_tuning_exclusion(self, mock_libvirt):
        """Test that resource tuning elements are excluded in user session mode."""
        mock_libvirt.open.return_value = MagicMock()
        mock_libvirt.openAuth.return_value = MagicMock()

        # 1. Test User Session (Should exclude tuning)
        cloner_user = SelectiveVMCloner(user_session=True)
        config = VMConfig(
            name="test-vm",
            ram_mb=2048,
            vcpus=2,
            resources={
                "cpu": {"shares": 1024, "quota": 10000},
                "memory": {"soft_limit": "1G"},
                "disk": {"read_bps": "10M"},
            }
        )
        
        xml_user = cloner_user._generate_vm_xml(config, Path("/tmp/root.qcow2"), None)
        
        assert "cputune" not in xml_user
        assert "memtune" not in xml_user
        assert "iotune" not in xml_user

        # 2. Test System Session (Should include tuning)
        cloner_system = SelectiveVMCloner(user_session=False)
        
        xml_system = cloner_system._generate_vm_xml(config, Path("/tmp/root.qcow2"), None)
        
        assert "cputune" in xml_system
        assert "memtune" in xml_system
        assert "iotune" in xml_system


class TestVMCreation:
    """Test VM creation (with mocked libvirt)."""

    @patch("clonebox.cloner.os.path.exists")
    @patch("clonebox.cloner.subprocess.run")
    @patch("clonebox.cloner.libvirt")
    def test_create_vm_permission_error(self, mock_libvirt, mock_run, mock_exists):
        mock_conn = MagicMock()
        mock_conn.lookupByName.side_effect = Exception("not found")
        mock_libvirt.open.return_value = mock_conn
        mock_libvirt.openAuth.return_value = mock_conn
        mock_exists.return_value = True  # Base image exists

        cloner = SelectiveVMCloner()
        config = VMConfig(name="test-vm", base_image="/path/to/base.qcow2")

        # Mock mkdir to raise PermissionError
        with patch.object(Path, "mkdir", side_effect=PermissionError("Permission denied")):
            with pytest.raises(PermissionError):
                cloner.create_vm(config)


class TestVMGUIDetection:
    """Test GUI/SPICE/VNC detection in diagnostics."""

    @patch("clonebox.cloner.libvirt")
    @patch("clonebox.cloner.SelectiveVMCloner._get_saved_ssh_port")
    def test_check_vm_processes_detects_spice(self, mock_get_ssh_port, mock_libvirt):
        """Test that _check_vm_processes detects SPICE graphics."""
        mock_conn = MagicMock()
        mock_libvirt.open.return_value = mock_conn
        mock_libvirt.openAuth.return_value = mock_conn
        
        # Mock SSH port to prevent early return
        mock_get_ssh_port.return_value = 2222

        # Mock VM XML with SPICE graphics
        vm_xml = """<domain type='qemu'>
            <devices>
                <graphics type='spice' port='5900' autoport='yes' listen='0.0.0.0'/>
            </devices>
        </domain>"""
        
        mock_vm = MagicMock()
        mock_vm.XMLDesc.return_value = vm_xml
        mock_conn.lookupByName.return_value = mock_vm
        
        # Mock process info
        mock_vm.info.return_value = [1, 4194304, 0, 2]  # running
        mock_vm.isActive.return_value = True
        
        cloner = SelectiveVMCloner()
        checks = cloner._check_vm_processes("test-vm")
        
        assert "spice_port" in checks
        assert checks["spice_port"] == "5900"

    @patch("clonebox.cloner.libvirt")
    @patch("clonebox.cloner.SelectiveVMCloner._get_saved_ssh_port")
    def test_check_vm_processes_detects_vnc(self, mock_get_ssh_port, mock_libvirt):
        """Test that _check_vm_processes detects VNC graphics."""
        mock_conn = MagicMock()
        mock_libvirt.open.return_value = mock_conn
        mock_libvirt.openAuth.return_value = mock_conn
        
        # Mock SSH port to prevent early return
        mock_get_ssh_port.return_value = 2222

        # Mock VM XML with VNC graphics
        vm_xml = """<domain type='qemu'>
            <devices>
                <graphics type='vnc' port='5901' autoport='yes' listen='0.0.0.0'/>
            </devices>
        </domain>"""
        
        mock_vm = MagicMock()
        mock_vm.XMLDesc.return_value = vm_xml
        mock_conn.lookupByName.return_value = mock_vm
        
        # Mock process info
        mock_vm.info.return_value = [1, 4194304, 0, 2]
        mock_vm.isActive.return_value = True
        
        cloner = SelectiveVMCloner()
        checks = cloner._check_vm_processes("test-vm")
        
        assert "vnc_port" in checks
        assert checks["vnc_port"] == "5901"

    @patch("clonebox.cloner.libvirt")
    @patch("clonebox.cloner.SelectiveVMCloner._get_saved_ssh_port")
    def test_check_vm_processes_no_graphics(self, mock_get_ssh_port, mock_libvirt):
        """Test that _check_vm_processes handles VMs without graphics."""
        mock_conn = MagicMock()
        mock_libvirt.open.return_value = mock_conn
        mock_libvirt.openAuth.return_value = mock_conn
        
        # Mock SSH port to prevent early return
        mock_get_ssh_port.return_value = 2222

        # Mock VM XML without graphics
        vm_xml = """<domain type='qemu'>
            <devices>
                <disk type='file' device='disk'/>
            </devices>
        </domain>"""
        
        mock_vm = MagicMock()
        mock_vm.XMLDesc.return_value = vm_xml
        mock_conn.lookupByName.return_value = mock_vm
        
        # Mock process info
        mock_vm.info.return_value = [1, 4194304, 0, 2]
        mock_vm.isActive.return_value = True
        
        cloner = SelectiveVMCloner()
        checks = cloner._check_vm_processes("test-vm")
        
        # Should not have spice or vnc ports
        assert "spice_port" not in checks
        assert "vnc_port" not in checks
