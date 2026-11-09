#!/usr/bin/env python3
"""
Flexible P15 print probe: choose GATT channel, pacing and preamble delay.

Usage:
    python3 tools/p15_probe_print.py --svc alt
    python3 tools/p15_probe_print.py --svc ff00 --preamble-delay 2
"""
import argparse
import os
import subprocess
import sys
import time

import dbus
import dbus.mainloop.glib
from gi.repository import GLib
from PIL import Image, ImageDraw, ImageFont

BLUEZ = "org.bluez"
ADAPTER = "/org/bluez/hci0"

CHANNELS = {
    "ff00": {
        "tx": "0000ff02-0000-1000-8000-00805f9b34fb",
        "rx": ["0000ff01-0000-1000-8000-00805f9b34fb"],
        "cx": "0000ff03-0000-1000-8000-00805f9b34fb",
    },
    "alt": {
        "tx": "49535343-8841-43f4-a8d4-ecbe34729bb3",
        "rx": ["49535343-1e4d-4bd9-ba61-23c647249616"],
        "cx": "49535343-aca3-481c-91ec-d85e28a60318",
    },
    "alt2": {
        "tx": "49535343-aca3-481c-91ec-d85e28a60318",
        "rx": ["49535343-1e4d-4bd9-ba61-23c647249616",
               "49535343-aca3-481c-91ec-d85e28a60318"],
        "cx": "49535343-1e4d-4bd9-ba61-23c647249616",
    },
    "vend": {
        "tx": "bef8d6c9-9c21-4c9e-b632-bd58c1009f9f",
        "rx": ["bef8d6c9-9c21-4c9e-b632-bd58c1009f9f"],
        "cx": None,
    },
}


def mm_dots(mm):
    return int(round(mm / 25.4 * 203))


def make_label():
    w, h = mm_dots(40), mm_dots(12)
    img = Image.new("L", (w, h), 255)
    d = ImageDraw.Draw(img)
    d.rectangle([1, 1, w - 2, h - 2], outline=0, width=2)
    fb = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 42)
    fs = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20)
    d.text((10, 2), "P15 OK", font=fb, fill=0)
    d.text((10, 52), "ALT channel", font=fs, fill=0)
    d.rectangle([w - 62, 46, w - 8, h - 6], fill=0)
    mono = img.convert("1", dither=Image.Dither.FLOYDSTEINBERG)
    return w, h, bytes(b ^ 0xFF for b in mono.tobytes())


def chunks_of(data, n):
    return [data[i:i + n] for i in range(0, len(data), n)]


class Probe:
    def __init__(self, mac, svc, packet, tick, preamble_delay, density):
        self.mac = mac
        self.cfg = CHANNELS[svc]
        self.packet = packet
        self.tick = tick
        self.preamble_delay = preamble_delay
        self.density = density
        self.dev_path = f"{ADAPTER}/dev_{mac.replace(':', '_')}"
        self.bus = dbus.SystemBus()
        self.loop = GLib.MainLoop()
        self.chars = {}
        self.result = None
        self.done = False
        self.credits = 0
        self.rx_log = []

    def props(self):
        return dbus.Interface(self.bus.get_object(BLUEZ, self.dev_path),
                              "org.freedesktop.DBus.Properties")

    def device(self):
        return dbus.Interface(self.bus.get_object(BLUEZ, self.dev_path),
                              "org.bluez.Device1")

    def connected(self):
        try:
            return bool(self.props().Get("org.bluez.Device1", "Connected"))
        except dbus.DBusException:
            return False

    def find_chars(self):
        om = dbus.Interface(self.bus.get_object(BLUEZ, "/"),
                            "org.freedesktop.DBus.ObjectManager")
        out = {}
        for p, ifs in om.GetManagedObjects().items():
            p = str(p)
            if p.startswith(self.dev_path + "/") and "org.bluez.GattCharacteristic1" in ifs:
                out[str(ifs["org.bluez.GattCharacteristic1"]["UUID"]).lower()] = p
        return out

    def ensure_link(self):
        self.chars = self.find_chars()
        if self.connected() and self.cfg["tx"] in self.chars:
            print("link ready")
            return
        if self.connected():
            try:
                self.device().Disconnect()
            except dbus.DBusException:
                pass
            time.sleep(1)
        print("creating LE link ...")
        r = subprocess.run(["sudo", "-n", "hcitool", "lecc", self.mac],
                           capture_output=True, text=True, timeout=20)
        print("  ", (r.stdout or r.stderr).strip())
        for _ in range(60):
            self.chars = self.find_chars()
            if self.cfg["tx"] in self.chars:
                return
            time.sleep(0.2)
        raise RuntimeError("GATT not ready")

    def ci(self, uuid):
        return dbus.Interface(self.bus.get_object(BLUEZ, self.chars[uuid]),
                              "org.bluez.GattCharacteristic1")

    def write(self, data, mode="command"):
        self.ci(self.cfg["tx"]).WriteValue(dbus.ByteArray(data),
                                           {"type": dbus.String(mode)})

    def on_props(self, iface, changed, invalidated, path=None):
        if "Value" in changed:
            data = bytes(changed["Value"])
            print(f"  [RX] {data.hex(' ')}", flush=True)
            if data[:1] in (b"\xaa", b"\x4f", b"\x4b"):
                self.result = "ok"
                GLib.timeout_add(300, self.quit)
            elif len(data) >= 2 and data[0] == 0x01:
                self.credits += data[1]
                print(f"  credits={self.credits}", flush=True)
            elif len(data) >= 3 and data[0] == 0x02:
                print(f"  mtu={(data[2] << 8) | data[1]}", flush=True)
        if "Connected" in changed and not changed["Connected"]:
            print("  link lost", flush=True)
            self.result = self.result or "disconnected"
            GLib.timeout_add(200, self.quit)

    def start(self, w, h, packed):
        for u in self.cfg["rx"]:
            if u in self.chars:
                try:
                    self.ci(u).StartNotify()
                    print("notify", u)
                except dbus.DBusException as e:
                    print("notify fail", u, e)
        if self.cfg["cx"] and self.cfg["cx"] in self.chars and self.cfg["cx"] not in self.cfg["rx"]:
            try:
                self.ci(self.cfg["cx"]).StartNotify()
                print("notify cx", self.cfg["cx"])
            except dbus.DBusException as e:
                print("notify cx fail", e)

        self.bus.add_signal_receiver(self.on_props,
                                     dbus_interface="org.freedesktop.DBus.Properties",
                                     signal_name="PropertiesChanged", bus_name=BLUEZ,
                                     path_keyword="path")

        bpr = (w + 7) // 8
        pre = bytearray()
        pre += bytes([0x1F, 0x70, 0x02, self.density])       # density
        pre += bytes([0x10, 0xFF, 0x10, 0x00, self.density]) # thickness
        pre += b"\x00" * 15                                   # wakeup
        pre += bytes([0x10, 0xFF, 0xF1, 0x02])                # enable

        body = bytearray([0x1D, 0x76, 0x30, 0x00,
                          bpr & 0xFF, bpr >> 8,
                          h & 0xFF, h >> 8])
        body += packed
        body += bytes([0x1D, 0x0C, 0x10, 0xFF, 0xF1, 0x45])

        self.stage = "pre"
        self.queue = chunks_of(bytes(pre), self.packet)
        self.body = chunks_of(bytes(body), self.packet)
        print(f"preamble {len(pre)}B, body {len(body)}B, packet={self.packet}, "
              f"tick={self.tick}ms, delay={self.preamble_delay}s")
        self.sent = 0
        GLib.timeout_add(200, self.tick_fn)
        self.loop.run()

    def tick_fn(self):
        if self.done:
            return False
        if not self.queue:
            if self.stage == "pre":
                print(f"preamble sent, waiting {self.preamble_delay}s ...", flush=True)
                self.stage = "body"
                self.queue = self.body
                self.sent = 0
                GLib.timeout_add(int(self.preamble_delay * 1000), self.tick_fn)
                return False
            print("all data sent", flush=True)
            GLib.timeout_add(15000, self.finish_timeout)
            return False
        try:
            self.write(self.queue.pop(0))
        except dbus.DBusException as e:
            print("write fail:", e, flush=True)
            self.result = "error"
            return self.quit()
        self.sent += 1
        if self.sent % 10 == 0:
            print(f"  sent {self.sent}", flush=True)
        return True

    def finish_timeout(self):
        if not self.done:
            self.result = self.result or "timeout"
            self.quit()
        return False

    def quit(self):
        self.done = True
        GLib.timeout_add(100, self.loop.quit)
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--svc", choices=CHANNELS, default="ff00")
    ap.add_argument("--mac", default="AA:BB:CC:DD:EE:FF")
    ap.add_argument("--packet", type=int, default=95)
    ap.add_argument("--tick", type=int, default=30)
    ap.add_argument("--preamble-delay", type=float, default=0.5)
    ap.add_argument("--density", type=int, default=2)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    w, h, packed = make_label()
    print(f"label {w}x{h}, {len(packed)}B")
    if args.dry_run:
        return 0

    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    p = Probe(args.mac, args.svc, args.packet, args.tick,
              args.preamble_delay, args.density)
    try:
        p.ensure_link()
        p.start(w, h, packed)
    finally:
        p.quit()
        time.sleep(0.3)
        try:
            p.device().Disconnect()
        except Exception:
            pass
    print("result:", p.result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
