import os
import textwrap
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


create_ca_pem()
