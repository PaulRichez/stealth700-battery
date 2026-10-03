# stealth700-battery

Read the battery level of a **Turtle Beach Stealth 700 Gen 3** headset straight
from its USB wireless transmitter — **no Swarm II required**.

```console
$ stealth700-battery
My Headset: 100%
```

Swarm II is the only official way to see this headset's battery on a PC, and it
installs a background service, a driver and a tray app just to show one number.
This is a ~200-line, dependency-light reader of the same data, plus a drop-in
provider so the headset shows up in [HaloBattery](https://github.com/HeyOkay/HaloBattery)
next to your mouse and controller.

> The protocol was reverse-engineered from Swarm II 1.0.0.57 and is written up in
> [`docs/protocol.md`](docs/protocol.md). The reader only *reads* status (it
> enables the on-device CoAP client, exactly as Swarm II does); it never writes
> settings or firmware.

## Install

```bash
pip install hidapi
pip install .            # from a clone, or: pip install stealth700-battery
```

Requires Python 3.8+ and the Stealth 700 Gen 3 USB transmitter plugged in with
the headset switched on.

## Use

### Command line

```bash
stealth700-battery              # -> My Headset: 100%
stealth700-battery --json       # -> {"name": "My Headset", "battery": 100, ...}
stealth700-battery --watch 30   # refresh every 30 s until Ctrl-C
stealth700-battery --diagnose   # list HID collections and the raw status
```

(or `python -m stealth700_battery …` without installing)

### As a library

```python
from stealth700_battery import read_status, read_battery

print(read_battery())           # 100  (or None if the dongle is absent)

status = read_status()
if status:
    print(status.name, status.battery, status.connected, status.charging)
```

`read_status()` returns `None` when the transmitter isn't present. When the
transmitter is plugged in but the headset is off, it returns the last known
level with `connected=False`.

## HaloBattery integration

To get a tray icon for the headset in
[HaloBattery](https://github.com/HeyOkay/HaloBattery):

1. Copy [`halobattery/turtlebeach.py`](halobattery/turtlebeach.py) into
   HaloBattery's `providers/` folder.
2. Register it in `providers/__init__.py`:

   ```python
   from .turtlebeach import TurtleBeachProvider  # noqa: F401
   ```

3. Add `TurtleBeachProvider()` to the app's provider list.

The provider follows HaloBattery's own conventions (picks the collection by
usage page, keeps the last level while the headset sleeps, reports
`kind="headset"`), so the headset gets its own battery ring in the tray.

## How it works (short version)

The transmitter is an **Airoha** chip speaking the **RACE** protocol over a
vendor HID collection (usage page `0xFF13`). Battery lives behind a small
**CoAP** server on the chip; a `GET /GSI` tunnelled inside RACE command `0x9902`
returns JSON whose key `240` is the battery percent. Full details, framing and
the GSI key map are in [`docs/protocol.md`](docs/protocol.md).

## Scope & caveats

- Verified on the Stealth 700 Gen 3 (`10F5:2251`). Sibling transmitters
  `10F5:2250` and `10F5:2253` share the firmware and should work, but are
  untested here.
- The charging flag (`250`) is a best guess — treat it as advisory.
- Windows is the only platform tested. The protocol itself is OS-agnostic
  (`hidapi` works on Linux/macOS too), but discovery hasn't been checked there.

## Credits

- Protocol family and HID framing cross-checked against
  [auracast-research/race-toolkit](https://github.com/auracast-research/race-toolkit).
- Built to feed [HeyOkay/HaloBattery](https://github.com/HeyOkay/HaloBattery).

## License

MIT — see [`LICENSE`](LICENSE).
