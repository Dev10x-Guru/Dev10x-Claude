#!/usr/bin/env bash
# Safe read-only database query wrapper around psql.
#
# Usage:
#   db.sh <database> "<SQL>"
#   db.sh <database> -f <file>
#   db.sh --list

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(dirname "$SCRIPT_DIR")"
SKILLS_DIR="$(dirname "$SKILL_DIR")"

declare -A DB_BACKEND=()
declare -A DB_ENV_VAR=()
declare -A DB_KR_SERVICE=()
declare -A DB_KR_ACCOUNT=()
declare -A DB_LABEL=()
declare -A ALIAS=()

load_config() {
  local config_file="$1"
  [[ -f "$config_file" ]] || return 0

  local output
  output=$("$SCRIPT_DIR/parse-databases.py" "$config_file") || return 0

  while IFS= read -r line; do
    [[ -z "$line" ]] && continue

    local name backend env_var kr_service kr_account label aliases
    name=$(printf '%s' "$line" | cut -d$'\t' -f1)
    backend=$(printf '%s' "$line" | cut -d$'\t' -f2)
    env_var=$(printf '%s' "$line" | cut -d$'\t' -f3)
    kr_service=$(printf '%s' "$line" | cut -d$'\t' -f4)
    kr_account=$(printf '%s' "$line" | cut -d$'\t' -f5)
    label=$(printf '%s' "$line" | cut -d$'\t' -f6)
    aliases=$(printf '%s' "$line" | cut -d$'\t' -f7)

    [[ -z "$name" ]] && continue
    [[ -n "${DB_BACKEND[$name]+x}" ]] && continue

    DB_BACKEND["$name"]="$backend"
    DB_ENV_VAR["$name"]="$env_var"
    DB_KR_SERVICE["$name"]="$kr_service"
    DB_KR_ACCOUNT["$name"]="$kr_account"
    DB_LABEL["$name"]="$label"

    IFS=',' read -ra alias_list <<< "$aliases"
    for a in "${alias_list[@]}"; do
      [[ -n "$a" ]] && ALIAS["$a"]="$name"
    done
  done <<< "$output"
}

discover_configs() {
  if [[ -n "${DB_CONFIG:-}" && -f "$DB_CONFIG" ]]; then
    load_config "$DB_CONFIG"
    return
  fi

  load_config "$SKILL_DIR/databases.yaml"

  # XDG user-level config (preferred global location — GH-448)
  load_config "${XDG_CONFIG_HOME:-$HOME/.config}/Dev10x/databases.yaml"

  # Deprecated fallback: legacy memory path (kept for backward compat)
  load_config "$HOME/.claude/memory/Dev10x/databases.yaml"

  for cfg in "$SKILLS_DIR"/*/databases.yaml; do
    [[ -f "$cfg" ]] || continue
    [[ "$cfg" == "$SKILL_DIR/databases.yaml" ]] && continue
    load_config "$cfg"
  done

  for cfg in "$HOME/.claude/skills"/*/databases.yaml; do
    [[ -f "$cfg" ]] || continue
    load_config "$cfg"
  done

  # Marketplace plugins (other installed plugin collections)
  for cfg in "$HOME/.claude/plugins/marketplaces"/*/skills/*/databases.yaml; do
    [[ -f "$cfg" ]] || continue
    load_config "$cfg"
  done
}

discover_configs

if [[ ${#DB_BACKEND[@]} -eq 0 ]]; then
  echo "ERROR: No databases configured." >&2
  echo "Create databases.yaml at ~/.config/Dev10x/databases.yaml or a skill directory." >&2
  echo "See: $SKILL_DIR/databases.yaml.example" >&2
  exit 1
fi

list_databases() {
  echo "Available databases:"
  echo
  for db in "${!DB_BACKEND[@]}"; do
    local backend="${DB_BACKEND[$db]}"
    local source_info=""
    case "$backend" in
      env)
        local var="${DB_ENV_VAR[$db]}"
        local status="set"
        [[ -z "${!var:-}" ]] && status="NOT SET"
        source_info="[env: $var=$status]"
        ;;
      keyring)
        source_info="[keyring: ${DB_KR_SERVICE[$db]}/${DB_KR_ACCOUNT[$db]}]"
        ;;
    esac
    local db_aliases=()
    for a in "${!ALIAS[@]}"; do
      [[ "${ALIAS[$a]}" == "$db" ]] && db_aliases+=("$a")
    done
    local alias_str=""
    if [[ ${#db_aliases[@]} -gt 0 ]]; then
      alias_str="(aliases: $(IFS=', '; echo "${db_aliases[*]}"))"
    fi
    printf "  %-20s %s  %s  %s\n" \
      "$db" "${DB_LABEL[$db]}" "$alias_str" "$source_info"
  done | sort
}

resolve_db() {
  local name="$1"
  if [[ -n "${ALIAS[$name]+x}" ]]; then
    echo "${ALIAS[$name]}"
  elif [[ -n "${DB_BACKEND[$name]+x}" ]]; then
    echo "$name"
  else
    echo "Unknown database: $name" >&2
    echo "Use --list to see available databases." >&2
    exit 1
  fi
}

get_dsn() {
  local db_key="$1"
  local backend="${DB_BACKEND[$db_key]}"

  local args=(--backend "$backend")
  case "$backend" in
    env)     args+=(--env-var "${DB_ENV_VAR[$db_key]}") ;;
    keyring) args+=(--service "${DB_KR_SERVICE[$db_key]}" --account "${DB_KR_ACCOUNT[$db_key]}") ;;
  esac

  "$SCRIPT_DIR/dsn-resolve.sh" "${args[@]}"
}

if [[ "${1:-}" == "--list" || "${1:-}" == "-l" ]]; then
  list_databases
  exit 0
fi

if [[ $# -lt 2 ]]; then
  echo "Usage: db.sh <database> \"<SQL>\"" >&2
  echo "       db.sh <database> -f <file>" >&2
  echo "       db.sh --list" >&2
  exit 1
fi

db_key=$(resolve_db "$1")
shift

dsn=$(get_dsn "$db_key")

# Extract password from DSN and pass via PGPASSWORD to avoid
# exposing credentials in the process listing (ps aux).
if [[ "$dsn" =~ ^postgres(ql)?://([^:]+):([^@]+)@(.+)$ ]]; then
  proto="${BASH_REMATCH[1]}"
  user="${BASH_REMATCH[2]}"
  pass="${BASH_REMATCH[3]}"
  rest="${BASH_REMATCH[4]}"
  export PGPASSWORD="$pass"
  dsn="postgres${proto}://${user}@${rest}"
fi

echo "-- ${DB_LABEL[$db_key]}" >&2

# Set psql prompt to show database alias prominently, preventing
# wrong-database execution when users have multiple psql sessions.
export PGAPPNAME="db.sh/$db_key"

if [[ "${1:-}" == "-f" || "${1:-}" == "--file" ]]; then
  exec psql "$dsn" \
    -c "SET statement_timeout = '30s'" \
    -c "SET default_transaction_read_only = on" \
    -v "prompt1=$db_key=> " \
    -f "$2"
else
  exec psql "$dsn" \
    -c "SET statement_timeout = '30s'" \
    -c "SET default_transaction_read_only = on" \
    -c "$1"
fi
