# app.py

import gradio as gr
import base64
import html
import pandas as pd
from datetime import datetime

# Force Matplotlib to use a non-interactive backend ('Agg'), which is crucial for
# running in a server environment like Gradio to prevent rendering issues.
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# Import custom modules for email handling and AI analysis.
from email_fetcher import get_gmail_service, fetch_and_parse_emails, fetch_email_metadata
from llm_agent import analyze_email_with_llm, find_unsubscribe_link
from actions import archive_email, delete_email

# --- Application Constants ---
# Defines the number of email slots to display in the UI for sifting/cleanup.
MAX_EMAILS = 5
# The number of emails to fetch and analyze for the "Sift Inbox" and "Clean Up" features.
NUM_EMAILS_FOR_SIFTING = 25
# The number of recent emails to scan for unsubscribe links.
NUM_EMAILS_TO_SCAN = 40
# The number of email metadata records to fetch for the dashboard analysis.
NUM_EMAILS_FOR_ANALYSIS = 200


def analyze_and_sort_emails(service, query, sort_descending, progress=gr.Progress()):
    """
    Fetches emails, analyzes each with an LLM for priority, and sorts them.

    Args:
        service: Authenticated Gmail service object.
        query (str): The Gmail API query string (e.g., 'is:unread').
        sort_descending (bool): True for highest priority first, False for lowest first.
        progress (gr.Progress): Gradio progress tracker.

    Returns:
        list: A sorted list of analyzed email dictionaries.
    """
    progress(0, desc="Fetching emails to analyze...")
    emails_to_scan = fetch_and_parse_emails(service, max_results=NUM_EMAILS_FOR_SIFTING, query_string=f'in:inbox {query}')
    if not emails_to_scan:
        return []

    analyzed_emails = []
    total_emails = len(emails_to_scan)
    for i, email in enumerate(emails_to_scan):
        progress(i / total_emails, desc=f"Analyzing priority of email {i+1}/{total_emails}...")
        analysis = analyze_email_with_llm(email['body'])
        # Only include emails that were successfully analyzed and have a priority score.
        if analysis and 'priority' in analysis:
            email['analysis'] = analysis
            analyzed_emails.append(email)
        else:
            print(f"Skipping email {email['id']} due to analysis failure.")

    # Sort emails based on the 'priority' score from the LLM analysis.
    return sorted(analyzed_emails, key=lambda e: e['analysis']['priority'], reverse=sort_descending)


def fetch_and_update_sift_ui(service, progress=gr.Progress()):
    """
    Fetches the highest-priority unread emails and generates Gradio UI updates.
    """
    sorted_emails = analyze_and_sort_emails(service, query="is:unread", sort_descending=True, progress=progress)

    updates = []
    # This loop generates a list of gr.update() objects to modify the UI components.
    for i in range(MAX_EMAILS):
        if i < len(sorted_emails):
            email = sorted_emails[i]
            analysis = email['analysis']
            subject = email['subject']
            card_content = (f"**Priority:** {analysis.get('priority', 'N/A')}/10 | "
                            f"**Category:** `{analysis.get('category', 'N/A')}`\n"
                            f"**Summary:** *{analysis.get('summary', 'N/A')}*")
            # Each extend call adds updates for one email slot's components.
            updates.extend([
                gr.update(label=f"📧 {subject}", visible=True), # Accordion
                gr.update(value=card_content),                # Markdown content
                gr.update(value=email['id']),                 # Hidden Textbox for ID
                gr.update(value=f"## {subject}\n\n---\n\n{email['body']}", visible=False), # Hidden full body
                gr.update(visible=True),                      # Read button
                gr.update(value="")                           # Status Textbox
            ])
        else:
            # If there are fewer emails than slots, hide the extra slots.
            updates.extend([gr.update(visible=False), gr.update(), gr.update(), gr.update(), gr.update(visible=False), gr.update()])
    return updates


def fetch_and_display_low_priority_read(service, progress=gr.Progress()):
    """
    Fetches the lowest-priority read emails and generates Gradio UI updates.
    """
    sorted_emails = analyze_and_sort_emails(service, query="is:read", sort_descending=False, progress=progress)

    updates = []
    for i in range(MAX_EMAILS):
        if i < len(sorted_emails):
            email = sorted_emails[i]
            analysis = email['analysis']
            subject = email['subject']
            card_content = (f"**Priority:** {analysis.get('priority', 'N/A')}/10 | "
                            f"**Category:** `{analysis.get('category', 'N/A')}`\n"
                            f"**Summary:** *{analysis.get('summary', 'N/A')}*")
            updates.extend([
                gr.update(label=f"🗑️ {subject}", visible=True), # Accordion
                gr.update(value=card_content),                # Markdown content
                gr.update(value=email['id']),                 # Hidden Textbox for ID
                gr.update(value="")                           # Status Textbox
            ])
        else:
            updates.extend([gr.update(visible=False), gr.update(), gr.update(), gr.update()])
    return updates


def find_and_display_all_unsubscribeable(service, progress=gr.Progress()):
    """
    Scans recent emails for unsubscribe links and displays them as HTML cards.
    """
    if not service: return "Authentication failed. Please restart the app."

    progress(0, desc="Fetching recent emails...")
    emails_to_scan = fetch_and_parse_emails(service, max_results=NUM_EMAILS_TO_SCAN, query_string='in:inbox')
    if not emails_to_scan: return "Could not find any emails to scan."

    found_emails_html = []
    total_emails = len(emails_to_scan)
    for i, email in enumerate(emails_to_scan):
        progress(i / total_emails, desc=f"Scanning email {i+1}/{total_emails} from {email['sender']}")
        # Uses a simple heuristic to identify potential promotional emails before a deeper scan.
        promo_keywords = ['newsletter', 'promotion', 'deals', 'sale', 'weekly', 'daily', 'update', 'exclusive', 'offer', 'unsubscribe']
        if any(keyword in email['subject'].lower() for keyword in promo_keywords) or any(keyword in email['body'].lower() for keyword in promo_keywords):
            unsub_link = find_unsubscribe_link(email['headers'], email['body'])
            if unsub_link:
                safe_sender = html.escape(email['sender'])
                safe_subject = html.escape(email['subject'])
                card_html = f"<div style='display: flex; justify-content: space-between; align-items: center; border: 1px solid #e0e0e0; border-radius: 8px; padding: 10px 15px; margin-bottom: 10px;'><div><strong style='font-size: 1.1em;'>{safe_sender}</strong><br><span style='color: #888;'>Subject: {safe_subject}</span></div><a href='{unsub_link}' target='_blank' style='text-decoration: none; background-color: #ff4b4b; color: white; padding: 8px 12px; border-radius: 5px; font-weight: bold; white-space: nowrap;'>Unsubscribe</a></div>"
                found_emails_html.append(card_html)

    if not found_emails_html: return "No emails with unsubscribe links found in your recent inbox!"
    return f"<h3>Found {len(found_emails_html)} emails with unsubscribe links:</h3>" + "".join(found_emails_html)


# --- Dashboard Plotting Functions ---

def plot_top_senders(df, ax):
    """Plots the top 10 email senders on a given Matplotlib axis."""
    top_senders = df['sender_email'].value_counts().nlargest(10)
    if not top_senders.empty:
        top_senders.sort_values().plot(kind='barh', ax=ax, color='skyblue')
        ax.set_title("Top 10 Senders by Volume", fontsize=14)
        ax.set_xlabel("Number of Emails", fontsize=12)
    else:
        ax.text(0.5, 0.5, "No sender data to plot.", ha='center', va='center', color='gray')
    ax.grid(True, linestyle='--', alpha=0.6)

def plot_hourly_distribution(df, ax):
    """Plots the distribution of received emails by hour of the day."""
    if not df.empty and 'hour' in df.columns:
        hourly_counts = df['hour'].value_counts().sort_index()
        hourly_counts.plot(kind='bar', ax=ax, color='coral')
        ax.set_title("Emails by Hour of Day", fontsize=14)
        ax.set_xlabel("Hour (24-hour format)", fontsize=12)
        ax.set_ylabel("Number of Emails", fontsize=12)
        ax.tick_params(axis='x', rotation=0)
    else:
        ax.text(0.5, 0.5, "No hourly data to plot.", ha='center', va='center', color='gray')
    ax.grid(True, axis='y', linestyle='--', alpha=0.6)

def plot_top_domains(df, ax):
    """Plots the top 10 sender domains on a given Matplotlib axis."""
    top_domains = df['sender_domain'].value_counts().nlargest(10)
    if not top_domains.empty:
        top_domains.sort_values().plot(kind='barh', ax=ax, color='mediumseagreen')
        ax.set_title("Top 10 Sender Domains", fontsize=14)
        ax.set_xlabel("Number of Emails", fontsize=12)
    else:
        ax.text(0.5, 0.5, "No domain data to plot.", ha='center', va='center', color='gray')
    ax.grid(True, linestyle='--', alpha=0.6)

def plot_daily_volume(df, ax):
    """Plots the daily email volume over the selected date range."""
    if not df.empty and 'date' in df.columns:
        # Resample the data to get a count of emails per day.
        daily_counts = df.set_index('date').resample('D').size()
        daily_counts.plot(kind='line', ax=ax, marker='o', linestyle='-', color='salmon')
        ax.set_title("Daily Email Volume", fontsize=14)
        ax.set_ylabel("Number of Emails", fontsize=12)
        ax.set_xlabel("Date", fontsize=12)
        plt.setp(ax.get_xticklabels(), rotation=30, ha='right')
    else:
        ax.text(0.5, 0.5, "No daily volume data found.", ha='center', va='center', color='gray')
    ax.grid(True, linestyle='--', alpha=0.7)


def generate_dashboard(service, start_date_str, end_date_str, progress=gr.Progress()):
    """
    Generates a 2x2 dashboard of email statistics and a summary report.
    """
    fig, axes = plt.subplots(2, 2, figsize=(18, 11))
    plt.style.use('seaborn-v0_8-whitegrid')
    all_axes = axes.flatten()

    # Validate the date strings from the Textbox inputs.
    parsed_start_date, parsed_end_date = None, None
    try:
        if start_date_str: parsed_start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
        if end_date_str: parsed_end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
    except ValueError:
        report_text = "❌ Invalid date format. Please use YYYY-MM-DD."
        [ax.axis('off') for ax in all_axes] # Hide axes on error
        all_axes[0].text(0.5, 0.5, "Invalid Date Format", ha='center', va='center', color='red')
        plt.tight_layout()
        return fig, report_text

    if not service:
        report_text = "Authentication failed. Please restart the app."
        [ax.axis('off') for ax in all_axes]
        all_axes[0].text(0.5, 0.5, "Authentication Failed", ha='center', va='center')
        plt.tight_layout()
        return fig, report_text

    progress(0.2, desc="Fetching email metadata...")
    df = fetch_email_metadata(service, max_emails=NUM_EMAILS_FOR_ANALYSIS, start_date=parsed_start_date, end_date=parsed_end_date)

    if df.empty:
        report_text = "Could not find any email data for the selected criteria."
        [ax.axis('off') for ax in all_axes]
        all_axes[0].text(0.5, 0.5, "No Email Data Found", ha='center', va='center', color='gray')
        plt.tight_layout()
        return fig, report_text

    progress(0.6, desc="Analyzing data and creating plots...")
    # Populate the 2x2 grid with plots.
    plot_top_senders(df, axes[0, 0])
    plot_hourly_distribution(df, axes[0, 1])
    plot_top_domains(df, axes[1, 0])
    plot_daily_volume(df, axes[1, 1])

    # Generate a dynamic summary report based on the data.
    report_text = (f"✅ Analysis complete! Scanned **{len(df)}** emails in the selected range.\n"
                   f"- Your most frequent sender is **{df['sender_email'].value_counts().index[0]}**.\n"
                   f"- The busiest company domain is **{df['sender_domain'].value_counts().index[0]}**.\n"
                   f"- You receive the most emails during the **{df['hour'].value_counts().idxmax()}:00 hour**.")
    
    # Adjust subplot params for a tight layout.
    plt.tight_layout(pad=3.0)
    return fig, report_text


# --- Build the Gradio User Interface ---

with gr.Blocks(title="InboxIQ", theme=gr.themes.Soft()) as demo:
    gr.Markdown("# InboxIQ: The Autonomous Email Manager")
    # gr.State is used to store session-specific data, like the authenticated
    # Gmail service object, which persists across user interactions.
    service_state = gr.State()

    with gr.Tabs():
        # --- TAB 1: Priority Inbox ---
        with gr.TabItem("🎯 Priority Inbox"):
            gr.Markdown("### Top 5 Highest-Priority Unread Emails\nClick the button to scan your unread mail and find the most important items that need your attention.")
            with gr.Row():
                sift_button = gr.Button("✨ Find My Top 5 Priorities")

            sift_all_outputs = []
            # Programmatically create UI components for each email slot.
            for i in range(MAX_EMAILS):
                with gr.Accordion(f"Email Slot {i+1}", visible=False) as sift_accordion:
                    sift_content_md = gr.Markdown()
                    sift_id_holder = gr.Textbox(visible=False) # Hidden field to store the email ID
                    sift_full_body_md = gr.Markdown(visible=False)
                    with gr.Row():
                        sift_read_btn = gr.Button("📖 Read Full Email", visible=False)
                        sift_archive_btn = gr.Button("Archive")
                        sift_delete_btn = gr.Button("Delete")
                    sift_status_text = gr.Textbox(label="Status", interactive=False)

                    # --- Event Handlers for Priority Inbox ---
                    sift_read_btn.click(fn=lambda: (gr.update(visible=True), gr.update(visible=False)), outputs=[sift_full_body_md, sift_read_btn])
                    # .then() chains events: after archiving, hide the accordion.
                    sift_archive_btn.click(fn=archive_email, inputs=[service_state, sift_id_holder], outputs=[sift_status_text]).then(lambda: gr.update(visible=False), outputs=[sift_accordion])
                    sift_delete_btn.click(fn=delete_email, inputs=[service_state, sift_id_holder], outputs=[sift_status_text]).then(lambda: gr.update(visible=False), outputs=[sift_accordion])

                    # Collect all output components to be updated by the main button click.
                    sift_all_outputs.extend([sift_accordion, sift_content_md, sift_id_holder, sift_full_body_md, sift_read_btn, sift_status_text])

            sift_button.click(fn=fetch_and_update_sift_ui, inputs=[service_state], outputs=sift_all_outputs, show_progress="full")

        # --- TAB 2: Clean Up Read Mail ---
        with gr.TabItem("🗑️ Clean Up Read Mails"):
            gr.Markdown("### Top 5 Lowest-Priority Read Emails\nFind unimportant read emails that you can safely delete to clean up your inbox.")
            with gr.Row():
                cleanup_button = gr.Button("🔍 Find Low-Priority Emails to Delete")

            cleanup_all_outputs = []
            for i in range(MAX_EMAILS):
                with gr.Accordion(f"Cleanup Slot {i+1}", visible=False) as cleanup_accordion:
                    cleanup_content_md = gr.Markdown()
                    cleanup_id_holder = gr.Textbox(visible=False)
                    with gr.Row():
                        cleanup_archive_btn = gr.Button("Archive")
                        cleanup_delete_btn = gr.Button("Delete", variant="stop")
                    cleanup_status_text = gr.Textbox(label="Status", interactive=False)

                    cleanup_archive_btn.click(fn=archive_email, inputs=[service_state, cleanup_id_holder], outputs=[cleanup_status_text]).then(lambda: gr.update(visible=False), outputs=[cleanup_accordion])
                    cleanup_delete_btn.click(fn=delete_email, inputs=[service_state, cleanup_id_holder], outputs=[cleanup_status_text]).then(lambda: gr.update(visible=False), outputs=[cleanup_accordion])

                    cleanup_all_outputs.extend([cleanup_accordion, cleanup_content_md, cleanup_id_holder, cleanup_status_text])

            cleanup_button.click(fn=fetch_and_display_low_priority_read, inputs=[service_state], outputs=cleanup_all_outputs, show_progress="full")

        # --- TAB 3: Unsubscribe Finder ---
        with gr.TabItem("🔎 Unsubscribe Finder"):
            with gr.Row():
                suggest_button = gr.Button("🔍 List All Unsubscribeable Emails")
            suggestion_output_unsub = gr.HTML("Click the button to scan your inbox for emails with unsubscribe links...")
            suggest_button.click(fn=find_and_display_all_unsubscribeable, inputs=[service_state], outputs=[suggestion_output_unsub], show_progress="full")

        # --- TAB 4: Inbox Health Dashboard ---
        with gr.TabItem("📊 Inbox Dashboard"):
            with gr.Column():
                gr.Markdown("## Your Inbox at a Glance\nSelect a date range and click the button to generate your personalized dashboard.")
                with gr.Row():
                    start_date_input = gr.Textbox(label="Start Date", placeholder="YYYY-MM-DD")
                    end_date_input = gr.Textbox(label="End Date", placeholder="YYYY-MM-DD")
                dashboard_button = gr.Button("🚀 Generate My Dashboard")
                status_report = gr.Markdown()
                dashboard_plot = gr.Plot()
            dashboard_button.click(fn=generate_dashboard, inputs=[service_state, start_date_input, end_date_input], outputs=[dashboard_plot, status_report], show_progress="full")

    # The `demo.load()` event runs once when the app UI is first loaded.
    # It's used here to perform the initial Gmail authentication.
    demo.load(fn=get_gmail_service, outputs=[service_state])

if __name__ == "__main__":
    demo.launch()