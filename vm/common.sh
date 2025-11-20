run_step() {
    local msg="$1"; shift
    printf "%s..." "$msg"

    local errfile
    outfile=$(mktemp)
    errfile=$(mktemp)
    timing=$(mktemp)

    if {
        time "$@" 1>"$outfile" 2>"$errfile";
    } 2>"$timing"; then
        printf "Done (%s)\n" "$(grep 'real' "$timing" | awk '{print $2}')"
        rm -f "$outfile" "$errfile"
    else
        printf "ERROR (%s)\n" "$(grep 'real' "$timing" | awk '{print $2}')"
        echo "=== STDOUT ==="
        cat "$outfile"
        echo "=== STDERR ==="
        cat "$errfile"
        echo "=== END ==="
        echo
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
