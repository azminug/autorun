"""Hardware ID (HWID) utilities for device identification"""
import subprocess
import hashlib
import platform
import uuid
import socket


def get_hwid():
    """
    Generate unique Hardware ID based on system properties.
    Uses combination of machine GUID, MAC address, and processor ID.
    """
    try:
        # Get Windows Machine GUID
        machine_guid = ""
        try:
            result = subprocess.run(
                ['reg', 'query', 'HKLM\\SOFTWARE\\Microsoft\\Cryptography', '/v', 'MachineGuid'],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if 'MachineGuid' in line:
                        machine_guid = line.split()[-1]
                        break
        except:
            pass

        # Get MAC address
        mac = ':'.join(['{:02x}'.format((uuid.getnode() >> i) & 0xff) for i in range(0, 48, 8)][::-1])
        
        # Get processor ID
        processor_id = ""
        try:
            result = subprocess.run(
                ['wmic', 'cpu', 'get', 'ProcessorId'],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                lines = [l.strip() for l in result.stdout.split('\n') if l.strip() and 'ProcessorId' not in l]
                if lines:
                    processor_id = lines[0]
        except:
            pass

        # Combine and hash
        combined = f"{machine_guid}:{mac}:{processor_id}:{platform.node()}"
        hwid = hashlib.sha256(combined.encode()).hexdigest()[:32].upper()
        
        return hwid
    except Exception as e:
        # Fallback to UUID-based HWID
        return hashlib.sha256(str(uuid.getnode()).encode()).hexdigest()[:32].upper()


def get_machine_info():
    """Get detailed machine information"""
    try:
        hostname = socket.gethostname()
        ip_address = socket.gethostbyname(hostname)
    except:
        hostname = platform.node()
        ip_address = "unknown"
    
    return {
        "hwid": get_hwid(),
        "hostname": hostname,
        "ip_address": ip_address,
        "platform": platform.system(),
        "platform_version": platform.version(),
        "platform_release": platform.release(),
        "processor": platform.processor(),
        "machine": platform.machine(),
        "python_version": platform.python_version()
    }


if __name__ == "__main__":
    print("HWID:", get_hwid())
    print("\nMachine Info:")
    info = get_machine_info()
    for key, value in info.items():
        print(f"  {key}: {value}")
