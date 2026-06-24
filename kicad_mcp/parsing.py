"""Netlist and PCB parsing helpers.

Author: Henry Dang
Email: phuongminh.dang@gmail.com
"""

import re


POWER_NET_HINTS = ("vcc", "vdd", "gnd", "pgnd", "agnd", "dgnd", "+", "-", "vbus", "batt", "3v3", "1v8", "5v", "pwr")


def extract_schematic_net_names(netlist_content: str) -> set[str]:
    """Extract net names from a KiCad S-expression netlist export."""
    pattern = r'\(net\s+\(code\s+"[^"]+"\)\s+\(name\s+"([^"]+)"\)'
    return set(re.findall(pattern, netlist_content))


def extract_pcb_net_names(pcb_content: str) -> set[str]:
    """Extract net names from a .kicad_pcb file (KiCad 9 numeric IDs and KiCad 10 names)."""
    names = set(re.findall(r'\(net\s+\d+\s+"([^"]+)"\)', pcb_content))
    names.update(re.findall(r'\(net\s+"([^"]+)"\)', pcb_content))
    return names


def classify_nets(nets: set[str]) -> tuple[list[str], list[str]]:
    power_nets: list[str] = []
    signal_nets: list[str] = []

    for net in sorted(nets):
        net_lower = net.lower()
        if any(hint in net_lower for hint in POWER_NET_HINTS):
            power_nets.append(net)
        else:
            signal_nets.append(net)

    return power_nets, signal_nets


def is_auto_unconnected_net(net_name: str) -> bool:
    return net_name.startswith("unconnected-") or net_name.startswith("unconnected (")


def summarize_violation_report(content: str, clean_markers: tuple[str, ...]) -> bool:
    return all(marker in content for marker in clean_markers)
