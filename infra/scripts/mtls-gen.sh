#!/usr/bin/env bash
# Messer mTLS material for customer-cloud (BYOC) and on-premise data planes.
#
# Creates (or reuses) a private certificate authority and, for each environment, a client certificate that
# identifies the data plane to the control plane and a server certificate for the endpoint that terminates
# the connection. Keys are EC P-256, signatures SHA-256. Nothing is uploaded anywhere.
#
# Usage:
#   infra/scripts/mtls-gen.sh [options] <environment> [<environment> ...]
#
# Options:
#   -o, --out DIR          Output directory (default: ./mtls)
#   -d, --days N           Validity of environment certificates in days (default: 365)
#   --ca-days N            Validity of a new CA in days (default: 3650)
#   --ca-name NAME         Common name of a new CA (default: "Messer Data Plane CA")
#   --server-san NAMES     Comma-separated DNS names of the server certificate
#                          (default: dp-gateway.messer.eu,<environment>.dp.messer.eu)
#   --force                Re-issue environment certificates that already exist
#   -h, --help             Show this help
#
# Output layout:
#   DIR/ca/ca.key  DIR/ca/ca.crt
#   DIR/<env>/client.key DIR/<env>/client.crt   (CN=messer-data-plane:<env>, extendedKeyUsage=clientAuth)
#   DIR/<env>/server.key DIR/<env>/server.crt   (SAN from --server-san, extendedKeyUsage=serverAuth)
#   DIR/<env>/ca.crt                            (copy of the CA certificate)
#
# Then load the client material into the cluster as the chart's mTLS secret:
#   kubectl -n messer create secret generic messer-data-plane-mtls \
#     --from-file=ca.crt=DIR/<env>/ca.crt --from-file=tls.crt=DIR/<env>/client.crt --from-file=tls.key=DIR/<env>/client.key
set -euo pipefail

OUT="./mtls"
DAYS=365
CA_DAYS=3650
CA_NAME="Messer Data Plane CA"
SERVER_SAN=""
FORCE=0
ENVS=()

usage() { sed -n '2,32p' "$0" | sed 's/^# \{0,1\}//'; }
die() { echo "mtls-gen: $*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    -o|--out) OUT="${2:?}"; shift 2 ;;
    -d|--days) DAYS="${2:?}"; shift 2 ;;
    --ca-days) CA_DAYS="${2:?}"; shift 2 ;;
    --ca-name) CA_NAME="${2:?}"; shift 2 ;;
    --server-san) SERVER_SAN="${2:?}"; shift 2 ;;
    --force) FORCE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    -*) die "unknown option $1 (see --help)" ;;
    *) ENVS+=("$1"); shift ;;
  esac
done

command -v openssl >/dev/null 2>&1 || die "openssl is required"
[[ ${#ENVS[@]} -gt 0 ]] || { usage; die "give at least one environment name"; }
[[ "$DAYS" =~ ^[0-9]+$ && "$CA_DAYS" =~ ^[0-9]+$ ]] || die "--days and --ca-days must be numbers"

umask 077
mkdir -p "$OUT/ca"
CA_KEY="$OUT/ca/ca.key"
CA_CRT="$OUT/ca/ca.crt"

if [[ ! -f "$CA_KEY" || ! -f "$CA_CRT" ]]; then
  echo "Creating CA in $OUT/ca"
  openssl ecparam -name prime256v1 -genkey -noout -out "$CA_KEY"
  openssl req -x509 -new -key "$CA_KEY" -sha256 -days "$CA_DAYS" -subj "/O=Messer/CN=${CA_NAME}" \
    -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
    -addext "keyUsage=critical,keyCertSign,cRLSign" \
    -addext "subjectKeyIdentifier=hash" \
    -out "$CA_CRT"
else
  echo "Reusing CA $CA_CRT"
fi

issue() {
  # issue <dir> <name> <subject> <extensions-file>
  local dir="$1" name="$2" subject="$3" ext="$4"
  openssl ecparam -name prime256v1 -genkey -noout -out "$dir/$name.key"
  openssl req -new -key "$dir/$name.key" -subj "$subject" -out "$dir/$name.csr"
  openssl x509 -req -in "$dir/$name.csr" -CA "$CA_CRT" -CAkey "$CA_KEY" -CAcreateserial \
    -CAserial "$OUT/ca/ca.srl" -days "$DAYS" -sha256 -extfile "$ext" -out "$dir/$name.crt" 2>/dev/null
  rm -f "$dir/$name.csr"
  openssl verify -CAfile "$CA_CRT" "$dir/$name.crt" >/dev/null
}

for env in "${ENVS[@]}"; do
  [[ "$env" =~ ^[a-z0-9][a-z0-9-]{0,62}$ ]] || die "invalid environment name '$env' (lowercase letters, digits, dashes)"
  dir="$OUT/$env"
  if [[ -f "$dir/client.crt" && $FORCE -eq 0 ]]; then
    echo "Skipping $env (certificates exist; use --force to re-issue)"
    continue
  fi
  mkdir -p "$dir"
  sans="${SERVER_SAN:-dp-gateway.messer.eu,${env}.dp.messer.eu}"
  san_list=""
  IFS=',' read -r -a names <<<"$sans"
  for n in "${names[@]}"; do
    n="$(echo "$n" | tr -d '[:space:]')"
    [[ -n "$n" ]] && san_list="${san_list:+$san_list,}DNS:$n"
  done

  ext_client="$(mktemp)"; ext_server="$(mktemp)"
  trap 'rm -f "$ext_client" "$ext_server"' EXIT
  cat >"$ext_client" <<EXT
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyAgreement
extendedKeyUsage=clientAuth
subjectKeyIdentifier=hash
authorityKeyIdentifier=keyid,issuer
subjectAltName=URI:spiffe://messer/data-plane/${env}
EXT
  cat >"$ext_server" <<EXT
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyAgreement
extendedKeyUsage=serverAuth
subjectKeyIdentifier=hash
authorityKeyIdentifier=keyid,issuer
subjectAltName=${san_list}
EXT
  issue "$dir" client "/O=Messer/OU=data-plane/CN=messer-data-plane:${env}" "$ext_client"
  issue "$dir" server "/O=Messer/OU=gateway/CN=${names[0]}" "$ext_server"
  cp "$CA_CRT" "$dir/ca.crt"
  rm -f "$ext_client" "$ext_server"
  trap - EXIT
  echo "Issued $dir/client.crt and $dir/server.crt (valid $DAYS days)"
done

cat <<NEXT

Next steps:
  1. Register the CA certificate ($CA_CRT) for each environment with Messer when the environment is registered.
  2. Create the chart secret in the data-plane cluster:
       kubectl -n messer create secret generic messer-data-plane-mtls \\
         --from-file=ca.crt=$OUT/<env>/ca.crt --from-file=tls.crt=$OUT/<env>/client.crt --from-file=tls.key=$OUT/<env>/client.key
  3. Keep $CA_KEY offline (password manager or HSM); it is only needed to issue or rotate certificates.
NEXT
