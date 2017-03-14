# code from http://stackoverflow.com/questions/16742381/how-to-convert-youtube-api-duration-to-seconds

import re

# see http://en.wikipedia.org/wiki/ISO_8601#Durations
ISO_8601_period_rx = re.compile(
    'P'   # designates a period
    '(?:(?P<years>\d+)Y)?'   # years
    '(?:(?P<months>\d+)M)?'  # months
    '(?:(?P<weeks>\d+)W)?'   # weeks
    '(?:(?P<days>\d+)D)?'    # days
    '(?:T' # time part must begin with a T
    '(?:(?P<hours>\d+)H)?'   # hourss
    '(?:(?P<minutes>\d+)M)?' # minutes
    '(?:(?P<seconds>\d+)S)?' # seconds
    ')?'   # end of time part
)

def convert_to_dict(ISO):
    return ISO_8601_period_rx.match(ISO).groupdict()
