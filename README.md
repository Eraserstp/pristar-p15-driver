# Pristar P15 — CUPS driver for Linux

**English** | [Русский](README.ru.md)

A CUPS driver for the **Pristar P15** Bluetooth label printer (also sold as
Marklife P15 and compatible clones). After installation the printer appears as
a normal CUPS queue and is available in the print dialog of any application.

Tested on Linux Mint 22.3 (CUPS 2.4.7, cups-filters 2.0) with 40 × 12 mm
gap labels.

## Features

- Print from any application: LibreOffice, Chromium, GTK/Qt apps, `lp`/`lpr`.
- Label sizes from 22 × 12 mm to 50 × 15 mm (12–15 mm across the head).
- Print options: density (1–3), gap/continuous paper, dithering, feed length.
- Automatic CUPS queue creation at install time when the printer is already
  known to BlueZ.
- A small `cap_net_raw` helper instead of a root daemon.
- No vendor app, cloud account or pairing dance required.

## Requirements

- Linux with CUPS 2.4 and cups-filters (Linux Mint 21/22, Ubuntu 22.04/24.04).
- A Bluetooth LE adapter.
- The printer powered on, charged and not connected to a phone.
- Python 3 with `python3-dbus`, `python3-gi`, `python3-pil` (installed as
  package dependencies).

## Installation

Build the package from this repository:

```bash
make deb
sudo dpkg -i ../pristar-p15-driver_*.deb
sudo apt -f install
```

Or install a pre-built `.deb`:

```bash
sudo dpkg -i pristar-p15-driver_0.1.0_amd64.deb
sudo apt -f install
```

The package installs the filter, backend, PPD and the setcap helper, then runs
`pristar-p15-setup --auto`. If the printer is already visible to BlueZ, the
queue `Pristar-P15` is created. The queue is **not** made the system default.

If the printer was not known at install time, turn it on and run:

```bash
sudo pristar-p15-setup
```

The script finds a device whose name starts with `P15` (or `P12`, `P7`, …),
writes `/etc/pristar-p15.conf` and creates the queue.

## Usage

```bash
lp -d Pristar-P15 document.pdf
lp -d Pristar-P15 -o media=12x40mmRotated.Fullbleed -o P15Density=3 photo.png
lpstat -p Pristar-P15
```

In the print dialog choose **Pristar-P15** and the label size (40 × 12 mm by
default). All standard CUPS tools work: `lp`, `lpr`, `system-config-printer`,
the GNOME/KDE print dialogs and application-specific print pages.

### Label sizes

| PPD option | Size |
|---|---|
| `12x22mmRotated.Fullbleed` | 22 × 12 mm |
| `14x22mmRotated.Fullbleed` | 22 × 14 mm |
| `15x26mmRotated.Fullbleed` | 26 × 15 mm |
| `12x30mmRotated.Fullbleed` | 30 × 12 mm |
| `14x30mmRotated.Fullbleed` | 30 × 14 mm |
| `15x30mmRotated.Fullbleed` | 30 × 15 mm |
| `12x40mmRotated.Fullbleed` | 40 × 12 mm (default) |
| `14x40mmRotated.Fullbleed` | 40 × 14 mm |
| `15x40mmRotated.Fullbleed` | 40 × 15 mm |
| `15x50mmRotated.Fullbleed` | 50 × 15 mm |

The name uses the Adobe PPD convention (short side × long side, rotated);
the print dialog shows the familiar “40x12 mm”.

### Print options

| Option | Values | Default |
|---|---|---|
| `P15Density` | 1 (light), 2, 3 (dark) | 2 |
| `P15PaperType` | `Gap`, `Continuous` | `Gap` |
| `P15Dither` | `Threshold` (text), `FS` (photos), `None` | `Threshold` |
| `P15FeedDots` | 100, 150, 200 | 100 |

For 1-bit CUPS raster (the normal path) dithering is not applied; only the
mechanical head margins are cropped, so no stray dots appear around text.

## How it works

```
application → CUPS → pdftopdf → pdftoraster
           → p15-raster filter  (CUPS raster → L11 commands)
           → p15 backend        (device URI p15:///<MAC>)
           → p15-leconnect (cap_net_raw) → LE link
           → BlueZ D-Bus GATT → printer
```

- **p15-leconnect** creates the LE link at the HCI level. The P15 does not set
  the “BR/EDR Not Supported” advertisement flag, so BlueZ otherwise chooses
  BR/EDR and GATT never appears.
- **p15-raster** parses CUPS raster (RaS3, 1 bpp K), rotates the page 270°,
  applies the measured head margins and emits the L11 bitmap sequence.
- **p15** sends the stream over GATT with credit-based flow control
  (95-byte packets, 30 ms ticks, 1 s starvation recovery) and waits for the
  printer's `OK` (`0x4F 0x4B`).

Protocol notes: [docs/ANALYSIS.md](docs/ANALYSIS.md),
[REVERSE_ENGINEERING.md](https://github.com/tomLadder/thermoprint/blob/main/REVERSE_ENGINEERING.md).

## Credits

Many thanks to **[tomLadder](https://github.com/tomLadder)** for the
[thermoprint](https://github.com/tomLadder/thermoprint) project and its
[REVERSE_ENGINEERING.md](https://github.com/tomLadder/thermoprint/blob/main/REVERSE_ENGINEERING.md),
which documents the L11 protocol, BLE flow control and P15 specifics. This
driver is an independent CUPS implementation built on that knowledge.
thermoprint is MIT-licensed.

Thanks also to the Marklife/Pristar community for testing and reports.

## Troubleshooting

**Printer not found / “printer GATT not available”**

- The printer must be on, charged, nearby and not connected to a phone.
- Some Bluetooth controllers occasionally answer `Command Disallowed` after an
  LE disconnect. The helper cancels a pending create and retries; if it still
  fails, power-cycle the adapter once:

  ```bash
  bluetoothctl power off
  sleep 2
  bluetoothctl power on
  ```

- Check the helper capability:

  ```bash
  getcap /usr/lib/pristar-p15/p15-leconnect
  # expected: cap_net_raw=ep
  ```

**Job completes but nothing prints**

- Check `lpstat -p Pristar-P15 -l` and `lpstat -W completed -o`.
- CUPS logs:

  ```bash
  sudo journalctl -u cups -f
  sudo tail -f /var/log/cups/error_log
  ```

  Set `LogLevel debug` in `/etc/cups/cupsd.conf` to see filter/backend
  messages, then restart CUPS.

**Print is shifted or clipped at the edge**

This is the mechanical tolerance of the head. Margins are configured in
`/etc/pristar-p15.conf`:

```ini
[device]
mac = <MAC>
helper = /usr/lib/pristar-p15/p15-leconnect
head_margin = 2   ; blank dots each side across the head
feed_start = 2    ; blank dots at the leading edge
feed_end = 6      ; blank dots at the trailing edge
x_shift = 0       ; shift across the head, in dots
```

**Test without CUPS**

```bash
sudo /usr/lib/pristar-p15/p15-leconnect <MAC>
printf '' | /usr/lib/cups/backend/p15     # device discovery only
```

## Development

```bash
make test          # unit tests: protocol, raster, image
make deb           # build the Debian package
make install       # install the built package
```

Manual filter run:

```bash
PPD=ppd/pristar-p15.ppd /usr/lib/cups/filter/pdftoraster \
    1 user test 1 "Resolution=203dpi" label.pdf > /tmp/label.rast
PRISTAR_P15_LIB=src python3 src/filter/p15-raster \
    1 user test 1 "P15Density=2" /tmp/label.rast > /tmp/job.bin
```

Project layout:

```
src/pristar_p15/      protocol, raster parser, image pipeline, BLE transport
src/filter/p15-raster CUPS filter
src/backend/p15       CUPS backend
src/helper/           p15-leconnect (C, cap_net_raw)
src/cli/              pristar-p15-setup
ppd/                  PPD generator and generated PPD
debian/               Debian packaging
tests/                unit tests
tools/                hardware bring-up and diagnostic scripts
```

## Limitations

- Bluetooth LE only (the P15 has no USB port).
- One job at a time (the BLE link is serialised with a lock file).
- CUPS 2.4 / PPD drivers. CUPS 3.x removes PPD support; a PAPPL/IPP
  Everywhere variant is planned.
- Clone firmware may not send a print confirmation. If all data was sent, the
  job is treated as successful to avoid duplicate prints.

## License

MIT — see [LICENSE](LICENSE).
