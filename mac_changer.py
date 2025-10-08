#!/usr/bin/env python3
"""
Windows Wi‑Fi MAC changer with Matrix-style UI.

Notes:
 - Requires Administrator.
 - Use only on machines/networks you own or are authorized to test.
 - Restores original MAC/NetworkAddress before exit and on signals.
"""

import ctypes
import os
import random
import re
import signal
import sys
import time
from subprocess import PIPE, CalledProcessError, run
from random import randint
from typing import List, Optional, Tuple

import winreg

NIC_CLASS_GUID = "{4d36e972-e325-11ce-bfc1-08002be10318}"

# ANSI color helpers
CSI = "\x1b["
GREEN = CSI + "32m"
BRIGHT_GREEN = CSI + "92m"
RESET = CSI + "0m"
CLEAR = CSI + "2J" + CSI + "H"


class MatrixUI:
    def __init__(self):
        self.enable_vt()

    @staticmethod
    def enable_vt():
        try:
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
            mode = ctypes.c_uint()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)) == 0:
                return
            ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
            kernel32.SetConsoleMode(handle, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING)
        except Exception:
            pass

    @staticmethod
    def matrix_rain(duration: float = 2.2, width: int = 80, density: float = 0.02):
        cols = max(10, width)
        drops = [0 for _ in range(cols)]
        chars = "01ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789@#%&*"
        start = time.time()
        print(CLEAR, end="")
        while time.time() - start < duration:
            line = []
            for i in range(cols):
                if random.random() < density:
                    drops[i] = 1
                ch = " "
                if drops[i] > 0:
                    ch = random.choice(chars)
                    drops[i] += 1
                    if drops[i] > random.randint(4, 20):
                        drops[i] = 0
                line.append(ch)
            out = "".join(
                f"{BRIGHT_GREEN}{c}{RESET}" if random.random() < 0.08 and c != " " else f"{GREEN}{c}{RESET}"
                for c in line
            )
            print(out)
            time.sleep(0.06)

    def loader(self, text: str = "Booting", duration: float = 1.8):
        try:
            width = min(100, max(60, os.get_terminal_size().columns)) if sys.stdout.isatty() else 80
        except OSError:
            width = 80
        self.matrix_rain(duration=duration, width=width, density=0.018)
        print(f"{BRIGHT_GREEN}{text}...{RESET}")

    def flourish(self, duration: float = 1.0):
        try:
            width = min(100, max(60, os.get_terminal_size().columns)) if sys.stdout.isatty() else 80
        except OSError:
            width = 80
        self.matrix_rain(duration=duration, width=width, density=0.025)


class Utils:
    @staticmethod
    def require_admin():
        try:
            if ctypes.windll.shell32.IsUserAnAdmin() != 1:
                print("\n[!] Please run the script as Administrator.\nExiting...")
                sys.exit(1)
        except Exception:
            print("\n[!] Unable to verify Administrator status. Proceeding may fail.\n")

    @staticmethod
    def is_valid_mac(mac: str) -> bool:
        if not mac:
            return False
        mac_norm = mac.replace("-", ":").lower()
        if not re.match(r"^([0-9a-f]{2}:){5}[0-9a-f]{2}$", mac_norm):
            return False
        try:
            return int(mac_norm.split(":")[0], 16) % 2 == 0
        except ValueError:
            return False

    @staticmethod
    def normalize_mac(mac: str) -> str:
        return mac.replace("-", ":").lower()

    @staticmethod
    def mac_for_registry(mac: str) -> str:
        return Utils.normalize_mac(mac).replace(":", "").upper()

    @staticmethod
    def random_mac() -> str:
        mac = ""
        while not Utils.is_valid_mac(mac):
            mac = ":".join("{:02x}".format(randint(0, 255)) for _ in range(6))
        return mac

    @staticmethod
    def is_wireless_media(media: str) -> bool:
        if not media:
            return False
        m = media.lower()
        return "802" in m or "native802" in m or "wireless" in m or "wifi" in m


class AdapterDiscovery:
    @staticmethod
    def discover_wifi_adapters() -> List[Tuple[str, str, str]]:
        adapters: List[Tuple[str, str, str]] = []
        ps_cmd = r"Get-NetAdapter | ForEach-Object { \"$($_.Name)|$($_.InterfaceGuid)|$($_.NdisPhysicalMedium)\" }"
        try:
            proc = run(["powershell", "-NoProfile", "-Command", ps_cmd],
                       stdout=PIPE, stderr=PIPE, text=True, check=True)
            for line in proc.stdout.splitlines():
                if "|" in line:
                    parts = [p.strip().strip('"') for p in line.split("|", 2)]
                    if len(parts) == 3:
                        name, guid, media = parts
                        if name and Utils.is_wireless_media(media):
                            adapters.append((name, guid, media or "Unknown"))
            if adapters:
                return adapters
        except CalledProcessError:
            pass

        # fallback to netsh wlan interfaces
        try:
            proc = run(["netsh", "wlan", "show", "interfaces"], stdout=PIPE, stderr=PIPE, text=True, check=True)
            name = guid = ""
            for line in proc.stdout.splitlines():
                l = line.strip()
                if l.lower().startswith("name"):
                    name = l.split(":", 1)[1].strip().strip('"')
                if l.lower().startswith("interface guid"):
                    guid = l.split(":", 1)[1].strip().strip('"')
                if name:
                    adapters.append((name, guid, "Native802_11"))
                    name = guid = ""
        except CalledProcessError:
            pass

        # final heuristic fallback using netsh interface show interface
        try:
            proc = run(["netsh", "interface", "show", "interface"], stdout=PIPE, stderr=PIPE, text=True, check=True)
            for line in proc.stdout.splitlines():
                parts = line.strip().split()
                if len(parts) >= 4 and parts[0] in ("Enabled", "Disabled"):
                    name = " ".join(parts[3:])
                    if any(k in name.lower() for k in ("wireless", "wi-fi", "wifi")):
                        adapters.append((name, "", "Unknown"))
        except CalledProcessError:
            pass

        return adapters


class RegistryManager:
    def __init__(self, nic_class_guid: str = NIC_CLASS_GUID):
        self.nic_class_guid = nic_class_guid

    def find_subkey_for_guid(self, guid: str) -> Optional[str]:
        if not guid:
            return None
        base = rf"SYSTEM\CurrentControlSet\Control\Class\{self.nic_class_guid}"
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as key:
                i = 0
                while True:
                    try:
                        sub = winreg.EnumKey(key, i)
                        with winreg.OpenKey(key, sub) as sk:
                            try:
                                val, _ = winreg.QueryValueEx(sk, "NetCfgInstanceId")
                                if isinstance(val, str) and val.lower() == guid.lower():
                                    return sub
                            except FileNotFoundError:
                                pass
                    except OSError:
                        break
                    i += 1
        except OSError:
            pass
        return None

    def read_network_address(self, subkey: str) -> Optional[str]:
        if not subkey:
            return None
        path = rf"SYSTEM\CurrentControlSet\Control\Class\{self.nic_class_guid}\{subkey}"
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as sk:
                val, _ = winreg.QueryValueEx(sk, "NetworkAddress")
                return val
        except FileNotFoundError:
            return None
        except OSError:
            return None

    def set_network_address(self, subkey: str, mac_nosep: str) -> bool:
        if not subkey:
            return False
        path = rf"SYSTEM\CurrentControlSet\Control\Class\{self.nic_class_guid}\{subkey}"
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0, winreg.KEY_SET_VALUE) as sk:
                winreg.SetValueEx(sk, "NetworkAddress", 0, winreg.REG_SZ, mac_nosep)
            return True
        except Exception as e:
            print(f"{BRIGHT_GREEN}[!] Registry write failed:{RESET} {e}")
            return False

    def clear_network_address(self, subkey: str) -> bool:
        if not subkey:
            return False
        path = rf"SYSTEM\CurrentControlSet\Control\Class\{self.nic_class_guid}\{subkey}"
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0, winreg.KEY_SET_VALUE) as sk:
                try:
                    winreg.DeleteValue(sk, "NetworkAddress")
                except FileNotFoundError:
                    pass
            return True
        except Exception as e:
            print(f"{BRIGHT_GREEN}[!] Failed to clear NetworkAddress:{RESET} {e}")
            return False


class SystemOps:
    @staticmethod
    def toggle_interface(name: str) -> bool:
        try:
            run(["netsh", "interface", "set", "interface", name, "admin=disable"], check=True, stdout=PIPE, stderr=PIPE)
            time.sleep(0.9)
            run(["netsh", "interface", "set", "interface", name, "admin=enable"], check=True, stdout=PIPE, stderr=PIPE)
            return True
        except CalledProcessError as e:
            print(f"{BRIGHT_GREEN}[!] Failed to toggle interface:{RESET} {e}")
            return False

    @staticmethod
    def netsh_fallback(name: str, mac: str) -> bool:
        try:
            run(["netsh", "interface", "set", "interface", name, "admin=disable"], check=True)
            run(["netsh", "interface", "set", "interface", name, f"ethernet={mac}", "admin=enable"], check=True)
            return True
        except CalledProcessError:
            return False

    @staticmethod
    def show_getmac():
        try:
            proc = run(["getmac", "/v"], stdout=PIPE, stderr=PIPE, text=True, check=True)
            print(proc.stdout)
        except CalledProcessError:
            pass

    @staticmethod
    def getmac_for_interface(interface: str) -> Optional[str]:
        try:
            proc = run(["getmac", "/v", "/fo", "list"], stdout=PIPE, stderr=PIPE, text=True, check=True)
            current_name = None
            for line in proc.stdout.splitlines():
                line = line.strip()
                if line.lower().startswith("connection name"):
                    current_name = line.split(":", 1)[1].strip()
                if line.lower().startswith("physical address") and current_name == interface:
                    return line.split(":", 1)[1].strip()
        except CalledProcessError:
            pass
        return None


class RestoreManager:
    def __init__(self, registry: RegistryManager, system_ops: SystemOps):
        self.registry = registry
        self.system_ops = system_ops
        self.adapter_name: Optional[str] = None
        self.adapter_guid: Optional[str] = None
        self.reg_subkey: Optional[str] = None
        self.original_registry_value: Optional[str] = None
        self.original_physical_address: Optional[str] = None
        # register signals
        try:
            signal.signal(signal.SIGINT, self._on_signal)
            signal.signal(signal.SIGTERM, self._on_signal)
        except Exception:
            pass

    def snapshot(self, name: str, guid: str):
        self.adapter_name = name
        self.adapter_guid = guid or None
        self.original_physical_address = SystemOps.getmac_for_interface(name)
        if self.adapter_guid:
            subkey = self.registry.find_subkey_for_guid(self.adapter_guid)
            self.reg_subkey = subkey
            if subkey:
                self.original_registry_value = self.registry.read_network_address(subkey)

    def restore(self):
        if self.reg_subkey:
            print(f"{BRIGHT_GREEN}[*] Restoring registry NetworkAddress for subkey {self.reg_subkey}{RESET}")
            if self.original_registry_value:
                self.registry.set_network_address(self.reg_subkey, self.original_registry_value)
            else:
                self.registry.clear_network_address(self.reg_subkey)
            if self.adapter_name:
                self.system_ops.toggle_interface(self.adapter_name)
        else:
            if self.adapter_name:
                self.system_ops.toggle_interface(self.adapter_name)
        print(f"{BRIGHT_GREEN}[*] Current MACs (verify):{RESET}")
        SystemOps.show_getmac()

    def _on_signal(self, signum, frame):
        print(f"\n{BRIGHT_GREEN}[*] Caught signal {signum}, restoring original MAC and exiting...{RESET}")
        try:
            self.restore()
        except Exception:
            pass
        sys.exit(1)


class MacChanger:
    def __init__(self):
        self.ui = MatrixUI()
        self.registry = RegistryManager()
        self.system_ops = SystemOps()
        self.restorer = RestoreManager(self.registry, self.system_ops)

    def run(self):
        self.ui.loader("Booting matrix environment", duration=2.0)
        Utils.require_admin()

        adapters = AdapterDiscovery.discover_wifi_adapters()
        if not adapters:
            print(f"{BRIGHT_GREEN}[!] No Wi‑Fi adapters detected. Exiting.{RESET}")
            self.ui.flourish(duration=1.0)
            sys.exit(1)

        options = [f"{name}  (GUID: {guid or 'N/A'})  Media: {media}" for name, guid, media in adapters]
        print(f"{BRIGHT_GREEN}Detected Wi‑Fi adapters:{RESET}")
        idx = self._prompt_choice(options, "Select adapter number to modify:")
        name, guid, media = adapters[idx]
        print(f"{BRIGHT_GREEN}Selected:{RESET} {GREEN}{name}{RESET} (GUID: {guid or 'N/A'}) Media: {media}")

        # snapshot for restore
        self.restorer.snapshot(name, guid)

        print()
        print(f"{BRIGHT_GREEN}MAC options:{RESET}")
        print(f"{GREEN}1{RESET}. Manual entry (pattern: XX:XX:XX:XX:XX:XX)")
        print(f"{GREEN}2{RESET}. Generate random unicast MAC")
        mac_choice = self._prompt_choice(["Manual", "Random"], "Choose MAC option (1 or 2):")

        if mac_choice == 0:
            try:
                user_mac = input(f"{BRIGHT_GREEN}Enter MAC (e.g. B8:3A:37:04:78:D1):{RESET} ").strip()
            except EOFError:
                user_mac = ""
            if not Utils.is_valid_mac(user_mac):
                print(f"{BRIGHT_GREEN}\n[!] Invalid MAC. Expected XX:XX:XX:XX:XX:XX and unicast first octet.{RESET}")
                self.ui.flourish(duration=1.0)
                try:
                    self.restorer.restore()
                except Exception:
                    pass
                sys.exit(1)
            mac_norm = Utils.normalize_mac(user_mac)
        else:
            mac_norm = Utils.random_mac()
            print(f"{BRIGHT_GREEN}Generated MAC:{RESET} {GREEN}{mac_norm}{RESET}")

        reg_value = Utils.mac_for_registry(mac_norm)
        applied = False

        self.ui.flourish(duration=1.6)

        try:
            if guid:
                subkey = self.registry.find_subkey_for_guid(guid)
                if subkey:
                    print(f"{BRIGHT_GREEN}[*] Writing NetworkAddress={reg_value} to registry subkey {subkey} ...{RESET}")
                    if self.registry.set_network_address(subkey, reg_value):
                        if self.system_ops.toggle_interface(name):
                            applied = True
                        else:
                            print(f"{BRIGHT_GREEN}[!] Toggle failed after registry write; reverting...{RESET}")
                            if self.restorer.original_registry_value:
                                self.registry.set_network_address(subkey, self.restorer.original_registry_value)
                            else:
                                self.registry.clear_network_address(subkey)
                else:
                    print(f"{BRIGHT_GREEN}[*] Registry subkey for adapter GUID not found; will try fallback.{RESET}")

            if not applied:
                print(f"{BRIGHT_GREEN}[*] Attempting netsh fallback (may be unsupported by some drivers)...{RESET}")
                if self.system_ops.netsh_fallback(name, mac_norm):
                    applied = True
                else:
                    print(f"{BRIGHT_GREEN}[!] Netsh fallback failed or unsupported.{RESET}")

            self.ui.flourish(duration=1.0)
            if applied:
                print(f"{BRIGHT_GREEN}[+] MAC change applied. Verify with getmac output:{RESET}\n")
                SystemOps.show_getmac()
            else:
                print(f"{BRIGHT_GREEN}[!] Failed to apply MAC change.{RESET}")
        finally:
            print(f"{BRIGHT_GREEN}[*] Restoring original MAC before exit...{RESET}")
            try:
                self.restorer.restore()
            except Exception as e:
                print(f"{BRIGHT_GREEN}[!] Error during restore:{RESET} {e}")
            self.ui.flourish(duration=1.4)
            print(f"{BRIGHT_GREEN}Shutting down matrix...{RESET}")
            time.sleep(0.6)


    @staticmethod
    def _prompt_choice(options: List[str], prompt: str) -> int:
        for idx, opt in enumerate(options, start=1):
            print(f"{BRIGHT_GREEN}{idx}{RESET}. {GREEN}{opt}{RESET}")
        while True:
            try:
                choice = input(f"{BRIGHT_GREEN}{prompt}{RESET} ").strip()
            except EOFError:
                return 0
            if not choice.isdigit():
                print(f"{BRIGHT_GREEN}[!] Enter the number of your choice.{RESET}")
                continue
            n = int(choice)
            if 1 <= n <= len(options):
                return n - 1
            print(f"{BRIGHT_GREEN}[!] Choose a number between 1 and {len(options)}.{RESET}")


if __name__ == "__main__":
    MacChanger().run()
