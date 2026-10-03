# Stealth 700 Gen 3 battery — protocol notes

Reverse-engineered from **Turtle Beach Swarm II 1.0.0.57** on Windows, verified
against a Stealth 700 Gen 3 transmitter reporting USB id `10F5:2251`.

## The chip

The wireless transmitter (dongle) is an **Airoha** `ab156x` SoC. Its SDK string,
read back from the device, is `IoT_SDK_for_BT_Audio_V3.6.0.c38sp_1`. It speaks
the **RACE** protocol (the same family exposed by the public
[race-toolkit](https://github.com/auracast-research/race-toolkit)).

The transmitter exposes two HID collections on interface `MI_03`:

| Collection | Usage page | Use |
|-----------|------------|-----|
| COL01 | `0x000C` | consumer controls (volume keys) |
| COL02 | `0xFF13` | **RACE vendor channel** — this is the one we use |

Pick the channel by usage page `0xFF13` / usage `0x0001`, never by interface
number.

## RACE transport over HID

Host → device is HID **output report id `0x06`**, 62 bytes:

```
06  <len_lo> <len_hi>  <race bytes...>        (zero-padded to 62)
```

Device → host is read back as HID **input report id `0x07`** with the same
3-byte prefix. `len` is the number of RACE bytes that follow.

A RACE command:

```
05  5A  <len_lo> <len_hi>  <id_lo> <id_hi>  <payload...>
│   │   └── length = payload length + 2 (the two id bytes count)
│   └────── 0x5A = command, expects a response (0x5C = no response)
└────────── channel marker
```

A RACE response starts `05 5B …`; an indication (device-initiated) `05 5D …`.

Confirmed read-only commands (handy to check the link without touching state):

| id | meaning | reply payload |
|----|---------|---------------|
| `0x0301` | SDK version | `IoT_SDK_for_BT_Audio_V3.6.0…` |
| `0x1E08` | build version | `ab156x_evb … IoT_SDK…` |

## Battery is behind CoAP, not a plain command

The direct RACE "get battery" command (`0x0CD6`) exists but returns status `02`
on the Xbox/USB transmitter. Swarm II actually reads battery through a **CoAP
server running on the chip**, tunnelled inside RACE command **`0x9902`**
(`RACE_ID_USB_COAP`).

CoAP control commands (RACE ids):

| id | meaning |
|----|---------|
| `0x9942` | enable CoAP **client** |
| `0x9943` | disable CoAP client |
| `0x9950` | CoAP client/server status |
| `0x9940` / `0x9941` | enable / disable CoAP **server** |

### Reading status

1. Enable the CoAP client: `05 5A 02 00 42 99`.
2. Send a CoAP `GET` for a resource, tunnelled in RACE `0x9902`. The CoAP
   message is standard [RFC 7252](https://datatracker.ietf.org/doc/html/rfc7252):

   ```
   40 01 00 01  B3 47 53 49
   │  │  └┬──┘  └┬┘ └──┬───┘
   │  │   msgid  │     "GSI"  (Uri-Path value)
   │  │          └ option: Uri-Path (#11), length 3
   │  └ code 0.01 = GET
   └ ver 1, type CON, token length 0
   ```

   wrapped as `05 5A 05 00 02 99 40 01 00 01 B3 47 53 49`.
3. The device replies (one or more `0x9902` segments). After the `0xFF` CoAP
   payload marker the body is JSON.

### Resources

`GET /index` lists the resources:

```
["Dbg","Inf","GSI","BT","TX","Swm","Mic","NG","SHH","Enc","Btn","Prm",
 "AQG","AQM","CEC","CG1","CG2","CG3","CG4","CG5","CM1","CM2","CM3","CM4","CM5"]
```

`GET /GSI` (headset "general status info") returns, for example:

```json
{"OR":"GSI","KVP":{"200":"0","210":"0","220":"My Headset","230":"1",
 "240":"100","250":"0","260":"86","270":"0","280":"4","290":"0",
 "2a0":"64","2b0":"22","2c0":"50"}}
```

### GSI key meanings

Confirmed against the live device and Swarm II's default-value template embedded
in `STEALTH_700.dll`:

| key | meaning | notes |
|-----|---------|-------|
| `220` | device name | e.g. `My Headset` |
| `230` | connected | `1` = headset linked to the transmitter |
| `240` | **battery %** | matches Swarm II's "Battery Status"; default template = 100 |
| `250` | charging? | `0` seen while not charging — **not verified under charge** |
| `2c0` | "Signature Sound" preset | a red herring: *not* battery, despite the `2C0`/`12c0` strings sitting next to the battery tray-icon code |

Other resources carry the Bluetooth link (`BT`: `320` = RSSI as a signed byte)
and the transmitter (`TX`). They are not needed for battery.

## Scope and caveats

* Verified only on the Stealth 700 Gen 3 (`10F5:2251`). Sibling transmitters
  `10F5:2250` and `10F5:2253` share the firmware and almost certainly work, but
  are untested here.
* Reading only enables the CoAP client — exactly what Swarm II does on every
  poll. Nothing on the device is written or reconfigured.
* The `250` charging flag is a best guess; treat it as advisory.
