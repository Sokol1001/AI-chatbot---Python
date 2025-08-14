import logging
from fastapi import FastAPI, Request, Form, Depends
from decouple import config
from openai import OpenAI
from sqlalchemy.orm import Session
from models import SessionLocal, Conversation, UserState
from utils import (
    send_message,
    send_user_message_to_chatwoot,
    handoff_to_agent,
    is_user_in_handoff,
    resume_ai_mode,
)

from datetime import datetime
import pytz 

tz = pytz.timezone("Asia/Jerusalem")
now = datetime.now(tz)

weekdays_he = ["יום שני", "יום שלישי", "יום רביעי", "יום חמישי", "יום שישי", "יום שבת", "יום ראשון"]
weekday_he = weekdays_he[now.weekday()]

current_datetime = now.strftime("%d/%m/%Y %H:%M")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

OPENAI_API_KEY = config("OPENAI_API_KEY")
openai_client = OpenAI(api_key=OPENAI_API_KEY)

app = FastAPI()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/")
async def index():
    return {"status": "ok"}


@app.post("/message")
async def twilio_message(request: Request, Body: str = Form(...), db: Session = Depends(get_db)):
    form = await request.form()
    from_field = form.get("From") or form.get("from") or ""
    whatsapp_number = from_field.split("whatsapp:")[-1] if from_field else None
    body = form.get("Body") or form.get("body") or Body or ""

    if not whatsapp_number:
        logger.error("No 'From' in Twilio webhook")
        return ""

    logger.info(f"Incoming message from {whatsapp_number}: {body[:200]}")

    # If user is currently in handoff, forward message to Chatwoot and stop.
    if is_user_in_handoff(whatsapp_number):
        send_user_message_to_chatwoot(whatsapp_number, body)
        return ""

    system_prompt = ".אתה העוזר הדיגיטלי של מרפאת נוירולוגיה ומיגרנה ישראלית. ספק תשובות מקצועיות, מדויקות, קצרות (לא יותר מ-27 מילים!) ואמפתיות לשאלות מטופלים על נוירולוגיה, טיפולים (בהתאם למידע שלהלן), שירותי המרפאה, תיאום תורים או נושאים נלווים – בשפה עברית קולחת, מתאימה לקהל קליני ישראלי. מידע על הקליניקה ושירותיה: הקליניקה פועלת באופן פרטי בלבד, ללא שיתוף פעולה עם קופות. טיפולי מיגרנה: גפנטים, טיפול בבוטוקס, טיפול ביולוגי תת-עורי, טיפול ביולוגי תוך-ורידי, טיפול תרופתי מתקדם. טיפולי אפילפסיה: תרופות חדשניות, ניתוחי כריתת לזיה אפילפטוגנית, ניתוחי כריתה מכוונת (כולל ניטור פולשני). הפרעות קשב וריכוז: גישה מהירה לריטלין, אטנט, ויואנס, טיפול בנוירופידבק. שעות פעילות הקליניקה הם מ:11:00 עד 19:00, כל הימים חוץ מיום שישי ושבת שבהם הקליניקה לא עובדת PRODUODOPA (מתקדם וייחודי), טיפולים ל-NPH (כולל ניתוח שאנט), הזרקת בוטוקס. הוראות מענה: כאשר משתמש מבקש לשוחח עם נציג, לתאם תור, או שואל שאלה שרק נציג/צוות רפואי יכול לספק לה מענה – השב אך ורק: 'אני מעביר אותך לנציג אנושי'. אין להעביר שאלות קטנות, כלליות או טריוויאליות לנציג – השב ישירות בהתאם לידע הקיים. בכל יתר המקרים: בצע קודם נימוק פנימי (סטפ-ביי-סטפ, לא מוצג למשתמש), נתח את צורכי המשתמש והבעיה, וגזור מסקנה. רק לאחר נימוק פנימי כתוב תשובה מקצועית, תמציתית, אמפתית ומדויקת – עד 27 מילים, כפסקה אחת. אין לספק ייעוץ פרטני. תמיד המלץ לפנות למרפאה או רופא להתאמה אישית. כתוב בעברית, ברור, ענייני וקליני. הימנע ממידע עודף או מושגים שאינם מתאימים. דגשים לוגיים: שמור נימוק פנימי מלא. במקרים הדורשים נציג – פעל לפי ההנחיות בלבד. שאלות פשוטות, כלליות או מידע ידוע – השב ישירות. תשובה סופית לא יותר מ-27 מילים. פורמט תשובה: פסקה קצרה (עד 27 מילים), ברורה, מנומסת ומקצועית בעברית בלבד. במקרה נציג – 'אני מעביר אותך לנציג אנושי' בלבד. שאלות קטנות/כלליות: תשובה עניינית עד 27 מילים, לא העברה לנציג. שמור מבנה תחילה-נימוק-מסקנה. דוגמאות: קלט: אני רוצה לדבר עם נציג לגבי הטיפול שלי → פלט: 'אני מעביר אותך לנציג אנושי'. קלט: רציתי לדעת מהם תופעות הלוואי של טיפול תרופתי למיגרנה → פלט: תופעות לוואי נפוצות כוללות עייפות, סחרחורות או בחילה. יש לפנות למרפאה להתאמה אישית. (עד 27 מילים). קלט: מה השעה היום? → פלט: כעת השעה [שעה נוכחית]. אשמח לעזור בעוד משהו. (עד 27 מילים). תזכורת עיקרית: ענה 'אני מעביר אותך לנציג אנושי' רק במקרים: משתמש מבקש לשוחח עם נציג, לתאם תור, או שאלה הדורשת מענה נציג/צוות המרפאה. שאלות קטנות, טריוויאליות או ידועות – השב ישירות. בכל יתר המקרים בצע נימוק פנימי וספק תשובה עניינית, מקצועית, מילולית בלבד, בעברית רהוטה וקצרה – לא יותר מ-27 מילים. "

    system_prompt_with_time = f"היום {weekday_he}, התאריך והזמן הנוכחי הוא {current_datetime}. " + system_prompt


    messages = [
        {"role": "system", "content": system_prompt_with_time},
        {"role": "user", "content": body},
    ]

    try:
        response = openai_client.chat.completions.create(
            model="chatgpt-4o-latest",
            messages=messages,
            max_tokens=150,
            temperature=0.7,
        )
        chatgpt_response = response.choices[0].message.content.strip()
    except Exception:
        logger.exception("OpenAI error")
        chatgpt_response = "מצטער, יש בעיה זמנית. נסו שוב מאוחר יותר."

    try:
        conv = (
            db.query(Conversation)
            .filter(Conversation.sender == whatsapp_number)
            .order_by(Conversation.id.desc())
            .first()
        )
        if not conv:
            conv = Conversation(sender=whatsapp_number, message=body, response=chatgpt_response)
            db.add(conv)
        else:
            conv.message = body
            conv.response = chatgpt_response
        db.commit()
    except Exception:
        logger.exception("DB err")
        db.rollback()

    # Send AI reply
    send_message(whatsapp_number, chatgpt_response)

    # If AI instructed to hand off, switch to Chatwoot and forward latest msg
    if "מעביר אותך לנציג" in chatgpt_response or "מעביר אותך לנציג אנושי" in chatgpt_response:
        success = handoff_to_agent(whatsapp_number)
        if success:
            send_user_message_to_chatwoot(whatsapp_number, body)

    return ""


def _extract_conversation(payload: dict) -> dict:
    if isinstance(payload.get("conversation"), dict):
        return payload["conversation"]
    return payload


def _extract_phone_number(payload: dict) -> str | None:
    conv = _extract_conversation(payload)

    phone = (conv.get("meta") or {}).get("sender", {}).get("phone_number")
    if phone:
        return phone

    msgs = conv.get("messages") or payload.get("messages") or []
    if isinstance(msgs, list):
        for m in msgs:
            phone = (m.get("sender") or {}).get("phone_number")
            if phone:
                return phone

    source_id = (conv.get("contact_inbox") or {}).get("source_id")
    if isinstance(source_id, str) and "whatsapp:" in source_id:
        return source_id.split("whatsapp:")[-1]

    return None


def _is_resolution_event(payload: dict) -> bool:
    conv = _extract_conversation(payload)
    status = conv.get("status")
    if status == "resolved":
        return True

    changed = payload.get("changed_attributes") or conv.get("changed_attributes") or []
    if isinstance(changed, list):
        for attr in changed:
            if isinstance(attr, dict) and "status" in attr:
                cur = (attr["status"] or {}).get("current_value")
                if cur == "resolved":
                    return True

    event = payload.get("event") or conv.get("event")
    if event == "conversation_resolved":
        return True

    return False


@app.post("/chatwoot_webhook")
async def chatwoot_webhook(request: Request):
    payload = await request.json()
    logger.info(f"Chatwoot webhook received: {payload}")

    try:
        # Extract phone number
        phone_number = None
        if payload.get("contact_inbox", {}).get("source_id"):
            phone_number = payload["contact_inbox"]["source_id"].replace("whatsapp:", "")
        elif payload.get("sender", {}).get("phone_number"):
            phone_number = payload["sender"]["phone_number"]
        elif payload.get("conversation", {}).get("meta", {}).get("sender", {}).get("phone_number"):
            phone_number = payload["conversation"]["meta"]["sender"]["phone_number"]

        if not phone_number:
            logger.warning("No phone_number in webhook payload — skipping")
            return {"status": "ignored"}

        db = SessionLocal()
        user_state = db.query(UserState).filter_by(sender=phone_number).first()
        if not user_state:
            user_state = UserState(sender=phone_number)
            db.add(user_state)

        # Determine conversation status
        status = payload.get("status") or payload.get("conversation", {}).get("status")

        if status == "resolved":
            if user_state.in_handoff:
                user_state.in_handoff = False
                db.commit()
                logger.info(f"Conversation resolved for {phone_number}, handoff disabled.")
                # Send message to user
                from utils import send_message
                send_message(phone_number, "הפנייה נסגרה, אנחנו זמינים ועומדים לרשותכם")
        elif status == "open":
            # Check if agent is assigned
            sender_type = payload.get("sender", {}).get("type") or payload.get("conversation", {}).get("meta", {}).get("assignee", {}).get("type")
            if sender_type == "agent":
                user_state.in_handoff = True
                db.commit()
                logger.info(f"Handoff activated for {phone_number} due to agent activity.")

        db.close()

    except Exception as e:
        logger.error(f"Error processing webhook: {e}")

    return {"status": "ok"}
