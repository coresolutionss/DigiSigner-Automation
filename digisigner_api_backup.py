import os

import requests
from dotenv import load_dotenv

load_dotenv()

API_URL = "https://api.digisigner.com/v1/signature_requests"


def create_signing_request(data, signer_email):
    api_key = os.getenv("DIGISIGNER_API_KEY", "").strip()
    template_id = os.getenv("DIGISIGNER_TEMPLATE_ID", "").strip()

    if not api_key or not template_id:
        raise ValueError("Missing DigiSigner API key or template ID in .env")

    if not signer_email or "@" not in signer_email:
        raise ValueError("Enter a valid signer email address.")

    field_mapping = {
        "first_name": os.getenv("DIGISIGNER_FIRST_NAME_FIELD"),
        "last_name": os.getenv("DIGISIGNER_LAST_NAME_FIELD"),
    }

    existing_fields = []

    for field_name, api_id in field_mapping.items():
        value = data.get(field_name)

        if api_id and value:
            existing_fields.append({
                "api_id": api_id.strip(),
                "content": str(value).strip(),
            })

    if not existing_fields:
        raise ValueError("No mapped DigiSigner fields have values.")

    payload = {
        "send_emails": False,
        "documents": [
            {
                "document_id": template_id,
                "title": "OCR Autofill Test",
                "signers": [
                    {
                        "email": signer_email,
                        "role": "Signer 1",
                        "existing_fields": existing_fields,
                    }
                ],
            }
        ],
    }

    response = requests.post(
        API_URL,
        auth=(api_key, ""),
        json=payload,
        timeout=30,
    )

    response.raise_for_status()

    result = response.json()

    try:
        return result["documents"][0]["signers"][0]["sign_document_url"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError(
            "DigiSigner did not return a signing URL."
        ) from exc
