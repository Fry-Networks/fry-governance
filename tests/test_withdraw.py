# Tests for withdraw method

from typing import Literal

import pytest
from algopy import arc4
from algopy_testing import AlgopyTestContext

from smart_contracts.fry_governance.constants import (
    FRY_ASA_ID,
    STAKE_BOX_MBR,
    VOTE_BOX_MBR,
    VOTE_TYPE_FIP,
)
from smart_contracts.fry_governance.contract import FryGovernance
from tests.conftest import make_vote_id


class TestWithdraw:
    """Test cases for the withdraw method."""

    def _create_vote_and_cast(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account,
        user_account,
        app,
        vote_id_bytes: bytes,
        stake_amount: int = 1_000_000,
        lock_duration: int = 15_768_000,
    ):
        """Helper to create a vote and cast a vote."""
        # Create vote
        context.ledger.patch_global_fields(latest_timestamp=1_700_000_000)
        vote_id = make_vote_id(vote_id_bytes)
        end_date = 1_700_000_000 + 86400 * 30

        mbr_payment_vote = context.any.txn.payment(
            sender=admin_account,
            receiver=app.address,
            amount=VOTE_BOX_MBR,
        )

        app_call_vote = context.any.txn.application_call(
            sender=admin_account,
            app_id=app,
        )

        with context.txn.create_group([mbr_payment_vote, app_call_vote], active_txn_index=1):
            contract.create_vote(
                vote_id,
                arc4.UInt8(3),
                arc4.UInt64(end_date),
                arc4.UInt64(lock_duration),
                arc4.UInt8(0),
                arc4.UInt8(VOTE_TYPE_FIP),
                mbr_payment_vote,
            )

        # Cast vote
        context.ledger.patch_global_fields(latest_timestamp=1_700_000_000 + 1000)

        mbr_payment_stake = context.any.txn.payment(
            sender=user_account,
            receiver=app.address,
            amount=STAKE_BOX_MBR,
        )

        fry_asset = context.any.asset(asset_id=FRY_ASA_ID)
        asset_transfer = context.any.txn.asset_transfer(
            sender=user_account,
            asset_receiver=app.address,
            xfer_asset=fry_asset,
            asset_amount=stake_amount,
        )

        app_call_cast = context.any.txn.application_call(
            sender=user_account,
            app_id=app,
        )

        with context.txn.create_group(
            [mbr_payment_stake, asset_transfer, app_call_cast], active_txn_index=2
        ):
            contract.cast_vote(
                vote_id,
                arc4.UInt8(1),
                mbr_payment_stake,
                asset_transfer,
            )

        return vote_id

    def test_withdraw_success(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account,
        user_account,
        app,
        vote_id_bytes: bytes,
    ):
        """Test successful withdrawal after lock period."""
        # Use short lock duration for testing (1 hour)
        lock_duration = 3600
        vote_id = self._create_vote_and_cast(
            context,
            contract,
            admin_account,
            user_account,
            app,
            vote_id_bytes,
            lock_duration=lock_duration,
        )

        # Fast forward past lock period
        # Vote cast at 1_700_000_000 + 1000, lock duration is 3600
        # So unlock time is 1_700_001_000 + 3600 = 1_700_004_600
        context.ledger.patch_global_fields(latest_timestamp=1_700_004_601)

        app_call = context.any.txn.application_call(
            sender=user_account,
            app_id=app,
        )

        with context.txn.create_group([app_call], active_txn_index=0):
            contract.withdraw(vote_id)

        # Verify stake box is deleted (no longer exists)
        voter_bytes = arc4.StaticArray[arc4.Byte, Literal[32]].from_bytes(
            user_account.bytes
        )
        with pytest.raises(AssertionError, match="Stake not found"):
            contract.get_stake(vote_id, voter_bytes)

    def test_withdraw_before_unlock_fails(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account,
        user_account,
        app,
        vote_id_bytes: bytes,
    ):
        """Test withdrawal before lock period ends fails."""
        lock_duration = 3600
        vote_id = self._create_vote_and_cast(
            context,
            contract,
            admin_account,
            user_account,
            app,
            vote_id_bytes,
            lock_duration=lock_duration,
        )

        # Try to withdraw before lock expires
        context.ledger.patch_global_fields(latest_timestamp=1_700_002_000)

        app_call = context.any.txn.application_call(
            sender=user_account,
            app_id=app,
        )

        with pytest.raises(AssertionError, match="Lock period not expired"):
            with context.txn.create_group([app_call], active_txn_index=0):
                contract.withdraw(vote_id)

    def test_withdraw_nonexistent_stake_fails(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        user_account,
        app,
        vote_id_bytes: bytes,
    ):
        """Test withdrawal of non-existent stake fails."""
        context.ledger.patch_global_fields(latest_timestamp=1_800_000_000)

        vote_id = make_vote_id(vote_id_bytes)

        app_call = context.any.txn.application_call(
            sender=user_account,
            app_id=app,
        )

        with pytest.raises(AssertionError, match="Stake not found"):
            with context.txn.create_group([app_call], active_txn_index=0):
                contract.withdraw(vote_id)

    def test_withdraw_wrong_user_fails(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account,
        user_account,
        user_account_2,
        app,
        vote_id_bytes: bytes,
    ):
        """Test that another user cannot withdraw someone else's stake."""
        lock_duration = 3600
        vote_id = self._create_vote_and_cast(
            context,
            contract,
            admin_account,
            user_account,
            app,
            vote_id_bytes,
            lock_duration=lock_duration,
        )

        # Try to withdraw as different user
        context.ledger.patch_global_fields(latest_timestamp=1_700_004_601)

        app_call = context.any.txn.application_call(
            sender=user_account_2,
            app_id=app,
        )

        # The stake box key includes the sender's address, so user_account_2 cannot
        # find user_account's stake box - it looks for s_ + vote_id + user_account_2.bytes
        # which doesn't exist. This is correct contract behavior.
        with pytest.raises(AssertionError, match="Stake not found"):
            with context.txn.create_group([app_call], active_txn_index=0):
                contract.withdraw(vote_id)

    def test_withdraw_double_withdraw_fails(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account,
        user_account,
        app,
        vote_id_bytes: bytes,
    ):
        """Test double withdrawal fails."""
        lock_duration = 3600
        vote_id = self._create_vote_and_cast(
            context,
            contract,
            admin_account,
            user_account,
            app,
            vote_id_bytes,
            lock_duration=lock_duration,
        )

        # First withdrawal
        context.ledger.patch_global_fields(latest_timestamp=1_700_004_601)

        app_call = context.any.txn.application_call(
            sender=user_account,
            app_id=app,
        )

        with context.txn.create_group([app_call], active_txn_index=0):
            contract.withdraw(vote_id)

        # Second withdrawal should fail
        app_call_2 = context.any.txn.application_call(
            sender=user_account,
            app_id=app,
        )

        with pytest.raises(AssertionError, match="Stake not found"):
            with context.txn.create_group([app_call_2], active_txn_index=0):
                contract.withdraw(vote_id)

    def test_withdraw_six_month_lock(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account,
        user_account,
        app,
        vote_id_bytes: bytes,
    ):
        """Test withdrawal with full 6-month lock period."""
        # Default lock duration: 6 months = 15,768,000 seconds
        lock_duration = 15_768_000
        vote_id = self._create_vote_and_cast(
            context,
            contract,
            admin_account,
            user_account,
            app,
            vote_id_bytes,
            lock_duration=lock_duration,
        )

        # Try just before unlock
        # Vote cast at 1_700_001_000, unlock at 1_700_001_000 + 15_768_000 = 1_715_769_000
        context.ledger.patch_global_fields(latest_timestamp=1_715_768_999)

        app_call = context.any.txn.application_call(
            sender=user_account,
            app_id=app,
        )

        with pytest.raises(AssertionError, match="Lock period not expired"):
            with context.txn.create_group([app_call], active_txn_index=0):
                contract.withdraw(vote_id)

        # Now at exactly unlock time
        context.ledger.patch_global_fields(latest_timestamp=1_715_769_000)

        app_call_2 = context.any.txn.application_call(
            sender=user_account,
            app_id=app,
        )

        with context.txn.create_group([app_call_2], active_txn_index=0):
            contract.withdraw(vote_id)
