#!/usr/bin/env python3
"""
FryGovernance Post-Deployment Script

CLI for interacting with deployed FryGovernance contract on testnet.

Usage:
    python scripts/post_deploy.py <command> [args]

Commands:
    create-fry-asa        Create test FRY ASA on testnet
    opt-in-fry            Opt contract into FRY ASA
    set-min-balance <amt> Set temp check threshold (in microunits)
    set-price <val> <usd> Set price parameters
    fund-contract <amt>   Send ALGO to contract (in microAlgos)
    create-user           Create/fund test user account
    create-vote           Create FIP or temp check vote
    cast-vote             Cast vote (FIP with staking)
    cast-temp-vote        Cast temp check vote
    withdraw              Withdraw staked FRY
    close-vote            Admin close vote
    emergency-refund      Admin emergency refund
    admin-update          Test creator update capability
    get-vote              Query vote state
    get-stake             Query stake state
    verify-all            Run full verification suite
"""

import base64
import hashlib
import os
import sys
import time
from pathlib import Path

from algosdk import account, mnemonic, transaction, abi, encoding
from algosdk.v2client import algod
from algosdk.atomic_transaction_composer import (
    AtomicTransactionComposer,
    AccountTransactionSigner,
    TransactionWithSigner,
)
from algokit_utils import (
    Account,
    get_algod_client,
    get_algonode_config,
)
from dotenv import load_dotenv, set_key
import json

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from smart_contracts.fry_governance.constants import (
    STAKE_BOX_MBR,
    STAKE_BOX_PREFIX,
    VOTE_BOX_MBR,
    VOTE_BOX_PREFIX,
    VOTE_TYPE_FIP,
    VOTE_TYPE_TEMP_CHECK,
)

# Load ARC56 spec for ABI
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
ARC56_PATH = PROJECT_ROOT / "smart_contracts" / "fry_governance" / "artifacts" / "FryGovernance.arc56.json"

# Determine network from environment or default to testnet
NETWORK = os.environ.get("DEPLOY_NETWORK", "testnet")
ENV_FILE = f".env.{NETWORK}"
load_dotenv(ENV_FILE)


def get_client() -> algod.AlgodClient:
    """Get Algod client for the configured network."""
    if NETWORK == "localnet":
        # Use local AlgoKit sandbox
        return algod.AlgodClient("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "http://localhost:4001")
    return get_algod_client(get_algonode_config(NETWORK, "algod", ""))


def get_deployer() -> Account:
    """Get deployer account from environment."""
    deployer_mnemonic = os.environ.get("DEPLOYER_MNEMONIC")
    if not deployer_mnemonic:
        raise ValueError(f"DEPLOYER_MNEMONIC not found in {ENV_FILE}")

    private_key = mnemonic.to_private_key(deployer_mnemonic)
    address = account.address_from_private_key(private_key)
    return Account(private_key=private_key, address=address)


def get_test_user() -> Account | None:
    """Get test user account from environment, or None if not set."""
    user_mnemonic = os.environ.get("TEST_USER_MNEMONIC")
    if not user_mnemonic:
        return None

    private_key = mnemonic.to_private_key(user_mnemonic)
    address = account.address_from_private_key(private_key)
    return Account(private_key=private_key, address=address)


def get_fry_asa_id() -> int | None:
    """Get FRY ASA ID from environment."""
    asa_id = os.environ.get("FRY_ASA_ID")
    if not asa_id:
        return None
    return int(asa_id)


def get_contract_app_id() -> int | None:
    """Get contract app ID from environment."""
    app_id = os.environ.get("CONTRACT_APP_ID")
    if not app_id:
        return None
    return int(app_id)


def get_abi_contract() -> abi.Contract:
    """Load ABI contract from ARC56 spec."""
    with open(ARC56_PATH) as f:
        arc56_spec = json.load(f)

    # Convert ARC56 to ABI contract format
    methods = []
    for m in arc56_spec.get("methods", []):
        # abi.Argument takes (arg_type, name) - type first!
        args = [abi.Argument(a["type"], a["name"]) for a in m.get("args", [])]
        returns = abi.Returns(m.get("returns", {}).get("type", "void"))
        methods.append(abi.Method(m["name"], args, returns, m.get("desc", "")))

    return abi.Contract(arc56_spec["name"], methods)


def get_app_address() -> str:
    """Get application address from app ID."""
    app_id = get_contract_app_id()
    if not app_id:
        raise ValueError(f"CONTRACT_APP_ID not found in {ENV_FILE}")
    return transaction.logic.get_application_address(app_id)


def call_method(
    method_name: str,
    args: list = None,
    foreign_assets: list = None,
    foreign_accounts: list = None,
    boxes: list = None,
    signer: Account = None,
    extra_payment: int = 0,
    extra_fee: int = 0,
) -> dict:
    """Call an ABI method on the contract."""
    client = get_client()
    app_id = get_contract_app_id()
    if not app_id:
        raise ValueError(f"CONTRACT_APP_ID not found in {ENV_FILE}")

    if signer is None:
        signer = get_deployer()

    contract = get_abi_contract()
    method = contract.get_method_by_name(method_name)

    atc = AtomicTransactionComposer()
    sp = client.suggested_params()

    # Add extra fee for inner transactions (fee pooling)
    if extra_fee > 0:
        sp.fee = sp.min_fee + extra_fee
        sp.flat_fee = True

    # Add payment transaction if needed
    if extra_payment > 0:
        pay_txn = transaction.PaymentTxn(
            sender=signer.address,
            sp=sp,
            receiver=get_app_address(),
            amt=extra_payment,
        )
        atc.add_transaction(TransactionWithSigner(pay_txn, AccountTransactionSigner(signer.private_key)))

    atc.add_method_call(
        app_id=app_id,
        method=method,
        sender=signer.address,
        sp=sp,
        signer=AccountTransactionSigner(signer.private_key),
        method_args=args or [],
        foreign_assets=foreign_assets or [],
        accounts=foreign_accounts or [],
        boxes=[(app_id, box) for box in (boxes or [])],
    )

    result = atc.execute(client, 4)
    return {
        "tx_id": result.tx_ids[-1],
        "return_value": result.abi_results[-1].return_value if result.abi_results else None,
    }


def make_vote_id(name: str) -> bytes:
    """Create a 32-byte vote ID from a name."""
    return hashlib.sha256(name.encode()).digest()


def make_stake_box_key(vote_id: bytes, voter_bytes: bytes) -> bytes:
    """Create stake box key using hash to fit 64-byte limit."""
    # Contract uses: STAKE_BOX_PREFIX + sha256(vote_id + voter)
    return STAKE_BOX_PREFIX + hashlib.sha256(vote_id + voter_bytes).digest()


def update_env(key: str, value: str) -> None:
    """Update a value in the current env file."""
    set_key(ENV_FILE, key, value)
    # Also update current environment
    os.environ[key] = value
    print(f"Updated {ENV_FILE}: {key}={value}")


# ============================================================================
# Commands
# ============================================================================


def cmd_create_fry_asa() -> None:
    """Create a test FRY ASA on testnet."""
    client = get_client()
    deployer = get_deployer()

    print(f"Creating test FRY ASA with deployer: {deployer.address}")

    # Get suggested params
    sp = client.suggested_params()

    # Create ASA
    txn = transaction.AssetConfigTxn(
        sender=deployer.address,
        sp=sp,
        total=10_000_000_000_000,  # 10M FRY with 6 decimals
        default_frozen=False,
        unit_name="FRY",
        asset_name="Fry Token (Testnet)",
        manager=deployer.address,
        reserve=deployer.address,
        freeze=deployer.address,
        clawback=deployer.address,
        decimals=6,
    )

    # Sign and send
    signed_txn = txn.sign(deployer.private_key)
    txid = client.send_transaction(signed_txn)
    print(f"Transaction ID: {txid}")

    # Wait for confirmation
    result = transaction.wait_for_confirmation(client, txid, 4)
    asa_id = result["asset-index"]

    print(f"\nFRY ASA created successfully!")
    print(f"ASA ID: {asa_id}")

    # Update {ENV_FILE}
    update_env("FRY_ASA_ID", str(asa_id))


def cmd_opt_in_fry() -> None:
    """Opt contract into FRY ASA."""
    app_id = get_contract_app_id()
    app_address = get_app_address()

    print(f"Opting contract into FRY ASA...")
    print(f"Contract App ID: {app_id}")
    print(f"Contract Address: {app_address}")

    fry_asa_id = get_fry_asa_id()
    if not fry_asa_id:
        raise ValueError(f"FRY_ASA_ID not set in {ENV_FILE}")

    print(f"FRY ASA ID: {fry_asa_id}")

    # Call opt_in_fry with extra fee for inner transaction
    result = call_method(
        "opt_in_fry",
        foreign_assets=[fry_asa_id],
        extra_fee=1000,  # Cover inner transaction fee
    )

    print(f"\nOpt-in successful!")
    print(f"Transaction ID: {result['tx_id']}")


def cmd_set_min_balance(amount: int) -> None:
    """Set minimum FRY balance for temp check voting."""
    print(f"Setting minimum balance to {amount} microunits ({amount / 1_000_000} FRY)")

    result = call_method(
        "admin_set_min_balance",
        args=[amount],
    )

    print(f"\nMin balance set successfully!")
    print(f"Transaction ID: {result['tx_id']}")


def cmd_set_price(price_value: int, price_is_usd: int) -> None:
    """Set price parameters."""
    print(f"Setting price: value={price_value}, is_usd={price_is_usd}")

    result = call_method(
        "admin_set_price",
        args=[price_value, price_is_usd],
    )

    print(f"\nPrice set successfully!")
    print(f"Transaction ID: {result['tx_id']}")


def cmd_fund_contract(amount: int) -> None:
    """Send ALGO to contract."""
    client = get_client()
    deployer = get_deployer()
    app_id = get_contract_app_id()

    if not app_id:
        raise ValueError(f"CONTRACT_APP_ID not set in {ENV_FILE}")

    # Get contract address
    app_info = client.application_info(app_id)
    app_address = app_info["params"]["accounts"][0] if app_info["params"].get("accounts") else None

    # Calculate app address from app ID
    from algosdk.logic import get_application_address
    app_address = get_application_address(app_id)

    print(f"Funding contract {app_address} with {amount} microAlgos ({amount / 1_000_000} ALGO)")

    sp = client.suggested_params()
    txn = transaction.PaymentTxn(
        sender=deployer.address,
        sp=sp,
        receiver=app_address,
        amt=amount,
    )

    signed_txn = txn.sign(deployer.private_key)
    txid = client.send_transaction(signed_txn)

    result = transaction.wait_for_confirmation(client, txid, 4)

    print(f"\nContract funded successfully!")
    print(f"Transaction ID: {txid}")


def cmd_create_user() -> None:
    """Create and fund a test user account."""
    client = get_client()
    deployer = get_deployer()

    # Check if user already exists
    existing_user = get_test_user()
    if existing_user:
        print(f"Test user already exists: {existing_user.address}")
        user = existing_user
    else:
        # Generate new account
        private_key, address = account.generate_account()
        user_mnemonic_str = mnemonic.from_private_key(private_key)
        user = Account(private_key=private_key, address=address)

        print(f"Created new test user: {address}")
        print(f"Mnemonic: {user_mnemonic_str}")

        # Save to {ENV_FILE}
        update_env("TEST_USER_MNEMONIC", user_mnemonic_str)

    # Fund user with ALGO
    print(f"\nFunding user with 10 ALGO...")
    sp = client.suggested_params()
    pay_txn = transaction.PaymentTxn(
        sender=deployer.address,
        sp=sp,
        receiver=user.address,
        amt=10_000_000,  # 10 ALGO
    )
    signed_pay = pay_txn.sign(deployer.private_key)
    txid = client.send_transaction(signed_pay)
    transaction.wait_for_confirmation(client, txid, 4)
    print(f"Funded user with ALGO. TxID: {txid}")

    # Opt user into FRY
    fry_asa_id = get_fry_asa_id()
    if not fry_asa_id:
        print("Warning: FRY_ASA_ID not set, skipping FRY opt-in")
        return

    print(f"\nOpting user into FRY ASA {fry_asa_id}...")
    sp = client.suggested_params()
    opt_in_txn = transaction.AssetTransferTxn(
        sender=user.address,
        sp=sp,
        receiver=user.address,
        amt=0,
        index=fry_asa_id,
    )
    signed_opt = opt_in_txn.sign(user.private_key)
    txid = client.send_transaction(signed_opt)
    transaction.wait_for_confirmation(client, txid, 4)
    print(f"User opted into FRY. TxID: {txid}")

    # Send test FRY to user
    print(f"\nSending 100 FRY to user...")
    sp = client.suggested_params()
    fry_txn = transaction.AssetTransferTxn(
        sender=deployer.address,
        sp=sp,
        receiver=user.address,
        amt=100_000_000,  # 100 FRY with 6 decimals
        index=fry_asa_id,
    )
    signed_fry = fry_txn.sign(deployer.private_key)
    txid = client.send_transaction(signed_fry)
    transaction.wait_for_confirmation(client, txid, 4)
    print(f"Sent FRY to user. TxID: {txid}")

    print(f"\nTest user setup complete!")
    print(f"Address: {user.address}")


def cmd_create_vote(vote_name: str, vote_type: int = VOTE_TYPE_FIP, lock_seconds: int | None = None) -> None:
    """Create a new vote."""
    client = get_client()
    deployer = get_deployer()
    app_id = get_contract_app_id()
    app_address = get_app_address()

    vote_id = make_vote_id(vote_name)
    vote_type_name = "FIP" if vote_type == VOTE_TYPE_FIP else "Temp Check"

    print(f"Creating {vote_type_name} vote: {vote_name}")
    print(f"Vote ID (hex): {vote_id.hex()}")

    # Calculate end date (30 days from now)
    end_date = int(time.time()) + (86400 * 30)
    # Lock duration: custom if provided, else 6 months for FIP, 0 for temp check
    if lock_seconds is not None:
        lock_duration = lock_seconds
    else:
        lock_duration = 15_768_000 if vote_type == VOTE_TYPE_FIP else 0

    # Use ATC for proper ABI method call with payment
    contract = get_abi_contract()
    method = contract.get_method_by_name("create_vote")

    atc = AtomicTransactionComposer()
    sp = client.suggested_params()

    # Payment transaction for MBR
    pay_txn = transaction.PaymentTxn(
        sender=deployer.address,
        sp=sp,
        receiver=app_address,
        amt=VOTE_BOX_MBR,
    )

    atc.add_method_call(
        app_id=app_id,
        method=method,
        sender=deployer.address,
        sp=sp,
        signer=AccountTransactionSigner(deployer.private_key),
        method_args=[
            list(vote_id),  # vote_id
            3,  # options_count
            end_date,  # end_date
            lock_duration,  # lock_duration
            0,  # super_majority
            vote_type,  # vote_type
            TransactionWithSigner(pay_txn, AccountTransactionSigner(deployer.private_key)),  # pay txn
        ],
        boxes=[(app_id, VOTE_BOX_PREFIX + vote_id)],
    )

    result = atc.execute(client, 4)

    print(f"\nVote created successfully!")
    print(f"Transaction ID: {result.tx_ids[-1]}")
    print(f"Vote ID: {vote_name}")
    print(f"End Date: {end_date}")


def cmd_cast_vote(vote_name: str, option: int, amount: int) -> None:
    """Cast a vote with FRY staking."""
    client = get_client()
    user = get_test_user()
    if not user:
        raise ValueError(f"TEST_USER_MNEMONIC not set in {ENV_FILE}")

    app_id = get_contract_app_id()
    fry_asa_id = get_fry_asa_id()
    app_address = get_app_address()

    if not app_id or not fry_asa_id:
        raise ValueError("CONTRACT_APP_ID and FRY_ASA_ID must be set")

    vote_id = make_vote_id(vote_name)
    user_bytes = encoding.decode_address(user.address)

    print(f"Casting vote on '{vote_name}'")
    print(f"Option: {option}, Amount: {amount} microFRY")

    contract = get_abi_contract()
    method = contract.get_method_by_name("cast_vote")

    atc = AtomicTransactionComposer()
    sp = client.suggested_params()
    signer = AccountTransactionSigner(user.private_key)

    # MBR payment
    pay_txn = transaction.PaymentTxn(
        sender=user.address,
        sp=sp,
        receiver=app_address,
        amt=STAKE_BOX_MBR,
    )

    # Asset transfer
    asset_txn = transaction.AssetTransferTxn(
        sender=user.address,
        sp=sp,
        receiver=app_address,
        amt=amount,
        index=fry_asa_id,
    )

    atc.add_method_call(
        app_id=app_id,
        method=method,
        sender=user.address,
        sp=sp,
        signer=signer,
        method_args=[
            list(vote_id),  # vote_id
            option,  # option_index
            TransactionWithSigner(pay_txn, signer),  # pay txn
            TransactionWithSigner(asset_txn, signer),  # axfer txn
        ],
        foreign_assets=[fry_asa_id],
        boxes=[
            (app_id, VOTE_BOX_PREFIX + vote_id),
            (app_id, make_stake_box_key(vote_id, user_bytes)),
        ],
    )

    result = atc.execute(client, 4)

    print(f"\nVote cast successfully!")
    print(f"Transaction ID: {result.tx_ids[-1]}")


def cmd_cast_temp_vote(vote_name: str, option: int) -> None:
    """Cast a temperature check vote (no staking)."""
    client = get_client()
    user = get_test_user()
    if not user:
        raise ValueError(f"TEST_USER_MNEMONIC not set in {ENV_FILE}")

    app_id = get_contract_app_id()
    fry_asa_id = get_fry_asa_id()
    app_address = get_app_address()

    if not app_id or not fry_asa_id:
        raise ValueError("CONTRACT_APP_ID and FRY_ASA_ID must be set")

    vote_id = make_vote_id(vote_name)
    user_bytes = encoding.decode_address(user.address)

    print(f"Casting temp vote on '{vote_name}'")
    print(f"Option: {option}")

    contract = get_abi_contract()
    method = contract.get_method_by_name("cast_temp_vote")

    atc = AtomicTransactionComposer()
    sp = client.suggested_params()
    signer = AccountTransactionSigner(user.private_key)

    # MBR payment
    pay_txn = transaction.PaymentTxn(
        sender=user.address,
        sp=sp,
        receiver=app_address,
        amt=STAKE_BOX_MBR,
    )

    atc.add_method_call(
        app_id=app_id,
        method=method,
        sender=user.address,
        sp=sp,
        signer=signer,
        method_args=[
            list(vote_id),  # vote_id
            option,  # option_index
            TransactionWithSigner(pay_txn, signer),  # pay txn
        ],
        foreign_assets=[fry_asa_id],
        boxes=[
            (app_id, VOTE_BOX_PREFIX + vote_id),
            (app_id, make_stake_box_key(vote_id, user_bytes)),
        ],
    )

    result = atc.execute(client, 4)

    print(f"\nTemp vote cast successfully!")
    print(f"Transaction ID: {result.tx_ids[-1]}")


def cmd_withdraw(vote_name: str) -> None:
    """Withdraw staked FRY after lock period."""
    client = get_client()
    user = get_test_user()
    if not user:
        raise ValueError(f"TEST_USER_MNEMONIC not set in {ENV_FILE}")

    app_id = get_contract_app_id()
    fry_asa_id = get_fry_asa_id()

    if not app_id or not fry_asa_id:
        raise ValueError("CONTRACT_APP_ID and FRY_ASA_ID must be set")

    vote_id = make_vote_id(vote_name)
    user_bytes = encoding.decode_address(user.address)

    print(f"Withdrawing stake from '{vote_name}'")

    contract = get_abi_contract()
    method = contract.get_method_by_name("withdraw")

    atc = AtomicTransactionComposer()
    sp = client.suggested_params()
    # Add extra fee for inner asset transfer
    sp.fee = sp.min_fee + 1000
    sp.flat_fee = True
    signer = AccountTransactionSigner(user.private_key)

    atc.add_method_call(
        app_id=app_id,
        method=method,
        sender=user.address,
        sp=sp,
        signer=signer,
        method_args=[list(vote_id)],
        foreign_assets=[fry_asa_id],
        boxes=[
            (app_id, VOTE_BOX_PREFIX + vote_id),
            (app_id, make_stake_box_key(vote_id, user_bytes)),
        ],
    )

    result = atc.execute(client, 4)

    print(f"\nWithdrawal successful!")
    print(f"Transaction ID: {result.tx_ids[-1]}")


def cmd_close_vote(vote_name: str) -> None:
    """Admin close a vote."""
    app_id = get_contract_app_id()

    if not app_id:
        raise ValueError("CONTRACT_APP_ID not set")

    vote_id = make_vote_id(vote_name)

    print(f"Closing vote '{vote_name}'")

    result = call_method(
        "admin_close_vote",
        args=[list(vote_id)],
        boxes=[VOTE_BOX_PREFIX + vote_id],
    )

    print(f"\nVote closed successfully!")
    print(f"Transaction ID: {result['tx_id']}")


def cmd_emergency_refund(vote_name: str, voter_address: str) -> None:
    """Admin emergency refund."""
    client = get_client()
    deployer = get_deployer()
    app_id = get_contract_app_id()
    fry_asa_id = get_fry_asa_id()

    if not app_id or not fry_asa_id:
        raise ValueError("CONTRACT_APP_ID and FRY_ASA_ID must be set")

    vote_id = make_vote_id(vote_name)
    voter_bytes = encoding.decode_address(voter_address)

    print(f"Emergency refund for '{vote_name}', voter: {voter_address}")

    contract = get_abi_contract()
    method = contract.get_method_by_name("admin_emergency_refund")

    atc = AtomicTransactionComposer()
    sp = client.suggested_params()
    # Add extra fee for inner asset transfer
    sp.fee = sp.min_fee + 1000
    sp.flat_fee = True
    signer = AccountTransactionSigner(deployer.private_key)

    atc.add_method_call(
        app_id=app_id,
        method=method,
        sender=deployer.address,
        sp=sp,
        signer=signer,
        method_args=[list(vote_id), list(voter_bytes)],
        foreign_assets=[fry_asa_id],
        accounts=[voter_address],
        boxes=[
            (app_id, make_stake_box_key(vote_id, voter_bytes)),
        ],
    )

    result = atc.execute(client, 4)

    print(f"\nEmergency refund successful!")
    print(f"Transaction ID: {result.tx_ids[-1]}")


def cmd_admin_update() -> None:
    """Update contract program (creator only)."""
    client = get_client()
    deployer = get_deployer()
    app_id = get_contract_app_id()

    if not app_id:
        raise ValueError("CONTRACT_APP_ID not set")

    print(f"Calling admin_update on contract {app_id}")
    print(f"Creator/Sender: {deployer.address}")

    # Load compiled TEAL programs
    approval_path = PROJECT_ROOT / "smart_contracts" / "fry_governance" / "artifacts" / "FryGovernance.approval.teal"
    clear_path = PROJECT_ROOT / "smart_contracts" / "fry_governance" / "artifacts" / "FryGovernance.clear.teal"

    with open(approval_path) as f:
        approval_teal = f.read()
    with open(clear_path) as f:
        clear_teal = f.read()

    # Compile the TEAL
    approval_result = client.compile(approval_teal)
    approval_program = base64.b64decode(approval_result["result"])
    clear_result = client.compile(clear_teal)
    clear_program = base64.b64decode(clear_result["result"])

    sp = client.suggested_params()

    # admin_update is a bare method with UpdateApplication on_complete
    app_txn = transaction.ApplicationCallTxn(
        sender=deployer.address,
        sp=sp,
        index=app_id,
        on_complete=transaction.OnComplete.UpdateApplicationOC,
        approval_program=approval_program,
        clear_program=clear_program,
    )

    signed_app = app_txn.sign(deployer.private_key)
    txid = client.send_transaction(signed_app)
    result = transaction.wait_for_confirmation(client, txid, 4)

    print(f"\nAdmin update successful!")
    print(f"Transaction ID: {txid}")


def cmd_get_vote(vote_name: str) -> None:
    """Query vote state."""
    app_id = get_contract_app_id()
    vote_id = make_vote_id(vote_name)

    print(f"Querying vote '{vote_name}'")
    print(f"Vote ID (hex): {vote_id.hex()}")

    result = call_method(
        "get_vote",
        args=[list(vote_id)],
        boxes=[VOTE_BOX_PREFIX + vote_id],
    )

    print(f"\nVote Record:")
    print(f"  Raw return: {result['return_value']}")


def cmd_get_stake(vote_name: str, voter_address: str | None = None) -> None:
    """Query stake state."""
    app_id = get_contract_app_id()
    vote_id = make_vote_id(vote_name)

    # Use test user if no voter specified
    if voter_address is None:
        user = get_test_user()
        if not user:
            raise ValueError("No voter address and TEST_USER_MNEMONIC not set")
        voter_address = user.address

    print(f"Querying stake for '{vote_name}', voter: {voter_address}")

    voter_bytes = encoding.decode_address(voter_address)

    result = call_method(
        "get_stake",
        args=[list(vote_id), list(voter_bytes)],
        boxes=[make_stake_box_key(vote_id, voter_bytes)],
    )

    print(f"\nStake Record:")
    print(f"  Raw return: {result['return_value']}")


def cmd_verify_all() -> None:
    """Run full verification suite."""
    print("=" * 60)
    print("FryGovernance Verification Suite")
    print("=" * 60)

    results = []

    def run_test(name: str, fn, *args, expect_fail: bool = False):
        print(f"\n--- {name} ---")
        try:
            fn(*args)
            if expect_fail:
                results.append((name, "FAIL", "Expected failure but succeeded"))
            else:
                results.append((name, "PASS", ""))
        except Exception as e:
            if expect_fail:
                results.append((name, "PASS", f"Expected failure: {e}"))
            else:
                results.append((name, "FAIL", str(e)))

    # Test 1: Create FIP vote
    run_test("Create FIP vote", cmd_create_vote, "test-fip-vote", VOTE_TYPE_FIP)

    # Test 2: Cast FIP vote
    run_test("Cast FIP vote", cmd_cast_vote, "test-fip-vote", 0, 1_000_000)

    # Test 3: Duplicate FIP vote (should fail)
    run_test("Duplicate FIP vote (should fail)", cmd_cast_vote, "test-fip-vote", 0, 1_000_000, expect_fail=True)

    # Test 4: Create temp check vote
    run_test("Create temp check vote", cmd_create_vote, "test-temp-vote", VOTE_TYPE_TEMP_CHECK)

    # Test 5: Cast temp vote
    run_test("Cast temp vote", cmd_cast_temp_vote, "test-temp-vote", 1)

    # Test 6: Duplicate temp vote (should fail)
    run_test("Duplicate temp vote (should fail)", cmd_cast_temp_vote, "test-temp-vote", 1, expect_fail=True)

    # Test 7: Get vote state
    run_test("Get FIP vote state", cmd_get_vote, "test-fip-vote")

    # Test 8: Get stake state
    run_test("Get stake state", cmd_get_stake, "test-fip-vote")

    # Test 9: Admin close vote
    run_test("Admin close vote", cmd_close_vote, "test-fip-vote")

    # Summary
    print("\n" + "=" * 60)
    print("VERIFICATION SUMMARY")
    print("=" * 60)
    for name, status, msg in results:
        status_str = f"[{status}]"
        print(f"{status_str:8} {name}")
        if msg:
            print(f"         {msg}")

    passed = sum(1 for _, s, _ in results if s == "PASS")
    total = len(results)
    print(f"\n{passed}/{total} tests passed")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1]

    try:
        if command == "create-fry-asa":
            cmd_create_fry_asa()
        elif command == "opt-in-fry":
            cmd_opt_in_fry()
        elif command == "set-min-balance":
            if len(sys.argv) < 3:
                print("Usage: post_deploy.py set-min-balance <amount>")
                sys.exit(1)
            cmd_set_min_balance(int(sys.argv[2]))
        elif command == "set-price":
            if len(sys.argv) < 4:
                print("Usage: post_deploy.py set-price <value> <is_usd>")
                sys.exit(1)
            cmd_set_price(int(sys.argv[2]), int(sys.argv[3]))
        elif command == "fund-contract":
            if len(sys.argv) < 3:
                print("Usage: post_deploy.py fund-contract <amount>")
                sys.exit(1)
            cmd_fund_contract(int(sys.argv[2]))
        elif command == "create-user":
            cmd_create_user()
        elif command == "create-vote":
            if len(sys.argv) < 3:
                print("Usage: post_deploy.py create-vote <name> [type] [lock_seconds]")
                print("  type: 0=FIP (default), 2=TempCheck")
                print("  lock_seconds: custom lock duration (default: 6 months for FIP, 0 for temp)")
                sys.exit(1)
            vote_type = int(sys.argv[3]) if len(sys.argv) > 3 else VOTE_TYPE_FIP
            lock_seconds = int(sys.argv[4]) if len(sys.argv) > 4 else None
            cmd_create_vote(sys.argv[2], vote_type, lock_seconds)
        elif command == "cast-vote":
            if len(sys.argv) < 5:
                print("Usage: post_deploy.py cast-vote <name> <option> <amount>")
                sys.exit(1)
            cmd_cast_vote(sys.argv[2], int(sys.argv[3]), int(sys.argv[4]))
        elif command == "cast-temp-vote":
            if len(sys.argv) < 4:
                print("Usage: post_deploy.py cast-temp-vote <name> <option>")
                sys.exit(1)
            cmd_cast_temp_vote(sys.argv[2], int(sys.argv[3]))
        elif command == "withdraw":
            if len(sys.argv) < 3:
                print("Usage: post_deploy.py withdraw <vote_name>")
                sys.exit(1)
            cmd_withdraw(sys.argv[2])
        elif command == "close-vote":
            if len(sys.argv) < 3:
                print("Usage: post_deploy.py close-vote <vote_name>")
                sys.exit(1)
            cmd_close_vote(sys.argv[2])
        elif command == "emergency-refund":
            if len(sys.argv) < 4:
                print("Usage: post_deploy.py emergency-refund <vote_name> <voter_address>")
                sys.exit(1)
            cmd_emergency_refund(sys.argv[2], sys.argv[3])
        elif command == "admin-update":
            cmd_admin_update()
        elif command == "get-vote":
            if len(sys.argv) < 3:
                print("Usage: post_deploy.py get-vote <vote_name>")
                sys.exit(1)
            cmd_get_vote(sys.argv[2])
        elif command == "get-stake":
            if len(sys.argv) < 3:
                print("Usage: post_deploy.py get-stake <vote_name> [voter_address]")
                sys.exit(1)
            voter = sys.argv[3] if len(sys.argv) > 3 else None
            cmd_get_stake(sys.argv[2], voter)
        elif command == "verify-all":
            cmd_verify_all()
        else:
            print(f"Unknown command: {command}")
            print(__doc__)
            sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
