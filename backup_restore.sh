#!/bin/bash

# Function to prompt for input with a default value
prompt_for_input() {
    local prompt_message="$1"
    local default_value="$2"
    read -rp "$prompt_message [$default_value]: " user_input
    echo "${user_input:-$default_value}"
}

# Function to create a backup
backup() {
    echo "Starting backup..."

    # Prompt for backup directory
    BACKUP_DIR=$(prompt_for_input "Enter the backup directory")
    mkdir -p "$BACKUP_DIR"

    # Prompt for directories to back up
    IFS=',' read -ra DIRECTORIES <<< "$(prompt_for_input "Enter directories to back up (comma-separated)")"
    # Prompt for maximum size of each archive part
    MAX_SIZE=$(prompt_for_input "Enter maximum size of each archive part" "3G")

    # Check if all directories exist
    for dir in "${DIRECTORIES[@]}"; do
        if [[ ! -d "$dir" ]]; then
            echo "Warning: Directory $dir does not exist. Skipping."
        fi
    done

    # Create the backup using 7z and split into parts
    TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
    BACKUP_FILE="$BACKUP_DIR/backup_$TIMESTAMP.7z"
    if 7z a -v"$MAX_SIZE" "$BACKUP_FILE" "${DIRECTORIES[@]}"; then
        echo "Backup completed successfully. Created files:"
        ls -lh "$BACKUP_DIR/backup_$TIMESTAMP.*"
    else
        echo "Error occurred during backup."
        exit 1
    fi
}

# Function to restore from backup
restore() {
    local backup_prefix="$1"

    # Check if the backup prefix is provided
    if [[ -z "$backup_prefix" ]]; then
        echo "Error: Backup prefix not specified."
        exit 1
    fi

    echo "Starting restore from $backup_prefix..."

    # Check if the backup files exist
    if ls "$backup_prefix.*" 1> /dev/null 2>&1; then
        if 7z x "$backup_prefix.*" -o/; then
            echo "Restore completed successfully."
        else
            echo "Error occurred during restore."
            exit 1
        fi
    else
        echo "Error: No backup files found with prefix '$backup_prefix'."
        exit 1
    fi
}

# Main script logic
case "$1" in
    backup)
        backup
        ;;
    restore)
        BACKUP_PREFIX=$(prompt_for_input "Enter the backup file prefix" "")
        restore "$BACKUP_PREFIX"
        ;;
    *)
        echo "Usage: $0 {backup|restore <backup_file_prefix>}"
        exit 1
        ;;
esac
