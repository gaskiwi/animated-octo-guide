from slack_logger import SlackLogger as _SL, init_logger as _init_logger
"""
run_school.py — School automation runner
Handles two entry points:
  1. Called by gateway when Blackbaud sends an assignment webhook
  2. Called by school_digest.py at morning digest time

Flow for assignments:
  - Parse assignment from Blackbaud payload
  - Ask qwen: should we complete this or research/summarize it?
  - Execute accordingly
  - Email result to personal address

Flow for digest:
  - Read unread Gmail from @sacredsf.org account
  - Pull upcoming assignments from Blackbaud REST API
  - Ask qwen to summarize, extract deadlines, organize
  - Email morning digest

Usage:
  python3 run_school.py assignment '<json payload>'
  python3 run_school.py digest
"""

import sys
import os
import json
import logging
import base64
import re
import textwrap
import smtplib
import email.mime.multipart
import email.mime.text
from pathlib import Path
from datetime import datetime, timedelta
from dotenv import load_dotenv
import requests
from slack_logger import SlackLogger as _SL, init_logger as _init_logger

load_dotenv(Path(__file__).parent / ".env")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ── Config ────────────────────────────────────────────────────────────────────
OLLAMA_URL        = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
PERSONAL_EMAIL    = os.environ.get("PERSONAL_EMAIL", "gas03272020@gmail.com")
SCHOOL_EMAIL      = os.environ.get("SCHOOL_EMAIL", "")           # set in .env
SMTP_HOST         = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT         = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER         = os.environ.get("SMTP_USER", "")              # school Gmail
SMTP_PASS         = os.environ.get("SMTP_APP_PASS", "")          # Gmail App Password
BLACKBAUD_SECRET  = os.environ.get("BLACKBAUD_WEBHOOK_SECRET", "")
CREDS_DIR         = Path("/home/pacers4ever/credentials")
GMAIL_TOKEN_FILE  = CREDS_DIR / "school_gmail_token.json"
GMAIL_CREDS_FILE  = CREDS_DIR / "school_gmail_credentials.json"

# ── qwen ──────────────────────────────────────────────────────────────────────
def ask_qwen(prompt, num_predict=2000):
    resp = requests.post(f"{OLLAMA_URL}/api/generate",
        json={"model": "qwen2.5-coder:7b", "prompt": prompt,
              "stream": False, "options": {"num_predict": num_predict}},
        timeout=300)
    resp.raise_for_status()
    return resp.json()["response"].strip()

# ── Gmail API ─────────────────────────────────────────────────────────────────
def get_gmail_service():
    """Build authenticated Gmail service using stored OAuth token."""
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build

        SCOPES = [
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.send",
        ]

        creds = None
        if GMAIL_TOKEN_FILE.exists():
            creds = Credentials.from_authorized_user_file(str(GMAIL_TOKEN_FILE), SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                GMAIL_TOKEN_FILE.write_text(creds.to_json())
            else:
                logging.error("Gmail token missing or invalid. Run school_auth.py to authorize.")
                return None

        return build("gmail", "v1", credentials=creds)
    except Exception as e:
        logging.error(f"Gmail service error: {e}")
        return None

def fetch_recent_emails(service, max_results=20, hours_back=24):
    """Fetch unread emails from the last N hours."""
    try:
        since = int((datetime.utcnow() - timedelta(hours=hours_back)).timestamp())
        query = f"is:unread after:{since}"
        result = service.users().messages().list(
            userId="me", q=query, maxResults=max_results
        ).execute()

        messages = result.get("messages", [])
        emails = []
        for msg in messages:
            detail = service.users().messages().get(
                userId="me", messageId=msg["id"], format="full"
            ).execute()

            headers = {h["name"]: h["value"] for h in detail["payload"]["headers"]}
            subject = headers.get("Subject", "(no subject)")
            sender  = headers.get("From", "unknown")
            date    = headers.get("Date", "")

            # Extract body text
            body = _extract_body(detail["payload"])

            emails.append({
                "id": msg["id"],
                "subject": subject,
                "from": sender,
                "date": date,
                "body": body[:2000],  # cap at 2000 chars
            })

        return emails
    except Exception as e:
        logging.error(f"Error fetching emails: {e}")
        return []

def _extract_body(payload):
    """Recursively extract plain text from Gmail message payload."""
    body = ""
    if "parts" in payload:
        for part in payload["parts"]:
            if part["mimeType"] == "text/plain":
                data = part["body"].get("data", "")
                body += base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
            elif "parts" in part:
                body += _extract_body(part)
    elif payload.get("mimeType") == "text/plain":
        data = payload["body"].get("data", "")
        body += base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
    return body.strip()

# ── Blackbaud API ─────────────────────────────────────────────────────────────
def get_blackbaud_assignments(days_ahead=7):
    """Fetch upcoming assignments from Blackbaud SKY API."""
    bb_token  = os.environ.get("BLACKBAUD_ACCESS_TOKEN", "")
    bb_subkey = os.environ.get("BLACKBAUD_SUBSCRIPTION_KEY", "")

    if not bb_token or not bb_subkey:
        logging.warning("Blackbaud credentials not configured — skipping assignment fetch")
        return []

    try:
        headers = {
            "Authorization": f"Bearer {bb_token}",
            "Bb-Api-Subscription-Key": bb_subkey,
        }
        # SKY API: assignments endpoint
        url = "https://api.sky.blackbaud.com/school/v1/assignments"
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        assignments = []
        for item in data.get("value", []):
            assignments.append({
                "title":       item.get("short_description", "Untitled"),
                "description": item.get("long_description", ""),
                "due":         item.get("due_date", ""),
                "class":       item.get("section_identifier", ""),
                "type":        item.get("type_label", ""),
            })
        return assignments
    except Exception as e:
        logging.error(f"Blackbaud API error: {e}")
        return []

# ── Agent decision & execution ────────────────────────────────────────────────
def decide_and_execute(assignment):
    """
    Ask qwen whether to complete or summarize/research this assignment,
    then do it and return the result.
    """
    title       = assignment.get("title", "")
    description = assignment.get("description", "")
    atype       = assignment.get("type", "")
    due         = assignment.get("due", "")
    class_name  = assignment.get("class", "")

    decision_prompt = textwrap.dedent(f"""
        You are a school assignment classifier.
        Given this assignment, decide:
        - "complete" if it's a coding task, math problem, short answer, quiz, or worksheet you can fully solve
        - "research" if it's an essay, project, lab report, or open-ended task needing human judgment

        Assignment:
        Title: {title}
        Class: {class_name}
        Type: {atype}
        Due: {due}
        Description: {description[:500]}

        Respond with ONLY one word: complete OR research
    """).strip()

    decision = ask_qwen(decision_prompt, num_predict=10).lower().strip()
    if "complete" in decision:
        mode = "complete"
    else:
        mode = "research"

    if mode == "complete":
        exec_prompt = textwrap.dedent(f"""
            You are a student completing a school assignment.
            Provide a complete, well-structured answer.

            Assignment: {title}
            Class: {class_name}
            Due: {due}
            Instructions: {description}

            Write the complete answer below:
        """).strip()
        result = ask_qwen(exec_prompt, num_predict=2000)
        label = "✅ Completed"
    else:
        exec_prompt = textwrap.dedent(f"""
            You are a study assistant helping a student understand an assignment.
            Provide: a summary of what's required, key concepts to research,
            a suggested outline, and 3-5 specific resources or approaches.

            Assignment: {title}
            Class: {class_name}
            Due: {due}
            Instructions: {description}
        """).strip()
        result = ask_qwen(exec_prompt, num_predict=2000)
        label = "📚 Research Guide"

    return mode, label, result

# ── Email sender ──────────────────────────────────────────────────────────────
def send_email(subject, html_body, to=None):
    """Send an email via Gmail SMTP using App Password."""
    to = to or PERSONAL_EMAIL
    # Guardrail hard gate: email is deny-by-default for the swarm. The school
    # flow runs deliberately with .env.school, which sets GUARDRAILS_ALLOW_EMAIL.
    from guardrails import check_action, GuardrailViolation
    try:
        check_action("email_send", detail=f"to={to}", actor="run_school")
    except GuardrailViolation as gv:
        logging.error(str(gv))
        return False
    if not SMTP_USER or not SMTP_PASS:
        logging.error("SMTP_USER or SMTP_APP_PASS not set — cannot send email")
        return False

    try:
        msg = email.mime.multipart.MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = SMTP_USER
        msg["To"]      = to
        msg.attach(email.mime.text.MIMEText(html_body, "html"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, to, msg.as_string())
        logging.info(f"Email sent to {to}: {subject}")
        return True
    except Exception as e:
        logging.error(f"Email send failed: {e}")
        return False

# ── Assignment webhook handler ────────────────────────────────────────────────
def handle_assignment_webhook(payload_str):
    """Called when Blackbaud POSTs a new assignment event to our gateway."""
    try:
        payload = json.loads(payload_str)
    except json.JSONDecodeError:
        logging.error("Invalid JSON payload")
        return

    # Blackbaud webhook envelope
    events = payload.get("events", [payload])
    for event in events:
        data = event.get("data", event)
        assignment = {
            "title":       data.get("short_description", data.get("title", "Unknown Assignment")),
            "description": data.get("long_description", data.get("description", "")),
            "due":         data.get("due_date", data.get("due", "")),
            "class":       data.get("section_identifier", data.get("class", "")),
            "type":        data.get("type_label", data.get("type", "")),
        }

        logging.info(f"Processing assignment: {assignment['title']}")
        _slog = _init_logger(token=SLACK_BOT_TOKEN, channel=SLACK_CHANNEL)
        _slog.start(title="📋 Assignment", task=assignment['title'], model="qwen2.5-coder")
        _slog.thinking(f"Deciding how to handle: {assignment['title'][:80]}…")
        mode, label, result = decide_and_execute(assignment)

        subject = f"[School Agent] {label}: {assignment['title']}"
        html = _assignment_email_html(assignment, label, result)
        send_email(subject, html)
        _slog.done(f"{label}: {assignment['title']}", result=result[:400])

# ── Morning digest ────────────────────────────────────────────────────────────
def run_digest():
    """Build and send the morning school digest."""
    logging.info("Starting morning school digest...")
    _slog = _init_logger(token=SLACK_BOT_TOKEN, channel=SLACK_CHANNEL)
    _slog.start(title="📚 School Digest", task="Morning briefing", model="qwen2.5-coder")

    today = datetime.now().strftime("%A, %B %-d")

    # 1. Fetch emails
    gmail = get_gmail_service()
    emails = []
    if gmail:
        emails = fetch_recent_emails(gmail, hours_back=24)
        logging.info(f"Fetched {len(emails)} emails")
        _slog.step(f"Fetched {len(emails)} emails from @sacredsf.org")
    else:
        logging.warning("Gmail unavailable — digest will skip emails")

    # 2. Fetch assignments
    assignments = get_blackbaud_assignments(days_ahead=7)
    logging.info(f"Fetched {len(assignments)} upcoming assignments")
    _slog.step(f"Fetched {len(assignments)} upcoming Blackbaud assignments")

    # 3. Ask qwen to summarize everything
    email_text = ""
    if emails:
        email_text = "RECENT EMAILS:\n"
        for e in emails[:10]:
            email_text += f"  From: {e['from']}\n  Subject: {e['subject']}\n  Preview: {e['body'][:300]}\n\n"

    assignment_text = ""
    if assignments:
        assignment_text = "UPCOMING ASSIGNMENTS:\n"
        for a in assignments[:10]:
            assignment_text += f"  [{a['class']}] {a['title']} — due {a['due']}\n  {a['description'][:200]}\n\n"

    if not email_text and not assignment_text:
        logging.info("Nothing to digest today")
        send_email(
            f"[School Digest] {today} — Nothing new",
            f"<p>No new emails or assignments found for {today}.</p>"
        )
        return

    _slog.thinking("qwen summarizing emails and assignments…")
    digest_prompt = textwrap.dedent(f"""
        You are a school assistant creating a morning briefing for a student.
        Today is {today}.

        Analyze the following and produce a structured morning digest with:
        1. **Action Items** — things that need to be done today or soon (with deadlines)
        2. **Email Summary** — key points from teacher/school emails, grouped by importance
        3. **Upcoming Assignments** — organized by due date, with brief descriptions
        4. **Quick Notes** — anything else worth flagging

        Keep each section concise. Use clear headers.

        {email_text}
        {assignment_text}
    """).strip()

    summary = ask_qwen(digest_prompt, num_predict=2000)
    html = _digest_email_html(today, summary, emails, assignments)
    send_email(f"[School Digest] {today}", html)
    logging.info("Morning digest sent")
    _slog.done("Morning digest emailed", result=f"{len(emails)} emails · {len(assignments)} assignments processed")

# ── HTML templates ────────────────────────────────────────────────────────────
def _digest_email_html(today, summary, emails, assignments):
    email_rows = "".join(
        f"<tr><td style='padding:4px 8px;color:#555'>{e['from'][:40]}</td>"
        f"<td style='padding:4px 8px'>{e['subject']}</td></tr>"
        for e in emails[:8]
    )
    assign_rows = "".join(
        f"<tr><td style='padding:4px 8px;color:#555'>{a['class']}</td>"
        f"<td style='padding:4px 8px'>{a['title']}</td>"
        f"<td style='padding:4px 8px;color:#e44'>{a['due']}</td></tr>"
        for a in assignments[:8]
    )

    summary_html = summary.replace("\n", "<br>").replace("**", "<strong>").replace("**", "</strong>")

    return f"""
    <html><body style="font-family:Arial,sans-serif;max-width:700px;margin:auto;color:#222">
    <div style="background:#1a1a2e;color:white;padding:20px;border-radius:8px 8px 0 0">
        <h2 style="margin:0">📚 School Digest — {today}</h2>
        <p style="margin:4px 0;opacity:0.7">Generated by your school agent · kamrui</p>
    </div>
    <div style="padding:20px;background:#f9f9f9;border:1px solid #ddd">
        <div style="background:white;padding:16px;border-radius:6px;margin-bottom:16px">
            {summary_html}
        </div>
        {'<h3>📧 Emails Processed</h3><table style="width:100%;border-collapse:collapse"><tr style="background:#eee"><th style="text-align:left;padding:4px 8px">From</th><th style="text-align:left;padding:4px 8px">Subject</th></tr>' + email_rows + '</table>' if email_rows else ''}
        {'<h3>📋 Assignments</h3><table style="width:100%;border-collapse:collapse"><tr style="background:#eee"><th style="text-align:left;padding:4px 8px">Class</th><th style="text-align:left;padding:4px 8px">Assignment</th><th style="text-align:left;padding:4px 8px">Due</th></tr>' + assign_rows + '</table>' if assign_rows else ''}
    </div>
    <div style="padding:10px;text-align:center;color:#999;font-size:12px">
        Powered by qwen2.5-coder on kamrui · openclaw agent
    </div>
    </body></html>
    """

def _assignment_email_html(assignment, label, result):
    result_html = result.replace("\n", "<br>")
    return f"""
    <html><body style="font-family:Arial,sans-serif;max-width:700px;margin:auto;color:#222">
    <div style="background:#1a1a2e;color:white;padding:20px;border-radius:8px 8px 0 0">
        <h2 style="margin:0">{label}</h2>
        <p style="margin:4px 0;font-size:18px">{assignment['title']}</p>
    </div>
    <div style="padding:16px;background:#f9f9f9;border:1px solid #ddd">
        <p><strong>Class:</strong> {assignment['class']} &nbsp;|&nbsp;
           <strong>Type:</strong> {assignment['type']} &nbsp;|&nbsp;
           <strong>Due:</strong> {assignment['due']}</p>
        <hr>
        <div style="background:white;padding:16px;border-radius:6px">
            {result_html}
        </div>
    </div>
    <div style="padding:10px;text-align:center;color:#999;font-size:12px">
        Powered by qwen2.5-coder on kamrui · openclaw agent
    </div>
    </body></html>
    """

# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "digest"
    if mode == "assignment":
        payload = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else "{}"
        handle_assignment_webhook(payload)
    elif mode == "digest":
        run_digest()
    else:
        print(f"Unknown mode: {mode}. Use 'assignment' or 'digest'")
        sys.exit(1)
