"""BlueZ D-Bus GATT transport for the P15 with credit-based flow control.

The P15 advertises without the BR/EDR-not-supported flag, so bluetoothd's
Device1.Connect() picks BR/EDR and never exposes GATT.  We therefore create
the LE link with the small setcap helper p15-leconnect; BlueZ adopts that LE
connection and publishes the ff00 GATT service, which we use over D-Bus.

Notifications on ff03 are credits: [0x01, N].  One 95-byte packet is sent per
30 ms tick while credits > 0; after one second without credits one is forced
(starvation recovery, matching the vendor app).
"""

import os
import subprocess
import sys
import time

import dbus
import dbus.mainloop.glib
from gi.repository import GLib

BLUEZ = "org.bluez"
SERVICE = "0000ff00-0000-1000-8000-00805f9b34fb"
CH_RX = "0000ff01-0000-1000-8000-00805f9b34fb"
CH_TX = "0000ff02-0000-1000-8000-00805f9b34fb"
CH_CX = "0000ff03-0000-1000-8000-00805f9b34fb"


def _log(msg):
    print("DEBUG: " + msg, file=sys.stderr, flush=True)


def _err(msg):
    print("ERROR: " + msg, file=sys.stderr, flush=True)


class BleError(Exception):
    pass


class P15Printer:
    def __init__(self, mac, helper, adapter="hci0", packet=95, tick_ms=30,
                 connect_timeout=20, keep_alive=False):
        if not mac:
            raise BleError("no printer MAC configured; run pristar-p15-setup")
        self.mac = mac
        self.helper = helper
        self.adapter = adapter
        self.packet = packet
        self.tick_ms = tick_ms
        self.connect_timeout = connect_timeout
        self.keep_alive = keep_alive

        self.dev_path = f"/org/bluez/{adapter}/dev_{mac.replace(':', '_')}"
        self.bus = None
        self.loop = None
        self.chars = {}
        self.credits = 0
        self.last_credit = time.monotonic()
        self.mtu = None
        self.result = None
        self.done = False
        self.queue = []
        self.sent = 0
        self.total = 0
        self.waiting_result = False
        self._subscribed = False

    # ---------------------------------------------------------------- link
    def _props(self):
        return dbus.Interface(self.bus.get_object(BLUEZ, self.dev_path),
                              "org.freedesktop.DBus.Properties")

    def _device(self):
        return dbus.Interface(self.bus.get_object(BLUEZ, self.dev_path),
                              "org.bluez.Device1")

    def services_resolved(self):
        try:
            p = self._props()
            return (bool(p.Get("org.bluez.Device1", "Connected")) and
                    bool(p.Get("org.bluez.Device1", "ServicesResolved")))
        except dbus.DBusException:
            return False

    def find_chars(self):
        try:
            om = dbus.Interface(self.bus.get_object(BLUEZ, "/"),
                                "org.freedesktop.DBus.ObjectManager")
            objects = om.GetManagedObjects()
        except dbus.DBusException:
            return {}
        found = {}
        for path, ifaces in objects.items():
            path = str(path)
            if not path.startswith(self.dev_path + "/"):
                continue
            if "org.bluez.GattCharacteristic1" in ifaces:
                prop = ifaces["org.bluez.GattCharacteristic1"]
                found[str(prop["UUID"]).lower()] = (
                    path, [str(f) for f in prop.get("Flags", [])])
        return found

    def _run_helper(self):
        if not os.path.exists(self.helper):
            raise BleError(f"LE helper not found: {self.helper}")
        _log(f"running {self.helper} {self.mac}")
        try:
            r = subprocess.run([self.helper, self.mac],
                               capture_output=True, text=True, timeout=30)
        except subprocess.TimeoutExpired:
            raise BleError("LE helper timed out")
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        if out:
            _log("helper: " + out.replace("\n", " | "))
        if r.returncode != 0:
            raise BleError(f"LE connect failed (exit {r.returncode})")
        self.last_credit = time.monotonic()

    def connect(self):
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus()
        self.loop = GLib.MainLoop()

        deadline = time.monotonic() + self.connect_timeout
        attempts = 0
        while time.monotonic() < deadline:
            self.chars = self.find_chars()
            if CH_TX in self.chars and self.services_resolved():
                break
            if attempts < 2:
                attempts += 1
                try:
                    self._run_helper()
                except BleError as e:
                    _log(str(e))
            time.sleep(0.15)
        else:
            raise BleError(
                "printer GATT not available. Is the printer on? "
                "If Bluetooth was busy, power-cycle the adapter once.")

        self._subscribe()
        # Give the printer a moment to grant the initial credits.
        self._wait_initial_credits(2.5)
        if self.credits == 0:
            # The vendor app starts with 4 credits; the printer's initial
            # [0x01, 4] is often sent before BlueZ publishes the GATT service.
            self.credits = 4
            self.last_credit = time.monotonic()
        _log(f"connected, {len(self.chars)} characteristics, "
             f"initial credits={self.credits}, mtu={self.mtu}")
        return self

    def _subscribe(self):
        if self._subscribed:
            return
        for uuid, (path, flags) in self.chars.items():
            if "notify" in flags or "indicate" in flags:
                try:
                    dbus.Interface(self.bus.get_object(BLUEZ, path),
                                   "org.bluez.GattCharacteristic1").StartNotify()
                except dbus.DBusException as e:
                    _log(f"notify {uuid} failed: {e}")
        self.bus.add_signal_receiver(
            self._on_props,
            dbus_interface="org.freedesktop.DBus.Properties",
            signal_name="PropertiesChanged", bus_name=BLUEZ,
            path_keyword="path")
        self._subscribed = True

    def _wait_initial_credits(self, timeout):
        deadline = time.monotonic() + timeout

        def check():
            if self.credits > 0 or time.monotonic() >= deadline:
                self.loop.quit()
                return False
            return True

        GLib.timeout_add(50, check)
        self.loop.run()

    def _on_props(self, iface, changed, invalidated, path=None):
        if path is not None and not str(path).startswith(self.dev_path):
            return
        if "Value" in changed:
            data = bytes(changed["Value"])
            if data:
                self._handle_notify(data)
        if "Connected" in changed and not changed["Connected"]:
            _log("link lost")
            if self.result is None:
                self.result = "disconnected"
            self._schedule_finish(200)

    def _handle_notify(self, data):
        first = data[0]
        if first in (0xAA, 0x4F, 0x4B):
            if self.sent >= self.total:
                self.result = "ok"
                self._schedule_finish(300)
            else:
                _log("early OK ignored")
        elif first == 0x01 and len(data) >= 2:
            self.credits += data[1]
            self.last_credit = time.monotonic()
        elif first == 0x02 and len(data) >= 3:
            self.mtu = (data[2] << 8) | data[1]
            _log(f"printer MTU {self.mtu}")
        elif first == 0xFF and len(data) >= 2:
            _log(f"printer status 0x{data[1]:02x}")

    # -------------------------------------------------------------- sending
    def send(self, stream, result_timeout=45, job_timeout=240):
        if not self.chars:
            raise BleError("not connected")
        self.queue = [stream[i:i + self.packet]
                      for i in range(0, len(stream), self.packet)]
        self.total = len(self.queue)
        self.sent = 0
        self.result = None
        self.done = False
        self.waiting_result = False
        self.last_credit = time.monotonic()
        _log(f"sending {len(stream)}B in {self.total} packets "
             f"({self.packet}B, {self.tick_ms}ms)")

        GLib.timeout_add(self.tick_ms, self._tick)
        GLib.timeout_add(job_timeout * 1000, self._job_timeout)
        self.loop.run()

        if self.result in ("ok", "disconnected"):
            return True
        if self.result == "timeout" and self.sent >= self.total:
            _err("no print confirmation after all data was sent; "
                 "treating as success")
            return True
        if self.result is None:
            _err("job finished without a result")
        return False

    def _tick(self):
        if self.done:
            return False
        if self.queue:
            if self.credits > 0:
                chunk = self.queue.pop(0)
                try:
                    dbus.Interface(
                        self.bus.get_object(BLUEZ, self.chars[CH_TX][0]),
                        "org.bluez.GattCharacteristic1"
                    ).WriteValue(dbus.ByteArray(chunk),
                                 {"type": dbus.String("command")})
                except dbus.DBusException as e:
                    _err(f"write failed: {e}")
                    self.result = "error"
                    return self._finish()
                self.credits -= 1
                self.last_credit = time.monotonic()
                self.sent += 1
                if self.sent % 20 == 0 or self.sent == self.total:
                    _log(f"sent {self.sent}/{self.total} credits={self.credits}")
            elif time.monotonic() - self.last_credit >= 1.0:
                _log("no credits, starvation recovery (+1)")
                self.credits = 1
                self.last_credit = time.monotonic()
            return True

        if not self.waiting_result:
            self.waiting_result = True
            _log("all data sent, waiting for print result")
            GLib.timeout_add(45000, self._result_timeout)
        return True

    def _result_timeout(self):
        if not self.done:
            self.result = self.result or "timeout"
            self._finish()
        return False

    def _job_timeout(self):
        if not self.done:
            _err("job timeout")
            self.result = self.result or "timeout"
            self._finish()
        return False

    def _schedule_finish(self, ms):
        if not self.done:
            GLib.timeout_add(ms, self._finish)

    def _finish(self):
        if not self.done:
            self.done = True
            GLib.timeout_add(100, self.loop.quit)
        return False

    # ------------------------------------------------------------ teardown
    def disconnect(self):
        if self.keep_alive:
            return
        try:
            self._device().Disconnect()
        except dbus.DBusException:
            pass
        except Exception:
            pass
