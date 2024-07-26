#!/bin/bash

# Set the directory containing the zip files to the current working directory
zip_dir=$PWD

# Define a function to process files
process_files() {
    # Process CUE, ISO, and BIN files
    for file_type in cue iso bin; do
        for file in *."$file_type"; do
            if [ -f "$file" ]; then
                case $file_type in
                    cue|iso)
                        process_disc_image "$file"
                        ;;
                    bin)
                        process_bin_file "$file"
                        ;;
                esac
                return 0
            fi
        done
    done

    # If no files were processed, exit with an error
    echo "Error: No CUE, ISO, or BIN file found" >&2
    return 1
}

# Define a function to process disc images (CUE and ISO files)
process_disc_image() {
    local file="$1"
    parallel chdman createcd -i {} -o "{.}.chd" ::: "$file"
    mv ./*.chd ../
}

# Define a function to process BIN files
process_bin_file() {
    local bin_file="$1"
    local cue_file="${bin_file%.bin}.cue"
    tee "$cue_file" << EOF
FILE "$bin_file" BINARY
  TRACK 01 MODE2/2352
    INDEX 01 00:00:00
EOF
    process_disc_image "$cue_file"
}

# Define a function to extract and process a zip file
process_zip_file() {
    local zip_file="$1"
    local extract_dir="${zip_file%.zip}"

    # Extract the zip file to a directory with the same name
    if 7z x "$zip_file" -o"$extract_dir"; then
        # Change into the extracted directory
        pushd "$extract_dir" || exit

        # Process files in the extracted directory
        process_files

        # Go back to the original directory
        popd || exit

        # Delete the original zip file
        rm "$zip_file"

        # Delete the extracted directory
        rm -r "$extract_dir"
    else
        echo "Error: Failed to extract zip file: $zip_file" >&2
        exit 1
    fi
}

# Iterate over zip files
for zip_file in "$zip_dir"/*.zip; do
    process_zip_file "$zip_file"
done