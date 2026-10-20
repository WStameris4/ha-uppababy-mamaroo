# UPPAbaby Mamaroo Smart Swing for Home Assistant

An unofficial Home Assistant integration for the **UPPAbaby Mamaroo Smart Swing**
(product 2001-MRO, which advertises as `mamaRoo5`). It talks to the swing directly
over Bluetooth Low Energy, through any Home Assistant Bluetooth adapter or proxy that
supports active connections. It uses no cloud and no account.

> **Status: early.** The protocol was decoded from the UPPAbaby Connect Android app
> (v1.0.2) and has not yet been verified against every swing setting. The motion names
> follow the order on the swing's panel, which is an assumption until confirmed.

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

Home Assistant then registers its own pairing ID. The swing may then forget the phone
app's pairing, so the UPPAbaby Connect app may need to be paired again.

## Entities

| Entity | What it does |
| --- | --- |
| Fan (the swing) | Motion on/off, speed 1–5 as a percentage, motion pattern (Cruise, Bounce, Sway, Rock, Wave) as a preset |
| Power switch | Turns the swing on or off |
| Sound switch | Turns the built-in sound on or off |
| Panel lock switch | Locks the touch panel |

State updates are pushed by the swing. Nothing is polled.

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
| `43 04 <n>` | Motion pattern |
| `43 05 <n>` | Sound track |
| `43 06 <n>` | Speed |
| `43 07 <n>` | Volume |
| `43 0A <u16>` | Shutdown timer |
| `43 0B <0/1>` | Panel lock |
| `DB <n>` | Start preset *n* |
| `53 …` | State report from the swing: motion, speed, sound, volume, power, motion on, sound on, timer, timer active, preset, panel lock |

## Disclaimer

This project is not affiliated with or endorsed by UPPAbaby. Mamaroo is a trademark
of its owner.
