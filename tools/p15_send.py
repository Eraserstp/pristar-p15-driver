#!/usr/bin/env python3
"""
Generic P15 diagnostic sender.

Connects over LE, subscribes to every notify/indicate characteristic,
sends the given hex commands, then logs all notifications for a while.

Usage:
    python3 tools/p15_send.py --wait 8 10FFF102 000000000000000000000000000000 1F2000
"""
import argparse
import subprocess
import sys
import time

import dbus
import dbus.mainloop.glib
from gi.repository import GLib

BLUEZ = "org.bluez"
ADAPTER = "/org/bluez/hci0"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("hex_cmds", nargs="*", help="hex strings to send, in order")
    ap.add_argument("--mac", default="AA:BB:CC:DD:EE:FF")
    ap.add_argument("--wait", type=float, default=8.0, help="listen seconds after last cmd")
    ap.add_argument("--gap", type=float, default=0.6, help="delay between commands")
    ap.add_argument("--packet", type=int, default=95)
    ap.add_argument("--mode", choices=["command", "request"], default="command")
    ap.add_argument("--no-disconnect", action="store_true")
    args = ap.parse_args()

    dev_path = f"{ADAPTER}/dev_{args.mac.replace(':', '_')}"
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    loop = GLib.MainLoop()

    def device():
        return dbus.Interface(bus.get_object(BLUEZ, dev_path), "org.bluez.Device1")

    def props():
        return dbus.Interface(bus.get_object(BLUEZ, dev_path),
                              "org.freedesktop.DBus.Properties")

    def find_chars():
        om = dbus.Interface(bus.get_object(BLUEZ, "/"),
                            "org.freedesktop.DBus.ObjectManager")
        out = {}
        for p, ifs in om.GetManagedObjects().items():
            p = str(p)
            if p.startswith(dev_path + "/") and "org.bluez.GattCharacteristic1" in ifs:
                pr = ifs["org.bluez.GattCharacteristic1"]
                out[str(pr["UUID"]).lower()] = (p, [str(f) for f in pr.get("Flags", [])])
        return out

    chars = find_chars()
    if not chars:
        print("no GATT; creating LE link ...")
        if props().Get("org.bluez.Device1", "Connected"):
            device().Disconnect()
            time.sleep(1)
        r = subprocess.run(["sudo", "-n", "hcitool", "lecc", args.mac],
                           capture_output=True, text=True, timeout=15)
        print(" ", (r.stdout or r.stderr).strip())
        for _ in range(60):
            chars = find_chars()
            if chars:
                break
            time.sleep(0.2)
    if not chars:
        print("GATT not available")
        return 1

    print("characteristics:")
    for u, (p, f) in chars.items():
        print(f"  {u}  {f}")

    log = []

    def on_props(iface, changed, invalidated, path=None):
        if "Value" in changed:
            data = bytes(changed["Value"])
            ts = time.strftime("%H:%M:%S")
            print(f"[RX {ts}] {data.hex(' ')}  ({len(data)}B)  {path.split('/')[-1]}",
                  flush=True)
            log.append(data)
        if "Connected" in changed and not changed["Connected"]:
            print("link lost", flush=True)

    bus.add_signal_receiver(on_props, dbus_interface="org.freedesktop.DBus.Properties",
                            signal_name="PropertiesChanged", bus_name=BLUEZ,
                            path_keyword="path")

    subscribed = []
    for u, (p, f) in chars.items():
        if "notify" in f or "indicate" in f:
            try:
                dbus.Interface(bus.get_object(BLUEZ, p),
                               "org.bluez.GattCharacteristic1").StartNotify()
                subscribed.append(u)
                print("notify", u)
            except dbus.DBusException as e:
                print("notify fail", u, e)
    print(f"subscribed: {len(subscribed)}")

    tx = chars.get("0000ff02-0000-1000-8000-00805f9b34fb")
    if not tx:
        print("no ff02 TX")
        return 1
    tx_iface = dbus.Interface(bus.get_object(BLUEZ, tx[0]),
                              "org.bluez.GattCharacteristic1")

    # Give the printer a moment to emit something on its own.
    time.sleep(1.5)

    cmds = [bytes.fromhex(c) for c in args.hex_cmds]
    if not cmds:
        print(f"listening {args.wait}s ...")
        GLib.timeout_add(int(args.wait * 1000), lambda: (loop.quit(), False)[1])
        loop.run()
    else:
        def send_all():
            for c in cmds:
                for i in range(0, len(c), args.packet):
                    chunk = c[i:i + args.packet]
                    try:
                        tx_iface.WriteValue(dbus.ByteArray(chunk),
                                            {"type": dbus.String(args.mode)})
                        print(f"TX [{args.mode}] {chunk.hex(' ')}", flush=True)
                    except dbus.DBusException as e:
                        print("TX fail", e, flush=True)
                        loop.quit()
                        return False
                    time.sleep(0.03)
                time.sleep(args.gap)
            print(f"all sent, listening {args.wait}s ...")
            GLib.timeout_add(int(args.wait * 1000), lambda: (loop.quit(), False)[1])
            return False

        GLib.timeout_add(100, send_all)
        loop.run()

    print(f"notifications received: {len(log)}")
    if not args.no_disconnect:
        try:
            device().Disconnect()
        except dbus.DBusException:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
