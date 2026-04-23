"""Matrix COSEC event ID mappings — sourced from COSEC DEVICES PUSH API GUIDE.

Maps cosec_event_id → EventMeta(event_type, auth_used, access_granted, description)

Auth method is determined from field-3 bitmask in setevent, not the event ID.
Use decode_auth_used(field_3_value) to get the auth method string.

Note: Matrix setevent uses field-1 through field-5 (NOT detail-1 through detail-5).
  field-1 = User ID (who accessed)
  field-2 = Reader/door ID
  field-3 = Auth bitmask (PIN/Card/Finger/Palm/Face)
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class EventMeta:
    event_type: str        # stored in access_event.event_type
    auth_used: str | None  # "card", "finger", "face", "pin", "palm", None
    access_granted: bool
    description: str


# ---------------------------------------------------------------------------
# Access Granted events (field-3 bitmask decoded separately for auth_used)
# ---------------------------------------------------------------------------
_GRANTED: dict[int, EventMeta] = {
    101: EventMeta("access_granted", None, True,  "User Allowed"),
    111: EventMeta("access_granted", None, True,  "Visitor Allowed"),
}

# ---------------------------------------------------------------------------
# Access Denied events
# ---------------------------------------------------------------------------
_DENIED: dict[int, EventMeta] = {
    151: EventMeta("access_denied", None,     False, "User Denied — User Invalid"),
    154: EventMeta("access_denied", None,     False, "User Denied — Time Out"),
    157: EventMeta("access_denied", None,     False, "User Denied — Disabled User"),
    158: EventMeta("access_denied", None,     False, "User Denied — Blocked User"),
    161: EventMeta("access_denied", None,     False, "User Denied — Control Zone"),
    162: EventMeta("access_denied", None,     False, "User Denied — Door Lock"),
    164: EventMeta("access_denied", None,     False, "User Denied — Validity Expired"),
    165: EventMeta("access_denied", None,     False, "User Denied — Invalid Route Access"),
    171: EventMeta("access_denied", None,     False, "Visitor Denied"),
    175: EventMeta("access_denied", None,     False, "User Denied — FR Disabled"),
    459: EventMeta("access_denied", "card",   False, "User Denied — Invalid Card"),
}

# ---------------------------------------------------------------------------
# Door / system events
# ---------------------------------------------------------------------------
_SYSTEM: dict[int, EventMeta] = {
    201: EventMeta("door_event",   None, False, "Door Status Changed"),
    204: EventMeta("door_event",   None, False, "Aux Input Status Changed"),
    205: EventMeta("door_event",   None, False, "Aux Output Status Changed"),
    206: EventMeta("door_event",   None, False, "Door Sense Input Status"),
    208: EventMeta("door_event",   None, False, "Door Open/Close"),
    306: EventMeta("alarm",        None, False, "Door Abnormal"),
    307: EventMeta("alarm",        None, False, "Door Force Open"),
    309: EventMeta("alarm",        None, False, "Door Controller Fault"),
    310: EventMeta("alarm",        None, False, "Tamper Alarm"),
    314: EventMeta("system",       None, False, "RTC"),
    317: EventMeta("alarm",        None, False, "Intercom Panic"),
    334: EventMeta("alarm",        None, False, "Threshold Temperature Exceeded"),
    351: EventMeta("system",       None, False, "Alarm Acknowledged"),
    352: EventMeta("system",       None, False, "Alarm Cleared"),
    354: EventMeta("alarm",        None, False, "Anti-Loiter Zone Violated"),
    402: EventMeta("system",       None, False, "Login to ACS"),
    403: EventMeta("system",       None, False, "Message Transaction Confirmation"),
    405: EventMeta("enrollment",   None, False, "Enrollment"),
    409: EventMeta("system",       None, False, "Credentials Deleted"),
    451: EventMeta("system",       None, False, "Configuration Change"),
    452: EventMeta("system",       None, False, "Event Rollover"),
    453: EventMeta("system",       None, False, "Master Controller Power ON"),
    454: EventMeta("system",       None, False, "Configuration Defaulted"),
    456: EventMeta("system",       None, False, "Backup and Update"),
    457: EventMeta("system",       None, False, "Default System"),
    465: EventMeta("system",       None, False, "Face Image and Template Available"),
}

_ALL: dict[int, EventMeta] = {**_GRANTED, **_DENIED, **_SYSTEM}

_UNKNOWN = EventMeta("unknown", None, False, "Unknown Event")


def get_event_meta(cosec_event_id: int) -> EventMeta:
    return _ALL.get(cosec_event_id, _UNKNOWN)


def is_access_granted(cosec_event_id: int) -> bool:
    return get_event_meta(cosec_event_id).access_granted


ACCESS_GRANTED_IDS: frozenset[int] = frozenset(k for k, v in _ALL.items() if v.access_granted)


# ---------------------------------------------------------------------------
# Decode auth method from detail-3 (field-3) bitmask
#
# From Matrix COSEC Push API Guide — Field 3 bitmask (bits 4-11):
#   Bit 4  (value 1)   = PIN
#   Bit 5  (value 2)   = Card
#   Bit 6  (value 4)   = Finger
#   Bit 7  (value 8)   = Palm
#   Bit 10 (value 64)  = Face (older firmware)
#   Bit 10 (value 64)  = Face (newer firmware)
#
# Multiple bits can be set (e.g. Finger + Card = 6).
# Bits 0-1 indicate Entry (0) or Exit (1).
# ---------------------------------------------------------------------------

def decode_auth_used(field_3_raw: str | None) -> str | None:
    """Decode auth method from the field-3 bitmask in setevent.

    Bit layout (Matrix COSEC Devices API Guide, Appendix — Field 3 Detail):
      Bit 0-1: Entry (0) / Exit (1)
      Bit 2:   Time Stamp
      Bit 3:   RFU
      Bit 4:   PIN
      Bit 5:   Card
      Bit 6:   Finger
      Bit 7:   Palm
      Bit 8:   Group
      Bit 9:   API
      Bit 10:  Face
      Bit 11:  BLE
      Bit 12:  Card 1
      Bit 13:  Card 2
      Bit 14:  QR

    Returns "finger", "card", "face", "finger+card", etc.
    Returns None if field_3 is missing or zero.
    """
    if not field_3_raw:
        return None
    try:
        val = int(field_3_raw)
    except (ValueError, TypeError):
        return None

    # Strip bits 0-3 (Entry/Exit, Time Stamp, RFU) — auth bits start at bit 4
    auth_bits = val >> 4

    methods = []
    if auth_bits & 0x01:   # bit 4 = PIN
        methods.append("pin")
    if auth_bits & 0x02:   # bit 5 = Card
        methods.append("card")
    if auth_bits & 0x04:   # bit 6 = Finger
        methods.append("finger")
    if auth_bits & 0x08:   # bit 7 = Palm
        methods.append("palm")
    # bit 8 = Group, bit 9 = API — not auth methods, skip
    if auth_bits & 0x40:   # bit 10 = Face
        methods.append("face")

    if not methods:
        return None
    return "+".join(methods)


def decode_direction(field_3_raw: str | None) -> str:
    """Decode entry/exit direction from field-3 bits 0-1.

    Bit 1=0, Bit 0=0 → Entry (IN)
    Bit 1=0, Bit 0=1 → Exit (OUT)
    """
    if not field_3_raw:
        return "IN"
    try:
        val = int(field_3_raw)
    except (ValueError, TypeError):
        return "IN"
    return "OUT" if (val & 0x01) else "IN"
