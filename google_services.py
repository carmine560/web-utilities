"""Handle Google Calendar events and Gmail messages."""

from email.message import EmailMessage
import base64
import os
import re
import sys

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


def get_calendar_resource(credentials_path, calendar_id, summary, timezone):
    """Get a Google Calendar resource and create a new calendar if needed."""
    resource = build(
        "calendar", "v3", credentials=get_credentials(credentials_path)
    )

    if not calendar_id:
        try:
            calendar = (
                resource.calendars()
                .insert(body={"summary": summary, "timeZone": timezone})
                .execute()
            )
            calendar_id = calendar["id"]
        except HttpError as e:
            print(e)
            sys.exit(1)

    return (resource, calendar_id)


def insert_calendar_event(resource, calendar_id, body):
    """Insert an event into a calendar and print its start time and summary."""
    try:
        event = (
            resource.events()
            .insert(calendarId=calendar_id, body=body)
            .execute()
        )
        print(event.get("start")["dateTime"], event.get("summary"))
    except HttpError as e:
        print(e)
        sys.exit(1)


def send_email_message(
    credentials_path, subject, email_message_from, email_message_to, content
):
    """Send an email message via Gmail."""
    if email_message_from and email_message_to and content:
        resource = build(
            "gmail", "v1", credentials=get_credentials(credentials_path)
        )

        email_message = EmailMessage()
        email_message["Subject"] = subject
        email_message["From"] = email_message_from
        email_message["To"] = email_message_to
        email_message.set_content(content)

        body = {
            "raw": base64.urlsafe_b64encode(email_message.as_bytes()).decode()
        }
        try:
            resource.users().messages().send(userId="me", body=body).execute()
        except HttpError as e:
            print(e)
            sys.exit(1)


def extract_string_from_email(
    credentials_path, email_message_from, string_regex
):
    """Extract the latest matching string from Gmail messages."""
    if not all((credentials_path, email_message_from, string_regex)):
        return None

    resource = build(
        "gmail", "v1", credentials=get_credentials(credentials_path)
    )
    try:
        result = (
            resource.users()
            .messages()
            .list(userId="me", q=f"from:{email_message_from}", maxResults=5)
            .execute()
        )
    except HttpError as e:
        print(e)
        return None

    for summary in result.get("messages", []):
        try:
            message = (
                resource.users()
                .messages()
                .get(userId="me", id=summary["id"], format="full")
                .execute()
            )
        except HttpError as e:
            print(e)
            return None

        payload = message["payload"]

        # Try the single-part body first.
        data = payload.get("body", {}).get("data")
        if data:
            decoded_data = base64.urlsafe_b64decode(data).decode()
            match = re.search(string_regex, decoded_data)
            if match:
                return match.group(1)

        # Try multipart parts if the single-part body is missing.
        for part in payload.get("parts", []):
            part_data = part.get("body", {}).get("data")
            if part_data:
                decoded_data = base64.urlsafe_b64decode(part_data).decode()
                match = re.search(string_regex, decoded_data)
                if match:
                    return match.group(1)

    return None


def get_credentials(token_json):
    """Obtain valid Google API credentials from a JSON token file."""
    scopes = [
        "https://www.googleapis.com/auth/calendar",
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.send",
    ]
    credentials = None
    if os.path.isfile(token_json):
        credentials = Credentials.from_authorized_user_file(token_json, scopes)
    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        else:
            try:
                flow = InstalledAppFlow.from_client_secrets_file(
                    input("Path to client_secrets.json: "), scopes
                )
                credentials = flow.run_local_server(port=0)
            except (FileNotFoundError, ValueError) as e:
                print(e)
                sys.exit(1)
        with open(token_json, "w", encoding="utf-8") as token:
            token.write(credentials.to_json())
    return credentials
