# Pytest fixtures for FryGovernance tests

from typing import Literal

import pytest
from algopy import Account, Application, Asset, OnCompleteAction, arc4
from algopy_testing import AlgopyTestContext, algopy_testing_context

from smart_contracts.fry_governance.constants import (
    ADMIN_ADDRESS,
    FRY_ASA_ID,
    STAKE_BOX_MBR,
    VOTE_BOX_MBR,
    VOTE_TYPE_FIP,
)
from smart_contracts.fry_governance.contract import FryGovernance


@pytest.fixture
def context() -> AlgopyTestContext:
    """Create a fresh Algopy testing context for each test."""
    with algopy_testing_context() as ctx:
        yield ctx


@pytest.fixture
def admin_account(context: AlgopyTestContext) -> Account:
    """Create admin account matching ADMIN_ADDRESS."""
    return context.any.account(address=ADMIN_ADDRESS)


@pytest.fixture
def user_account(context: AlgopyTestContext) -> Account:
    """Create a regular user account."""
    return context.any.account()


@pytest.fixture
def user_account_2(context: AlgopyTestContext) -> Account:
    """Create a second regular user account."""
    return context.any.account()


@pytest.fixture
def fry_asset(context: AlgopyTestContext) -> Asset:
    """Create FRY asset matching FRY_ASA_ID."""
    return context.any.asset(asset_id=FRY_ASA_ID)


@pytest.fixture
def contract(context: AlgopyTestContext, admin_account: Account) -> FryGovernance:
    """Deploy and initialize the FryGovernance contract."""
    contract = FryGovernance()

    # Set timestamp for testing
    context.ledger.patch_global_fields(latest_timestamp=1_700_000_000)

    # Get the contract's app
    app = context.ledger.get_app(contract.__app_id__)

    # Create an app call transaction for contract creation
    app_call = context.any.txn.application_call(
        sender=admin_account,
        app_id=app,
        on_completion=OnCompleteAction.NoOp,
    )

    # Execute creation in a transaction context
    with context.txn.create_group([app_call], active_txn_index=0):
        contract.create(arc4.UInt64(FRY_ASA_ID))

    return contract


@pytest.fixture
def app(context: AlgopyTestContext, contract: FryGovernance) -> Application:
    """Get the application associated with the contract."""
    return context.ledger.get_app(contract.__app_id__)


@pytest.fixture
def vote_id_bytes() -> bytes:
    """Generate a sample 32-byte vote ID."""
    return b"test_vote_id_0000000000000000001"  # Exactly 32 bytes


@pytest.fixture
def vote_id_bytes_2() -> bytes:
    """Generate a second sample 32-byte vote ID."""
    return b"test_vote_id_0000000000000000002"  # Exactly 32 bytes


def make_vote_id(vote_id_bytes: bytes) -> arc4.StaticArray[arc4.Byte, Literal[32]]:
    """Helper to create a vote ID arc4 type."""
    return arc4.StaticArray[arc4.Byte, Literal[32]].from_bytes(vote_id_bytes)


def create_vote_helper(
    context: AlgopyTestContext,
    contract: FryGovernance,
    admin_account: Account,
    app: Application,
    vote_id_bytes: bytes,
    end_date: int = 1_700_000_000 + 86400 * 30,
    lock_duration: int = 15_768_000,
    options_count: int = 3,
    vote_type: int = VOTE_TYPE_FIP,
) -> None:
    """Helper to create a vote in tests."""
    vote_id = make_vote_id(vote_id_bytes)

    # Create payment for MBR
    mbr_payment = context.any.txn.payment(
        sender=admin_account,
        receiver=app.address,
        amount=VOTE_BOX_MBR,
    )

    # Create app call
    app_call = context.any.txn.application_call(
        sender=admin_account,
        app_id=app,
    )

    # Execute in atomic group [Payment, AppCall]
    with context.txn.create_group([mbr_payment, app_call], active_txn_index=1):
        contract.create_vote(
            vote_id,  # positional
            arc4.UInt8(options_count),  # positional
            arc4.UInt64(end_date),  # positional
            arc4.UInt64(lock_duration),  # positional
            arc4.UInt8(0),  # positional - super_majority
            arc4.UInt8(vote_type),  # positional
            mbr_payment,  # positional - gtxn reference
        )


# Helper constants for tests
TEST_END_DATE = 1_700_000_000 + 86400 * 30  # 30 days from a base timestamp
TEST_LOCK_DURATION = 15_768_000  # 6 months
TEST_OPTIONS_COUNT = 3
