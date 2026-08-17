"""
Generates VAPID keys and writes them into local.settings.json.
Uses only the `cryptography` library (installed as a pywebpush dependency).
Run via install.bat — not intended to be called directly.
"""
import base64
import json
import pathlib
import sys

SETTINGS = pathlib.Path("local.settings.json")
PEM_FILE = pathlib.Path("private_key.pem")


def main():
    try:
        from cryptography.hazmat.primitives.asymmetric.ec import generate_private_key, SECP256R1
        from cryptography.hazmat.primitives import serialization
    except ImportError:
        print("  ERROR: cryptography package not found. Run: pip install -r requirements.txt")
        sys.exit(1)

    if not SETTINGS.exists():
        print("  ERROR: local.settings.json not found.")
        sys.exit(1)

    settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
    existing = settings["Values"].get("VAPID_PUBLIC_KEY", "")
    if existing and not existing.startswith("<"):
        print("  VAPID keys already configured — skipping generation.")
        return

    key = generate_private_key(SECP256R1())

    # Raw 32-byte private scalar → base64url (pywebpush 2.x accepts this format)
    raw_priv = key.private_numbers().private_value.to_bytes(32, "big")
    private_b64 = base64.urlsafe_b64encode(raw_priv).rstrip(b"=").decode()

    # 65-byte uncompressed public point → base64url (Web Push applicationServerKey)
    pub_bytes = key.public_key().public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    public_b64 = base64.urlsafe_b64encode(pub_bytes).rstrip(b"=").decode()

    # Save PEM for reference / backup
    PEM_FILE.write_bytes(key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ))

    settings["Values"]["VAPID_PUBLIC_KEY"] = public_b64
    settings["Values"]["VAPID_PRIVATE_KEY"] = private_b64
    SETTINGS.write_text(json.dumps(settings, indent=2), encoding="utf-8")

    print(f"  Public key:  {public_b64[:40]}...")
    print(f"  Private key: {private_b64[:20]}...")
    print("  Written to local.settings.json  |  PEM backup: private_key.pem")
    print()
    print("  For Azure deployment, set these as Function App Application Settings:")
    print(f"    VAPID_PUBLIC_KEY  = {public_b64}")
    print(f"    VAPID_PRIVATE_KEY = {private_b64}")


if __name__ == "__main__":
    main()
