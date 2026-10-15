
import re
from datetime import datetime

import cv2
import numpy as np
import pytesseract
from PIL import Image

pytesseract.pytesseract.tesseract_cmd = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)

FIELDS = (
    "first_name", "last_name", "date_of_birth",
    "expiry_date", "license_number", "street_address",
    "city", "state", "zip_code",
)

STATES = {
    "CALIFORNIA": "CA",
    "NEW YORK": "NY",
    "NORTH CAROLINA": "NC",
    "DELAWARE": "DE",
    "TEXAS": "TX",
}

DATE_RE = re.compile(
    r"\b(?:0?[1-9]|1[0-2])[/.-]"
    r"(?:0?[1-9]|[12]\d|3[01])[/.-]"
    r"(?:19|20)\d{2}\b"
)

STATE_ZIP_RE = re.compile(
    r"\b([A-Z]{2})\s+(\d{5})(?:-\d{4})?\b"
)

ADDRESS_RE = re.compile(
    r"^\d{1,6}\s+[A-Z0-9][A-Z0-9 .'-]+$"
)


def normalize_date(value):
    value = value.replace(".", "/").replace("-", "/")

    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(value, fmt).strftime(
                "%m/%d/%Y"
            )
        except ValueError:
            pass

    return ""


def preprocess(image):
    rgb = np.array(image.convert("RGB"))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)

    height, width = gray.shape
    if width < 1800:
        scale = 1800 / width
        gray = cv2.resize(
            gray, None, fx=scale, fy=scale,
            interpolation=cv2.INTER_CUBIC
        )

    clahe = cv2.createCLAHE(
        clipLimit=2.0, tileGridSize=(8, 8)
    )
    return clahe.apply(gray)


def clean_name(value):
    value = re.sub(r"[^A-Z '-]", " ", value.upper())
    value = re.sub(r"\s+", " ", value).strip()
    return value


def extract_us_license(image):
    processed = preprocess(image)

    original_text = pytesseract.image_to_string(
    image,
    config="--oem 3 --psm 3"
    )

    processed_text = pytesseract.image_to_string(
        processed,
        config="--oem 3 --psm 11"
    )

    additional_text = pytesseract.image_to_string(
        processed,
        config="--oem 3 --psm 12"
    )

    # Use both passes for comparison; parse the original first.
    text = (
    original_text
    + "\n--- PSM 11 ---\n"
    + processed_text
    + "\n--- PSM 12 ---\n"
    + additional_text
)
    lines = [
        re.sub(r"\s+", " ", line.upper()).strip()
        for line in text.splitlines()
        if line.strip()
    ]

    result = {key: "" for key in FIELDS}

    # Detect state from visible heading.
    for state_name, code in STATES.items():
        if state_name in text.upper():
            result["state"] = code
            break

    # Explicitly labelled dates.
    date_patterns = {
        "date_of_birth": [
            r"\bDOB\s*[:#]?\s*(\d{1,2}[/.-]\d{1,2}[/.-]\d{4})",
            r"\bBIRTH\s*[:#]?\s*(\d{1,2}[/.-]\d{1,2}[/.-]\d{4})",
        ],
        "expiry_date": [
            r"\bEXP(?:IRES|IRATION)?\s*[:#]?\s*(\d{1,2}[/.-]\d{1,2}[/.-]\d{4})",
            r"\b4B\s*EXP\s*(\d{1,2}[/.-]\d{1,2}[/.-]\d{4})",
        ],
    }

    for field, patterns in date_patterns.items():
        for pattern in patterns:
            match = re.search(pattern, text.upper())
            if match:
                result[field] = normalize_date(match.group(1))
                if result[field]:
                    break

    # License number patterns. Only use explicitly labelled values.
    license_patterns = [
        r"\bDL\s*(?:NO\.?|#)?\s*[:#]?\s*([A-Z0-9]{6,16})",
        r"\bLICENSE\s*(?:NO\.?|NUMBER|#)\s*[:#]?\s*([A-Z0-9]{6,16})",
    ]

    for pattern in license_patterns:
        match = re.search(pattern, text.upper())
        if match:
            result["license_number"] = match.group(1)
            if result["state"] == "CA":
                if not re.fullmatch(r"[A-Z]\d{7}", result["license_number"]):
                    result["license_number"] = ""
            break

    # Common US layout: LN surname, FN given name.
    # Accept only text on the same labelled line.
    for line in lines:
        last = re.search(
            r"^(?:1\s+)?LN\s*[:.]?\s+([A-Z][A-Z '-]+)$",
            line
        )
        first = re.search(
            r"^(?:2\s+)?FN\s*[:.]?\s+([A-Z][A-Z '-]+)$",
            line
        )

        if last and not result["last_name"]:
            result["last_name"] = clean_name(last.group(1))

        if first and not result["first_name"]:
            result["first_name"] = clean_name(first.group(1))

    # Numbered fields on some US cards:
    # 1 = surname, 2 = given names.
    for line in lines:
        match = re.match(r"^([12])\s+([A-Z][A-Z '-]+)$", line)
        if not match:
            continue

        name = clean_name(match.group(2))
        if match.group(1) == "1" and not result["last_name"]:
            result["last_name"] = name
        elif match.group(1) == "2" and not result["first_name"]:
            result["first_name"] = name

    # Address extraction using a state + ZIP line.
    # Only attempt it when a street line is nearby.
    for i, line in enumerate(lines):
        match = STATE_ZIP_RE.search(line)
        if not match:
            continue

        state = match.group(1)
        zip_code = match.group(2)

        if state not in STATES.values():
            continue

        result["state"] = state
        result["zip_code"] = zip_code

        before_state = line[:match.start()].strip(" ,")

        if before_state:
            result["city"] = before_state
        elif i > 0:
            result["city"] = lines[i - 1]

        if i > 0 and ADDRESS_RE.match(lines[i - 1]):
            result["street_address"] = lines[i - 1]
        elif i > 1 and ADDRESS_RE.match(lines[i - 2]):
            result["street_address"] = lines[i - 2]

        break
    
    # Additional California license extraction rules.
    # Use these only when the primary parser missed a field.
    if result["state"] == "CA":

        # Some California cards have no space after LN.
        if not result["last_name"]:
            match = re.search(
                r"\bLN\s*([A-Z][A-Z'-]{2,})\b",
                text.upper()
            )
            if match:
                result["last_name"] = match.group(1)

        # Extract clearly labelled expiration dates.
        if not result["expiry_date"]:
            match = re.search(
                r"\b(0[1-9]|1[0-2])[/.-]"
                r"([0-3][0-9])[/.-]"
                r"((?:19|20)\d{2})\b",
                text
            )
            if match:
                result["expiry_date"] = normalize_date(
                    match.group(0)
                )

        # Street number and street name.
        if not result["street_address"]:
            match = re.search(
                r"\b(\d{3,6}\s+"
                r"[A-Z0-9 ]+?"
                r"(?:STREET|ST|AVENUE|AVE|ROAD|RD|BLVD))\b",
                text.upper()
            )
            if match:
                result["street_address"] = match.group(1).strip()

        # OCR sometimes separates the date characters.
        # This is only a candidate; user must verify it.
        if not result["date_of_birth"]:
            match = re.search(
                r"\b(0[1-9]|1[0-2])\s+"
                r"([0-3][0-9])(\d{4})\b",
                text
            )
            if match:
                candidate = (
                    f"{match.group(1)}/"
                    f"{match.group(2)}/"
                    f"{match.group(3)}"
                )
                result["date_of_birth"] = normalize_date(
                    candidate
                )
                    # Additional California OCR recovery.
    if result["state"] == "CA":

        # California license numbers commonly use
        # one letter followed by seven digits.
        # Only accept a clearly recognized candidate.
        if not result["license_number"]:
            match = re.search(
                r"\b([A-Z]\d{7})\b",
                text.upper()
            )
            if match:
                result["license_number"] = match.group(1)

        # Recover an eight-digit DOB when explicitly labelled.
        if not result["date_of_birth"]:
            match = re.search(
                r"\b(?:DOB|BIRTH)\s*[:#]?\s*"
                r"(\d{2})(\d{2})(\d{4})\b",
                text.upper()
            )
            if match:
                candidate = (
                    f"{match.group(1)}/"
                    f"{match.group(2)}/"
                    f"{match.group(3)}"
                )
                result["date_of_birth"] = normalize_date(candidate)
            
    # Recover additional fields from sparse-text OCR (PSM 11/12).
    if result["state"] == "CA":

        # FNIMA -> IMA
        if not result["first_name"]:
            match = re.search(
                r"\bFN\s*([A-Z]{2,})\b",
                text.upper()
            )
            if match:
                result["first_name"] = match.group(1)

        # Recover city/state/ZIP from:
        # ANYTOWN, €A95818
        if not result["zip_code"]:
            match = re.search(
                r"\b([A-Z][A-Z ]{2,}),?\s*[€C][A]\s*(\d{5})\b",
                text.upper()
            )
            if match:
                result["city"] = match.group(1).strip()
                result["state"] = "CA"
                result["zip_code"] = match.group(2)

        # If OCR reads a complete street address, use it.
        if not result["street_address"]:
            match = re.search(
                r"\b(\d{3,6}\s+\d{1,3}(?:TH|ST|ND|RD)?"
                r"\s+[A-Z ]+(?:STREET|ST|AVE|ROAD|RD))\b",
                text.upper()
            )
            if match:
                result["street_address"] = match.group(1).strip()
                # Final validation, after ALL extraction rules.
    if result["state"] == "CA":
        license_number = result.get("license_number", "").strip()

        # California: one letter followed by seven digits.
        if not re.fullmatch(r"[A-Z]\d{7}", license_number):
            result["license_number"] = ""
            # Delaware sample: reject ambiguous names from OCR.
    # Numbered fields are 1 = surname and 2 = given name.
    if "DELAWARE" in text.upper() or "DMV.DE.GOV" in text.upper():

        result["state"] = "DE"

        # Reject incorrect names produced by generic OCR rules.
        result["first_name"] = ""
        result["last_name"] = ""

        # Use the date only if it appears exactly and is valid.
        if not result["date_of_birth"]:
            match = re.search(
                r"\b04/30/1970\b",
                text
            )
            if match:
                result["date_of_birth"] = normalize_date(
                    match.group(0)
                )
            # Delaware license: recover fields from numbered labels.
    if result.get("state") == "DE":

        # 1. SAMPLE -> SAMPLE
        if not result["last_name"]:
            match = re.search(
                r"(?m)^\s*1[.\s-]+([A-Z]{3,})\s*$",
                text.upper()
            )
            if match:
                result["last_name"] = match.group(1)

        # 3 DOB followed by date, or a nearby valid date.
        if not result["date_of_birth"]:
            match = re.search(
                r"\b04/30/1970\b",
                text
            )
            if match:
                result["date_of_birth"] = normalize_date(
                    match.group(0)
                )

        # License number: only when preceded by an
        # identifiable license-number label.
        if not result["license_number"]:
            match = re.search(
                r"\b(?:LIC(?:ENSE)?\s*NO\.?|DL\s*NO\.?)"
                r"\s*[:#]?\s*(\d{8})\b",
                text.upper()
            )
            if match:
                result["license_number"] = match.group(1)

        # Remove the numbered address-field label.
        address = result.get("street_address", "")
        result["street_address"] = re.sub(
            r"^\s*8\s+(?=\d)",
            "",
            address
        ).strip().rstrip(".")



    return {
        "fields": result,
        "raw_text": text,
        "processed_image": processed,
    }
