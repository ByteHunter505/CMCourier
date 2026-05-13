#!/usr/bin/env bash
#
# Generate the JCEKS metadata keystore that Alfresco 23.x Community needs to
# bootstrap. Idempotent — does nothing if the keystore already exists.
#
# Usage (from this directory, on the staging host):
#   bash generate-keystore.sh
#
# The output keystore lands at:
#   ./alfresco-extension/keystore/keystore
# which is mounted into the alfresco container at:
#   /usr/local/tomcat/shared/classes/alfresco/extension/keystore/keystore
# matching the `-Dencryption.keystore.location=...` flag in alfresco-compose.yml.
#
# WHY this exists: Alfresco 23.x Community does NOT ship a keystore embedded
# in the WAR. Without a real filesystem keystore the WAR crashes during Spring
# context init (FileNotFoundException -> Context [/alfresco] startup failed)
# and Tomcat serves 404 forever on /alfresco/*.
#
# We run keytool from inside a throwaway alfresco repository container so we
# don't have to install Java on the host.

set -euo pipefail

KEYSTORE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/alfresco-extension/keystore"
KEYSTORE_FILE="${KEYSTORE_DIR}/keystore"
IMAGE="alfresco/alfresco-content-repository-community:23.4.1"

# Default Alfresco metadata keystore passwords. These match the values in
# alfresco-compose.yml (-Dmetadata-keystore.password / .metadata.password).
# Override via environment if you want a non-default install.
: "${KEYSTORE_PASSWORD:=mp6yc0UD9e}"
: "${METADATA_KEY_PASSWORD:=oKIWzVdEdA}"

if [[ -f "${KEYSTORE_FILE}" ]]; then
  echo "Keystore already exists at ${KEYSTORE_FILE} — nothing to do."
  echo "Delete it first if you want to regenerate."
  exit 0
fi

mkdir -p "${KEYSTORE_DIR}"

echo "Generating ${KEYSTORE_FILE} via throwaway ${IMAGE} container..."
docker run --rm \
  -v "${KEYSTORE_DIR}:/out" \
  "${IMAGE}" \
  bash -c "/usr/lib/jvm/jre-17/bin/keytool -genseckey \
    -alias metadata \
    -keypass '${METADATA_KEY_PASSWORD}' \
    -storepass '${KEYSTORE_PASSWORD}' \
    -keystore /out/keystore \
    -storetype JCEKS \
    -keyalg DESede \
    -keysize 168 \
  && chmod 0644 /out/keystore"

echo
echo "Done. Keystore contents:"
docker run --rm \
  -v "${KEYSTORE_DIR}:/out" \
  "${IMAGE}" \
  /usr/lib/jvm/jre-17/bin/keytool -list \
    -storetype JCEKS \
    -storepass "${KEYSTORE_PASSWORD}" \
    -keystore /out/keystore 2>/dev/null | grep -E "(Keystore type|Your keystore|metadata,)"
