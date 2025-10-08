# Windows_MAC_Changer

Windows-only Wi‑Fi MAC changer with a Matrix-style terminal UI, registry-level spoofing (NetworkAddress) and fallback via `netsh`.  
This tool discovers Wi‑Fi adapters, lets the user select one, accepts a manual MAC (validated) or generates a random unicast MAC, applies the change, and restores the original MAC before exiting. It also attempts a safe restore on interrupts.

> WARNING: Run as Administrator. Use only on systems and networks you own or are explicitly authorized to test.

## Features
- Matrix-style terminal animations for boot, action, and exit
- Discover Wi‑Fi adapters via PowerShell or netsh
- Registry-level MAC spoofing (NetworkAddress) when supported by driver
- netsh fallback attempt
- Snapshot and restore original MAC automatically and on signals (SIGINT/SIGTERM)
- OOP design for maintainability

## Requirements
- Windows 10/11
- Python 3.8+
- Run the script from an elevated (Administrator) command prompt
- PowerShell recommended (script falls back to netsh if not available)

## Usage
1. Clone the repository:
   ```powershell
   git clone https://github.com/Kaizencabal/Windows_MAC_Changer.git
   cd Windows_MAC_Changer
