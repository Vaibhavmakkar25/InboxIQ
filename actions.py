# actions.py

def archive_email(service, message_id):
    """
    Archives an email by removing the 'INBOX' label.

    This is the standard method for archiving in the Gmail API.

    Args:
        service: The authenticated Gmail API service object.
        message_id (str): The ID of the email to archive.

    Returns:
        str: A status message indicating success or failure.
    """
    try:
        service.users().messages().modify(
            userId='me',
            id=message_id,
            body={'removeLabelIds': ['INBOX']}
        ).execute()
        print(f"Archived message: {message_id}")
        return f"✅ Successfully archived message."
    except Exception as e:
        error_message = f"Error archiving email: {e}"
        print(error_message)
        return f"❌ {error_message}"

def delete_email(service, message_id):
    """
    Moves an email to the trash.

    Note: This is a "soft" delete. Gmail permanently deletes emails from the
    trash after approximately 30 days.

    Args:
        service: The authenticated Gmail API service object.
        message_id (str): The ID of the email to delete.

    Returns:
        str: A status message indicating success or failure.
    """
    try:
        service.users().messages().trash(userId='me', id=message_id).execute()
        print(f"Deleted (trashed) message: {message_id}")
        return f"✅ Successfully deleted message."
    except Exception as e:
        error_message = f"Error deleting email: {e}"
        print(error_message)
        return f"❌ {error_message}"