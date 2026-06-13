"""Google Calendar and Gmail service utilities."""

import base64
import json
import os
import re
from email.message import EmailMessage

from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import Error as GoogleApiError
from googleapiclient.errors import HttpError

from core_utilities.errors import ExternalServiceError, UtilityOperationError
from core_utilities.file_utilities import read_encrypted_file
from core_utilities.file_utilities import write_encrypted_file


def _read_encrypted_credentials(token_json, scopes):
    """Read encrypted token JSON and build credentials."""
    encrypted_token_json = f"{token_json}.gpg"
    try:
        token_data = read_encrypted_file(encrypted_token_json)
        token_info = json.loads(token_data.decode("utf-8"))
        return Credentials.from_authorized_user_info(token_info, scopes)
    except (OSError, ValueError, GoogleAuthError, UtilityOperationError) as e:
        raise ExternalServiceError(
            "Unable to load Google credentials from "
            f"{encrypted_token_json}: {e}"
        ) from e


def _write_encrypted_credentials(token_json, credentials, fingerprint):
    """Encrypt and save Google credentials without a plaintext temp file."""
    encrypted_token_json = f"{token_json}.gpg"
    try:
        credentials_json = credentials.to_json()
        write_encrypted_file(
            encrypted_token_json,
            credentials_json.encode("utf-8"),
            fingerprint=fingerprint,
        )
    except (OSError, TypeError, ValueError, UtilityOperationError) as e:
        raise ExternalServiceError(
            "Unable to write Google credentials to "
            f"{encrypted_token_json}: {e}"
        ) from e


def get_credentials(token_json, fingerprint=""):
    """Obtain valid Google API credentials from an encrypted JSON token."""
    scopes = [
        "https://www.googleapis.com/auth/calendar",
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.send",
    ]
    credentials = None
    encrypted_token_json = f"{token_json}.gpg"
    if os.path.isfile(encrypted_token_json):
        credentials = _read_encrypted_credentials(token_json, scopes)
    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            try:
                credentials.refresh(Request())
            except (OSError, ValueError, GoogleAuthError) as e:
                raise ExternalServiceError(
                    "Unable to refresh Google credentials for "
                    f"{token_json}: {e}"
                ) from e
        else:
            try:
                flow = InstalledAppFlow.from_client_secrets_file(
                    input("Path to client_secrets.json: "), scopes
                )
                credentials = flow.run_local_server(port=0)
            except (OSError, ValueError, GoogleAuthError) as e:
                raise ExternalServiceError(
                    "Unable to obtain Google credentials for "
                    f"{token_json}: {e}"
                ) from e
        _write_encrypted_credentials(token_json, credentials, fingerprint)
    return credentials


def get_calendar_resource(
    credentials_path, calendar_id, summary, timezone, fingerprint=""
):
    """Get a Google Calendar resource and create a new calendar if needed."""
    credentials = get_credentials(credentials_path, fingerprint=fingerprint)
    try:
        resource = build("calendar", "v3", credentials=credentials)
    except (OSError, ValueError, GoogleAuthError, GoogleApiError) as e:
        raise ExternalServiceError(
            "Unable to build Google Calendar resource for "
            f"{credentials_path}: {e}"
        ) from e

    if not calendar_id:
        try:
            calendar = (
                resource.calendars()
                .insert(body={"summary": summary, "timeZone": timezone})
                .execute()
            )
            calendar_id = calendar["id"]
        except HttpError as e:
            raise ExternalServiceError(
                f"Unable to create calendar resource: {e}"
            ) from e

    return (resource, calendar_id)


def insert_calendar_event(resource, calendar_id, body):
    """Insert an event into a calendar and return the created event."""
    try:
        event = (
            resource.events()
            .insert(calendarId=calendar_id, body=body)
            .execute()
        )
    except HttpError as e:
        if getattr(e.resp, "status", None) == 409:
            return None
        raise ExternalServiceError(
            f"Unable to insert calendar event: {e}"
        ) from e
    return event


def send_email_message(
    credentials_path,
    subject,
    email_message_from,
    email_message_to,
    content,
    fingerprint="",
):
    """Send an email message via Gmail."""
    if not (email_message_from and email_message_to and content):
        return False

    credentials = get_credentials(credentials_path, fingerprint=fingerprint)
    try:
        resource = build("gmail", "v1", credentials=credentials)
    except (OSError, ValueError, GoogleAuthError, GoogleApiError) as e:
        raise ExternalServiceError(
            f"Unable to build Gmail resource for {credentials_path}: {e}"
        ) from e

    email_message = EmailMessage()
    email_message["Subject"] = subject
    email_message["From"] = email_message_from
    email_message["To"] = email_message_to
    email_message.set_content(content)

    body = {"raw": base64.urlsafe_b64encode(email_message.as_bytes()).decode()}
    try:
        resource.users().messages().send(userId="me", body=body).execute()
    except HttpError as e:
        raise ExternalServiceError(f"Unable to send Gmail message: {e}") from e
    return True


def extract_string_from_email(
    credentials_path, email_message_from, string_regex, fingerprint=""
):
    """Extract the latest matching string from Gmail messages."""
    if not all((credentials_path, email_message_from, string_regex)):
        return None

    credentials = get_credentials(credentials_path, fingerprint=fingerprint)
    try:
        resource = build("gmail", "v1", credentials=credentials)
    except (OSError, ValueError, GoogleAuthError, GoogleApiError) as e:
        raise ExternalServiceError(
            f"Unable to build Gmail resource for {credentials_path}: {e}"
        ) from e
    try:
        result = (
            resource.users()
            .messages()
            .list(userId="me", q=f"from:{email_message_from}", maxResults=5)
            .execute()
        )
    except HttpError as e:
        raise ExternalServiceError(
            f"Unable to list Gmail messages: {e}"
        ) from e

    for summary in result.get("messages", []):
        try:
            message = (
                resource.users()
                .messages()
                .get(userId="me", id=summary["id"], format="full")
                .execute()
            )
        except HttpError as e:
            raise ExternalServiceError(
                f"Unable to fetch Gmail message {summary['id']}: {e}"
            ) from e

        payload = message["payload"]

        # Try the single-part body first.
        data = payload.get("body", {}).get("data")
        if data:
            decoded_data = base64.urlsafe_b64decode(data).decode()
            matched = re.search(string_regex, decoded_data)
            if matched:
                return matched.group(1)

        # Try multipart parts if the single-part body is missing.
        for part in payload.get("parts", []):
            part_data = part.get("body", {}).get("data")
            if part_data:
                decoded_data = base64.urlsafe_b64decode(part_data).decode()
                matched = re.search(string_regex, decoded_data)
                if matched:
                    return matched.group(1)

    return None
