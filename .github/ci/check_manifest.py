"""CI: confirm each .exe is 64-bit and carries an asInvoker manifest (no UAC prompt)."""
import sys

import pefile

ok = True
for path in sys.argv[1:]:
    pe = pefile.PE(path, fast_load=True)
    pe.parse_data_directories(
        directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]])
    manifest = ""
    for entry in getattr(pe, "DIRECTORY_ENTRY_RESOURCE", None).entries:
        if entry.id != pefile.RESOURCE_TYPE["RT_MANIFEST"]:
            continue
        for name in entry.directory.entries:
            for lang in name.directory.entries:
                data = lang.data.struct
                manifest = pe.get_data(data.OffsetToData, data.Size).decode("utf-8", "replace")
    as_invoker = 'level="asInvoker"' in manifest
    is_64 = pe.FILE_HEADER.Machine == 0x8664
    print(f"{path}\n  64-bit: {is_64}\n  manifest present: {bool(manifest)}\n"
          f"  requestedExecutionLevel asInvoker: {as_invoker}")
    ok = ok and as_invoker and is_64
sys.exit(0 if ok else 1)
