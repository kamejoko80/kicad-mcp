import re
from pathlib import Path

base = Path(r"C:/Users/NCPC/AppData/Local/Temp/kicad_fp_layers")
for name in ["all", "minimal", "fab_only"]:
    svg = (base / name / "SOT65P210X110-6N.svg").read_text(encoding="utf-8", errors="replace")
    fills = sorted(set(re.findall(r'fill="([^"]+)"', svg)))
    opacities = sorted(set(re.findall(r'opacity="([^"]+)"', svg)))
    paths = svg.count("<path")
    print(name, "paths", paths, "fills", fills, "opacities", opacities)
