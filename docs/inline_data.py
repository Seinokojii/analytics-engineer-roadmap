#!/usr/bin/env python3
"""Puts data.json into index.html between the data markers.

The page must open from file:// as well as from Pages, and fetch() is blocked
on file://, so the data travels inside the document.
"""
import pathlib, re

d = pathlib.Path(__file__).parent
html = (d / "index.html").read_text()
data = (d / "data.json").read_text().replace("</script", "<\\/script")
new, n = re.subn(r'(<script id="data" type="application/json">).*?(</script>)',
                 lambda m: m.group(1) + data + m.group(2), html, flags=re.S)
assert n == 1, "data markers not found"
(d / "index.html").write_text(new)
print(f"inlined {len(data) // 1024} KB into index.html ({len(new) // 1024} KB total)")
