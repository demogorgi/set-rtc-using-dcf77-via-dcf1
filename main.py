# Micropython script to set the rtc time to the time sent by a DCF1 receiver
# module: https://www.pollin.de/p/dcf-77-empfangsmodul-dcf1-810054
# The DCF1 module receives the DCF77 signal, see https://en.wikipedia.org/wiki/DCF77

import dcf2rtc
import network
from machine import Pin, RTC, SoftI2C
from time import sleep_ms

# Wiring on a Wemos D1 mini pro (ESP8266), see README.md
PON_PIN  = 14   # D5 - PON of the DCF1
DATA_PIN = 12   # D6 - demodulated signal of the DCF1

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

dcf2rtc.DEBUG = SHOW_BITS
dcf2rtc.DEBUG_PROGRESS = SHOW_PROGRESS

# PON is active low: the DCF1 only runs while this pin is held at 0. Creating
# the pin without an explicit value leaves it high on the ESP8266, which keeps
# the receiver switched off and the data line flat - measured, not guessed.
pon_pin = Pin(PON_PIN, Pin.OUT, value=0)

# MicroPython starts the ESP8266 as an access point. Its constant radio traffic
# is a needless noise source for the DCF1, so switch the radio off.
network.WLAN(network.AP_IF).active(False)
network.WLAN(network.STA_IF).active(False)

# dcf1
dcf = Pin(DATA_PIN, Pin.IN)
print("DCF1 enabled: PON=GPIO%d low, DATA=GPIO%d (%d)" %
      (PON_PIN, DATA_PIN, dcf.value()))

# real time clock
rtc = RTC()

# OLED shield: optional, the clock is set without it as well
display = None
if USE_OLED:
    try:
        import oled, ui
        display = ui.Display(oled.SSD1306(SoftI2C(scl=Pin(OLED_SCL),
                                                  sda=Pin(OLED_SDA),
                                                  freq=400000)), utc=USE_UTC)
        display.splash()
        dcf2rtc.observer = display.handle
    except OSError as e:
        print("no OLED shield found:", e)

# One telegram takes a minute, and a weak signal or a single lost bit makes it
# unusable - so keep trying until one of them decodes cleanly.
while True:
    if dcf2rtc.detectNewMinute(dcf) and dcf2rtc.computeTime(rtc, dcf, utc=USE_UTC):
        break
    print("no valid telegram, retrying ...")

# keep showing the clock; Ctrl-C leaves the loop
while display is not None and not display.failed:
    display.clock()
    sleep_ms(100)
