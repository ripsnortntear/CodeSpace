#!/bin/bash

# Function to prompt for input with a default value
prompt_for_input() {
    local prompt_message="$1"
    local default_value="$2"
    read -rp "$prompt_message [$default_value]: " user_input
    echo "${user_input:-$default_value}"
}

# Prompt for backup directory
BACKUP_DIR=$(prompt_for_input "Enter the backup directory")

# Prompt for source directory
SOURCE_DIR=$(prompt_for_input "Enter the source directory")

# Prompt for files to exclude
EXCLUDE_FILES=$(prompt_for_input "Enter files to exclude (space-separated and exact locations)")

# Prompt for archive name
ARCHIVE_NAME=$(prompt_for_input "Enter the archive name" "var_backup.7z")

# Prompt for maximum size of each archive part
MAX_SIZE=$(prompt_for_input "Enter maximum size of each archive part" "3G")

# Create backup directory if it doesn't exist
mkdir -p "$BACKUP_DIR"

# Create an array of exclude patterns
EXCLUDE_PATTERNS=()
for file in $EXCLUDE_FILES; do
    EXCLUDE_PATTERNS+=("-x!$SOURCE_DIR/$file")
done

# Create the backup using 7z with split option for max size
if 7z a -v"$MAX_SIZE" -mx=9 "$BACKUP_DIR/$ARCHIVE_NAME" "$SOURCE_DIR" "${EXCLUDE_PATTERNS[@]}"; then
    echo "Backup completed successfully."
else
    echo "Backup failed."
fi
