"""DigiSigner signing-request creation from an existing template.

Set DIGISIGNER_API_KEY and DIGISIGNER_TEMPLATE_ID in .env.
Template text fields must have API IDs matching FIELD_API_IDS below.
"""
import os
import requests
from dotenv import load_dotenv

load_dotenv()

API_URL = 'https://api.digisigner.com/v1/signature_requests'

FIELD_API_IDS = {
    'first_name': '5eebd524-e2be-49c0-9eda-d42d50101ba9',
    'last_name': '78f47611-320c-4512-812e-cf0e028c1a78',
    'date_of_birth': 'cf7c911b-6345-4190-8bc8-2270ee42aef7',
    'license_number': '85b3b28a-a570-4c7a-b016-62a84f3ef5d4',
    'passport_number': '15df8544-4b02-471e-ad68-d734d88251cb',
    'street_address': '4d153a58-ff48-4fb1-a2b1-40c689b13a1b',
    'city': '961e4d1e-a2b6-442b-9830-2d0316cdf89c',
    'state': '3b1cf3b9-f74b-4493-8b39-a2f66b7b269c',
    'zip_code': '3b4b7713-eaa0-4675-b079-5c7da2725c9e',
    'email': '286cdeb7-e79a-4183-a54a-c4d6ac50f13f',
    'company_name': '082fc198-865d-433b-addc-dd6c6a2571b1',
    'tax_id': 'e32c4c70-609c-4f1f-83bf-a086d7d02d83',
}


def create_signing_request(data, signer_email):
    api_key = os.getenv('DIGISIGNER_API_KEY', '').strip()
    template_id = os.getenv('DIGISIGNER_TEMPLATE_ID', '').strip()
    if not api_key or not template_id:
        raise ValueError('Missing DIGISIGNER_API_KEY or DIGISIGNER_TEMPLATE_ID in .env')
    if not signer_email or '@' not in signer_email:
        raise ValueError('A valid signer email address is required')

    existing_fields = [
        {'api_id': api_id, 'content': str(data[key]).strip()}
        for key, api_id in FIELD_API_IDS.items()
        if data.get(key) is not None and str(data[key]).strip()
    ]
    if not existing_fields:
        raise ValueError('No non-empty fields available to prefill')

    payload = {
        'send_emails': False,
        'documents': [{
            'document_id': template_id,
            'title': 'OCR Autofill Test',
            'signers': [{
                'email': signer_email.strip(),
                'role': 'Signer 1',
                'existing_fields': existing_fields,
            }],
        }],
    }

    response = requests.post(
        API_URL,
        auth=(api_key, ''),
        json=payload,
        timeout=30,
    )
    if not response.ok:
        # Avoid echoing full response bodies that could contain personal information.
        raise ValueError(f'DigiSigner API returned HTTP {response.status_code}. Check template field IDs, signer role, and API permissions.')

    result = response.json()
    try:
        url = result['documents'][0]['signers'][0]['sign_document_url']
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError('DigiSigner response did not include a signing URL') from exc
    if not url:
        raise ValueError('DigiSigner returned an empty signing URL')
    return url
