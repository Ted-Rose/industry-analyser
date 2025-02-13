import os
import textwrap
import json
from django.conf import settings
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent.parent

def create_ca_pem():
    print("Starting to create 'ca.pem'...")
    capem_content = os.environ.get('capem')
    if capem_content:
        print("capem_content found")
        lines = capem_content.replace("-----BEGIN CERTIFICATE----- ", "-----BEGIN CERTIFICATE-----\n")
        lines = lines.replace(" -----END CERTIFICATE-----", "\n-----END CERTIFICATE-----")

        base64_content = lines.split("\n", 1)[1].rsplit("\n", 1)[0]
        formatted_content = textwrap.fill(base64_content, 64)

        # Add the header and footer back with line breaks as required for pem files
        pem_content = f"-----BEGIN CERTIFICATE-----\n{formatted_content}\n-----END CERTIFICATE-----"
        file_path = os.path.join(BASE_DIR, 'ca.pem')

        with open(file_path, 'w') as file:
            file.write(pem_content)
        print(f"'ca.pem' has been created at {file_path}.")
    else:
        print("Environment variable 'capem' is not set.")


def create_private_settings_json():
    print("Starting to create 'private_settings.json'...")
    private_settings_str = os.environ.get('private_settings')
    if private_settings_str:
        try:
            print("private_settings content found")
            private_settings = json.loads(private_settings_str)

            file_path = os.path.join(BASE_DIR, 'private_settings.json')
            with open(file_path, 'w') as file:
                json.dump(private_settings, file, indent=4)
            print(f"'private_settings.json' has been created at {file_path}.")
        except json.JSONDecodeError as e:
            print(f"Error decoding 'private_settings': {e}")
    else:
        print("Environment variable 'private_settings' is not set.")


create_ca_pem()
create_private_settings_json()
