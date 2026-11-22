"""Verify that a Windows executable contains an embedded application icon."""

from __future__ import annotations

import struct
import sys
from pathlib import Path

import pefile


RT_ICON = 3
RT_GROUP_ICON = 14


def _resource_payloads(pe: pefile.PE, resource_type_id: int) -> list[bytes]:
    directory = getattr(pe, "DIRECTORY_ENTRY_RESOURCE", None)
    if directory is None:
        return []

    payloads: list[bytes] = []
    for resource_type in directory.entries:
        if resource_type.id != resource_type_id or not hasattr(resource_type, "directory"):
            continue
        for resource_name in resource_type.directory.entries:
            if not hasattr(resource_name, "directory"):
                continue
            for language in resource_name.directory.entries:
                data = getattr(language, "data", None)
                if data is None:
                    continue
                payloads.append(pe.get_data(data.struct.OffsetToData, data.struct.Size))
    return payloads


def verify_icon(executable: Path) -> int:
    if not executable.is_file():
        raise FileNotFoundError(f"Executable not found: {executable}")

    pe = pefile.PE(str(executable), fast_load=True)
    try:
        pe.parse_data_directories(
            directories=[
                pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]
            ]
        )
        groups = _resource_payloads(pe, RT_GROUP_ICON)
        icons = _resource_payloads(pe, RT_ICON)

        valid_group = False
        frame_count = 0
        for payload in groups:
            if len(payload) < 6:
                continue
            reserved, resource_type, count = struct.unpack_from("<HHH", payload)
            if reserved == 0 and resource_type == 1 and count > 0:
                valid_group = True
                frame_count = max(frame_count, count)

        if not valid_group or not icons:
            raise RuntimeError(
                "No valid RT_GROUP_ICON/RT_ICON resources were found in the executable."
            )

        print(
            f"Verified embedded application icon: {executable.name} "
            f"({frame_count} icon sizes, {len(icons)} icon image resources)."
        )
        return 0
    finally:
        pe.close()


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: verify_windows_icon.py <path-to-exe>", file=sys.stderr)
        return 2
    try:
        return verify_icon(Path(sys.argv[1]))
    except Exception as exc:
        print(f"Application icon verification failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
