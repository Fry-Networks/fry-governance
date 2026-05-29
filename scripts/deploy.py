#!/usr/bin/env python3
"""
FryGovernance Deployment Script

Usage:
    python scripts/deploy.py testnet
    python scripts/deploy.py mainnet
    python scripts/deploy.py localnet
"""

import base64
import json
import os
import sys
from pathlib import Path

from algosdk import account, mnemonic, transaction
from algosdk.v2client import algod
from algosdk.abi import Contract
from algosdk.atomic_transaction_composer import (
    AtomicTransactionComposer,
    AccountTransactionSigner,
    TransactionWithSigner,
)
from algokit_utils import (
    get_algod_client,
    get_algonode_config,
)
from dotenv import load_dotenv

# Paths
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
ARTIFACTS_DIR = PROJECT_ROOT / "smart_contracts" / "fry_governance" / "artifacts"


def get_client(network: str) -> algod.AlgodClient:
    """Get Algod client for the specified network."""
    if network == "localnet":
        return algod.AlgodClient(
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "http://localhost:4001"
        )
    elif network == "testnet":
        return get_algod_client(get_algonode_config("testnet", "algod", ""))
    elif network == "mainnet":
        return get_algod_client(get_algonode_config("mainnet", "algod", ""))
    else:
        raise ValueError(f"Unknown network: {network}")


def load_env(network: str) -> None:
    """Load environment variables for the specified network."""
    env_file = PROJECT_ROOT / f".env.{network}"
    if env_file.exists():
        load_dotenv(env_file)
    else:
        load_dotenv()


def get_deployer_account(network: str) -> tuple[str, str]:
    """Get deployer account from environment. Returns (address, private_key)."""
    load_env(network)

    deployer_mnemonic = os.environ.get("DEPLOYER_MNEMONIC")
    if not deployer_mnemonic:
        raise ValueError(
            f"DEPLOYER_MNEMONIC not found. Set it in .env.{network} or environment."
        )

    private_key = mnemonic.to_private_key(deployer_mnemonic)
    address = account.address_from_private_key(private_key)

    return address, private_key


def get_fry_asa_id(network: str) -> int:
    """Get FRY ASA ID from environment."""
    load_env(network)

    fry_asa_id = os.environ.get("FRY_ASA_ID")
    if not fry_asa_id:
        raise ValueError(
            f"FRY_ASA_ID not found. Set it in .env.{network} or environment."
        )

    return int(fry_asa_id)


def load_teal_programs() -> tuple[bytes, bytes]:
    """Load compiled TEAL programs."""
    approval_path = ARTIFACTS_DIR / "FryGovernance.approval.teal"
    clear_path = ARTIFACTS_DIR / "FryGovernance.clear.teal"

    if not approval_path.exists():
        raise FileNotFoundError(f"Approval program not found: {approval_path}")
    if not clear_path.exists():
        raise FileNotFoundError(f"Clear program not found: {clear_path}")

    return approval_path.read_text(), clear_path.read_text()


def load_arc56_spec() -> dict:
    """Load ARC56 application specification."""
    arc56_path = ARTIFACTS_DIR / "FryGovernance.arc56.json"
    if not arc56_path.exists():
        raise FileNotFoundError(f"ARC56 spec not found: {arc56_path}")

    return json.loads(arc56_path.read_text())


def deploy(network: str) -> tuple[int, str]:
    """Deploy FryGovernance contract to the specified network."""
    print(f"\n{'='*60}")
    print(f"Deploying FryGovernance to {network}")
    print(f"{'='*60}\n")

    # Get client, account, and FRY ASA ID
    client = get_client(network)
    deployer_address, deployer_key = get_deployer_account(network)
    fry_asa_id = get_fry_asa_id(network)

    print(f"Deployer address: {deployer_address}")
    print(f"FRY ASA ID: {fry_asa_id}")

    # Check deployer balance
    account_info = client.account_info(deployer_address)
    balance = account_info.get("amount", 0)
    print(f"Deployer balance: {balance / 1_000_000:.6f} ALGO")

    if balance < 1_000_000:  # 1 ALGO minimum
        raise ValueError("Deployer account needs at least 1 ALGO")

    # Load TEAL programs
    print("\nLoading TEAL programs...")
    approval_teal, clear_teal = load_teal_programs()

    # Compile TEAL
    print("Compiling programs...")
    approval_result = client.compile(approval_teal)
    clear_result = client.compile(clear_teal)

    approval_program = base64.b64decode(approval_result["result"])
    clear_program = base64.b64decode(clear_result["result"])

    print(f"Approval program size: {len(approval_program)} bytes")
    print(f"Clear program size: {len(clear_program)} bytes")

    # Load ARC56 spec for schema
    arc56_spec = load_arc56_spec()

    # Get state schema from ARC56
    state = arc56_spec.get("state", {})
    global_schema = state.get("schema", {}).get("global", {})
    local_schema = state.get("schema", {}).get("local", {})

    global_ints = global_schema.get("ints", 0)
    global_bytes = global_schema.get("bytes", 0)
    local_ints = local_schema.get("ints", 0)
    local_bytes = local_schema.get("bytes", 0)

    print(f"Global schema: {global_ints} ints, {global_bytes} bytes")
    print(f"Local schema: {local_ints} ints, {local_bytes} bytes")

    # Get suggested params
    sp = client.suggested_params()

    # Create application using ABI method call
    # The create method signature from ARC56: create(uint64)void
    print("\nCreating application...")

    # Build the application create transaction
    create_txn = transaction.ApplicationCreateTxn(
        sender=deployer_address,
        sp=sp,
        on_complete=transaction.OnComplete.NoOpOC,
        approval_program=approval_program,
        clear_program=clear_program,
        global_schema=transaction.StateSchema(global_ints, global_bytes),
        local_schema=transaction.StateSchema(local_ints, local_bytes),
        # ABI method call for create(uint64)void
        app_args=[
            # Method selector for "create(uint64)void"
            bytes.fromhex("240d2f67"),  # First 4 bytes of sha512_256("create(uint64)void")
            # FRY ASA ID as uint64 (big-endian)
            fry_asa_id.to_bytes(8, "big"),
        ],
    )

    # Sign and send
    signed_txn = create_txn.sign(deployer_key)
    txid = client.send_transaction(signed_txn)
    print(f"Transaction ID: {txid}")

    # Wait for confirmation
    result = transaction.wait_for_confirmation(client, txid, 4)
    app_id = result["application-index"]
    app_address = transaction.logic.get_application_address(app_id)

    print(f"\n{'='*60}")
    print(f"Deployment Successful!")
    print(f"{'='*60}")
    print(f"App ID: {app_id}")
    print(f"App Address: {app_address}")
    print(f"Creator: {deployer_address}")
    print(f"Transaction ID: {txid}")
    print(f"Network: {network}")
    print(f"{'='*60}\n")

    # Post-deployment steps
    print("Post-deployment steps required:")
    print("1. Call opt_in_fry() to opt contract into FRY ASA")
    print("2. Call admin_set_min_balance() with minimum FRY balance for temp checks")
    print("3. Fund contract with minimum balance for expected box storage")
    print()

    return app_id, app_address


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/deploy.py <network>")
        print("Networks: localnet, testnet, mainnet")
        sys.exit(1)

    network = sys.argv[1].lower()

    if network not in ["localnet", "testnet", "mainnet"]:
        print(f"Unknown network: {network}")
        print("Valid networks: localnet, testnet, mainnet")
        sys.exit(1)

    try:
        app_id, app_address = deploy(network)
        print(f"Deployed app ID: {app_id}")
        print(f"\nUpdate .env.{network} with:")
        print(f"CONTRACT_APP_ID={app_id}")
    except Exception as e:
        print(f"Deployment failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
