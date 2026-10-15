
from datetime import datetime

import cv2
import numpy as np
import zxingcpp
from PIL import Image


def format_date(value):
    value = value.strip()

    if len(value) != 8 or not value.isdigit():
        return ""

    for fmt in ("%m%d%Y", "%Y%m%d"):
        try:
            parsed = datetime.strptime(value, fmt)
            if 1900 <= parsed.year <= 2100:
                return parsed.strftime("%m/%d/%Y")
        except ValueError:
            continue

    return ""



def parse_aamva(raw_text):
    """Parse common AAMVA PDF417 driver-license fields."""
    import re

    fields = {
        "first_name": "",
        "last_name": "",
        "date_of_birth": "",
        "expiry_date": "",
        "license_number": "",
        "street_address": "",
        "city": "",
        "state": "",
        "zip_code": "",
    }

    # Support both actual control characters and
    # literal markers such as <LF>, <RS>, <CR>.
    text = raw_text

    replacements = {
        "<LF>": "\n",
        "<CR>": "\n",
        "<RS>": "\n",
        "<GS>": "\n",
        "\r": "\n",
        "\x1e": "\n",
        "\x1d": "\n",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    codes = {
        "DCS": "last_name",
        "DAC": "first_name",
        "DCT": "first_name",
        "DBB": "date_of_birth",
        "DBA": "expiry_date",
        "DAQ": "license_number",
        "DAG": "street_address",
        "DAI": "city",
        "DAJ": "state",
        "DAK": "zip_code",
    }

    # AAMVA fields normally start with three-letter
    # identifiers. Some follow a DL/ID subfile prefix.
    for line in text.split("\n"):
        line = line.strip()

        if not line:
            continue

        if line.startswith(("DL", "ID")) and len(line) > 5:
            line = line[2:]

        code = line[:3]

        if code in codes:
            value = line[3:].strip()

            if value:
                field_name = codes[code]

                if field_name in ("date_of_birth", "expiry_date"):
                    value = format_date(value)

                if field_name == "zip_code":
                    value = value[:5]

                if value and not fields[field_name]:
                    fields[field_name] = value

    return fields

def scan_pdf417(image):
    """Decode PDF417 barcode from a PIL image."""

    rgb = np.array(image.convert("RGB"))

    attempts = [rgb]

    # Enlarging can help with some small barcode images.
    height, width = rgb.shape[:2]

    if width < 1800:
        enlarged = cv2.resize(
            rgb,
            None,
            fx=2,
            fy=2,
            interpolation=cv2.INTER_CUBIC,
        )
        attempts.append(enlarged)

    for candidate in attempts:
        barcodes = zxingcpp.read_barcodes(candidate)

        for barcode in barcodes:
            if barcode.format == zxingcpp.BarcodeFormat.PDF417:
                raw_text = barcode.text

                return {
                    "success": True,
                    "fields": parse_aamva(raw_text),
                    "raw_text": raw_text,
                }

    return {
        "success": False,
        "fields": {},
        "raw_text": "",
    }
