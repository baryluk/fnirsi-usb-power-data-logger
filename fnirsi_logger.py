#!/usr/bin/env python3

import usb.core
import usb.util
import sys
import time

# Bus 001 Device 020: ID 0483:003a STMicroelectronics FNB-48
VID = 0x0483
PID_FNB48 = 0x003A

# C1
# Bus 001 Device 029: ID 0483:003b STMicroelectronics USB Tester
PID_C1 = 0x003B


#  iManufacturer           1 FNIRSI
#  iProduct                2 FNB-48
#  iSerial                 3 0001A0000000


def main():
    # find our device
    dev = usb.core.find(idVendor=VID, idProduct=PID_FNB48)
    if dev is None:
        dev = usb.core.find(idVendor=VID, idProduct=PID_C1)
    assert dev, "Device not found"

    if False:
        print(dev, file=sys.stderr)

    dev.reset()

    # if dev.is_kernel_driver_active(0):
    #        try:
    #                dev.detach_kernel_driver(0)
    #        except usb.core.USBError as e:
    #                sys.exit("Could not detach kernel driver: ")

    # https://github.com/pyusb/pyusb/issues/76#issuecomment-118460796
    for cfg in dev:
        for intf in cfg:
            if dev.is_kernel_driver_active(intf.bInterfaceNumber):
                try:
                    dev.detach_kernel_driver(intf.bInterfaceNumber)
                except usb.core.USBError as e:
                    sys.exit(f"Could not detatch kernel driver from interface({intf.bInterfaceNumber}): {e}")

    usb.util.claim_interface(dev, 0)

    # set the active configuration. With no arguments, the first
    # configuration will be the active one

    if False:
        for cfg in dev:
            print("cfg", cfg.bConfigurationValue, file=sys.stderr)
            for intf in cfg:
                print(
                    "   ",
                    "intf",
                    intf.bInterfaceNumber,
                    intf.bAlternateSetting,
                    file=sys.stderr,
                )
                for ep in intf:
                    print("         ", "ep", ep.bEndpointAddress, file=sys.stderr)

    # dev.set_configuration(1)

    # get an endpoint instance
    cfg = dev.get_active_configuration()
    intf = cfg[(0, 0)]

    ep_out = usb.util.find_descriptor(
        intf,
        # match the first OUT endpoint
        custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT,
    )

    ep_in = usb.util.find_descriptor(
        intf,
        # match the first IN endpoint
        custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_IN,
    )

    assert ep_in
    assert ep_out

    ep_out.write(b"\xaa\x81" + b"\x00" * 61 + b"\x8e")
    ep_out.read(size_or_buffer=64)
    ep_out.write(b"\xaa\x82" + b"\x00" * 61 + b"\x96")
    ep_out.read(size_or_buffer=64)

    ep_out.write(b"\xaa\x83" + b"\x00" * 61 + b"\x9e")
    ep_out.read(size_or_buffer=64)

    alpha = 0.9  # smoothing factor for temperature
    temp_ema = None

    # At the moment only 100 sps is supported
    sps = 100
    time_interval = 1.0 / sps

    energy = 0.0
    capacity = 0.0

    first_data_point = True

    print()  # Extra line to concatenation work better in gnuplot.
    print("timestamp sample_in_packet voltage_V current_A dp_V dn_V temp_C_ema energy_Wh capacity_Ah")

    def decode(data):
        nonlocal temp_ema, energy, capacity, first_data_point

        # data is 63 bytes (64 bytes of HID data minus vendor constant 0xaa)
        # 4 samples each 15 bytes. 60 bytes total.
        # at the end 2 bytes of unknown purpose.
        # (one is semi constant, other is totally random)

        if first_data_point:
            first_data_point = False
            # Ignore first data point. It has garbage,
            # or something that we do not understand yet.
            return

        t0 = time.time() - 4 * time_interval
        for i in range(4):
            offset = 15 * i
            # 4 + 4 + 2 + 2 + 2 + 1 (unknown constant 1) = 15 bytes
            voltage = (
                data[offset + 4] * 256 * 256 * 256
                + data[offset + 3] * 256 * 256
                + data[offset + 2] * 256
                + data[offset + 1]
            ) / 100000
            current = (
                data[offset + 8] * 256 * 256 * 256
                + data[offset + 7] * 256 * 256
                + data[offset + 6] * 256
                + data[offset + 5]
            ) / 100000
            dp = (data[offset + 9] + data[offset + 10] * 256) / 1000
            dn = (data[offset + 11] + data[offset + 12] * 256) / 1000
            # data[13] ? constant 1
            temp_C = (data[offset + 14] + data[offset + 15] * 256) / 10.0
            if temp_ema is not None:
                temp_ema = temp_C * (1.0 - alpha) + temp_ema * alpha
            else:
                temp_ema = temp_C
            power = voltage * current
            energy += power * time_interval
            capacity += current * time_interval
            t = t0 + i * time_interval
            print(
                f"{t:.3f} {i} {voltage:7.5f} {current:7.5f} {dp:5.3f} {dn:5.3f} {temp_ema:6.3f} {energy:.6f} {capacity:.6f}"
            )

        # the purpose of data[62] is unknown. it appears fully random.

    # ep_in.write('')
    # data = dev.read(endpoint_in.bEndpointAddress, 64, 1000)

    time.sleep(0.1)
    continue_time = time.time()
    while True:
        data = ep_in.read(size_or_buffer=64, timeout=1000)
        decode(data[1:])

        if time.time() >= continue_time:
            continue_time = time.time() + 0.003  # 3 ms
            ep_out.write(b"\xaa\x83" + b"\x00" * 61 + b"\x9e")
            ep_out.read(size_or_buffer=64)

    # dev.write(0x81, 'test')  # write to a specific endnpoint explicitly


if __name__ == "__main__":
    main()
