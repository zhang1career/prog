# Sourced by board flash scripts. Sets HW_PROG to this tree's prog executable.
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  echo "source this file; do not execute it" >&2
  exit 1
fi

if [[ -z "${HW_PROG:-}" ]]; then
  HW_PROG="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/prog"
fi

if [[ ! -x "$HW_PROG" ]]; then
  echo "prog tool is not executable: $HW_PROG" >&2
  return 1
fi
