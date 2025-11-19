run_step() {
    local msg="$1"; shift
    printf "%s..." "$msg"

    local errfile
    outfile=$(mktemp)
    errfile=$(mktemp)

    if "$@" 1>"$outfile" 2>"$errfile"; then
        printf "Done\n"
        rm -f "$outfile" "$errfile"
    else
        printf "ERROR\n"
        echo "=== STDOUT ==="
        cat "$outfile"
        echo "=== STDERR ==="
        cat "$errfile"
        echo "=== END ===\n"
        rm -f "$outfile" "$errfile"
        return 1
    fi
}

require_cmd() {
    local missing=0
    for cmd in "$@"; do
        if ! command -v "$cmd" >/dev/null 2>&1; then
            >&2 echo "Missing required command: $cmd"
            missing=1
        fi
    done
}
