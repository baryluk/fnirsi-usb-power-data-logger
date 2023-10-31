#!/usr/bin/env python3

import sys
import time

import usb.core
import usb.util
import configparser

#Import user settings
config = configparser.ConfigParser()
config.read('settings.ini')

#Global variables
is_fnb58_or_fnb48s = False


crc = None

if config['DEFAULT']['CRCCheck'] == 'yes':
    try:
        import crc
    except ModuleNotFoundError:
        print("Warning: crc package not found. crc checks will not be performed", file=sys.stderr)
        config['DEFAULT']['CRCCheck'] = 'no'

# FNB48
# Bus 001 Device 020: ID 0483:003a STMicroelectronics FNB-48
VID = 0x0483
PID_FNB48 = 0x003A

#  iManufacturer           1 FNIRSI
#  iProduct                2 FNB-48
#  iSerial                 3 0001A0000000

# C1
# Bus 001 Device 029: ID 0483:003b STMicroelectronics USB Tester
PID_C1 = 0x003B

# FNB58
VID_FNB58 = 0x2E3C
PID_FNB58 = 0x5558

# FNB48S
# Bus 001 Device 003: ID 2e3c:0049 FNIRSI USB Tester
VID_FNB48S = 0x2E3C
PID_FNB48S = 0x0049


def setup_crc():
    if crc is None:
        return None
    # $ ./reveng -w 8 -s $(shuf -n 100 /tmp/dump2.txt)
    # width=8  poly=0x39  init=0x42  refin=false  refout=false  xorout=0x00  check=0x4b  residue=0x00  name=(none)
    width = 8
    poly = 0x39
    init_value = 0x42
    final_xor_value = 0x00
    reverse_input = False
    reverse_output = False
    configuration = crc.Configuration(width, poly, init_value, final_xor_value, reverse_input, reverse_output)
    if hasattr(crc, "CrcCalculator"):  # crc 1.x
        crc_calculator = crc.CrcCalculator(configuration, use_table=True)
        return crc_calculator.calculate_checksum
    else:  # crc 2.x+
        calculator = crc.Calculator(configuration, optimized=True)
        return calculator.checksum

def find_device():
    dev = usb.core.find(idVendor=VID, idProduct=PID_FNB48)
    if dev is None:
        dev = usb.core.find(idVendor=VID, idProduct=PID_C1)
    if dev is None:
        dev = usb.core.find(idVendor=VID_FNB58, idProduct=PID_FNB58)
        if dev:
            is_fnb58_or_fnb48s = True
    if dev is None:
        dev = usb.core.find(idVendor=VID_FNB48S, idProduct=PID_FNB48S)
        if dev:
            is_fnb58_or_fnb48s = True
    return dev

def find_hid_interface_num(dev):
    # https://github.com/pyusb/pyusb/issues/76#issuecomment-118460796
    intf_hid = 0
    for cfg in dev:
        for interface in cfg:
            if interface.bInterfaceClass == 0x03:  # HID class
                return interface.bInterfaceNumber
                

def ensure_interface_not_busy(dev, interface_num):
    if dev.is_kernel_driver_active(interface_num):
        try:
            dev.detach_kernel_driver(interface_num)
        except usb.core.USBError as e:
            sys.exit(f"Could not detatch kernel driver from interface({interface_num}): {e}")

def print_configs(dev):
    for cfg in dev:
        print("cfg", cfg.bConfigurationValue, file=sys.stderr)
        for interface in cfg:
            print(
                "   ",
                "interface",
                interface.bInterfaceNumber,
                interface.bAlternateSetting,
                file=sys.stderr,
            )
            for ep in interface:
                print("         ", "ep", ep.bEndpointAddress, file=sys.stderr)

#global variables for decodee
temp_ema = None
energy = 0.0
capacity = 0.0

def decode(data, calculate_crc, time_interval):
    global energy
    global capacity
    alpha = 0.9  # smoothing factor for temperature
    temp_ema = None

    # Data is 64 bytes (64 bytes of HID data minus vendor constant 0xaa)
    # First byte is HID vendor constant 0xaa
    # Second byte is payload type:
    #    0x04 is data packet
    #    Other types (0x03 and maybe other ones) is unknown
    # Next 4 samples each 15 bytes. 60 bytes total.
    # At the end 2 bytes:
    #   1 byte is semi constant with unknown purpose.
    #   1 byte (last) is a 8-bit CRC checksum

    packet_type = data[1]
    if packet_type != 0x04:
        # ignore all non-data packets
        # print("Ignoring")
        return

    if calculate_crc:
        actual_checksum = data[-1]
        expected_checksum = calculate_crc(data[1:-1])
        if actual_checksum != expected_checksum:
            print(
                f"Ignoring packet of length {len(data)} with unexpected checksum. Expected: {expected_checksum:02x} Actual: {actual_checksum:02x}",
                file=sys.stderr,
            )
            return

    t0 = time.time() - 4 * time_interval
    for i in range(4):
        offset = 2 + 15 * i
        # 4 + 4 + 2 + 2 + 2 + 1 (unknown constant 1) = 15 bytes
        voltage = (
            data[offset + 3] * 256 * 256 * 256
            + data[offset + 2] * 256 * 256
            + data[offset + 1] * 256
            + data[offset + 0]
        ) / 100000
        current = (
            data[offset + 7] * 256 * 256 * 256
            + data[offset + 6] * 256 * 256
            + data[offset + 5] * 256
            + data[offset + 4]
        ) / 100000
        dp = (data[offset + 8] + data[offset + 9] * 256) / 1000
        dn = (data[offset + 10] + data[offset + 11] * 256) / 1000
        # unknown12 = data[offset + 12]  # ? constant 1  # some PD info?
        # It does not look to be a sign of current. I tried reversing
        # USB-C-In and USB-C-Out, which does reversed orientation of the
        # blue arrow for current on device screen, but unknown12 remains 1.
        # print(f"unknown{offset+12} {unknown12:02x}")
        temp_C = (data[offset + 13] + data[offset + 14] * 256) / 10.0
        if temp_ema is not None:
            temp_ema = temp_C * (1.0 - alpha) + temp_ema * alpha
        else:
            temp_ema = temp_C
        power = voltage * current
        # TODO(baryluk): This might be slightly inaccurate, if there is sampling jitter.
        energy += power * time_interval
        capacity += current * time_interval
        t = t0 + i * time_interval
        print(
            f"{t:.3f} {i} {voltage:7.5f} {current:7.5f} {dp:5.3f} {dn:5.3f} {temp_ema:6.3f} {energy:.6f} {capacity:.6f}"
        )
    # unknown62 = data[62]  # data[-2]
    # print(f"unknown62 {unknown:02x}")
    # print()



def main():
    dev = find_device()
    assert dev, "Device not found"

    
    dev.reset()
    
    #print_configs(dev)    

    interface_hid_num = find_hid_interface_num(dev)
    ensure_interface_not_busy(dev, interface_hid_num)    

    #If you check pyusb's code, this is not implemented
    #usb.util.claim_interface(dev, 0)

    # set the active configuration. With no arguments, the first
    # configuration will be the active one
    dev.set_configuration()

    # get an endpoint instance
    cfg = dev.get_active_configuration()
    intf = cfg[(interface_hid_num, 0)]

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

    #Setup communication with power meter
    ep_out.write(b"\xaa\x81" + b"\x00" * 61 + b"\x8e")
    ep_out.write(b"\xaa\x82" + b"\x00" * 61 + b"\x96")

    if is_fnb58_or_fnb48s:
        ep_out.write(b"\xaa\x82" + b"\x00" * 61 + b"\x96")
    else:
        ep_out.write(b"\xaa\x83" + b"\x00" * 61 + b"\x9e")


    # At the moment only 100 sps is supported
    sps = 100
    time_interval = 1.0 / sps
    crc_calculator = None
    if config['DEFAULT']['CRCCheck'] == 'yes':
        try:
            crc_calculator = setup_crc()  # can be None
        except Exception as e:
            print("When initializing crc module got exception: {e}, disabling crc checks", file=sys.stderr)
            crc_calculator = None
        
    print()  # Extra line to concatenation work better in gnuplot.
    print("timestamp sample_in_packet voltage_V current_A dp_V dn_V temp_C_ema energy_Ws capacity_As")

    time.sleep(0.1)
    refresh = 1.0 if is_fnb58_or_fnb48s else 0.003  # 1 s for FNB58 / FNB48S, 3 ms for others
    continue_time = time.time() + refresh
    terminate_execution = False
    
    while not terminate_execution:
        try:
            data = ep_in.read(size_or_buffer=64, timeout=1000)
            # print("".join([f"{x:02x}" for x in data]))
            decode(data, crc_calculator, time_interval)

            if time.time() >= continue_time:
                continue_time = time.time() + refresh
                #Why are we writing back to the device?
                ep_out.write(b"\xaa\x83" + b"\x00" * 61 + b"\x9e")
        except KeyboardInterrupt:
            terminate_execution = True


    while True:
        #Exhaust data in descriptor
        ep_in.read(size_or_buffer=64, timeout=1000)
        
        

if __name__ == "__main__":
    main()
