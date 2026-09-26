import os
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

from industry_analyser.ssl_pem import format_db_ssl_pem  # noqa: E402


def create_ca_pem():
    print("Starting to create 'ca.pem'...")
    capem_content = (
        os.environ.get('DB_SSL_CERT') or os.environ.get('capem') or ''
    )
    if not capem_content:
        print("Environment variable 'DB_SSL_CERT'/'capem' is not set.")
        return
    pem_content = format_db_ssl_pem(capem_content)
    file_path = os.path.join(BASE_DIR, 'ca.pem')
    with open(file_path, 'w') as file:
        file.write(pem_content)
    print(f"'ca.pem' has been created at {file_path}.")


create_ca_pem()
