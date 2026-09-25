"""Email notifications through Resend (https://resend.com)."""
import html
import os

import requests

RESEND_URL = "https://api.resend.com/emails"


def send_email(subject, html_body):
    """Send to NOTIFY_EMAIL. Returns True if Resend accepted it; never raises (a failed email must not break a request)."""
    key, to = os.environ.get("RESEND_API_KEY"), os.environ.get("NOTIFY_EMAIL")
    if not key or not to:
        return False
    sender = os.environ.get("RESEND_FROM", "AccidentAI <onboarding@resend.dev>")
    try:
        r = requests.post(RESEND_URL, timeout=15, headers={"Authorization": f"Bearer {key}"},
                          json={"from": sender, "to": [to], "subject": subject, "html": html_body})
        if not r.ok:
            print("Resend error:", r.status_code, r.text[:200])
        return r.ok
    except requests.RequestException as e:
        print("Resend unreachable:", e)
        return False


def download_email(info, total):
    rows = "".join(
        f"<tr><td style='padding:4px 12px 4px 0;color:#6b7280'>{html.escape(label)}</td>"
        f"<td style='padding:4px 0'><b>{html.escape(str(value))}</b></td></tr>"
        for label, value in info.items() if value)
    return f"""
    <div style="font-family:Segoe UI,Arial,sans-serif;max-width:520px;margin:auto;padding:24px;border:1px solid #e5e7eb;border-radius:12px">
      <h2 style="margin:0 0 4px;color:#1d4ed8">AccidentAI a été téléchargé</h2>
      <p style="margin:0 0 16px;color:#374151">Quelqu'un vient de cliquer sur « Télécharger pour Windows ».</p>
      <table style="font-size:14px;border-collapse:collapse">{rows}</table>
      <p style="margin:20px 0 0;font-size:15px">Total des téléchargements : <b>{total}</b></p>
    </div>"""
