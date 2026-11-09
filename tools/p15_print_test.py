#!/usr/bin/env python3
"""
Pristar P15 print test with proper credit-based flow control.

Protocol (L11):
  density -> wakeup -> enable -> raster bitmap -> feed-to-gap -> stop

Flow control (matches the official app and thermoprint):
  - printer sends [0x01, N] on ff03 to grant N credits;
  - send exactly one 95-byte packet per 30 ms tick while credits > 0;
  - if no credits for 1 s, force one (starvation recovery);
  - success: 0xAA / 0x4F / 0x4B on ff01, or a clean disconnect.
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
CH_RX = "0000ff01-0000-1000-8000-00805f9b34fb"
CH_TX = "0000ff02-0000-1000-8000-00805f9b34fb"
CH_CX = "0000ff03-0000-1000-8000-00805f9b34fb"

DPI = 203
WIDTH_MM = 40.0
HEIGHT_MM = 12.0
PACKET = 95
TICK_MS = 30
STARVATION_S = 1.0
DENSITY = 2


def mm_to_dots(mm):
    return int(round(mm / 25.4 * DPI))


def make_label(text="P15 OK", sub="Pristar 40x12mm", calibration=False, rotation=270,
               head_margin=2, x_shift=0, feed_start=2, feed_end=6):
    width = mm_to_dots(WIDTH_MM)      # 320 dots along the feed (40 mm)
    height = mm_to_dots(HEIGHT_MM)    # 96 dots across the head (12 mm)
    inner_w = width - feed_start - feed_end
    inner_h = height - 2 * head_margin
    inner = Image.new("L", (inner_w, inner_h), 255)
    d = ImageDraw.Draw(inner)
    d.rectangle([1, 1, inner_w - 2, inner_h - 2], outline=0, width=2)
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    if calibration:
        d.rectangle([0, 0, 15, 18], fill=0)
        d.rectangle([inner_w - 16, 0, inner_w - 1, 18], fill=0)
        d.rectangle([inner_w // 2 - 1, 0, inner_w // 2 + 1, 8], fill=0)
        d.text((20, 22), "LEFT", font=ImageFont.truetype(font_path, 28), fill=0)
        font_right = ImageFont.truetype(font_path, 28)
        right_w = d.textlength("RIGHT", font=font_right)
        d.text((inner_w - right_w - 8, 22), "RIGHT", font=font_right, fill=0)
        d.text((inner_w // 2 - 34, 54), "40 x 12", font=ImageFont.truetype(font_path, 20), fill=0)
        for x in range(20, inner_w - 10, 20):
            d.line([x, inner_h - 10, x, inner_h - 2], fill=0, width=1)
        for i, x in enumerate(range(0, inner_w, 80)):
            d.text((x + 2, inner_h - 26), str(i), font=ImageFont.truetype(font_path, 14), fill=0)
    else:
        d.text((10, 2), text, font=ImageFont.truetype(font_path, 42), fill=0)
        d.text((10, 52), sub, font=ImageFont.truetype(font_path, 18), fill=0)
        d.rectangle([inner_w - 62, 46, inner_w - 8, inner_h - 6], fill=0)

    img = Image.new("L", (width, height), 255)
    img.paste(inner, (feed_start, head_margin + x_shift))
    mono = img.convert("1", dither=Image.Dither.FLOYDSTEINBERG)
    # The P15 head is 12 mm (96 dots) wide; the label runs 40 mm along the feed.
    # Rotate the landscape page so width=96 (head) and height=320 (feed).
    rotated = mono.transpose(Image.Transpose.ROTATE_270 if rotation == 270
                             else Image.Transpose.ROTATE_90)
    packed = bytes(b ^ 0xFF for b in rotated.tobytes())
    return img, rotated, packed, rotated.width, rotated.height


def make_ruler(rotation=270):
    """Landscape ruler: horizontal lines every 4 dots along the 96-dot head axis."""
    width = mm_to_dots(WIDTH_MM)
    height = mm_to_dots(HEIGHT_MM)
    img = Image.new("L", (width, height), 255)
    d = ImageDraw.Draw(img)
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    small = ImageFont.truetype(font_path, 9)
    for y in range(0, height):
        if y % 4 == 0:
            d.line([0, y, width - 1, y], fill=0, width=1)
        if y % 8 == 0:
            d.text((1, max(0, y - 5)), str(y), font=small, fill=0)
    d.line([0, 0, width - 1, 0], fill=0, width=3)
    d.line([0, height - 1, width - 1, height - 1], fill=0, width=3)
    mono = img.convert("1", dither=Image.Dither.NONE)
    rotated = mono.transpose(Image.Transpose.ROTATE_270 if rotation == 270
                             else Image.Transpose.ROTATE_90)
    packed = bytes(b ^ 0xFF for b in rotated.tobytes())
    return img, rotated, packed, rotated.width, rotated.height


def build_preamble(density):
    out = bytearray()
    out += bytes([0x1F, 0x70, 0x02, density])        # density
    out += bytes([0x10, 0xFF, 0x10, 0x00, density])  # thickness
    out += b"\x00" * 15                               # wakeup
    out += bytes([0x10, 0xFF, 0xF1, 0x02])           # enable
    return bytes(out)


def build_body(packed, width, height):
    bpr = (width + 7) // 8
    out = bytearray([0x1D, 0x76, 0x30, 0x00,
                     bpr & 0xFF, (bpr >> 8) & 0xFF,
                     height & 0xFF, (height >> 8) & 0xFF])
    out += packed
    out += bytes([0x1D, 0x0C])                       # position to gap
    out += bytes([0x10, 0xFF, 0xF1, 0x45])           # stop
    return bytes(out)


def chunk(data, n):
    return [data[i:i + n] for i in range(0, len(data), n)]


class PrintJob:
    def __init__(self, mac, packet, tick, density, preamble_delay):
        self.mac = mac
        self.packet = packet
        self.tick_ms = tick
        self.density = density
        self.preamble_delay = preamble_delay
        self.dev_path = f"{ADAPTER}/dev_{mac.replace(':', '_')}"
        self.bus = dbus.SystemBus()
        self.loop = GLib.MainLoop()
        self.chars = {}
        self.credits = 0
        self.last_credit = time.monotonic()
        self.mtu = None
        self.result = None
        self.done = False
        self.state = "preamble"
        self.queue = []
        self.sent = 0
        self.total = 0
        self.preamble_bytes = 0
        self.body_start_at = 0.0
        self.waiting_result = False
        self.total_packets = 0

    # ---------- link ----------
    def props(self):
        return dbus.Interface(self.bus.get_object(BLUEZ, self.dev_path),
                              "org.freedesktop.DBus.Properties")

    def device(self):
        return dbus.Interface(self.bus.get_object(BLUEZ, self.dev_path),
                              "org.bluez.Device1")

    def find_chars(self):
        om = dbus.Interface(self.bus.get_object(BLUEZ, "/"),
                            "org.freedesktop.DBus.ObjectManager")
        out = {}
        for p, ifs in om.GetManagedObjects().items():
            p = str(p)
            if p.startswith(self.dev_path + "/") and "org.bluez.GattCharacteristic1" in ifs:
                pr = ifs["org.bluez.GattCharacteristic1"]
                out[str(pr["UUID"]).lower()] = (p, [str(f) for f in pr.get("Flags", [])])
        return out

    def ensure_link(self):
        self.chars = self.find_chars()
        try:
            connected = bool(self.props().Get("org.bluez.Device1", "Connected"))
        except dbus.DBusException:
            connected = False
        if self.chars and connected:
            return
        if connected:
            try:
                self.device().Disconnect()
            except dbus.DBusException:
                pass
            time.sleep(1)
        print("creating LE link ...")
        r = subprocess.run(["sudo", "-n", "hcitool", "lecc", self.mac],
                           capture_output=True, text=True, timeout=15)
        print(" ", (r.stdout or r.stderr).strip())
        for _ in range(60):
            self.chars = self.find_chars()
            try:
                connected = bool(self.props().Get("org.bluez.Device1", "Connected"))
            except dbus.DBusException:
                connected = False
            if CH_TX in self.chars and connected:
                return
            time.sleep(0.2)
        raise RuntimeError("GATT not ready")

    def ci(self, uuid):
        return dbus.Interface(self.bus.get_object(BLUEZ, self.chars[uuid][0]),
                              "org.bluez.GattCharacteristic1")

    # ---------- notifications ----------
    def on_props(self, iface, changed, invalidated, path=None):
        if "Value" in changed:
            data = bytes(changed["Value"])
            short = path.split("/")[-1]
            print(f"  [RX {time.strftime('%H:%M:%S')}] {data.hex(' ')} ({len(data)}B) {short}",
                  flush=True)
            if not data:
                return
            if data[0] in (0xAA, 0x4F, 0x4B):
                if self.sent >= getattr(self, "total_packets", 10 ** 9):
                    self.result = "ok"
                    self.schedule_finish(400)
                else:
                    print("  -> OK response before all data sent (ignored)", flush=True)
            elif len(data) >= 2 and data[0] == 0x01:
                self.credits += data[1]
                self.last_credit = time.monotonic()
            elif len(data) >= 3 and data[0] == 0x02:
                self.mtu = (data[2] << 8) | data[1]
                print(f"  -> MTU {self.mtu}", flush=True)
        if "Connected" in changed and not changed["Connected"]:
            print("  -> link lost (treat as finished)", flush=True)
            self.result = self.result or "disconnected"
            self.schedule_finish(200)

    def subscribe(self):
        for u, (p, flags) in self.chars.items():
            if "notify" in flags or "indicate" in flags:
                try:
                    self.ci(u).StartNotify()
                except dbus.DBusException as e:
                    print("notify fail", u, e)
        self.bus.add_signal_receiver(
            self.on_props, dbus_interface="org.freedesktop.DBus.Properties",
            signal_name="PropertiesChanged", bus_name=BLUEZ, path_keyword="path")

    # ---------- printing ----------
    def run(self, preamble, body):
        self.subscribe()
        # Wait briefly for the printer's initial credits ([0x01, 4]) and MTU.
        print("waiting for initial credits ...", flush=True)
        deadline = time.monotonic() + 3.0

        def wait_check():
            if self.credits > 0 or time.monotonic() >= deadline:
                self.loop.quit()
                return False
            return True

        GLib.timeout_add(50, wait_check)
        self.loop.run()
        print(f"initial credits: {self.credits}, MTU: {self.mtu}")

        self.pre_queue = chunk(preamble, self.packet)
        self.body_queue = chunk(body, self.packet)
        self.preamble_bytes = len(preamble)
        self.total = len(preamble) + len(body)
        self.total_packets = len(self.pre_queue) + len(self.body_queue)
        self.queue = self.pre_queue
        print(f"job {self.total}B = {self.total_packets} packets "
              f"of {self.packet}B (preamble {len(preamble)}B, body {len(body)}B)")

        GLib.timeout_add(self.tick_ms, self.tick)
        GLib.timeout_add(90000, self.finish_timeout)
        self.loop.run()

    def tick(self):
        if self.done:
            return False

        now = time.monotonic()

        if self.state == "preamble" and not self.queue:
            print(f"preamble sent, waiting {self.preamble_delay}s before bitmap", flush=True)
            self.state = "body"
            self.queue = self.body_queue
            self.body_start_at = now + self.preamble_delay
            return True

        if self.state == "body" and self.queue and now < self.body_start_at:
            return True

        if self.queue:
            if self.credits > 0:
                chunk_ = self.queue.pop(0)
                try:
                    self.ci(CH_TX).WriteValue(dbus.ByteArray(chunk_),
                                              {"type": dbus.String("command")})
                except dbus.DBusException as e:
                    print("write failed:", e, flush=True)
                    self.result = "error"
                    return self.finish()
                self.credits -= 1
                self.last_credit = time.monotonic()
                self.sent += 1
                if self.sent % 10 == 0 or self.sent == self.total_packets:
                    print(f"  sent {self.sent}/{self.total_packets} pkt, "
                          f"credits={self.credits}", flush=True)
            else:
                if time.monotonic() - self.last_credit >= STARVATION_S:
                    print("  no credits, starvation recovery (+1)", flush=True)
                    self.credits = 1
                    self.last_credit = time.monotonic()
            return True

        if not self.waiting_result:
            self.waiting_result = True
            print("data sent, waiting for print result ...", flush=True)
            GLib.timeout_add(30000, self.finish_timeout)
        return True

    def schedule_finish(self, ms):
        if not self.done:
            GLib.timeout_add(ms, self.finish)

    def finish_timeout(self):
        if not self.done:
            print("result timeout", flush=True)
            self.result = self.result or "timeout"
            self.finish()
        return False

    def finish(self):
        if not self.done:
            self.done = True
            GLib.timeout_add(100, self.loop.quit)
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mac", nargs="?", default="AA:BB:CC:DD:EE:FF")
    ap.add_argument("--packet", type=int, default=PACKET)
    ap.add_argument("--tick", type=int, default=TICK_MS)
    ap.add_argument("--density", type=int, default=DENSITY)
    ap.add_argument("--preamble-delay", type=float, default=0.5)
    ap.add_argument("--text", default="P15 OK")
    ap.add_argument("--sub", default="Pristar 40x12mm")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--calibration", action="store_true")
    ap.add_argument("--ruler", action="store_true")
    ap.add_argument("--rotate", type=int, choices=[90, 270], default=270)
    ap.add_argument("--head-margin", type=int, default=2,
                    help="blank dots each side across the head (12 mm axis)")
    ap.add_argument("--x-shift", type=int, default=0,
                    help="shift image across the head, dots")
    ap.add_argument("--feed-start", type=int, default=2,
                    help="blank dots at the leading edge (40 mm axis)")
    ap.add_argument("--feed-end", type=int, default=6,
                    help="blank dots at the trailing edge (40 mm axis)")
    args = ap.parse_args()

    if args.ruler:
        img, rotated, packed, w, h = make_ruler(args.rotate)
    else:
        img, rotated, packed, w, h = make_label(args.text, args.sub, args.calibration,
                                                args.rotate, args.head_margin, args.x_shift,
                                                args.feed_start, args.feed_end)
    if args.calibration:
        args.text, args.sub = "calibration", ""
    preamble = build_preamble(args.density)
    body = build_body(packed, w, h)
    outdir = os.path.join(os.path.dirname(__file__), "..", "out")
    os.makedirs(outdir, exist_ok=True)
    name = "ruler" if args.ruler else ("calibration" if args.calibration else "test_label")
    img.save(os.path.join(outdir, name + ".png"))
    rotated.save(os.path.join(outdir, name + "_rot" + str(args.rotate) + ".png"))
    with open(os.path.join(outdir, "test_job.bin"), "wb") as f:
        f.write(preamble + body)
    print(f"label {w}x{h} px, packed {len(packed)}B, job {len(preamble)+len(body)}B")
    if args.dry_run:
        return 0

    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    job = PrintJob(args.mac, args.packet, args.tick, args.density, args.preamble_delay)
    try:
        job.ensure_link()
        job.run(preamble, body)
    finally:
        job.done = True
        time.sleep(0.3)
        try:
            job.device().Disconnect()
        except Exception:
            pass
    print("result:", job.result)
    return 0 if job.result in ("ok", "disconnected") else 1


if __name__ == "__main__":
    sys.exit(main())
