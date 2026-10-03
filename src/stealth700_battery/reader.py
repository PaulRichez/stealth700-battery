"""Read a Turtle Beach Stealth 700 Gen 3 battery level over USB, without Swarm II.

Reverse-engineered from Turtle Beach Swarm II 1.0.0.57. See ``docs/protocol.md``
for the full write-up. Short version:

The wireless transmitter is an Airoha chip that speaks the **RACE** protocol over
a vendor HID collection (usage page ``0xFF13``). Device status (battery, name,
connection, audio settings) lives behind a small **CoAP** server on the chip;
Swarm II reads it with CoAP GET requests tunnelled inside RACE command ``0x9902``.

Transport framing — HID output report, report id ``0x06``::

    06 <len_lo> <len_hi> <race bytes...>        (padded to 62 bytes)

Replies arrive as HID input report id ``0x07`` with the same ``07 len_lo len_hi``
prefix.

A RACE command is ``05 5A <len_lo> <len_hi> <id_lo> <id_hi> <payload...>`` where
``0x5A`` means "command, expects a response" and the length counts the two id
bytes plus the payload. A RACE response starts ``05 5B``.

Reading status is three steps:

1. enable the CoAP client — RACE id ``0x9942`` (``05 5A 02 00 42 99``)
2. CoAP ``GET /GSI`` tunnelled in RACE id ``0x9902``::

       CoAP: 40 01 00 01  B3 'G' 'S' 'I'       (GET, Uri-Path "GSI")
       RACE: 05 5A 05 00  02 99  <coap...>

3. the reply payload is JSON::

       {"OR":"GSI","KVP":{"220":"My Headset","230":"1","240":"100", ...}}

   where key ``240`` is the headset battery percent, ``230`` the connection
   flag and ``220`` the name.

Only the CoAP client is enabled — exactly what Swarm II does. Nothing on the
device is written or reconfigured.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import List, Optional

import hid

# --- device identity -------------------------------------------------------
VENDOR_ID = 0x10F5                      # Turtle Beach / Voyetra
# Known Stealth 700 Gen 3 transmitters (from Swarm II's Update.ini).
TRANSMITTER_PIDS = {
    0x2250: "Stealth 700 Gen 3 transmitter",
    0x2251: "Stealth 700 Gen 3 transmitter",
    0x2253: "Stealth 700 Gen 3 transmitter",
}
# The RACE channel is the Airoha vendor HID collection, identified by its usage
# (never by interface number, which is not part of the protocol).
RACE_USAGE_PAGE = 0xFF13
RACE_USAGE = 0x0001

# --- framing ---------------------------------------------------------------
HID_REPORT_SIZE = 62
OUT_REPORT_ID = 0x06
IN_REPORT_ID = 0x07

RACE_CMD = 0x5A                         # command, expects a response
RACE_RSP = 0x5B                         # response marker
RACE_ID_COAP_CLIENT_ENABLE = 0x9942     # enable the on-device CoAP client
RACE_ID_USB_COAP = 0x9902               # tunnel carrying CoAP messages

COAP_GET = 0x01                         # CoAP method code: GET
STATUS_RESOURCE = "GSI"                 # headset "general status info"

# CoAP KVP keys inside the GSI resource.
KEY_NAME = "220"
KEY_CONNECTED = "230"
KEY_BATTERY = "240"
KEY_CHARGING = "250"                    # observed 0 when not charging (unverified under charge)


@dataclass
class HeadsetStatus:
    """A snapshot of the headset as reported by its transmitter."""
    name: str
    battery: int                        # 0..100
    connected: bool
    charging: bool


def _coap_get(path: str) -> bytes:
    """Build a minimal CoAP GET request for a single-segment Uri-Path."""
    # Ver=1, Type=CON, TKL=0 -> 0x40 ; code 0.01 (GET) ; message id 0x0001.
    # One Uri-Path option (number 11): delta 11, length = len(path).
    option = bytes([0xB0 | len(path)]) + path.encode("ascii")
    return bytes([0x40, COAP_GET, 0x00, 0x01]) + option


def _race(cmd_id: int, payload: bytes = b"") -> bytes:
    length = len(payload) + 2           # the length field counts the 2 id bytes
    return bytes([0x05, RACE_CMD, length & 0xFF, (length >> 8) & 0xFF,
                  cmd_id & 0xFF, (cmd_id >> 8) & 0xFF]) + payload


def _find_transmitter():
    """Return (path, product_name) for the RACE vendor collection, or (None, "")."""
    for info in hid.enumerate(VENDOR_ID, 0):
        if info.get("usage_page") == RACE_USAGE_PAGE and info.get("usage") == RACE_USAGE:
            # The USB product string is the real model, e.g. "Stealth 700X Gen 3".
            product = (info.get("product_string") or "").strip()
            name = product or TRANSMITTER_PIDS.get(info.get("product_id"), "Turtle Beach headset")
            return info["path"], name
    return None, ""


def find_transmitter_path() -> Optional[bytes]:
    """Return the HID path of the RACE vendor collection, or None if absent."""
    return _find_transmitter()[0]


class _Channel:
    """One open RACE conversation with the transmitter."""

    def __init__(self, path: bytes):
        self._dev = hid.device()
        self._dev.open_path(path)

    def close(self) -> None:
        try:
            self._dev.close()
        except Exception:
            pass

    def _write(self, race: bytes) -> None:
        buf = [OUT_REPORT_ID, len(race) & 0xFF, (len(race) >> 8) & 0xFF] + list(race)
        buf += [0] * (HID_REPORT_SIZE - len(buf))
        self._dev.write(buf)

    def _read_once(self) -> bytes:
        rep = self._dev.get_input_report(IN_REPORT_ID, HID_REPORT_SIZE)
        if not rep:
            return b""
        rep = bytes(rep)
        length = int.from_bytes(rep[1:3], "little")
        return rep[3:3 + length] if length else b""

    def _drain(self, times: int = 5) -> None:
        for _ in range(times):
            self._read_once()

    def coap_get_json(self, path: str, attempts: int = 30) -> Optional[dict]:
        """Enable CoAP, GET a resource and return its parsed JSON payload."""
        self._drain()
        self._write(_race(RACE_ID_COAP_CLIENT_ENABLE))
        time.sleep(0.3)
        self._drain()

        coap = _coap_get(path)
        self._write(_race(RACE_ID_USB_COAP, coap))

        blob = b""
        for _ in range(attempts):
            blob += self._read_once()
            time.sleep(0.03)

        match = re.search(rb"\{.*\}", blob, re.S)
        if not match:
            return None
        try:
            return json.loads(match.group().decode("utf-8", "replace"))
        except ValueError:
            return None


def read_status() -> Optional[HeadsetStatus]:
    """Read the headset status, or None if the transmitter is not present.

    A present transmitter with the headset switched off returns a status with
    ``connected=False`` and the last known battery level.
    """
    path, product_name = _find_transmitter()
    if path is None:
        return None

    chan = _Channel(path)
    try:
        doc = chan.coap_get_json(STATUS_RESOURCE)
    finally:
        chan.close()

    if not doc:
        return None
    kvp = doc.get("KVP", {})
    if KEY_BATTERY not in kvp:
        return None

    try:
        battery = int(kvp[KEY_BATTERY])
    except (TypeError, ValueError):
        return None

    # Prefer the transmitter's real USB product string over the on-device
    # nickname (GSI key 220), which defaults to the generic "My Headset".
    name = product_name or kvp.get(KEY_NAME) or "Turtle Beach headset"
    return HeadsetStatus(
        name=name,
        battery=max(0, min(100, battery)),
        connected=kvp.get(KEY_CONNECTED) == "1",
        charging=kvp.get(KEY_CHARGING) == "1",
    )


def read_battery() -> Optional[int]:
    """Convenience: just the battery percent, or None if unavailable."""
    status = read_status()
    return status.battery if status else None


def diagnostics() -> List[str]:
    """Human-readable lines describing what is visible on the bus."""
    lines: List[str] = []
    infos = hid.enumerate(VENDOR_ID, 0)
    lines.append(f"Turtle Beach (VID {VENDOR_ID:#06x}) HID collections: {len(infos)}")
    for info in infos:
        lines.append(
            f"  pid={info.get('product_id'):#06x} "
            f"usage={info.get('usage_page'):#06x}:{info.get('usage'):#06x}"
        )
    status = read_status()
    if status is None:
        lines.append("No status (transmitter absent or no GSI reply).")
    else:
        lines.append(
            f"{status.name}: {status.battery}% "
            f"(connected={status.connected}, charging={status.charging})"
        )
    return lines
