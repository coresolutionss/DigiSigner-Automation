
import streamlit as st

FIELDS = {
    "first_name": "First Name",
    "last_name": "Last Name",
    "date_of_birth": "Date of Birth",
    "expiry_date": "Expiration Date",
    "license_number": "License Number",
    "street_address": "Street Address",
    "city": "City",
    "state": "State",
    "zip_code": "ZIP Code",
    "passport_number": "Passport Number",
    "email": "Email",
    "company_name": "Company Name",
    "tax_id": "Tax ID",
}


def verify_document():
    front = st.session_state.get("front_fields", {})
    barcode = st.session_state.get("barcode_fields", {})

    if not front and not barcode:
        return

    st.subheader("Document Verification")

    st.info(
        "Compare the extracted information with the original "
        "documents. Select the correct source or enter a "
        "verified value manually."
    )

    verified = {}
    unresolved = []

    # Reset widget values when either scan changes.
    scan_version = st.session_state.get("scan_version", 0)

    with st.form("document_verification_form"):
        for field, label in FIELDS.items():
            front_value = str(front.get(field) or "").strip()
            barcode_value = str(barcode.get(field) or "").strip()

            st.markdown(f"**{label}**")

            col1, col2 = st.columns(2)

            with col1:
                st.caption("Front OCR")
                st.write(front_value or "Not detected")

            with col2:
                st.caption("Back barcode")
                st.write(barcode_value or "Not detected")

            options = ["Manual"]
            if front_value:
                options.insert(0, "Front OCR")
            if barcode_value:
                options.insert(
                    1 if front_value else 0,
                    "Barcode"
                )

            default = (
                "Front OCR" if front_value
                else "Barcode" if barcode_value
                else "Manual"
            )

            source = st.selectbox(
                f"Select source for {label}",
                options=options,
                index=options.index(default),
                key=f"verify_source_{scan_version}_{field}",
            )

            manual_value = st.text_input(
                f"Manual correction for {label}",
                value="",
                key=f"verify_manual_{scan_version}_{field}",
                placeholder="Enter corrected value if using Manual",
            )

            if source == "Front OCR":
                value = front_value
            elif source == "Barcode":
                value = barcode_value
            else:
                value = manual_value.strip()

            verified[field] = value

            if (
                front_value
                and barcode_value
                and front_value.upper() != barcode_value.upper()
            ):
                unresolved.append(field)

            st.divider()

        acknowledged = st.checkbox(
            "I have checked the selected information "
            "against the original document(s)."
        )

        submitted = st.form_submit_button(
            "Confirm Verified Information",
            type="primary",
        )

    if submitted:
        if not acknowledged:
            st.error(
                "Please verify the information and "
                "check the confirmation box."
            )
            return

        st.session_state["confirmed_data"] = verified
        st.session_state["verification_complete"] = True
        st.session_state["barcode_conflicts"] = {}

        st.success("Document information verified!")
        st.json(verified)
