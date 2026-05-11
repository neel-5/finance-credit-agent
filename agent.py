"""
Finance Credit Follow-Up Email Agent
Core agent logic: ingestion, staging, LLM email generation, logging, dry-run.
"""

import os
import re
import json
import sqlite3
import smtplib
import logging
from datetime import datetime, date
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import pandas as pd
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
DB_PATH = os.getenv("DB_PATH", "audit.db")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

STAGE_CONFIG = {
    1: {
        "label": "Stage 1 – Warm & Friendly",
        "tone": "warm_friendly",
        "days_range": (1, 7),
        "subject_prefix": "Quick Reminder",
    },
    2: {
        "label": "Stage 2 – Polite but Firm",
        "tone": "polite_firm",
        "days_range": (8, 14),
        "subject_prefix": "Payment Reminder",
    },
    3: {
        "label": "Stage 3 – Formal & Serious",
        "tone": "formal_serious",
        "days_range": (15, 21),
        "subject_prefix": "IMPORTANT: Outstanding Payment",
    },
    4: {
        "label": "Stage 4 – Stern & Urgent",
        "tone": "stern_urgent",
        "days_range": (22, 30),
        "subject_prefix": "FINAL NOTICE",
    },
}

TONE_INSTRUCTIONS = {
    "warm_friendly": (
        "Write a warm, friendly, and polite payment reminder. "
        "Assume the client may have simply overlooked the invoice. "
        "Keep the tone conversational and appreciative. "
        "Do not pressure or threaten."
    ),
    "polite_firm": (
        "Write a polite but firm payment reminder. "
        "Note that the payment is still pending and request a confirmation of the payment date. "
        "Be professional and clear without being aggressive."
    ),
    "formal_serious": (
        "Write a formal and serious payment reminder. "
        "Express escalating concern about the outstanding amount. "
        "Mention that continued non-payment may impact their credit terms. "
        "Request a response within 48 hours. Keep the language professional and direct."
    ),
    "stern_urgent": (
        "Write a stern and urgent final payment reminder. "
        "This is the last automated notice before escalation to the legal and recovery team. "
        "Be direct, firm, and unambiguous. Give the client 24 hours to act. "
        "Do not soften the message — the seriousness must be clear."
    ),
}


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}

# ── Input Sanitisation ────────────────────────────────────────────────────────

_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions",
    r"system\s*prompt",
    r"you\s+are\s+now",
    r"disregard\s+(all\s+)?",
    r"act\s+as\s+",
    r"jailbreak",
    r"<\s*script",
    r"```",
]
_INJECTION_RE = re.compile(
    "|".join(_INJECTION_PATTERNS), re.IGNORECASE
)


def sanitise_field(value: str) -> str:
    """
    Remove or neutralise content that could constitute a prompt injection
    attempt embedded inside invoice data fields.
    """
    if not isinstance(value, str):
        return str(value)
    if _INJECTION_RE.search(value):
        logger.warning("Potential prompt injection detected in field value: %r — stripped.", value)
        return "[REDACTED]"
    # Strip leading/trailing whitespace; collapse interior whitespace runs
    return " ".join(value.split())


# ── Database ──────────────────────────────────────────────────────────────────

def init_db(db_path: str = DB_PATH) -> None:
    """Create the audit log table if it doesn't already exist."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS email_audit (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp     TEXT    NOT NULL,
            invoice_no    TEXT    NOT NULL,
            client_name   TEXT    NOT NULL,
            contact_email TEXT    NOT NULL,
            amount        REAL    NOT NULL,
            currency      TEXT    NOT NULL,
            due_date      TEXT    NOT NULL,
            days_overdue  INTEGER NOT NULL,
            stage         INTEGER NOT NULL,
            tone          TEXT    NOT NULL,
            subject       TEXT    NOT NULL,
            body          TEXT    NOT NULL,
            send_status   TEXT    NOT NULL,
            dry_run       INTEGER NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS escalation_log (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp     TEXT    NOT NULL,
            invoice_no    TEXT    NOT NULL,
            client_name   TEXT    NOT NULL,
            contact_email TEXT    NOT NULL,
            amount        REAL    NOT NULL,
            currency      TEXT    NOT NULL,
            due_date      TEXT    NOT NULL,
            days_overdue  INTEGER NOT NULL,
            status        TEXT    NOT NULL DEFAULT 'pending_review'
        )
        """
    )
    conn.commit()
    conn.close()


def log_email(
    invoice_no: str,
    client_name: str,
    contact_email: str,
    amount: float,
    currency: str,
    due_date: str,
    days_overdue: int,
    stage: int,
    tone: str,
    subject: str,
    body: str,
    send_status: str,
    dry_run: bool,
    db_path: str = DB_PATH,
) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT INTO email_audit
            (timestamp, invoice_no, client_name, contact_email, amount, currency,
             due_date, days_overdue, stage, tone, subject, body, send_status, dry_run)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            datetime.utcnow().isoformat(),
            invoice_no, client_name, contact_email,
            amount, currency, due_date, days_overdue,
            stage, tone, subject, body, send_status,
            int(dry_run),
        ),
    )
    conn.commit()
    conn.close()


def log_escalation(
    invoice_no: str,
    client_name: str,
    contact_email: str,
    amount: float,
    currency: str,
    due_date: str,
    days_overdue: int,
    db_path: str = DB_PATH,
) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT INTO escalation_log
            (timestamp, invoice_no, client_name, contact_email, amount, currency,
             due_date, days_overdue)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            datetime.utcnow().isoformat(),
            invoice_no, client_name, contact_email,
            amount, currency, due_date, days_overdue,
        ),
    )
    conn.commit()
    conn.close()


# ── Data Ingestion ────────────────────────────────────────────────────────────

REQUIRED_COLUMNS = {
    "invoice_no", "client_name", "client_salutation",
    "amount", "currency", "due_date", "contact_email",
    "follow_up_count", "payment_link",
}


def load_invoices(csv_path: str) -> pd.DataFrame:
    """Load and validate the invoices CSV."""
    df = pd.read_csv(csv_path)
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"CSV is missing required columns: {missing}")

    df["due_date"] = pd.to_datetime(df["due_date"]).dt.date
    today = date.today()
    df["days_overdue"] = df["due_date"].apply(
        lambda d: max((today - d).days, 0)
    )
    # Only process overdue invoices
    df = df[df["days_overdue"] > 0].copy()

    # Sanitise text fields against prompt injection
    for col in ["client_name", "client_salutation", "invoice_no", "payment_link"]:
        df[col] = df[col].apply(sanitise_field)

    return df.reset_index(drop=True)


def determine_stage(days_overdue: int) -> int | None:
    """Return the follow-up stage (1-4), or None if >30 days (escalate)."""
    if days_overdue > 30:
        return None
    for stage, cfg in STAGE_CONFIG.items():
        lo, hi = cfg["days_range"]
        if lo <= days_overdue <= hi:
            return stage
    return None


# ── LLM Email Generation ──────────────────────────────────────────────────────

def _build_prompt(row: dict, stage: int) -> str:
    cfg = STAGE_CONFIG[stage]
    tone_instruction = TONE_INSTRUCTIONS[cfg["tone"]]
    return f"""You are a professional finance assistant generating a credit follow-up email.

TASK: {tone_instruction}

INVOICE DETAILS (use ALL of these in the email — do not invent any other details):
- Client Name: {row['client_name']}
- Salutation: {row['client_salutation']}
- Invoice Number: {row['invoice_no']}
- Amount Due: {row['currency']} {row['amount']:,.2f}
- Due Date: {row['due_date']}
- Days Overdue: {row['days_overdue']}
- Payment Link: {row['payment_link']}

INSTRUCTIONS:
1. Address the client as "{row['client_salutation']} {row['client_name'].split()[-1]}" in the salutation.
2. Include the invoice number, amount, due date, days overdue, and payment link naturally within the email body.
3. Match the tone described above precisely.
4. Keep the email concise (3-5 short paragraphs max).
5. End with a professional sign-off from "Finance Team, Accounts Receivable".

OUTPUT FORMAT — respond ONLY with a valid JSON object, no markdown fences, no explanation:
{{
  "subject": "<email subject line>",
  "body": "<full email body as plain text, newlines as \\n>"
}}"""


class EmailGenerationError(RuntimeError):
    """A Gemini failure converted into a short, UI-safe message."""


def _friendly_gemini_error(exc: Exception) -> str:
    details = str(exc)
    lower_details = details.lower()

    if "api_key_invalid" in lower_details or "api key not valid" in lower_details:
        return (
            "Gemini rejected GEMINI_API_KEY. Generate a new Google AI Studio key "
            "and update both your local .env and Streamlit Cloud secrets."
        )
    if "429" in details or "quota" in lower_details or "resource_exhausted" in lower_details:
        return (
            "Gemini quota or rate limit was reached for this API key. Wait for "
            "quota reset, enable billing, or use another key."
        )
    if "404" in details or "not found" in lower_details:
        return (
            f"Gemini model '{GEMINI_MODEL}' is not available for this key. "
            "Set GEMINI_MODEL to a model listed in Google AI Studio."
        )
    return f"Gemini generation failed: {details}"


def generate_template_email(row: dict, stage: int) -> dict:
    """Create a deterministic dry-run fallback email when Gemini is unavailable."""
    cfg = STAGE_CONFIG[stage]
    last_name = row["client_name"].split()[-1]
    salutation = f"{row['client_salutation']} {last_name}"
    amount = f"{row['currency']} {float(row['amount']):,.2f}"
    invoice_no = row["invoice_no"]
    due_date = row["due_date"]
    days_overdue = int(row["days_overdue"])
    payment_link = row["payment_link"]

    subject = f"{cfg['subject_prefix']}: Invoice {invoice_no}"
    if stage == 1:
        opener = (
            f"I hope you are doing well. This is a friendly reminder that invoice "
            f"{invoice_no} for {amount}, due on {due_date}, is now {days_overdue} "
            "day(s) overdue."
        )
        action = "Whenever convenient, please complete the payment or let us know if it has already been processed."
    elif stage == 2:
        opener = (
            f"Our records show that invoice {invoice_no} for {amount}, due on "
            f"{due_date}, remains unpaid after {days_overdue} day(s)."
        )
        action = "Please confirm the expected payment date so we can update our records."
    elif stage == 3:
        opener = (
            f"We are following up formally on invoice {invoice_no} for {amount}, "
            f"which was due on {due_date} and is now {days_overdue} day(s) overdue."
        )
        action = "Please respond within 48 hours, as continued non-payment may affect your credit terms."
    else:
        opener = (
            f"This is a final automated notice for invoice {invoice_no} for {amount}, "
            f"due on {due_date}. The invoice is now {days_overdue} day(s) overdue."
        )
        action = "Please arrange payment within 24 hours to avoid escalation to the legal and recovery team."

    body = (
        f"Dear {salutation},\n\n"
        f"{opener}\n\n"
        f"{action} You can make the payment here: {payment_link}\n\n"
        "Regards,\n"
        "Finance Team, Accounts Receivable"
    )
    return {
        "subject": subject,
        "body": body,
        "provider": "template_fallback",
    }


def generate_email(
    row: dict,
    stage: int,
    allow_template_fallback: bool | None = None,
) -> dict:
    """
    Call the Gemini API to generate a personalised follow-up email.
    Returns {"subject": ..., "body": ...}
    """
    if allow_template_fallback is None:
        allow_template_fallback = _env_flag("ALLOW_TEMPLATE_FALLBACK", False)

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        message = "GEMINI_API_KEY not set. Add it to your .env file or Streamlit secrets."
        if allow_template_fallback:
            fallback = generate_template_email(row, stage)
            fallback["warning"] = message
            return fallback
        raise EmailGenerationError(message)

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        model_name=GEMINI_MODEL,
        generation_config=genai.GenerationConfig(
            temperature=0.4,
            response_mime_type="application/json",
        ),
    )

    prompt = _build_prompt(row, stage)
    try:
        response = model.generate_content(prompt)
    except Exception as exc:
        message = _friendly_gemini_error(exc)
        if allow_template_fallback:
            fallback = generate_template_email(row, stage)
            fallback["warning"] = message
            return fallback
        raise EmailGenerationError(message) from exc

    raw = response.text.strip()
    # Strip accidental markdown fences if the model adds them
    raw = re.sub(r"^```(?:json)?", "", raw, flags=re.IGNORECASE).strip()
    raw = re.sub(r"```$", "", raw).strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        message = f"Gemini returned non-JSON output for {row['invoice_no']}."
        if allow_template_fallback:
            fallback = generate_template_email(row, stage)
            fallback["warning"] = message
            return fallback
        raise EmailGenerationError(message) from exc

    required_keys = {"subject", "body"}
    if not required_keys.issubset(parsed.keys()):
        message = f"Gemini response missing keys. Got: {list(parsed.keys())}"
        if allow_template_fallback:
            fallback = generate_template_email(row, stage)
            fallback["warning"] = message
            return fallback
        raise EmailGenerationError(message)

    # Basic hallucination guard: verify invoice number appears in the body
    if row["invoice_no"] not in parsed["body"] and row["invoice_no"] not in parsed["subject"]:
        logger.warning(
            "Invoice number %s not found in generated email — possible hallucination.",
            row["invoice_no"],
        )

    parsed["provider"] = "gemini"
    return parsed


# ── Email Sending ─────────────────────────────────────────────────────────────

def send_email(
    to_address: str,
    subject: str,
    body: str,
) -> bool:
    """
    Send an email via SMTP. Returns True on success.
    Reads SMTP config from environment variables.
    """
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")
    sender_email = os.getenv("SENDER_EMAIL", smtp_user)

    if not smtp_user or not smtp_pass:
        raise EnvironmentError(
            "SMTP_USER and SMTP_PASS must be set in .env to send real emails."
        )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender_email
    msg["To"] = to_address
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.ehlo()
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(sender_email, to_address, msg.as_string())

    return True


# ── Main Processing Loop ──────────────────────────────────────────────────────

def process_invoices(
    csv_path: str,
    dry_run: bool = True,
    db_path: str = DB_PATH,
    allow_template_fallback: bool | None = None,
) -> list[dict]:
    """
    Full pipeline: load → stage → generate → (send or dry-run) → log.
    Returns a list of result dicts for display.
    """
    init_db(db_path)
    df = load_invoices(csv_path)
    results = []
    if allow_template_fallback is None:
        allow_template_fallback = _env_flag("ALLOW_TEMPLATE_FALLBACK", False)

    for _, row in df.iterrows():
        row_dict = row.to_dict()
        row_dict["due_date"] = str(row_dict["due_date"])
        days = int(row_dict["days_overdue"])
        stage = determine_stage(days)

        if stage is None:
            # Escalation cap: >30 days overdue — no email sent
            logger.info(
                "[ESCALATE] %s – %s – %d days overdue → flagged for legal review",
                row_dict["invoice_no"], row_dict["client_name"], days,
            )
            log_escalation(
                invoice_no=row_dict["invoice_no"],
                client_name=row_dict["client_name"],
                contact_email=row_dict["contact_email"],
                amount=float(row_dict["amount"]),
                currency=row_dict["currency"],
                due_date=row_dict["due_date"],
                days_overdue=days,
                db_path=db_path,
            )
            results.append({
                **row_dict,
                "stage": "ESCALATED",
                "tone": "legal_review",
                "subject": None,
                "body": None,
                "send_status": "escalated",
            })
            continue

        try:
            email_data = generate_email(
                row_dict,
                stage,
                allow_template_fallback=allow_template_fallback,
            )
        except Exception as exc:
            logger.error(
                "Failed to generate email for %s: %s",
                row_dict["invoice_no"], exc,
            )
            results.append({
                **row_dict,
                "stage": stage,
                "tone": STAGE_CONFIG[stage]["tone"],
                "subject": None,
                "body": None,
                "send_status": f"generation_error: {exc}",
            })
            continue

        subject = email_data["subject"]
        body = email_data["body"]
        tone = STAGE_CONFIG[stage]["tone"]
        provider = email_data.get("provider", "gemini")
        generation_warning = email_data.get("warning")

        if dry_run:
            send_status = "template_fallback" if provider == "template_fallback" else "dry_run"
            logger.info(
                "[DRY-RUN] %s → %s | Stage %d | %s",
                row_dict["invoice_no"], row_dict["contact_email"], stage, subject,
            )
        else:
            try:
                send_email(row_dict["contact_email"], subject, body)
                send_status = "sent"
                logger.info(
                    "[SENT] %s → %s", row_dict["invoice_no"], row_dict["contact_email"]
                )
            except Exception as exc:
                send_status = f"send_error: {exc}"
                logger.error(
                    "[SEND ERROR] %s: %s", row_dict["invoice_no"], exc
                )

        log_email(
            invoice_no=row_dict["invoice_no"],
            client_name=row_dict["client_name"],
            contact_email=row_dict["contact_email"],
            amount=float(row_dict["amount"]),
            currency=row_dict["currency"],
            due_date=row_dict["due_date"],
            days_overdue=days,
            stage=stage,
            tone=tone,
            subject=subject,
            body=body,
            send_status=send_status,
            dry_run=dry_run,
            db_path=db_path,
        )

        results.append({
            **row_dict,
            "stage": stage,
            "tone": tone,
            "subject": subject,
            "body": body,
            "send_status": send_status,
            "provider": provider,
            "generation_warning": generation_warning,
        })

    return results


# ── CLI Entrypoint ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Finance Credit Follow-Up Email Agent")
    parser.add_argument("--csv", default="invoices.csv", help="Path to invoices CSV")
    parser.add_argument(
        "--send",
        action="store_true",
        help="Actually send emails (default: dry-run mode)",
    )
    parser.add_argument("--db", default=DB_PATH, help="Path to SQLite audit DB")
    parser.add_argument(
        "--template-fallback",
        action="store_true",
        help="Use deterministic template emails if Gemini is unavailable.",
    )
    args = parser.parse_args()

    results = process_invoices(
        csv_path=args.csv,
        dry_run=not args.send,
        db_path=args.db,
        allow_template_fallback=args.template_fallback,
    )

    print("\n── Summary ──────────────────────────────────────────")
    for r in results:
        print(
            f"  {r['invoice_no']:20s} | {r['client_name']:20s} | "
            f"{r['days_overdue']:3d}d | Stage: {r['stage']} | {r['send_status']}"
        )
