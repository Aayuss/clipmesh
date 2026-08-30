#!/usr/bin/env bash
set -euo pipefail

umask 077

readonly REPOSITORY="Aayuss/clipmesh"
readonly SIGNING_DIRECTORY="${HOME}/.clipmesh-release-signing"
readonly KEYSTORE_PATH="${SIGNING_DIRECTORY}/clipmesh-android-release.jks"
readonly KEY_ALIAS="clipmesh-release"
readonly STORE_PASSWORD_SERVICE="ClipMesh Android Release Keystore Password"
readonly KEY_PASSWORD_SERVICE="ClipMesh Android Release Key Password"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

if [[ "$(uname -s)" != "Darwin" ]]; then
  fail "Run this setup only on the persistent macOS machine where the release keystore will be backed up."
fi

for command_name in gh security keytool openssl base64 awk grep tr chmod mkdir ln rm id uname; do
  command -v "${command_name}" >/dev/null 2>&1 || fail "Required command not found: ${command_name}"
done

gh auth status >/dev/null 2>&1 || fail "GitHub CLI is not authenticated. Run: gh auth login"
gh repo view "${REPOSITORY}" --json nameWithOwner --jq '.nameWithOwner' \
  | grep -Fx "${REPOSITORY}" >/dev/null \
  || fail "The authenticated GitHub account cannot access ${REPOSITORY}."

readonly KEYCHAIN_ACCOUNT="$(id -un)"
readonly KEYCHAIN_PATH="${HOME}/Library/Keychains/login.keychain-db"
[[ -f "${KEYCHAIN_PATH}" ]] || fail "Login keychain not found at ${KEYCHAIN_PATH}."

mkdir -p "${SIGNING_DIRECTORY}"
chmod 700 "${SIGNING_DIRECTORY}"

[[ ! -L "${KEYSTORE_PATH}" ]] || fail "Refusing to use a symlink as the release keystore: ${KEYSTORE_PATH}"
if [[ -e "${KEYSTORE_PATH}" && ! -f "${KEYSTORE_PATH}" ]]; then
  fail "Release keystore path exists but is not a regular file: ${KEYSTORE_PATH}"
fi

keystore_exists=0
store_password_exists=0
key_password_exists=0
[[ -f "${KEYSTORE_PATH}" ]] && keystore_exists=1
security find-generic-password -a "${KEYCHAIN_ACCOUNT}" -s "${STORE_PASSWORD_SERVICE}" -w >/dev/null 2>&1 \
  && store_password_exists=1 || true
security find-generic-password -a "${KEYCHAIN_ACCOUNT}" -s "${KEY_PASSWORD_SERVICE}" -w >/dev/null 2>&1 \
  && key_password_exists=1 || true

state_total=$((keystore_exists + store_password_exists + key_password_exists))
if [[ "${state_total}" -ne 0 && "${state_total}" -ne 3 ]]; then
  fail "Partial signing state detected. No files or Keychain entries were changed. Resolve the mismatch among ${KEYSTORE_PATH} and the two ClipMesh Keychain password items, then rerun."
fi

temporary_keystore=""
created_store_password=0
created_key_password=0
created_keystore=0
cleanup_failed_provisioning() {
  status=$?
  if [[ -n "${temporary_keystore}" && -f "${temporary_keystore}" ]]; then
    rm -f -- "${temporary_keystore}"
  fi
  if [[ "${status}" -ne 0 ]]; then
    if [[ "${created_key_password}" -eq 1 ]]; then
      security delete-generic-password -a "${KEYCHAIN_ACCOUNT}" -s "${KEY_PASSWORD_SERVICE}" >/dev/null 2>&1 || true
    fi
    if [[ "${created_store_password}" -eq 1 ]]; then
      security delete-generic-password -a "${KEYCHAIN_ACCOUNT}" -s "${STORE_PASSWORD_SERVICE}" >/dev/null 2>&1 || true
    fi
    if [[ "${created_keystore}" -eq 1 && -f "${KEYSTORE_PATH}" ]]; then
      rm -f -- "${KEYSTORE_PATH}"
    fi
  fi
}
trap cleanup_failed_provisioning EXIT

if [[ "${state_total}" -eq 0 ]]; then
  store_password="$(openssl rand -base64 48 | tr -d '\n')"
  key_password="$(openssl rand -base64 48 | tr -d '\n')"
  temporary_keystore="${SIGNING_DIRECTORY}/.clipmesh-android-release.$$.jks"

  CLIPMESH_SETUP_STORE_PASSWORD="${store_password}" \
  CLIPMESH_SETUP_KEY_PASSWORD="${key_password}" \
    keytool -genkeypair \
      -keystore "${temporary_keystore}" \
      -storetype JKS \
      -storepass:env CLIPMESH_SETUP_STORE_PASSWORD \
      -keypass:env CLIPMESH_SETUP_KEY_PASSWORD \
      -alias "${KEY_ALIAS}" \
      -keyalg RSA \
      -keysize 4096 \
      -validity 10000 \
      -dname "CN=ClipMesh Android Release, O=ClipMesh, C=NP" \
      -noprompt >/dev/null
  chmod 600 "${temporary_keystore}"

  security add-generic-password -U -a "${KEYCHAIN_ACCOUNT}" -s "${STORE_PASSWORD_SERVICE}" \
    -w "${store_password}" "${KEYCHAIN_PATH}" >/dev/null
  created_store_password=1
  security add-generic-password -U -a "${KEYCHAIN_ACCOUNT}" -s "${KEY_PASSWORD_SERVICE}" \
    -w "${key_password}" "${KEYCHAIN_PATH}" >/dev/null
  created_key_password=1

  ln "${temporary_keystore}" "${KEYSTORE_PATH}"
  created_keystore=1
  rm -f -- "${temporary_keystore}"
  temporary_keystore=""
  created_store_password=0
  created_key_password=0
  created_keystore=0
fi

chmod 600 "${KEYSTORE_PATH}"
store_password="$(security find-generic-password -a "${KEYCHAIN_ACCOUNT}" -s "${STORE_PASSWORD_SERVICE}" -w)"
key_password="$(security find-generic-password -a "${KEYCHAIN_ACCOUNT}" -s "${KEY_PASSWORD_SERVICE}" -w)"

CLIPMESH_SETUP_STORE_PASSWORD="${store_password}" \
  keytool -list -keystore "${KEYSTORE_PATH}" -storetype JKS \
    -storepass:env CLIPMESH_SETUP_STORE_PASSWORD -alias "${KEY_ALIAS}" >/dev/null

certificate_sha256="$({
  LC_ALL=C CLIPMESH_SETUP_STORE_PASSWORD="${store_password}" \
    keytool -list -v -keystore "${KEYSTORE_PATH}" -storetype JKS \
      -storepass:env CLIPMESH_SETUP_STORE_PASSWORD -alias "${KEY_ALIAS}"
} | LC_ALL=C awk -F': ' '/SHA256:/{print tolower($2); exit}' | tr -d ':[:space:]')"
[[ "${certificate_sha256}" =~ ^[0-9a-f]{64}$ ]] \
  || fail "Could not derive the signing certificate SHA-256 fingerprint."

keystore_base64="$(base64 < "${KEYSTORE_PATH}" | tr -d '\n')"
set_github_secret() {
  local secret_name="$1"
  local secret_value="$2"
  if ! printf '%s' "${secret_value}" | gh secret set "${secret_name}" --repo "${REPOSITORY}"; then
    fail "GitHub secret update failed at ${secret_name}. Earlier GitHub names may already be updated; the local key is intact and rerunning this command is safe."
  fi
}
set_github_secret CLIPMESH_ANDROID_KEYSTORE_B64 "${keystore_base64}"
set_github_secret CLIPMESH_ANDROID_KEYSTORE_PASSWORD "${store_password}"
set_github_secret CLIPMESH_ANDROID_KEY_ALIAS "${KEY_ALIAS}"
set_github_secret CLIPMESH_ANDROID_KEY_PASSWORD "${key_password}"
if ! gh variable set CLIPMESH_ANDROID_SIGNING_CERT_SHA256 --repo "${REPOSITORY}" --body "${certificate_sha256}"; then
  fail "GitHub variable update failed. The local key and uploaded secrets are intact; rerunning this command is safe."
fi

required_secret_names=(
  CLIPMESH_ANDROID_KEYSTORE_B64
  CLIPMESH_ANDROID_KEYSTORE_PASSWORD
  CLIPMESH_ANDROID_KEY_ALIAS
  CLIPMESH_ANDROID_KEY_PASSWORD
)
configured_secret_names="$(gh secret list --repo "${REPOSITORY}" --json name --jq '.[].name')"
for required_name in "${required_secret_names[@]}"; do
  grep -Fx "${required_name}" <<<"${configured_secret_names}" >/dev/null \
    || fail "GitHub did not report required secret name: ${required_name}"
done
configured_variable_names="$(gh variable list --repo "${REPOSITORY}" --json name --jq '.[].name')"
grep -Fx CLIPMESH_ANDROID_SIGNING_CERT_SHA256 <<<"${configured_variable_names}" >/dev/null \
  || fail "GitHub did not report required variable name: CLIPMESH_ANDROID_SIGNING_CERT_SHA256"

printf '\nAndroid release signing is configured for %s.\n' "${REPOSITORY}"
printf 'Keystore: %s\n' "${KEYSTORE_PATH}"
printf 'Public certificate SHA-256: %s\n' "${certificate_sha256}"
printf 'Verified GitHub secret/variable names only; no secret values were printed.\n'
printf '\nCRITICAL BACKUP REQUIRED: make an encrypted offline backup of the keystore and preserve both Keychain passwords. Losing them permanently prevents future updates under this Android signing identity.\n'
