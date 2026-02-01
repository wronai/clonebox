
import sys
import os
from unittest.mock import MagicMock, patch

# Mock libvirt
sys.modules["libvirt"] = MagicMock()

from clonebox.cloner import SelectiveVMCloner, VMConfig
from clonebox.secrets import SSHKeyPair

def test_cloudinit_generation():
    print("Testing cloud-init user-data generation...")
    
    with patch("clonebox.cloner.get_container") as mock_get_container:
        mock_container = MagicMock()
        mock_get_container.return_value = mock_container
        
        # Mock SSHKeyPair.generate
        with patch("clonebox.secrets.SSHKeyPair.generate") as mock_keygen:
            mock_key = MagicMock()
            mock_key.public = "ssh-rsa AAAA..."
            mock_key.private = "-----BEGIN OPENSSH PRIVATE KEY-----..."
            mock_keygen.return_value = mock_key

            # Initialize cloner
            with patch.object(SelectiveVMCloner, "_connect"):
                cloner = SelectiveVMCloner(user_session=True)
                
                # Config with snap packages
                config = VMConfig(
                    name="test-vm",
                    snap_packages=["firefox", "code"],
                    gui=True
                )
                
                # Mock file writing and subprocess
                with patch("pathlib.Path.write_text") as mock_write:
                    with patch("subprocess.run"): # Mock genisoimage
                        with patch("pathlib.Path.mkdir"):
                             cloner._create_cloudinit_iso(MagicMock(), config)
                    
                    # Retrieve the content written to user-data
                    user_data = None
                    for call in mock_write.call_args_list:
                        content = call[0][0]
                        if "#cloud-config" in content:
                            user_data = content
                            break
                    
                    if not user_data:
                        print("❌ FAILED: Could not capture user-data content")
                        sys.exit(1)
                    
                    print("Captured user-data content successfully.")
                    
                    # Verify hardening logic
                    # We look for the retry loop structure
                    expected_retry_fragment = "snap install firefox --classic && break"
                    
                    if expected_retry_fragment in user_data and "for i in 1 2 3; do" in user_data:
                        print("✅ PASSED: Snap retry logic found for firefox")
                    else:
                        print("❌ FAILED: Snap retry logic NOT found for firefox")
                        # print("Content snippet:")
                        # print(user_data)
                        sys.exit(1)
                        
                    if "mkdir -p /home/ubuntu/.config/pulse" in user_data:
                         print("✅ PASSED: GUI directory creation found")
                    else:
                         print("❌ FAILED: GUI directory creation NOT found")
                         sys.exit(1)

if __name__ == "__main__":
    test_cloudinit_generation()
