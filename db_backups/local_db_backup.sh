#!/bin/bash

# Ensure jq is installed
if ! command -v jq &> /dev/null
then
    echo "Error: jq is not installed. Please install it to continue."
    echo "On macOS, you can use Homebrew: brew install jq"
    exit 1
fi

# Read the private settings from the JSON file using jq
CONFIG_FILE="private_settings.json"

if [ ! -f "$CONFIG_FILE" ]; then
    echo "Error: Configuration file '$CONFIG_FILE' not found."
    exit 1
fi

DB_NAME=$(jq -r '.DATABASES.default.NAME' "$CONFIG_FILE")
DB_USER=$(jq -r '.DATABASES.default.USER' "$CONFIG_FILE")
DB_PASSWORD=$(jq -r '.DATABASES.default.PASSWORD' "$CONFIG_FILE")
DB_HOST=$(jq -r '.DATABASES.default.HOST' "$CONFIG_FILE")
DB_PORT=$(jq -r '.DATABASES.default.PORT' "$CONFIG_FILE")

DB_ENGINE='django.db.backends.postgresql'
DB_SSLMODE='verify-full'

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="db_backups/${DB_NAME}_${TIMESTAMP}.dump" # Example: mydbname_20251104_093503.dump

# Debug output
echo "Extracted values:"
echo "ENGINE: $DB_ENGINE"
echo "NAME: $DB_NAME"
echo "USER: $DB_USER"
echo "HOST: $DB_HOST"
echo "PORT: $DB_PORT"

# SSL options are handled differently in pg_dump
# We'll use PGSSLMODE and PGSSLROOTCERT environment variables instead
# if [ ! -z "$DB_SSLMODE" ]; then
#     export PGSSLMODE="$DB_SSLMODE"
#     echo "Setting SSL mode: $DB_SSLMODE"
# fi

# if [ ! -z "$DB_SSLROOTCERT" ]; then
#     export PGSSLROOTCERT="$DB_SSLROOTCERT"
#     echo "Setting SSL root cert: $DB_SSLROOTCERT"
# fi

# --- Validate extracted information ---
if [ -z "$DB_NAME" ] || [ -z "$DB_USER" ] || [ -z "$DB_PASSWORD" ] || [ -z "$DB_HOST" ] || [ -z "$DB_PORT" ]; then
    echo "Error: Could not extract all database credentials from $CONFIG_FILE. Please check the file format."
    exit 1
fi

# --- Set environment variable for pg_dump to use password ---
# This is crucial for non-interactive password entry.
export PGPASSWORD="$DB_PASSWORD"

echo "Starting database backup for '$DB_NAME' on '$DB_HOST:$DB_PORT'..."
echo "Backup will be saved to: $BACKUP_FILE"

# --- Check pg_dump version compatibility ---
PG_DUMP_VERSION=$(pg_dump --version | grep -oE '[0-9]+\.[0-9]+' | head -1)
echo "Local pg_dump version: $PG_DUMP_VERSION"

# Try to get server version
echo "Checking PostgreSQL server version..."
SERVER_VERSION=$(PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -t -c "SELECT version();" 2>/dev/null | grep -oE '[0-9]+\.[0-9]+' | head -1)

if [ ! -z "$SERVER_VERSION" ]; then
    echo "PostgreSQL server version: $SERVER_VERSION"
    
    # Compare major versions
    PG_DUMP_MAJOR=$(echo "$PG_DUMP_VERSION" | cut -d. -f1)
    SERVER_MAJOR=$(echo "$SERVER_VERSION" | cut -d. -f1)
    
    if [ "$PG_DUMP_MAJOR" != "$SERVER_MAJOR" ]; then
        echo "⚠️ WARNING: Version mismatch detected! Server is $SERVER_VERSION but pg_dump is $PG_DUMP_VERSION"
        echo "This may cause compatibility issues. Consider upgrading pg_dump:"
        echo "  brew upgrade postgresql@$SERVER_MAJOR"
        echo "  brew link --force postgresql@$SERVER_MAJOR"
        
        read -p "Do you want to continue anyway? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo "Backup aborted by user."
            exit 1
        fi
    fi
else
    echo "Could not determine server version. Proceeding with backup anyway."
fi

# --- Perform the pg_dump ---
# Using the custom format (-Fc) is recommended for flexibility with pg_restore.
# The SSL options are passed directly to pg_dump.
pg_dump \
    -h "$DB_HOST" \
    -p "$DB_PORT" \
    -U "$DB_USER" \
    -d "$DB_NAME" \
    -F c \
    --no-owner \
    --no-privileges \
    --verbose \
    --create \
    --clean \
    --if-exists \
    --compress=9 \
    --file="$BACKUP_FILE"

# Clear the password and SSL settings from environment variables for security
unset PGPASSWORD
unset PGSSLMODE
unset PGSSLROOTCERT

# --- Check if pg_dump was successful ---
PG_DUMP_STATUS=$?
if [ $PG_DUMP_STATUS -eq 0 ]; then
    if [ -f "$BACKUP_FILE" ] && [ -s "$BACKUP_FILE" ]; then
        echo "Database backup completed successfully! 🎉"
        echo "Backup file size: $(du -h "$BACKUP_FILE" | awk '{print $1}')"
    else
        echo "Error: Backup file was not created or is empty."
        exit 1
    fi
else
    echo "Error: Database backup failed with exit code $PG_DUMP_STATUS! ❌"
    
    # Provide guidance based on common error codes
    if [ $PG_DUMP_STATUS -eq 1 ]; then
        echo "This may be due to a version mismatch between pg_dump and the PostgreSQL server."
        echo "Your server is likely running PostgreSQL 16.x but your pg_dump is version 14.x."
        echo "To fix this, you can upgrade your local PostgreSQL client tools:"
        echo "  brew install postgresql@16"
        echo "  brew link --force postgresql@16"
    elif [ $PG_DUMP_STATUS -eq 2 ]; then
        echo "This may be due to invalid command line arguments."
    elif [ $PG_DUMP_STATUS -eq 3 ]; then
        echo "This may be due to a connection issue. Check your network and credentials."
    fi
    
    exit 1
fi

exit 0
    