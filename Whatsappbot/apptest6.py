import flet as ft
import urllib.parse
import csv
import json
import os
import time
import threading
import pyautogui
import pyperclip
import random

CONTACTS_FILE = "contacts.json"
ACCENT_COLOR = ft.Colors.BLUE_500

# Message rephrasing templates
def rephrase_message(name, base_message):
    templates = [
        f"Hi {name}, {base_message}",
        f"Hello {name}! {base_message}",
        f"Dear {name}, just a quick note: {base_message}",
        f"Hey {name}, hope you're doing well! {base_message}",
        f"Good day {name}, here's something for you: {base_message}"
    ]
    return random.choice(templates)

def generate_whatsapp_link(phone):
    return f"https://web.whatsapp.com/send?phone={phone}"

def save_contacts_to_file(contacts):
    with open(CONTACTS_FILE, "w", encoding="utf-8") as f:
        json.dump(contacts, f)

def load_contacts_from_file():
    if os.path.exists(CONTACTS_FILE):
        with open(CONTACTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def main(page: ft.Page):
    page.title = "Smart Broadcast Messenger"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.bgcolor = ft.Colors.GREY_50
    page.scroll = "auto"
    page.padding = 10

    contacts = load_contacts_from_file()
    contacts_view = ft.Column([])
    selected_contacts = set()
    bulk_sending = False

    name_field = ft.TextField(label="Business Name", expand=True, border_radius=8, bgcolor=ft.Colors.WHITE)
    message_field = ft.TextField(label="Daily Message", multiline=True, expand=True,
                                 min_lines=3, max_lines=5, border_radius=8, bgcolor=ft.Colors.WHITE)

    name_input = ft.TextField(label="Customer Name", expand=True, border_radius=8, bgcolor=ft.Colors.WHITE)
    phone_input = ft.TextField(label="Phone Number", expand=True, border_radius=8, bgcolor=ft.Colors.WHITE)

    delay_field = ft.TextField(label="Delay (seconds) Use Min 5 Sec", value="5", width=200,
                               border_radius=8, keyboard_type=ft.KeyboardType.NUMBER)

    progress_bar = ft.ProgressBar(width=400, visible=False)
    progress_text = ft.Text("", visible=False)

    def update_bulk_controls():
        select_all_checkbox.value = len(selected_contacts) == len(contacts) and len(contacts) > 0
        bulk_send_btn.disabled = len(selected_contacts) == 0 or bulk_sending
        page.update()

    def add_contact_view():
        contacts_view.controls.clear()
        for i, c in enumerate(contacts):
            checkbox = ft.Checkbox(value=i in selected_contacts,
                                   on_change=lambda e, idx=i: toggle_contact_selection(idx, e.control))
            contact_row = ft.Row([
                checkbox,
                ft.Column([
                    ft.Text(c['name'], size=14, weight="bold"),
                    ft.Text(c['phone'], size=12, color=ft.Colors.GREY_600)
                ], expand=True),
                ft.IconButton(icon=ft.Icons.DELETE,
                              on_click=lambda e, idx=i: remove_contact(idx), tooltip="Remove")
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
            contacts_view.controls.append(contact_row)
        update_bulk_controls()
        page.update()

    def add_contact(e):
        if name_input.value and phone_input.value:
            contacts.append({"name": name_input.value.strip(), "phone": phone_input.value.strip()})
            save_contacts_to_file(contacts)
            name_input.value = ""
            phone_input.value = ""
            add_contact_view()
            page.snack_bar = ft.SnackBar(content=ft.Text("Contact added!"), bgcolor=ft.Colors.GREEN)
            page.snack_bar.open = True
            page.update()
        else:
            page.snack_bar = ft.SnackBar(content=ft.Text("Both name and phone required!"))
            page.snack_bar.open = True
            page.update()

    def remove_contact(index):
        del contacts[index]
        save_contacts_to_file(contacts)
        selected_contacts.clear()
        add_contact_view()
        page.update()

    def toggle_contact_selection(index, checkbox):
        if checkbox.value:
            selected_contacts.add(index)
        else:
            selected_contacts.discard(index)
        update_bulk_controls()

    def select_all_contacts(e):
        select_all = e.control.value
        selected_contacts.clear()
        if select_all:
            selected_contacts.update(range(len(contacts)))
        add_contact_view()
        update_bulk_controls()
        page.update()

    def process_csv(e: ft.FilePickerResultEvent):
        if e.files:
            try:
                with open(e.files[0].path, newline='', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        if 'Name' in row and 'Phone' in row:
                            contacts.append({"name": row['Name'], "phone": row['Phone']})
                save_contacts_to_file(contacts)
                add_contact_view()
                page.snack_bar = ft.SnackBar(content=ft.Text("CSV uploaded!"), bgcolor=ft.Colors.GREEN)
                page.snack_bar.open = True
                page.update()
            except Exception as ex:
                page.snack_bar = ft.SnackBar(content=ft.Text(f"CSV error: {str(ex)}"))
                page.snack_bar.open = True
                page.update()

    def bulk_send_messages(e=None):
        nonlocal bulk_sending

        if not message_field.value.strip():
            page.snack_bar = ft.SnackBar(content=ft.Text("Message cannot be empty!"))
            page.snack_bar.open = True
            return

        if not selected_contacts:
            page.snack_bar = ft.SnackBar(content=ft.Text("Select contacts first!"))
            page.snack_bar.open = True
            return

        bulk_sending = True
        update_bulk_controls()
        progress_bar.visible = True
        progress_text.visible = True
        progress_bar.value = 0
        page.update()

        def send():
            delay = float(delay_field.value or 5)
            selected_list = list(selected_contacts)
            total = len(selected_list)

            for i, index in enumerate(selected_list):
                contact = contacts[index]
                phone = contact['phone']
                name = contact['name']
                rephrased_msg = rephrase_message(name, message_field.value.strip())
                pyperclip.copy(rephrased_msg)

                os.system(f"start whatsapp://send?phone={phone}")
                time.sleep(10)
                pyautogui.hotkey("ctrl", "v")
                time.sleep(1)
                pyautogui.press("enter")
                progress_bar.value = (i + 1) / total
                progress_text.value = f"Sent to {name} ({i+1}/{total})"
                page.update()
                time.sleep(delay)

            bulk_sending = False
            progress_bar.visible = False
            progress_text.visible = False
            update_bulk_controls()
            page.snack_bar = ft.SnackBar(content=ft.Text(f"Sent to {total} contacts!"))
            page.snack_bar.open = True
            page.update()

        threading.Thread(target=send).start()

    file_picker = ft.FilePicker(on_result=process_csv)
    page.overlay.append(file_picker)

    bulk_send_btn = ft.ElevatedButton(
        text="Send to Selected",
        on_click=bulk_send_messages,
        bgcolor=ft.Colors.GREEN_600,
        color=ft.Colors.WHITE,
        disabled=True
    )

    select_all_checkbox = ft.Checkbox(label="Select All", on_change=select_all_contacts)

    page.add(
        ft.Column([
            ft.Text("📢 Smart Broadcast Messenger", size=22, weight="bold", color=ACCENT_COLOR),
            ft.Container(
                content=ft.Column([
                    ft.Text("Business Details", weight="bold"),
                    name_field,
                    message_field
                ], spacing=10),
                bgcolor=ft.Colors.WHITE, padding=10, border_radius=10, margin=10
            ),
            ft.Container(
                content=ft.Column([
                    ft.Text("Add Contact", weight="bold"),
                    name_input,
                    phone_input,
                    ft.ElevatedButton("Add", on_click=add_contact, bgcolor=ACCENT_COLOR, color=ft.Colors.WHITE)
                ], spacing=10),
                bgcolor=ft.Colors.WHITE, padding=10, border_radius=10, margin=10
            ),
            ft.Container(
                content=ft.Column([
                    ft.Text("Upload Contacts (CSV with Name & Phone)", weight="bold"),
                    ft.ElevatedButton("Upload CSV", on_click=lambda e: file_picker.pick_files(allowed_extensions=["csv"]))
                ], spacing=10),
                bgcolor=ft.Colors.WHITE, padding=10, border_radius=10, margin=10
            ),
            ft.Container(
                content=ft.Column([
                    ft.Text("Send Settings", weight="bold"),
                    ft.Row([select_all_checkbox, delay_field, bulk_send_btn], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    progress_text, progress_bar
                ], spacing=10),
                bgcolor=ft.Colors.WHITE, padding=10, border_radius=10, margin=10
            ),
            ft.Container(content=contacts_view)
        ], scroll=ft.ScrollMode.ALWAYS)
    )

    add_contact_view()

ft.app(target=main, view=ft.AppView.FLET_APP)
