/*
 * p15-leconnect - create an LE connection to a BLE device.
 *
 * The Pristar/Marklife P15 advertises without the "BR/EDR Not Supported" flag,
 * so BlueZ's select_conn_bearer() picks BR/EDR and GATT never comes up.
 * Creating the LE link at the HCI level makes BlueZ adopt it as an LE device
 * and expose its GATT services, which the CUPS backend then uses over D-Bus.
 *
 * Uses libbluetooth.so.3 via dlopen (the same path as hcitool), so no
 * libbluetooth headers are needed at build time.
 *
 * Requires CAP_NET_RAW:
 *     setcap cap_net_raw+ep /usr/lib/pristar-p15/p15-leconnect
 *
 * Usage: p15-leconnect [-d hciX] <AA:BB:CC:DD:EE:FF>
 * Exit: 0 = LE link created (or already present), 1 = failed.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

typedef struct {
    uint8_t b[6];
} __attribute__((packed)) bdaddr_t;

typedef int (*hci_open_dev_fn)(int dev_id);
typedef int (*hci_send_cmd_fn)(int dd, uint16_t ogf, uint16_t ocf,
                               uint8_t plen, void *param);
typedef int (*hci_close_dev_fn)(int dd);
typedef int (*hci_le_create_conn_fn)(int dd, uint16_t interval, uint16_t window,
                                     uint8_t initiator_filter,
                                     uint8_t peer_bdaddr_type,
                                     bdaddr_t peer_bdaddr,
                                     uint8_t own_bdaddr_type,
                                     uint16_t min_interval,
                                     uint16_t max_interval,
                                     uint16_t latency,
                                     uint16_t supervision_timeout,
                                     uint16_t min_ce_length,
                                     uint16_t max_ce_length,
                                     uint16_t *handle, int to);

static int parse_mac(const char *s, uint8_t out[6])
{
    unsigned int b[6];
    if (sscanf(s, "%x:%x:%x:%x:%x:%x",
               &b[0], &b[1], &b[2], &b[3], &b[4], &b[5]) != 6)
        return -1;
    for (int i = 0; i < 6; i++)
        out[i] = (uint8_t)b[i];
    return 0;
}

int main(int argc, char **argv)
{
    int dev_id = 0;
    const char *mac = NULL;

    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "-d") || !strcmp(argv[i], "--dev")) {
            if (++i >= argc) {
                fprintf(stderr, "p15-leconnect: -d needs a value\n");
                return 1;
            }
            dev_id = atoi(argv[i]);
        } else if (argv[i][0] == '-') {
            fprintf(stderr, "usage: p15-leconnect [-d hciX] <MAC>\n");
            return 1;
        } else {
            mac = argv[i];
        }
    }
    if (!mac) {
        fprintf(stderr, "usage: p15-leconnect [-d hciX] <MAC>\n");
        return 1;
    }

    uint8_t addr[6];
    if (parse_mac(mac, addr) < 0) {
        fprintf(stderr, "p15-leconnect: bad MAC '%s'\n", mac);
        return 1;
    }

    void *lib = dlopen("libbluetooth.so.3", RTLD_NOW);
    if (!lib) {
        fprintf(stderr, "p15-leconnect: dlopen: %s\n", dlerror());
        return 1;
    }
    hci_open_dev_fn open_dev = (hci_open_dev_fn)dlsym(lib, "hci_open_dev");
    hci_send_cmd_fn send_cmd = (hci_send_cmd_fn)dlsym(lib, "hci_send_cmd");
    hci_close_dev_fn close_dev = (hci_close_dev_fn)dlsym(lib, "hci_close_dev");
    hci_le_create_conn_fn create_conn =
        (hci_le_create_conn_fn)dlsym(lib, "hci_le_create_conn");
    if (!open_dev || !close_dev || !create_conn || !send_cmd) {
        fprintf(stderr, "p15-leconnect: libbluetooth symbols not found\n");
        return 1;
    }

    int dd = open_dev(dev_id);
    if (dd < 0) {
        fprintf(stderr, "p15-leconnect: hci_open_dev(%d): %s%s\n", dev_id,
                strerror(errno),
                errno == EPERM ? " (need cap_net_raw)" : "");
        return 1;
    }

    bdaddr_t peer;
    /* BlueZ bdaddr_t is little-endian: b[0] is the last printed octet. */
    for (int i = 0; i < 6; i++)
        peer.b[i] = addr[5 - i];

    /*
     * Some controllers (notably some Broadcom models) get stuck after a previous LE
     * link: they answer LE Create Connection with "Command Disallowed" until
     * a pending create is cancelled.  Cancel first, then retry a few times.
     */
    int rc = -1, err = 0;
    for (int attempt = 0; attempt < 3; attempt++) {
        fprintf(stderr, "p15-leconnect: attempt %d\n", attempt + 1);
        send_cmd(dd, 0x08, 0x000E, 0, NULL);   /* LE Create Connection Cancel */
        usleep(500000);
        errno = 0;
        rc = create_conn(dd, 0x0004, 0x0004, 0x00, 0x00, peer, 0x00,
                         0x000F, 0x000F, 0x0000, 0x0C80, 0x0001, 0x0001,
                         NULL, 15000);
        err = errno;
        fprintf(stderr, "p15-leconnect: create rc=%d errno=%d (%s)\n",
                rc, err, strerror(err));
        if (rc == 0)
            break;
        usleep(500000);
    }
    close_dev(dd);

    if (rc == 0) {
        printf("LE link ready\n");
        return 0;
    }

    /*
     * EIO usually means the controller returned Command Disallowed (already
     * connected) or a connection attempt is in flight. Let the caller verify
     * via BlueZ GATT; report success so it can wait for ServicesResolved.
     */
    if (err == EIO) {
        printf("LE link already present or in progress\n");
        return 0;
    }

    fprintf(stderr, "p15-leconnect: hci_le_create_conn: %s\n", strerror(err));
    return 1;
}
