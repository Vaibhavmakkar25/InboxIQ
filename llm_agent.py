# llm_agent.py

import google.generativeai as genai
import json
import re
import time
from dotenv import load_dotenv
import os

# --- Configuration ---
# Load environment variables from a .env file for security.
load_dotenv()
# Ensure your Google API Key is set in the .env file (e.g., API_KEY="your_key_here").
GOOGLE_API_KEY = os.getenv("API_KEY")

genai.configure(api_key=GOOGLE_API_KEY)

def analyze_email_with_llm(email_body):
    """
    Analyzes email content using the Gemini model to determine its category,
    priority, and a brief summary.

    Args:
        email_body (str): The text content of the email.

    Returns:
        dict: A dictionary containing 'category', 'priority', and 'summary',
              or None if the analysis fails.
    """
    model = genai.GenerativeModel('gemini-1.5-flash')
    prompt = """Analyze the following email content.
    Respond in a strict JSON format. Do not include any other text or formatting like ```json.
    The JSON object must have exactly three keys:
    1. 'category': Choose one of the following strings: 'Newsletter/Promotional', 'Personal Conversation', 'Urgent/Action Required', 'Transaction/Receipt', 'Notification', 'Spam'.
    2. 'priority': An integer from 1 (lowest, can be ignored) to 10 (highest, needs immediate attention).
    3. 'summary': A concise, one-sentence summary of the email's main point or call to action.
    Here is the email body:
    ---
    {}
    """.format(email_body[:4000]) # Truncate body to manage token usage and context size.

    # Add a short delay to avoid hitting API rate limits.
    time.sleep(1)

    try:
        response = model.generate_content(prompt)
        # Clean up the response to ensure it's a valid JSON string.
        clean_json_string = response.text.strip().replace('```json', '').replace('```', '')
        analysis_result = json.loads(clean_json_string)
        return analysis_result
    except Exception as e:
        print(f"An error occurred while analyzing the email with Gemini: {e}")
        # Log the raw response from the model for easier debugging.
        if 'response' in locals():
            print(f"--- Raw Model Response --- \n{response.text}")
        return None

def find_unsubscribe_link(email_headers, email_body):
    """
    Finds an unsubscribe link in an email using a two-step process.

    1. It first checks for a 'List-Unsubscribe' header, which is the most reliable method.
    2. If not found, it falls back to using an LLM to scan the email body for a link.

    Args:
        email_headers (list): A list of header dictionaries from the Gmail API.
        email_body (str): The text content of the email.

    Returns:
        str: The unsubscribe URL, or None if no link is found.
    """
    # First, try the most reliable method: the 'List-Unsubscribe' header.
    try:
        list_unsub_header = next((h['value'] for h in email_headers if h['name'].lower() == 'list-unsubscribe'), None)
        if list_unsub_header:
            # Extract the first HTTP(S) link from the header value.
            http_link = re.search(r'<(https?://[^>]+)>', list_unsub_header)
            if http_link:
                print(f"Found unsubscribe link in header: {http_link.group(1)}")
                return http_link.group(1)
    except Exception as e:
        print(f"Error parsing List-Unsubscribe header: {e}")

    # If header fails, fall back to an LLM scan of the email body.
    print("Header link not found, falling back to LLM body scan...")
    model = genai.GenerativeModel('gemini-1.5-flash')
    prompt = """Analyze the following email content. Your only job is to find the unsubscribe URL.
    Look for phrases like 'unsubscribe', 'manage your preferences', or 'opt-out'.
    Return ONLY the full URL. If you cannot find a URL, return the single word 'None'.
    Here is the email body:
    ---
    {}
    """.format(email_body[:4000]) # Truncate body to manage token usage.

    time.sleep(1) # Respect API rate limits.

    try:
        response = model.generate_content(prompt)
        link = response.text.strip()
        # Validate that the response is a URL.
        if link and link.lower().startswith('http'):
            return link
        return None
    except Exception as e:
        print(f"LLM scan for unsubscribe link failed: {e}")
        return None