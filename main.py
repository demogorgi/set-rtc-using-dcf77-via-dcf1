# Micropython script to set the rtc time to the time sent by a DCF1 receiver
# module: https://www.pollin.de/p/dcf-77-empfangsmodul-dcf1-810054
# The DCF1 module receives the DCF77 signal, see https://en.wikipedia.org/wiki/DCF77

import dcf2rtc
from machine import Pin, RTC

# Wiring on a Wemos D1 mini pro (ESP8266), see README.md
PON_PIN  = 14   # D5 - PON of the DCF1
DATA_PIN = 12   # D6 - demodulated signal of the DCF1

# PON is active low: the DCF1 only runs while this pin is held at 0. Creating
# the pin without an explicit value leaves it high on the ESP8266, which keeps
# the receiver switched off and the data line flat - measured, not guessed.
pon_pin = Pin(PON_PIN, Pin.OUT, value=0)

# dcf1
dcf = Pin(DATA_PIN, Pin.IN)

# real time clock
rtc = RTC()

# One telegram takes a minute, and a weak signal or a single lost bit makes it
# unusable - so keep trying until one of them decodes cleanly.
while True:
    if dcf2rtc.detectNewMinute(dcf) and dcf2rtc.computeTime(rtc, dcf):
        break
    print("no valid telegram, retrying ...")
