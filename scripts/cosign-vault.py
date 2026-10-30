#!/usr/bin/env python3
"""Sign/verify an OCI image with the Vault Transit key using short-lived K8s auth.

Tokens and Vault response bodies stay in process memory. The Vault CA is public
data and is written only to a temporary file required by cosign's TLS client.
The caller must log in to the registry using its existing short-lived Docker
configuration before signing.
"""
from __future__ import annotations

import argparse
import base64
import json
import pathlib
import ssl
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

NAMESPACE = "hm-sec"
LOCAL_PORT = "18202"


def run(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(args, check=True, capture_output=True, timeout=120, **kwargs)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("sign", "verify", "public-key"))
    parser.add_argument("image", nargs="?", help="Immutable image reference (prefer registry/repo@sha256:digest)")
    parser.add_argument("--output", help="Output path for a public key (public-key action only)")
    parser.add_argument("--public-key", default=str(pathlib.Path(__file__).resolve().with_name("cosign.pub")),
                        help="Public key used for offline verification")
    args = parser.parse_args()
    if args.action != "public-key" and (not args.image or "@sha256:" not in args.image):
        raise SystemExit("Use an immutable image digest, not a mutable tag")

    ca_b64 = run([
        "kubectl", "get", "secret", "vault-server-tls", "-n", NAMESPACE,
        "-o", "jsonpath={.data.ca\\.crt}",
    ], text=True).stdout.strip()
    ca_pem = base64.b64decode(ca_b64)
    tls = ssl.create_default_context(cadata=ca_pem.decode())

    with tempfile.TemporaryDirectory(prefix="cosign-vault-") as temp:
        ca_path = pathlib.Path(temp) / "vault-ca.pem"
        ca_path.write_bytes(ca_pem)
        forward = subprocess.Popen(
            ["kubectl", "port-forward", "-n", NAMESPACE, "svc/vault", f"{LOCAL_PORT}:8200"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            endpoint = f"https://127.0.0.1:{LOCAL_PORT}/v1/"

            def api(path: str, body: dict | None = None) -> dict:
                data = None if body is None else json.dumps(body).encode()
                request = urllib.request.Request(
                    endpoint + path, data=data,
                    headers={"Content-Type": "application/json"}, method="POST",
                )
                try:
                    with urllib.request.urlopen(request, context=tls, timeout=8) as response:
                        return json.loads(response.read())
                except urllib.error.HTTPError as error:
                    raise RuntimeError(f"Vault auth returned HTTP {error.code}") from None

            for _ in range(40):
                try:
                    jwt = run([
                        "kubectl", "create", "token", "jenkins-cosign", "-n", "cicd",
                        "--duration=10m", "--audience=vault",
                    ], text=True).stdout.strip()
                    response = api("auth/kubernetes/login", {"role": "jenkins-cosign", "jwt": jwt})
                    vault_token = response.get("auth", {}).get("client_token")
                    if vault_token:
                        break
                except Exception:
                    if forward.poll() is not None:
                        raise RuntimeError("Vault port-forward exited") from None
                    time.sleep(0.5)
            else:
                raise RuntimeError("Vault Kubernetes auth did not return a token")

            env = dict(__import__("os").environ)
            env.update({
                "VAULT_ADDR": f"https://127.0.0.1:{LOCAL_PORT}",
                "VAULT_TOKEN": vault_token,
                "VAULT_CACERT": str(ca_path),
                "TRANSIT_SECRET_ENGINE_PATH": "transit",
            })
            signing_config = pathlib.Path(temp) / "signing-config.json"
            run([
                "cosign", "signing-config", "create", "--no-default-fulcio",
                "--no-default-oidc", "--no-default-rekor", "--no-default-tsa",
                "--out", str(signing_config),
            ], text=True)
            if args.action == "sign":
                command = ["cosign", "sign", "--yes", "--key", "hashivault://cosign",
                           "--signing-config", str(signing_config), "--allow-http-registry", args.image]
            elif args.action == "verify":
                command = ["cosign", "verify", "--key", args.public_key,
                           "--insecure-ignore-tlog", "--allow-http-registry", args.image]
            else:
                if not args.output:
                    raise SystemExit("--output is required for public-key action")
                command = ["cosign", "public-key", "--key", "hashivault://cosign"]
            result = subprocess.run(command, env=env, text=True, capture_output=True, timeout=120)
            if result.returncode:
                detail = (result.stderr or result.stdout or "cosign failed").replace(vault_token, "[REDACTED]").replace(jwt, "[REDACTED]")
                raise RuntimeError(detail[-1200:])
            if args.action == "public-key":
                pathlib.Path(args.output).write_text(result.stdout)
                print("Vault Transit public key exported; private key material is not exportable")
            else:
                print(f"cosign {args.action} succeeded for immutable image digest")
            if args.action == "verify":
                print(f"Verified signatures: {len(json.loads(result.stdout))}")
        finally:
            forward.terminate()
            try:
                forward.wait(timeout=3)
            except subprocess.TimeoutExpired:
                forward.kill()
                forward.wait(timeout=3)


if __name__ == "__main__":
    main()
