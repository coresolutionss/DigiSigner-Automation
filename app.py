"""Streamlit OCR + PDF417 review workflow for synthetic/test documents.

Requires: streamlit, pillow, requests, opencv-python, numpy, pytesseract,
          us_license_ocr.py, barcode_reader.py, digisigner_api.py.
"""
import io
import re
from datetime import datetime

import cv2
import numpy as np
import requests
import streamlit as st
from PIL import Image, UnidentifiedImageError

from barcode_reader import scan_pdf417
from digisigner_api import create_signing_request
from us_license_ocr import extract_us_license

st.set_page_config(page_title="DigiSigner Document Scanner", page_icon="📄", layout="wide")

FIELD_LABELS = {
    "first_name": "First Name", "last_name": "Last Name",
    "date_of_birth": "Date of Birth", "expiry_date": "Expiration Date",
    "license_number": "License Number", "street_address": "Street Address",
    "city": "City", "state": "State", "zip_code": "ZIP Code",
    "passport_number": "Passport Number", "email": "Email",
    "company_name": "Company Name", "tax_id": "Tax ID",
}
DATE_FIELDS = {"date_of_birth", "expiry_date"}


def clean(value):
    return str(value or "").strip()


def normalized(value):
    return re.sub(r"\s+", " ", clean(value)).casefold()


def image_from_upload(upload):
    return Image.open(io.BytesIO(upload.getvalue())).convert("RGB")


def processed_preview(image):
    rgb = np.asarray(image)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    height, width = gray.shape
    if width and width < 1600:
        scale = 1600 / width
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    gray = cv2.bilateralFilter(gray, 5, 50, 50)
    return cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)


def invalidate_confirmation():
    st.session_state.pop("confirmed_data", None)
    st.session_state.pop("signing_url", None)
    st.session_state["scan_version"] = st.session_state.get("scan_version", 0) + 1


def reset_for_changed_uploads(front_file, back_file):
    current_front = front_file.getvalue() if front_file else None
    current_back = back_file.getvalue() if back_file else None
    # Comparing upload bytes prevents stale data from being used with a new file.
    import hashlib
    signatures = (
        hashlib.sha256(current_front).hexdigest() if current_front else None,
        hashlib.sha256(current_back).hexdigest() if current_back else None,
    )
    old = st.session_state.get("upload_signatures")
    if old is not None and signatures != old:
        if signatures[0] != old[0]:
            st.session_state.pop("front_fields", None)
            st.session_state.pop("ocr_text", None)
        if signatures[1] != old[1]:
            st.session_state.pop("barcode_fields", None)
        invalidate_confirmation()
    st.session_state["upload_signatures"] = signatures


def compare_fields(front, back):
    return {
        key: {"front_ocr": clean(front.get(key)), "back_barcode": clean(back.get(key))}
        for key in FIELD_LABELS
        if clean(front.get(key)) and clean(back.get(key))
        and normalized(front.get(key)) != normalized(back.get(key))
    }


def verification_form(front, back):
    st.header("3. Review and verify information")
    conflicts = compare_fields(front, back)
    if conflicts:
        st.warning(f"{len(conflicts)} field(s) differ between front OCR and back barcode. Check the original document before choosing values.")
        with st.expander("View differences", expanded=True):
            st.json(conflicts)
    else:
        st.info("Review all extracted values against the original document. Empty or matching fields may still be incorrect.")

    version = st.session_state.get("scan_version", 0)
    with st.form(f"verification_form_{version}"):
        choices = {}
        for key, label in FIELD_LABELS.items():
            a, b = clean(front.get(key)), clean(back.get(key))
            st.markdown(f"**{label}**")
            col_a, col_b = st.columns(2)
            col_a.caption("Front OCR")
            col_a.write(a or "Not detected")
            col_b.caption("Back PDF417")
            col_b.write(b or "Not detected")

            options = ["Manual entry"]
            if a:
                options.insert(0, "Front OCR")
            if b:
                options.insert(1 if a else 0, "Barcode")
            # For conflicting sources, force explicit review rather than a silent default.
            default = "Manual entry" if a and b and normalized(a) != normalized(b) else (
                "Front OCR" if a else "Barcode" if b else "Manual entry"
            )
            source = st.selectbox(
                f"Use value for {label}", options,
                index=options.index(default), key=f"source_{version}_{key}",
            )
            manual = st.text_input(
                f"Manual value for {label}",
                placeholder="Enter value if using Manual entry",
                key=f"manual_{version}_{key}",
            )
            choices[key] = (source, a, b, manual)
            st.divider()

        acknowledged = st.checkbox(
            "I checked the selected values against the original document(s), including any differences."
        )
        submitted = st.form_submit_button("Confirm Verified Information", type="primary")

    if submitted:
        if not acknowledged:
            st.error("Please review the document and check the acknowledgement box.")
            return
        result = {}
        for key, (source, a, b, manual) in choices.items():
            result[key] = a if source == "Front OCR" else b if source == "Barcode" else clean(manual)
        if not result["first_name"] or not result["last_name"]:
            st.error("First name and last name are required. Correct missing values before confirming.")
            return
        for key in DATE_FIELDS:
            if result[key]:
                try:
                    datetime.strptime(result[key], "%m/%d/%Y")
                except ValueError:
                    st.error(f"{FIELD_LABELS[key]} must use MM/DD/YYYY format.")
                    return
        if result["email"] and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", result["email"]):
            st.error("Enter a valid email address or leave the field blank.")
            return
        st.session_state["confirmed_data"] = result
        st.session_state.pop("signing_url", None)
        st.success("Information confirmed after manual review.")


st.title("DigiSigner Document Scanner")
st.caption("Prototype for synthetic/test documents. Review extracted values before creating a signing request.")

st.header("1. Upload documents")
front_upload = st.file_uploader("Front of driver's license", type=["png", "jpg", "jpeg"], key="front_upload")
back_upload = st.file_uploader("Back of driver's license (PDF417)", type=["png", "jpg", "jpeg"], key="back_upload")
reset_for_changed_uploads(front_upload, back_upload)

front_image = back_image = None
if front_upload:
    try:
        front_image = image_from_upload(front_upload)
    except (UnidentifiedImageError, OSError, ValueError):
        st.error("The front upload is not a valid image.")
if back_upload:
    try:
        back_image = image_from_upload(back_upload)
    except (UnidentifiedImageError, OSError, ValueError):
        st.error("The back upload is not a valid image.")

st.header("2. Scan documents")
left, right = st.columns(2)
with left:
    st.subheader("Front OCR")
    if front_image:
        st.image(front_image, use_container_width=True)
        with st.expander("Processed OCR preview"):
            st.image(processed_preview(front_image), use_container_width=True, clamp=True)
        if st.button("Scan Front Document", type="primary"):
            try:
                with st.spinner("Reading front image..."):
                    response = extract_us_license(front_image)
                st.session_state["front_fields"] = response.get("fields", {})
                st.session_state["ocr_text"] = response.get("raw_text", "")
                invalidate_confirmation()
                st.success("Front OCR finished.")
            except Exception as exc:
                st.error(f"Front OCR failed: {exc}")
    else:
        st.info("Upload a front image to scan it.")
with right:
    st.subheader("Back PDF417")
    if back_image:
        st.image(back_image, use_container_width=True)
        if st.button("Scan PDF417 Barcode"):
            try:
                with st.spinner("Reading PDF417 barcode..."):
                    response = scan_pdf417(back_image)
                if response.get("success"):
                    st.session_state["barcode_fields"] = response.get("fields", {})
                    invalidate_confirmation()
                    st.success("PDF417 barcode decoded.")
                else:
                    st.warning("No readable PDF417 barcode detected. Try a sharper back image.")
            except Exception as exc:
                st.error(f"Barcode scanning failed: {exc}")
    else:
        st.info("Upload a back image to scan its barcode.")

front_fields = st.session_state.get("front_fields", {})
barcode_fields = st.session_state.get("barcode_fields", {})
if front_fields or barcode_fields:
    with st.expander("Extracted data (debug)", expanded=False):
        st.write("Front OCR fields")
        st.json(front_fields)
        st.write("Back barcode fields")
        st.json(barcode_fields)
        st.caption("Debug output may contain personal data. Disable in production.")
        if st.checkbox("Show raw OCR text (sensitive)"):
            st.code(st.session_state.get("ocr_text", ""))
    verification_form(front_fields, barcode_fields)

if "confirmed_data" in st.session_state:
    st.header("4. Confirmed data")
    st.json(st.session_state["confirmed_data"])
    st.header("5. DigiSigner")
    signer_email = st.text_input(
        "Signer email address", value=st.session_state["confirmed_data"].get("email", ""),
        key=f"signer_email_{st.session_state.get('scan_version', 0)}",
    )
    if st.button("Create Prefilled DigiSigner Form"):
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", signer_email.strip()):
            st.error("Enter a valid signer email address.")
        else:
            try:
                with st.spinner("Creating DigiSigner signing request..."):
                    url = create_signing_request(
                        data=st.session_state["confirmed_data"],
                        signer_email=signer_email.strip(),
                    )
                if not url:
                    raise ValueError("DigiSigner did not return a signing URL")
                st.session_state["signing_url"] = url
                st.success("DigiSigner form created.")
            except requests.exceptions.RequestException:
                st.error("DigiSigner request failed. Check API credentials, template and network.")
            except (ValueError, KeyError, TypeError) as exc:
                st.error(f"DigiSigner configuration or response error: {exc}")
    if st.session_state.get("signing_url"):
        st.link_button("Open Prefilled DigiSigner Form", st.session_state["signing_url"])
