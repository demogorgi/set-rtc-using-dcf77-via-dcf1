# Micropython script to set the rtc time to the time sent by a DCF1 receiver
# module: https://www.pollin.de/p/dcf-77-empfangsmodul-dcf1-810054
# The DCF1 module receives the DCF77 signal, see https://en.wikipedia.org/wiki/DCF77

import gc

# Wiring on a Wemos D1 mini pro (ESP8266), see README.md
PON_PIN  = 12   # D6 - PON of the DCF1
DATA_PIN = 13   # D7 - demodulated signal of the DCF1

# Wemos D1 mini OLED shield (64x48, SSD1306): fixed I2C pins of the shield.
# Set USE_OLED to False if no shield is plugged in.
USE_OLED = True
OLED_SCL = 5    # D1
OLED_SDA = 4    # D2

# DCF77 carries German local time. Set this to True to store UTC in the RTC
# instead, which spares you the twice yearly jump when you log or compare times.
USE_UTC = False

# Set this to True to watch every received bit scroll past in the REPL. It is
# the quickest way to tell a reception problem from a decoding problem: no bits
# at all means the receiver is not delivering, a stream that never reaches 59
# means bits are being lost.
SHOW_BITS = False

# Print decoder phase changes and progress every ten received bits. A complete
# telegram takes about a minute to arrive.
SHOW_PROGRESS = True

if USE_OLED:
    gc.collect()
    import oled
    gc.collect()
    import ui
    gc.collect()

import dcf2rtc
import network
import ntp2rtc
import timebase
from machine import Pin, RTC, SoftI2C
from time import sleep_ms, ticks_ms, ticks_diff

dcf2rtc.DEBUG = SHOW_BITS
dcf2rtc.DEBUG_PROGRESS = SHOW_PROGRESS


def select_boot_mode():
    try:
        with open("boot_mode.txt", "r") as state_file:
            mode = state_file.read().strip()
    except OSError as e:
        if not e.args or e.args[0] != 2:
            raise
        mode = "dcf"

    if mode not in ("dcf", "ntp"):
        raise ValueError("invalid boot mode in boot_mode.txt: %r" % mode)

    with open("boot_mode.txt", "w") as state_file:
        state_file.write("dcf" if mode == "ntp" else "ntp")
    return mode


boot_mode = select_boot_mode()
print("time source this boot:", boot_mode.upper())

# MicroPython starts the ESP8266 as an access point. Its constant radio traffic
# is a needless noise source for the DCF1; the station radio is enabled only
# during NTP synchronization.
network.WLAN(network.AP_IF).active(False)
station = network.WLAN(network.STA_IF)
station.active(False)

# PON is active low. Keep the DCF1 switched off during NTP boots.
pon_pin = Pin(PON_PIN, Pin.OUT, value=0 if boot_mode == "dcf" else 1)
dcf = None
if boot_mode == "dcf":
    dcf = Pin(DATA_PIN, Pin.IN)
    print("DCF1 enabled: PON=GPIO%d low, DATA=GPIO%d (%d)" %
          (PON_PIN, DATA_PIN, dcf.value()))

# real time clock
rtc = RTC()
corrected_clock = timebase.CorrectedClock()

# OLED shield: optional, the clock is set without it as well
display = None
if USE_OLED:
    gc.collect()
    try:
        display = ui.Display(oled.SSD1306(SoftI2C(scl=Pin(OLED_SCL),
                                                  sda=Pin(OLED_SDA),
                                                  freq=400000)), utc=USE_UTC,
                             source=boot_mode.upper())
        display.alternating_splash()
        if boot_mode == "ntp":
            display.ntp_splash()
            display.status("NTP", "WLAN", "CLAUDINE")
        else:
            display.splash()
            dcf2rtc.observer = display.handle
    except OSError as e:
        print("no OLED shield found:", e)


def sync_dcf():
    # One telegram takes a minute, and a weak signal or a single lost bit makes
    # it unusable - so keep trying until one of them decodes cleanly.
    while True:
        if dcf2rtc.detectNewMinute(dcf) and dcf2rtc.computeTime(
                rtc, dcf, utc=USE_UTC):
            return
        print("no valid telegram, retrying ...")


def sync_ntp():
    from wifi_credentials import SSID, PASSWORD

    station.active(True)
    while True:
        try:
            if not station.isconnected():
                print("connecting to Wi-Fi:", SSID)
                if display is not None and not display.failed:
                    display.status("NTP", "VERBINDE", "WLAN")
                station.connect(SSID, PASSWORD)
                started = ticks_ms()
                while (not station.isconnected() and
                       ticks_diff(ticks_ms(), started) < 30000):
                    sleep_ms(250)
                if not station.isconnected():
                    raise OSError("Wi-Fi connection timed out")

            print("synchronizing time with NTP")
            if display is not None and not display.failed:
                display.status("NTP", "NTP SYNC", "WARTEN")
            ntp2rtc.syncTime(rtc, utc=USE_UTC)
            station.active(False)
            print("NTP time set:", rtc.datetime())
            return
        except OSError as e:
            print("NTP synchronization failed:", e, "- retrying in 10 s")
            if display is not None and not display.failed:
                display.status("NTP", "FEHLER", "RETRY")
            station.disconnect()
            sleep_ms(10000)


def sync_time():
    if boot_mode == "ntp":
        sync_ntp()
    else:
        sync_dcf()
    corrected_clock.set(rtc.datetime())


sync_time()
last_sync_date = corrected_clock.now(rtc.datetime())[:3]

# Refresh the RTC once a day at 03:05 using the selected source for this boot.
# The display and schedule use ticks_ms so they are not affected by RTC drift.
while True:
    now = corrected_clock.now(rtc.datetime())
    if now[3] == 3 and now[4] >= 5 and now[:3] != last_sync_date:
        print("daily time synchronization via", boot_mode.upper())
        sync_time()
        last_sync_date = corrected_clock.now(rtc.datetime())[:3]

    if display is not None and not display.failed:
        display.clock(now)
    sleep_ms(100)
