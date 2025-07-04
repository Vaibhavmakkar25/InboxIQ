# email_fetcher.py

import os.path
import base64
import re
import pandas as pd
from bs4 import BeautifulSoup
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Define the scope of access needed for the Gmail API.
SCOPES = ['https://mail.google.com/']

def get_gmail_service():
    """
    Authenticates with the Gmail API and returns a service object.

    Handles token creation, storage (in token.json), and renewal.
    """
    creds = None
    # The file token.json stores the user's access and refresh tokens.
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)

    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    return build('gmail', 'v1', credentials=creds)

def fetch_email_metadata(service, max_emails=200, start_date=None, end_date=None):
    """
    Fetches email metadata in batches and returns it as a pandas DataFrame.

    This function is optimized for fetching a large number of emails for dashboard
    analysis by only requesting metadata (headers) and using batch requests.

    Args:
        service: The authenticated Gmail API service object.
        max_emails (int): The maximum number of email metadata to fetch.
        start_date (datetime, optional): The start date for filtering emails.
        end_date (datetime, optional): The end date for filtering emails.

    Returns:
        pd.DataFrame: A DataFrame with email metadata, or an empty DataFrame on error.
    """
    # Build the Gmail API query string based on the provided date range.
    query_parts = ['in:inbox']
    if start_date:
        query_parts.append(f"after:{start_date.strftime('%Y/%m/%d')}")
    if end_date:
        query_parts.append(f"before:{end_date.strftime('%Y/%m/%d')}")
    query_string = " ".join(query_parts)

    print(f"Fetching metadata for up to {max_emails} emails with query: '{query_string}'")

    try:
        # First, get a list of message IDs that match the query.
        results = service.users().messages().list(userId='me', q=query_string, maxResults=max_emails).execute()
        messages = results.get('messages', [])
        if not messages:
            return pd.DataFrame()

        email_data = []
        BATCH_SIZE = 100 # Gmail API batch limit is 100 requests.

        # Define a callback function to process the result of each request in the batch.
        def callback(request_id, response, exception):
            if exception is None:
                headers = response['payload']['headers']
                sender = next((h['value'] for h in headers if h['name'].lower() == 'from'), 'N/A')
                date = next((h['value'] for h in headers if h['name'].lower() == 'date'), 'N/A')
                email_data.append({'sender': sender, 'date': date})

        # Process message IDs in chunks of BATCH_SIZE.
        for i in range(0, len(messages), BATCH_SIZE):
            message_chunk = messages[i:i + BATCH_SIZE]
            # Create a new batch request object.
            batch = service.new_batch_http_request(callback=callback)
            print(f"Preparing batch for emails {i+1} to {i+len(message_chunk)}...")
            for message_info in message_chunk:
                # Add a GET request for each message's metadata to the batch.
                batch.add(service.users().messages().get(userId='me', id=message_info['id'], format='metadata'))
            batch.execute()

        if not email_data:
            return pd.DataFrame()

        # Convert the collected data into a pandas DataFrame for easy analysis.
        df = pd.DataFrame(email_data)
        # Extract the clean email address from the 'From' header (e.g., from "Sender Name <sender@example.com>").
        df['sender_email'] = df['sender'].apply(lambda x: re.search(r'<(.+?)>', x).group(1) if re.search(r'<(.+?)>', x) else x)

        # Process date and extract features needed for the dashboard plots.
        df['date'] = pd.to_datetime(df['date'], errors='coerce', utc=True)
        df.dropna(subset=['date'], inplace=True) # Drop rows where date parsing failed.
        df['sender_domain'] = df['sender_email'].str.split('@').str[1]
        df['hour'] = df['date'].dt.hour
        df['day_of_week'] = df['date'].dt.day_name()

        return df

    except Exception as e:
        print(f"An error occurred while fetching email metadata: {e}")
        return pd.DataFrame()

def fetch_and_parse_emails(service, max_results=50, query_string='in:inbox'):
    """
    Fetches the full content of recent emails based on a query.

    This function fetches the full payload, including the body, and is best
    used for smaller numbers of emails that require content analysis.

    Args:
        service: The authenticated Gmail API service object.
        max_results (int): The maximum number of emails to fetch and parse.
        query_string (str): The Gmail search query (e.g., 'in:inbox is:unread').

    Returns:
        list: A list of parsed email dictionaries, or an empty list on error.
    """
    print(f"Fetching last {max_results} emails with query: '{query_string}'...")
    try:
        results = service.users().messages().list(userId='me', q=query_string, maxResults=max_results).execute()
        messages = results.get('messages', [])
        parsed_emails = []
        if not messages:
            return []

        for message_info in messages:
            msg = service.users().messages().get(userId='me', id=message_info['id']).execute()
            payload = msg['payload']
            headers = payload['headers']

            # Extract key metadata from headers.
            from_header = next((h['value'] for h in headers if h['name'].lower() == 'from'), '')
            sender_match = re.search(r'<(.+?)>', from_header)
            sender = sender_match.group(1) if sender_match else from_header
            subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), 'No Subject')

            # Extract the email body, preferring plain text over HTML.
            body = ""
            if 'parts' in payload:
                # This logic handles multipart emails.
                part = next((p for p in payload['parts'] if p.get('mimeType') == 'text/plain'), None)
                if part and 'data' in part['body']:
                    data = part['body'].get('data', '')
                    body = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
                else:
                    # If no plain text part, fall back to the HTML part and parse it.
                    html_part = next((p for p in payload['parts'] if p.get('mimeType') == 'text/html'), None)
                    if html_part and 'data' in html_part['body']:
                        data = html_part['body'].get('data', '')
                        html_content = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
                        soup = BeautifulSoup(html_content, "html.parser")
                        body = soup.get_text(separator='\n')
            elif 'data' in payload['body']:
                # This handles simple, non-multipart emails.
                data = payload['body'].get('data', '')
                body = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')

            if body.strip():
                parsed_emails.append({"id": msg['id'], "sender": sender, "subject": subject, "body": body, "headers": headers})

        return parsed_emails
    except Exception as e:
        print(f"An error occurred while fetching and parsing emails: {e}")
        return []