#!/bin/sh
# Install the published Linux x64 binary without Python or shell-profile edits.
set -eu

root="$HOME/.gorak"
local_release=
while [ "$#" -gt 0 ]; do
    case "$1" in
        --directory|--from-directory)
            [ "$#" -ge 2 ] || { echo "Missing value for $1" >&2; exit 2; }
            case "$1" in
                --directory) root=$2 ;;
                --from-directory) local_release=$2 ;;
            esac
            shift 2 ;;
        --help)
            echo 'Usage: sh install.sh [--directory PATH] [--from-directory RELEASE_ARTIFACTS]'
            exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done
[ "$(uname -s)" = Linux ] && [ "$(uname -m)" = x86_64 ] || {
    echo 'This installer supports Linux x64 only.' >&2; exit 1;
}
[ "$(id -u)" -ne 0 ] || { echo 'Run this per-user installer without sudo.' >&2; exit 1; }
case "$root" in /*) ;; *) echo 'Installation directory must be absolute.' >&2; exit 2 ;; esac
staging=$(mktemp -d)
trap 'rm -rf "$staging"' EXIT HUP INT TERM
asset=gorak-linux-x64
if [ -n "$local_release" ]; then
    cp "$local_release/$asset" "$staging/$asset"
    cp "$local_release/SHA256SUMS" "$staging/SHA256SUMS"
else
    releases=https://github.com/dougwhite/gorak/releases
    latest=$(curl --proto '=https' --proto-redir '=https' -fsSL -o /dev/null -w '%{url_effective}' "$releases/latest")
    case "$latest" in "$releases/tag/"*) tag=${latest##*/} ;; *) echo 'Unexpected release redirect.' >&2; exit 1 ;; esac
    case "$tag" in v[0-9]*) ;; *) echo 'Invalid release tag.' >&2; exit 1 ;; esac
    case "$tag" in *[!A-Za-z0-9.+-]*) echo 'Invalid release tag.' >&2; exit 1 ;; esac
    for name in "$asset" SHA256SUMS; do
        curl --proto '=https' --proto-redir '=https' -fsSL "$releases/download/$tag/$name" -o "$staging/$name"
    done
fi
hash=$(awk -v name="$asset" '$2 == name { print $1 }' "$staging/SHA256SUMS")
[ "${#hash}" -eq 64 ] || { echo 'Missing or ambiguous executable checksum.' >&2; exit 1; }
case "$hash" in *[!0-9a-f]*) echo 'Invalid executable checksum.' >&2; exit 1 ;; esac
printf '%s  %s\n' "$hash" "$staging/$asset" | sha256sum --check --status
chmod 700 "$staging/$asset"
"$staging/$asset" --_install --root "$root" --scope user --sha256 "$hash"
printf '\nAdd this directory to PATH: %s/bin\n' "$root"
printf 'For the default location, add this to your shell profile:\n  export PATH="$HOME/.gorak/bin:$PATH"\n'
printf 'Then run gorak --version. Shell profiles have not been changed.\n'
