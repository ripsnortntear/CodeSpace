#!/bin/bash

# Constants
API_URL="https://api.cloudflare.com/client/v4"
IFCONFIG_URL="https://ifconfig.co"
CONTENT_TYPE="Content-Type: application/json"

# Function to prompt for user input with validation
prompt_for_input() {
    local prompt="$1"
    local input
    while true; do
        read -rp "$prompt" input
        if [[ -n "$input" ]]; then
            echo "$input"
            return
        else
            echo "Input cannot be empty. Please try again."
        fi
    done
}

# Function to handle errors
handle_error() {
    local message="$1"
    echo "Error: $message"
    exit 1
}

# Function to get the current public IP address
get_public_ip() {
    curl -s -X GET "$IFCONFIG_URL" || handle_error "Unable to retrieve public IP address."
}

# Function to get the zone ID
get_zone_id() {
    local response
    response=$(curl -s -X GET "$API_URL/zones?name=$zone_name" \
        -H "Authorization: Bearer $api_token" \
        -H "$CONTENT_TYPE")

    if [[ $(echo "$response" | jq -r '.success') == "false" ]]; then
        handle_error "Error retrieving zone ID: $(echo "$response" | jq -r '.errors')"
    fi

    echo "$response" | jq -r '.result[0].id'
}

# Function to fetch all A records
get_a_records() {
    local zone_id="$1"
    local response
    response=$(curl -s -X GET "$API_URL/zones/$zone_id/dns_records?type=A" \
        -H "Authorization: Bearer $api_token" \
        -H "$CONTENT_TYPE")

    if [[ $(echo "$response" | jq -r '.success') == "false" ]]; then
        handle_error "Error fetching A records: $(echo "$response" | jq -r '.errors')"
    fi

    echo "$response" | jq -c '.result[]'
}

# Function to update a DNS record
update_dns_record() {
    local name="$1"
    local record_id="$2"
    local current_ip="$3"
    local ipv4="$4"
    local proxied="$5"
    local ttl="$6"

    echo "Updating $name from $current_ip to $ipv4..."
    local update_response
    update_response=$(curl -s -X PUT "$API_URL/zones/$zone_id/dns_records/$record_id" \
        -H "Authorization: Bearer $api_token" \
        -H "$CONTENT_TYPE" \
        --data "{\"type\":\"A\",\"name\":\"$name\",\"content\":\"$ipv4\",\"ttl\":$ttl,\"proxied\":$proxied}")

    if [[ $(echo "$update_response" | jq -r '.success') == "true" ]]; then
        echo "✓ Successfully updated $name ($current_ip -> $ipv4)"
    else
        echo "✗ Failed to update $name: $(echo "$update_response" | jq -r '.errors')"
    fi
}

# Function to install jq
install_jq() {
    if command -v apt &> /dev/null; then
        echo "Installing jq using apt..."
        sudo apt update && sudo apt install -y jq
    elif command -v dnf &> /dev/null; then
        echo "Installing jq using dnf..."
        sudo dnf install -y jq
    elif command -v yum &> /dev/null; then
        echo "Installing jq using yum..."
        sudo yum install -y jq
    elif command -v apk &> /dev/null; then
        echo "Installing jq using apk..."
        sudo apk add jq
    elif command - v pacman &> /dev/null; then
        echo "Installing jq using pacman..."
        sudo pacman -Sy --noconfirm jq
    elif command -v brew &> /dev/null; then
        echo "Installing jq using Homebrew..."
        brew install jq
    else
        handle_error "Could not detect package manager!"
    fi
}

# Check for jq installation
if ! command -v jq &> /dev/null; then
    echo "jq is not installed. Attempting to install..."
    install_jq
    if ! command -v jq &> /dev/null; then
        handle_error "Failed to install jq. Please install it manually."
    fi
    echo "jq has been successfully installed."
else
    echo "jq is already installed."
fi

# Main script logic
api_token=$(prompt_for_input "Enter your Cloudflare API Token: ")
zone_name=$(prompt_for_input "Enter your Zone Name: ")

ipv4=$(get_public_ip)

zone_id=$(get_zone_id)

records=$(get_a_records "$zone_id")

while IFS= read -r record; do
    name=$(echo "$record" | jq -r '.name')
    record_id=$(echo "$record" | jq -r '.id')
    current_ip=$(echo "$record" | jq -r '.content')
    proxied=$(echo "$record" | jq -r '.proxied')
    ttl=$(echo "$record" | jq -r '.ttl // 1')

    if [ "$current_ip" != "$ipv4" ]; then
        update_dns_record "$name" "$record_id" "$current_ip" "$ipv4" "$proxied" "$ttl"
    else
        echo "✓ $name is up to date ($current_ip)"
    fi
done <<< "$records"
