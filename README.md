# UPPAbaby Mamaroo Smart Swing for Home Assistant

An unofficial Home Assistant integration for the **UPPAbaby Mamaroo Smart Swing**
(product 2001-MRO, which advertises as `mamaRoo5`). It talks to the swing directly
over Bluetooth Low Energy, through any Home Assistant Bluetooth adapter or proxy that
supports active connections. It uses no cloud and no account.

> **Status: early.** The protocol was decoded from the UPPAbaby Connect Android app
> (v1.0.2) and checked against a real swing for pairing, motion, speed, sound and
> volume, and the shutdown timer. Presets are not exposed yet.

> **Safety.** The swing is not designed for sleep or unsupervised use (see the UPPAbaby
> manual). Only start motion remotely when someone is with the baby.

## Why Bluetooth and not WiFi

The swing has WiFi, but only for its own cloud link, which powers the Alexa and Google
Home skills. The UPPAbaby Connect app sends every command over Bluetooth and never
talks to the swing on the local network. This integration does the same.

## Installation

1. In HACS, add this repository as a custom repository (category **Integration**) and
   download it.
2. Restart Home Assistant.
3. Home Assistant discovers the swing when one of your Bluetooth adapters or proxies can
   hear it. You can also add it from **Settings → Devices & services → Add integration →
   UPPAbaby Mamaroo Smart Swing**.

## Pairing

The swing accepts commands only from a client that has registered a pairing ID with it.
During setup:

1. Turn the swing on and put it in pairing mode by holding the music button.
2. Select **Submit** within 30 seconds.

Home Assistant then registers its own pairing ID. The swing keeps several pairing IDs,
so the UPPAbaby Connect app stays paired too.

## Bonding the Bluetooth proxy

Outside pairing mode, the swing asks every device that connects to bond with it (a
Bluetooth security request). A device that doesn't bond is disconnected 30 seconds
later. Phones bond when you accept the "Pair with mamaRoo5?" prompt.

Bond each Bluetooth proxy or adapter that Home Assistant uses to reach the swing, once:

- **Android-based proxies** (for example a tablet running a Bluetooth proxy app): accept
  the "Pairing request: mamaRoo5" prompt or notification that appears while Home
  Assistant is connected, or pair `mamaRoo5` under **Settings → Bluetooth → Pair new
  device**.

Once bonded, the link stays up. The bonded proxy also resolves the swing's rotating
private address to one stable address. Without a bond the integration still works, but it
reconnects every 30 seconds and can lose the swing for a minute or two when its address
changes.

## Entities

| Entity | What it does |
| --- | --- |
| Power switch | Turns the swing on or off |
| Motion switch | Starts or stops motion (powering the swing on first if needed) |
| Motion pattern select | Cruise, Bounce, Sway, Rock, Wave; choosing one starts it, like tapping its icon on the panel |
| Speed number | 1–5, like the panel's speed lights |
| Sound switch | Turns the built-in sound on or off (powering the swing on first if needed) |
| Sound track select | Jingle, Bliss, Chirp, Tide (the panel's sounds 1–4, named as in the UPPAbaby Connect app) |
| Volume number | 1–4, like the panel's volume lights |
| Timer number | Minutes until the swing stops; shows the time left while set, 0 when off; setting 0 cancels |
| Panel lock switch | Locks the touch panel |

The swing pushes its state about once a second. Nothing is polled.

The device page shows the firmware and hardware revision the swing reports over Bluetooth
(the Device Information service), read once after Home Assistant starts.

If a connection drops (for example through a proxy that isn't bonded, see above), the
integration reconnects in 2–3 seconds. Entities keep their state through that gap, and a
command sent during it waits for the reconnect.

## Raw commands

`mamaroo.send_command` writes raw bytes, as hex, to the swing's control
characteristic. It is useful for protocol work. Turn on debug logging for
`custom_components.mamaroo` to see every byte sent and received.

## Protocol notes

All traffic goes through a single characteristic,
`622d0101-2416-0fa7-e132-2f1495cc2ce0`, in service
`622d0100-2416-0fa7-e132-2f1495cc2ce0` (write and notify). Replies start with the
opcode they answer.

| Bytes | Meaning |
| --- | --- |
| `B0` | Read the swing's Bluetooth ID; reply `B0 <status> <16-byte id>` |
| `B2 00` | Open a new pairing; the swing replies `B1 01` asking for a pairing ID |
| `B1 01 <16-byte uuid>` | Register a pairing ID; result arrives as `B3 xx 00` |
| `B2 01 <16-byte uuid>` | Handshake with a stored pairing ID after connecting: send `B0` first and wait for the swing's `B2 01` prompt; result `B3 xx 00` |
| `43 01 <0/1>` | Power |
| `43 02 <0/1>` | Motion on/off |
| `43 03 <0/1>` | Sound on/off |
| `43 04 <n>` | Motion pattern, 1–5 = the panel's icons left to right |
| `43 05 <n>` | Sound track: 1 Jingle, 2 Bliss, 3 Chirp, 4 Tide |
| `43 06 <n>` | Speed, 1–5 |
| `43 07 <n>` | Volume, 1–4 |
| `43 0A <n>` | Shutdown timer, *n* minutes (one byte); `00` cancels |
| `43 0B <0/1>` | Panel lock |
| `DB <n>` | Start preset *n* (untested) |
| `DC <n>` | Read preset *n*; reply `DC <status> <motion> <speed> <sound> <volume> …`, status 0 = saved, 1 = empty |
| `41 …` | The swing's acknowledgement of a `43` write, in the same layout as `53` |
| `53 …` | State report, about once a second: motion, speed, sound, volume, power, motion on, sound on, timer (seconds left, big-endian u16 at bytes 10–11), timer active, preset, panel lock |

## Disclaimer

This project is not affiliated with or endorsed by UPPAbaby. Mamaroo is a trademark
of its owner.
