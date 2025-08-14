import logging
import requests
from decouple import config
from twilio.rest import Client
from models import SessionLocal, Conversation, UserState

TWILIO_ACCOUNT_SID = config("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = config("TWILIO_AUTH_TOKEN")
TWILIO_MESSAGING_SERVICE_SID = config("TWILIO_MESSAGING_SERVICE_SID")
TWILIO_NUMBER = config("TWILIO_NUMBER")
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

CHATWOOT_API_URL = config("CHATWOOT_API_URL").rstrip("/")
CHATWOOT_TOKEN = config("CHATWOOT_TOKEN")
CHATWOOT_ACCOUNT_ID = config("CHATWOOT_ACCOUNT_ID")
CHATWOOT_INBOX_ID = int(config("CHATWOOT_INBOX_ID")) if config("CHATWOOT_INBOX_ID") else None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def send_message(to_number: str, body_text: str) -> bool:
    try:
        message = twilio_client.messages.create(
            messaging_service_sid=TWILIO_MESSAGING_SERVICE_SID,
            body=body_text,
            to=f"whatsapp:{to_number}"
        )
        logger.info(f"Twilio message sent to {to_number}: {message.sid}")
        return True
    except Exception as e:
        logger.error(f"Error sending Twilio message to {to_number}: {e}")
        return False


def _extract_contact_id(resp_json: dict):
    if not isinstance(resp_json, dict):
        return None
    return (
        resp_json.get("payload", {}).get("contact", {}).get("id")
        or resp_json.get("payload", {}).get("id")
        or resp_json.get("id")
    )


def create_contact(whatsapp_number: str):
    url = f"{CHATWOOT_API_URL}/api/v1/accounts/{CHATWOOT_ACCOUNT_ID}/contacts"
    headers = {"api_access_token": CHATWOOT_TOKEN, "Content-Type": "application/json"}
    payload = {"name": whatsapp_number, "phone_number": whatsapp_number}
    resp = requests.post(url, json=payload, headers=headers, timeout=15)
    if resp.status_code in (200, 201):
        cid = _extract_contact_id(resp.json())
        if cid:
            logger.info(f"Created contact {whatsapp_number} -> id {cid}")
            return cid
        logger.error(f"Unexpected create contact response: {resp.json()}")
        return None
    logger.error(f"Failed to create contact {whatsapp_number}: {resp.status_code} {resp.text}")
    return None


def find_contact_id(whatsapp_number: str):
    url = f"{CHATWOOT_API_URL}/api/v1/accounts/{CHATWOOT_ACCOUNT_ID}/contacts/search"
    headers = {"api_access_token": CHATWOOT_TOKEN}
    params = {"q": whatsapp_number}
    resp = requests.get(url, headers=headers, params=params, timeout=10)
    if resp.status_code != 200:
        logger.error(f"Contact search failed for {whatsapp_number}: {resp.status_code} {resp.text}")
        return None
    data = resp.json()
    payload = data.get("payload")
    if isinstance(payload, list) and payload:
        contact = payload[0]
        cid = contact.get("id")
        logger.info(f"Found contact {whatsapp_number} -> id {cid}")
        return cid
    return None


def get_or_create_contact(whatsapp_number: str):
    cid = find_contact_id(whatsapp_number)
    if cid:
        return cid
    return create_contact(whatsapp_number)


def _extract_conversation_id(resp_json: dict):
    if not isinstance(resp_json, dict):
        return None
    return (
        resp_json.get("id")
        or resp_json.get("payload", {}).get("id")
        or resp_json.get("payload", {}).get("conversation", {}).get("id")
    )


def create_conversation(contact_id: int, inbox_id: int, whatsapp_number: str):
    url = f"{CHATWOOT_API_URL}/api/v1/accounts/{CHATWOOT_ACCOUNT_ID}/conversations"
    headers = {"api_access_token": CHATWOOT_TOKEN, "Content-Type": "application/json"}
    payload = {
        "source_id": f"whatsapp:{whatsapp_number}",
        "inbox_id": inbox_id,
        "contact_id": contact_id,
        "status": "open",
    }
    resp = requests.post(url, json=payload, headers=headers, timeout=15)
    if resp.status_code in (200, 201):
        conv_id = _extract_conversation_id(resp.json())
        if conv_id:
            logger.info(f"Created conversation for {whatsapp_number} -> id {conv_id}")
            return conv_id
        logger.error(f"Unexpected create conversation response: {resp.json()}")
        return None
    logger.error(f"Failed to create conversation: {resp.status_code} {resp.text}")
    return None


def get_open_conversation_for_contact(contact_id: int, whatsapp_number: str):
    url = f"{CHATWOOT_API_URL}/api/v1/accounts/{CHATWOOT_ACCOUNT_ID}/contacts/{contact_id}/conversations"
    headers = {"api_access_token": CHATWOOT_TOKEN}
    resp = requests.get(url, headers=headers, timeout=10)
    if resp.status_code != 200:
        logger.error(f"Failed to get conversations for contact {contact_id}: {resp.status_code} {resp.text}")
        return None
    data = resp.json()
    payload = data.get("payload", [])
    if not isinstance(payload, list):
        return None
    for conv in payload:
        if conv.get("status") == "open":
            return conv.get("id")
    return None


def get_or_create_open_conversation(contact_id: int, whatsapp_number: str):
    conv_id = get_open_conversation_for_contact(contact_id, whatsapp_number)
    if conv_id:
        return conv_id
    if not CHATWOOT_INBOX_ID:
        logger.error("CHATWOOT_INBOX_ID is not set; cannot create conversation")
        return None
    return create_conversation(contact_id, CHATWOOT_INBOX_ID, whatsapp_number)


def send_user_message_to_chatwoot(whatsapp_number: str, message_text: str) -> bool:
    contact_id = get_or_create_contact(whatsapp_number)
    if not contact_id:
        logger.error(f"Cannot forward user message to Chatwoot: failed to get/create contact for {whatsapp_number}")
        return False
    conv_id = get_or_create_open_conversation(contact_id, whatsapp_number)
    if not conv_id:
        logger.error(f"Cannot forward user message to Chatwoot: failed to get/create conversation for {whatsapp_number}")
        return False
    url = f"{CHATWOOT_API_URL}/api/v1/accounts/{CHATWOOT_ACCOUNT_ID}/conversations/{conv_id}/messages"
    headers = {"api_access_token": CHATWOOT_TOKEN, "Content-Type": "application/json"}
    payload = {"content": message_text, "message_type": 0}
    resp = requests.post(url, json=payload, headers=headers, timeout=10)
    if resp.status_code in (200, 201):
        logger.info(f"Forwarded user message to Chatwoot conversation {conv_id}")
        return True
    logger.error(f"Failed to post user message to Chatwoot: {resp.status_code} {resp.text}")
    return False


def set_handoff_flag(phone_number: str, value: bool):
    db = SessionLocal()
    try:
        state = db.query(UserState).filter(UserState.sender == phone_number).first()
        if state:
            state.in_handoff = value
        else:
            state = UserState(sender=phone_number, in_handoff=value)
            db.add(state)
        db.commit()
        logger.info(f"Set in_handoff={value} for {phone_number}")
    except Exception as e:
        logger.exception(f"Error setting handoff flag for {phone_number}: {e}")
        db.rollback()
    finally:
        db.close()


def is_user_in_handoff(phone_number: str) -> bool:
    db = SessionLocal()
    try:
        state = db.query(UserState).filter(UserState.sender == phone_number).first()
        return bool(state and state.in_handoff)
    finally:
        db.close()


def handoff_to_agent(phone_number: str) -> bool:
    contact_id = get_or_create_contact(phone_number)
    if not contact_id:
        logger.error("handoff_to_agent: failed to get/create contact")
        return False
    conv_id = get_or_create_open_conversation(contact_id, phone_number)
    if not conv_id:
        logger.error("handoff_to_agent: failed to get/create conversation")
        return False

    url = f"{CHATWOOT_API_URL}/api/v1/accounts/{CHATWOOT_ACCOUNT_ID}/conversations/{conv_id}"
    headers = {"api_access_token": CHATWOOT_TOKEN, "Content-Type": "application/json"}
    payload = {"status": "open"}
    try:
        resp = requests.patch(url, json=payload, headers=headers, timeout=10)
        if resp.status_code not in (200, 201):
            logger.warning(f"Could not patch conversation {conv_id}: {resp.status_code} {resp.text}")
    except Exception as e:
        logger.exception(f"Error patching Chatwoot conversation: {e}")

    set_handoff_flag(phone_number, True)
    logger.info(f"Handoff mode enabled for {phone_number}, chatwoot conv {conv_id}")
    return True


def resume_ai_mode(phone_number: str) -> bool:
    db = SessionLocal()
    try:
        state = db.query(UserState).filter(UserState.sender == phone_number).first()
        if state:
            state.in_handoff = False
        else:
            state = UserState(sender=phone_number, in_handoff=False)
            db.add(state)
        db.commit()
        logger.info(f"AI resumed for {phone_number}")
        return True
    except Exception as e:
        logger.exception(f"Error resuming AI mode for {phone_number}: {e}")
        db.rollback()
        return False
    finally:
        db.close()
