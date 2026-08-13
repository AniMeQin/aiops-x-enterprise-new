#!/bin/sh
set -eu

if [ "$#" -ne 2 ]; then
  echo "usage: $0 <output-directory> <server-ip-or-dns>" >&2
  exit 2
fi

output_directory=$1
server_name=$2
umask 077
mkdir -p "$output_directory"

case "$server_name" in
  *:*) echo "server name must be an IP address or DNS name" >&2; exit 2 ;;
esac

openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 \
  -out "$output_directory/ca-key.pem" >/dev/null 2>&1
openssl req -x509 -new -sha256 -days 3650 \
  -key "$output_directory/ca-key.pem" \
  -subj "/CN=AIOps-X Agent CA" \
  -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
  -addext "keyUsage=critical,keyCertSign,cRLSign" \
  -out "$output_directory/ca-cert.pem"

openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 \
  -out "$output_directory/server-key.pem" >/dev/null 2>&1
openssl req -new -sha256 -key "$output_directory/server-key.pem" \
  -subj "/CN=$server_name" -out "$output_directory/server.csr"
case "$server_name" in
  *[!0-9.]* ) subject_alt_name="DNS:$server_name" ;;
  * ) subject_alt_name="IP:$server_name" ;;
esac
cat >"$output_directory/server-ext.cnf" <<EOF
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=$subject_alt_name,DNS:agent-gateway
EOF
openssl x509 -req -sha256 -days 825 \
  -in "$output_directory/server.csr" \
  -CA "$output_directory/ca-cert.pem" \
  -CAkey "$output_directory/ca-key.pem" \
  -CAcreateserial \
  -extfile "$output_directory/server-ext.cnf" \
  -out "$output_directory/server-cert.pem" >/dev/null 2>&1

openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 \
  -out "$output_directory/task-signing-key.pem" >/dev/null 2>&1
openssl req -x509 -new -sha256 -days 825 \
  -key "$output_directory/task-signing-key.pem" \
  -subj "/CN=AIOps-X Agent Task Signing" \
  -addext "basicConstraints=critical,CA:FALSE" \
  -addext "keyUsage=critical,digitalSignature" \
  -out "$output_directory/task-signing-cert.pem"

mv "$output_directory/ca-key.pem" "$output_directory/agent-ca-key.pem"
mv "$output_directory/ca-cert.pem" "$output_directory/agent-ca-cert.pem"
mv "$output_directory/server-key.pem" "$output_directory/agent-server-key.pem"
mv "$output_directory/server-cert.pem" "$output_directory/agent-server-cert.pem"
mv "$output_directory/task-signing-key.pem" "$output_directory/agent-task-signing-key.pem"
mv "$output_directory/task-signing-cert.pem" "$output_directory/agent-task-signing-cert.pem"
rm -f "$output_directory/server.csr" "$output_directory/server-ext.cnf" "$output_directory/ca-cert.srl"
chmod 600 "$output_directory"/*-key.pem
chmod 644 "$output_directory"/*-cert.pem
echo "Agent PKI generated in $output_directory"
