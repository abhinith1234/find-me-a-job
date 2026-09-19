from __future__ import annotations

from findmeajob import notify


class FakeSMTP:
    sent = None

    def __init__(self, host, port, timeout):
        assert (host, port, timeout) == ("smtp.test", 587, 30)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def starttls(self):
        pass

    def login(self, user, password):
        assert (user, password) == ("sender@example.com", "test-app-password")

    def send_message(self, message):
        self.sent = message
        FakeSMTP.sent = message


def test_send_builds_and_sends_html_email(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.test")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USER", "sender@example.com")
    monkeypatch.setenv("SMTP_PASS", "test-app-password")
    monkeypatch.setenv("MAIL_TO", "recipient@example.com")
    monkeypatch.setattr(notify.smtplib, "SMTP", FakeSMTP)

    notify.send("Test digest", "<h1>Test</h1>")

    assert FakeSMTP.sent["To"] == "recipient@example.com"
    assert FakeSMTP.sent["Subject"] == "Test digest"
    assert "Test" in FakeSMTP.sent.as_string()
