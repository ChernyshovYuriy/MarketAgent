"""
core/email_notifier.py
Sends email alerts for HIGH_PRIORITY (and optionally WATCH) events.

Supports:
  - Plain SMTP with STARTTLS (Gmail, Outlook, custom mailserver)
  - Gmail App Password (recommended for Gmail)
  - SendGrid API (optional, set provider: sendgrid in config)

Config block expected in config.yaml:

  email:
    enabled: true
    provider: smtp               # smtp | sendgrid
    from_address: agent@example.com
    to_addresses:
      - you@example.com
    notify_labels:               # which score labels trigger an email
      - HIGH_PRIORITY
      # - WATCH                  # uncomment to also get WATCH alerts
    min_score: 75                # extra guard — only email if score >= this
    cooldown_minutes: 60         # don't re-email the same ticker within N min
    batch: true                  # send one digest email per cycle (vs one per event)

    smtp:
      host: smtp.gmail.com
      port: 587
      username: agent@gmail.com
      password: "xxxx xxxx xxxx xxxx"   # Gmail App Password

    sendgrid:
      api_key: SG.xxxxxxxxxxxx
"""

import logging
import smtplib
import ssl
import time
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


class EmailNotifier:
    def __init__(self, config: Dict[str, Any]):
        self.cfg = config.get("email", {})
        self.enabled = self.cfg.get("enabled", False)

        if not self.enabled:
            logger.info("[Email] Notifications disabled in config.")
            return

        self.provider       = self.cfg.get("provider", "smtp").lower()
        self.from_addr      = self.cfg.get("from_address", "")
        self.to_addrs       = self.cfg.get("to_addresses", [])
        self.notify_labels  = set(self.cfg.get("notify_labels", ["HIGH_PRIORITY"]))
        self.min_score      = self.cfg.get("min_score", 75)
        self.batch          = self.cfg.get("batch", True)
        self.cooldown_secs  = self.cfg.get("cooldown_minutes", 60) * 60

        # ticker → last_notified_timestamp
        self._cooldown_cache: Dict[str, float] = {}

        if not self.to_addrs:
            logger.warning("[Email] No to_addresses configured — notifications disabled.")
            self.enabled = False

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def notify_cycle(self, events: List[Dict[str, Any]]):
        """
        Called once per agent cycle with the full list of processed events.
        Filters to qualifying events, respects cooldown, sends one digest.
        """
        if not self.enabled:
            return

        qualifying = self._filter(events)
        if not qualifying:
            logger.debug("[Email] No qualifying events this cycle.")
            return

        if self.batch:
            self._send_digest(qualifying)
        else:
            for event in qualifying:
                self._send_single(event)

    # ------------------------------------------------------------------ #
    #  Filtering                                                           #
    # ------------------------------------------------------------------ #

    def _filter(self, events: List[Dict]) -> List[Dict]:
        now = time.monotonic()
        result = []
        for event in events:
            if event.get("label") not in self.notify_labels:
                continue
            if event.get("final_score", 0) < self.min_score:
                continue
            # Cooldown check per ticker
            for ticker in event.get("tickers", []):
                last = self._cooldown_cache.get(ticker, float("-inf"))
                if now - last >= self.cooldown_secs:
                    result.append(event)
                    # Mark all tickers in this event as notified
                    for t in event.get("tickers", []):
                        self._cooldown_cache[t] = now
                    break   # one event → one cooldown update, then move on
        return result

    # ------------------------------------------------------------------ #
    #  Email builders                                                      #
    # ------------------------------------------------------------------ #

    def _send_digest(self, events: List[Dict]):
        """One email summarising all qualifying events this cycle."""
        count   = len(events)
        subject = (
            f"🚨 {count} HIGH PRIORITY alert{'s' if count > 1 else ''} — CA Market Agent"
            if any(e["label"] == "HIGH_PRIORITY" for e in events)
            else f"📋 {count} market alert{'s' if count > 1 else ''} — CA Market Agent"
        )
        body_text, body_html = self._build_digest_body(events)
        self._send(subject, body_text, body_html)
        logger.info("[Email] Digest sent: %d events → %s", count, self.to_addrs)

    def _send_single(self, event: Dict):
        tickers = ", ".join(event.get("tickers", []))
        score   = event.get("final_score", 0)
        label   = event.get("label", "")
        subject = f"[{label}] {tickers}  score={score:.0f} — CA Market Agent"
        body_text, body_html = self._build_single_body(event)
        self._send(subject, body_text, body_html)
        logger.info("[Email] Single alert sent: %s (%.0f) → %s",
                    tickers, score, self.to_addrs)

    # ------------------------------------------------------------------ #
    #  Body builders                                                       #
    # ------------------------------------------------------------------ #

    def _build_digest_body(self, events: List[Dict]):
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        # ---- Plain text ----
        lines = [f"CA Market Agent — cycle alert  [{ts}]", "=" * 56, ""]
        for e in events:
            tickers = ", ".join(e.get("tickers", []))
            lines += [
                f"  {'★' if e['label'] == 'HIGH_PRIORITY' else '○'} [{e['label']}]  "
                f"{tickers}  —  score {e.get('final_score', 0):.0f}/100",
                f"    {e.get('headline', '')}",
                f"    Type    : {e.get('event_type', '').replace('_', ' ').title()}",
                f"    Source  : {e.get('source', '')}",
                f"    Link    : {e.get('url', 'n/a')}",
                f"    Flags   : {', '.join(e.get('risk_flags', [])) or 'none'}",
                "",
            ]
        lines += ["--", "You are receiving this because you configured CA Market Agent.",
                  "Edit config.yaml → email section to change preferences."]
        plain = "\n".join(lines)

        # ---- HTML ----
        rows = ""
        for e in events:
            tickers  = ", ".join(e.get("tickers", []))
            score    = e.get("final_score", 0)
            label    = e.get("label", "")
            flags    = ", ".join(e.get("risk_flags", [])) or "—"
            headline = e.get("headline", "")
            url      = e.get("url", "")
            etype    = e.get("event_type", "").replace("_", " ").title()
            source   = e.get("source", "")
            badge_bg = "#c0392b" if label == "HIGH_PRIORITY" else "#2980b9"
            link_td  = (f'<a href="{url}" style="color:#2980b9">View source</a>'
                        if url else "—")
            rows += f"""
            <tr style="border-bottom:1px solid #eee">
              <td style="padding:10px 8px;font-weight:bold;white-space:nowrap">
                <span style="background:{badge_bg};color:#fff;padding:2px 7px;
                             border-radius:3px;font-size:11px">{label}</span>
                <br><span style="font-size:18px">{tickers}</span>
              </td>
              <td style="padding:10px 8px;text-align:center;font-size:22px;
                         font-weight:bold;color:{badge_bg}">{score:.0f}</td>
              <td style="padding:10px 8px">
                <strong>{headline}</strong><br>
                <span style="color:#666;font-size:12px">
                  {etype} &nbsp;·&nbsp; {source}
                </span>
              </td>
              <td style="padding:10px 8px;font-size:12px;color:#c0392b">{flags}</td>
              <td style="padding:10px 8px;font-size:12px">{link_td}</td>
            </tr>"""

        html = f"""<!DOCTYPE html>
<html><body style="font-family:Arial,sans-serif;max-width:900px;margin:0 auto;padding:20px">
  <h2 style="color:#2c3e50;border-bottom:2px solid #e74c3c;padding-bottom:8px">
    📈 CA Market Agent — {len(events)} Alert{'s' if len(events)>1 else ''}
    <span style="font-size:14px;font-weight:normal;color:#888">{ts}</span>
  </h2>
  <table style="width:100%;border-collapse:collapse">
    <thead>
      <tr style="background:#f5f6fa;text-align:left">
        <th style="padding:8px">Ticker</th>
        <th style="padding:8px">Score</th>
        <th style="padding:8px">Headline</th>
        <th style="padding:8px">Risk Flags</th>
        <th style="padding:8px">Link</th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
  <p style="color:#aaa;font-size:11px;margin-top:24px">
    Sent by CA Market Agent · Edit <code>config.yaml → email</code> to change preferences.
  </p>
</body></html>"""
        return plain, html

    def _build_single_body(self, event: Dict):
        # Reuse digest builder for a one-event list
        return self._build_digest_body([event])

    # ------------------------------------------------------------------ #
    #  Transport                                                           #
    # ------------------------------------------------------------------ #

    def _send(self, subject: str, body_text: str, body_html: str):
        if self.provider == "sendgrid":
            self._send_sendgrid(subject, body_text, body_html)
        else:
            self._send_smtp(subject, body_text, body_html)

    def _send_smtp(self, subject: str, body_text: str, body_html: str):
        smtp_cfg  = self.cfg.get("smtp", {})
        host      = smtp_cfg.get("host", "smtp.gmail.com")
        port      = smtp_cfg.get("port", 587)
        username  = smtp_cfg.get("username", self.from_addr)
        password  = smtp_cfg.get("password", "")

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = self.from_addr
        msg["To"]      = ", ".join(self.to_addrs)
        msg.attach(MIMEText(body_text, "plain"))
        msg.attach(MIMEText(body_html, "html"))

        context = ssl.create_default_context()
        try:
            with smtplib.SMTP(host, port, timeout=15) as server:
                server.ehlo()
                server.starttls(context=context)
                server.ehlo()
                if username and password:
                    server.login(username, password)
                server.sendmail(self.from_addr, self.to_addrs, msg.as_string())
            logger.debug("[Email] SMTP delivery OK via %s:%d", host, port)
        except smtplib.SMTPAuthenticationError:
            logger.error(
                "[Email] SMTP authentication failed for %s. "
                "For Gmail use an App Password: "
                "https://myaccount.google.com/apppasswords", username
            )
        except Exception as exc:
            logger.error("[Email] SMTP send failed: %s", exc)

    def _send_sendgrid(self, subject: str, body_text: str, body_html: str):
        """SendGrid HTTP API — no extra library needed."""
        import json as _json
        import urllib.request as _urllib

        sg_cfg  = self.cfg.get("sendgrid", {})
        api_key = sg_cfg.get("api_key", "")
        if not api_key:
            logger.error("[Email] SendGrid api_key not set in config.")
            return

        payload = _json.dumps({
            "personalizations": [{"to": [{"email": a} for a in self.to_addrs]}],
            "from":    {"email": self.from_addr},
            "subject": subject,
            "content": [
                {"type": "text/plain", "value": body_text},
                {"type": "text/html",  "value": body_html},
            ],
        }).encode()

        req = _urllib.Request(
            "https://api.sendgrid.com/v3/mail/send",
            data=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type":  "application/json",
            },
            method="POST",
        )
        try:
            with _urllib.urlopen(req, timeout=15) as resp:
                if resp.status in (200, 202):
                    logger.debug("[Email] SendGrid delivery OK (status %d)", resp.status)
                else:
                    logger.error("[Email] SendGrid returned status %d", resp.status)
        except Exception as exc:
            logger.error("[Email] SendGrid send failed: %s", exc)
