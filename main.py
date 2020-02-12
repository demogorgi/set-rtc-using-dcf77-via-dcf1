# Micropython script to set rtc-time to time from
# DCF1 receiver module https://www.pollin.de/p/dcf-77-empfangsmodul-dcf1-810054?gclid=EAIaIQobChMIpdOkt7bK5wIViM13Ch0Tsw1dEAQYASABEgKgafD_BwE
# DCF1 module receives DCF77 signal, see https://en.wikipedia.org/wiki/DCF77

import dcf2rtc
from machine import Pin, Signal, RTC

# to wake up dcf1 (maybe connecting to PON pin is sufficient)
pon_pin = Pin(14, Pin.OUT) #D5
#pon_pin.on()
#sleep_ms(200)
#pon_pin.off()

# dcf1
dcf = Pin(12, Pin.IN) #D6

# real time clock
rtc = RTC()

cnd = True
while cnd:
    if dcf2rtc.detectNewMinute(dcf):
        cnd = dcf2rtc.computeTime(rtc,dcf)
