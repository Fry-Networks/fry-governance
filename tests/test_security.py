# Security tests for FryGovernance

from typing import Literal

import pytest
from algopy import arc4
from algopy_testing import AlgopyTestContext

from smart_contracts.fry_governance.constants import (
    FRY_ASA_ID,
    STAKE_BOX_MBR,
    VOTE_BOX_MBR,
    VOTE_TYPE_TEMP_CHECK,
)
from smart_contracts.fry_governance.contract import FryGovernance
from tests.conftest import make_vote_id


class TestMinBalanceProtection:
    """Test that min balance setting is protected."""

    def test_cannot_set_min_balance_as_non_admin(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        user_account,
        app,
    ):
        """Test that non-admin cannot set min balance."""
        user_app_call = context.any.txn.application_call(
            sender=user_account,
            app_id=app,
        )

        with context.txn.create_group([user_app_call], active_txn_index=0):
            with pytest.raises(AssertionError, match="Only admin can set min balance"):
                contract.admin_set_min_balance(arc4.UInt64(1_000_000))


class TestAdminPrivileges:
    """Test that admin functions are properly protected."""

    def test_all_admin_functions_require_admin(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        user_account,
        app,
        vote_id_bytes: bytes,
    ):
        """Test that all admin functions reject non-admin callers."""
        vote_id = make_vote_id(vote_id_bytes)

        # admin_set_min_balance
        user_app_call = context.any.txn.application_call(
            sender=user_account,
            app_id=app,
        )
        with context.txn.create_group([user_app_call], active_txn_index=0):
            with pytest.raises(AssertionError, match="Only admin"):
                contract.admin_set_min_balance(arc4.UInt64(1_000_000))

        # admin_set_price
        user_app_call = context.any.txn.application_call(
            sender=user_account,
            app_id=app,
        )
        with context.txn.create_group([user_app_call], active_txn_index=0):
            with pytest.raises(AssertionError, match="Only admin"):
                contract.admin_set_price(arc4.UInt64(100), arc4.UInt8(1))

        # opt_in_fry
        user_app_call = context.any.txn.application_call(
            sender=user_account,
            app_id=app,
        )
        with context.txn.create_group([user_app_call], active_txn_index=0):
            with pytest.raises(AssertionError, match="Only admin"):
                contract.opt_in_fry()

        # create_vote
        mbr_payment = context.any.txn.payment(
            sender=user_account,
            receiver=app.address,
            amount=VOTE_BOX_MBR,
        )
        user_app_call = context.any.txn.application_call(
            sender=user_account,
            app_id=app,
        )
        with context.txn.create_group([mbr_payment, user_app_call], active_txn_index=1):
            with pytest.raises(AssertionError, match="Only admin"):
                contract.create_vote(
                    vote_id,
                    arc4.UInt8(2),
                    arc4.UInt64(1_800_000_000),
                    arc4.UInt64(3600),
                    arc4.UInt8(0),
                    arc4.UInt8(0),
                    mbr_payment,
                )


class TestDoubleVoting:
    """Test prevention of double voting attacks."""

    def test_cannot_vote_twice_same_proposal(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account,
        user_account,
        app,
        vote_id_bytes: bytes,
    ):
        """Test user cannot vote twice on same proposal."""
        vote_id = make_vote_id(vote_id_bytes)

        # Create vote
        mbr_payment_vote = context.any.txn.payment(
            sender=admin_account,
            receiver=app.address,
            amount=VOTE_BOX_MBR,
        )

        admin_app_call = context.any.txn.application_call(
            sender=admin_account,
            app_id=app,
        )

        with context.txn.create_group([mbr_payment_vote, admin_app_call], active_txn_index=1):
            contract.create_vote(
                vote_id,
                arc4.UInt8(2),
                arc4.UInt64(1_700_000_000 + 86400),
                arc4.UInt64(3600),
                arc4.UInt8(0),
                arc4.UInt8(0),
                mbr_payment_vote,
            )

        # First vote
        context.ledger.patch_global_fields(latest_timestamp=1_700_000_000 + 1000)

        fry_asset = context.any.asset(asset_id=FRY_ASA_ID)

        mbr_payment = context.any.txn.payment(
            sender=user_account,
            receiver=app.address,
            amount=STAKE_BOX_MBR,
        )
        asset_transfer = context.any.txn.asset_transfer(
            sender=user_account,
            asset_receiver=app.address,
            xfer_asset=fry_asset,
            asset_amount=1_000_000,
        )

        user_app_call = context.any.txn.application_call(
            sender=user_account,
            app_id=app,
        )

        with context.txn.create_group([mbr_payment, asset_transfer, user_app_call], active_txn_index=2):
            contract.cast_vote(
                vote_id,
                arc4.UInt8(0),
                mbr_payment,
                asset_transfer,
            )

        # Second vote attempt
        mbr_payment2 = context.any.txn.payment(
            sender=user_account,
            receiver=app.address,
            amount=STAKE_BOX_MBR,
        )
        asset_transfer2 = context.any.txn.asset_transfer(
            sender=user_account,
            asset_receiver=app.address,
            xfer_asset=fry_asset,
            asset_amount=1_000_000,
        )
        user_app_call2 = context.any.txn.application_call(
            sender=user_account,
            app_id=app,
        )

        with context.txn.create_group([mbr_payment2, asset_transfer2, user_app_call2], active_txn_index=2):
            with pytest.raises(AssertionError, match="Already voted"):
                contract.cast_vote(
                    vote_id,
                    arc4.UInt8(1),
                    mbr_payment2,
                    asset_transfer2,
                )


class TestWithdrawalSecurity:
    """Test withdrawal security measures."""

    def test_cannot_withdraw_others_stake(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account,
        user_account,
        user_account_2,
        app,
        vote_id_bytes: bytes,
    ):
        """Test that user cannot withdraw another user's stake."""
        vote_id = make_vote_id(vote_id_bytes)

        # Create vote
        mbr_payment_vote = context.any.txn.payment(
            sender=admin_account,
            receiver=app.address,
            amount=VOTE_BOX_MBR,
        )

        admin_app_call = context.any.txn.application_call(
            sender=admin_account,
            app_id=app,
        )

        with context.txn.create_group([mbr_payment_vote, admin_app_call], active_txn_index=1):
            contract.create_vote(
                vote_id,
                arc4.UInt8(2),
                arc4.UInt64(1_700_000_000 + 86400),
                arc4.UInt64(3600),
                arc4.UInt8(0),
                arc4.UInt8(0),
                mbr_payment_vote,
            )

        # User 1 stakes
        context.ledger.patch_global_fields(latest_timestamp=1_700_000_000 + 1000)

        fry_asset = context.any.asset(asset_id=FRY_ASA_ID)

        mbr_payment = context.any.txn.payment(
            sender=user_account,
            receiver=app.address,
            amount=STAKE_BOX_MBR,
        )
        asset_transfer = context.any.txn.asset_transfer(
            sender=user_account,
            asset_receiver=app.address,
            xfer_asset=fry_asset,
            asset_amount=1_000_000,
        )

        user_app_call = context.any.txn.application_call(
            sender=user_account,
            app_id=app,
        )

        with context.txn.create_group([mbr_payment, asset_transfer, user_app_call], active_txn_index=2):
            contract.cast_vote(
                vote_id,
                arc4.UInt8(0),
                mbr_payment,
                asset_transfer,
            )

        # User 2 tries to withdraw User 1's stake after lock period
        context.ledger.patch_global_fields(latest_timestamp=1_700_000_000 + 1000 + 3601)

        user2_app_call = context.any.txn.application_call(
            sender=user_account_2,
            app_id=app,
        )

        # User 2's stake box key uses user_account_2's address, not user_account's
        # So the contract correctly reports "Stake not found" because user_account_2
        # never staked on this vote
        with context.txn.create_group([user2_app_call], active_txn_index=0):
            with pytest.raises(AssertionError, match="Stake not found"):
                contract.withdraw(vote_id)

    def test_cannot_withdraw_before_lock_expires(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account,
        user_account,
        app,
        vote_id_bytes: bytes,
    ):
        """Test that withdrawal before lock period fails."""
        vote_id = make_vote_id(vote_id_bytes)

        # Create vote
        mbr_payment_vote = context.any.txn.payment(
            sender=admin_account,
            receiver=app.address,
            amount=VOTE_BOX_MBR,
        )

        admin_app_call = context.any.txn.application_call(
            sender=admin_account,
            app_id=app,
        )

        # 6 month lock
        lock_duration = 15_768_000

        with context.txn.create_group([mbr_payment_vote, admin_app_call], active_txn_index=1):
            contract.create_vote(
                vote_id,
                arc4.UInt8(2),
                arc4.UInt64(1_700_000_000 + 86400),
                arc4.UInt64(lock_duration),
                arc4.UInt8(0),
                arc4.UInt8(0),
                mbr_payment_vote,
            )

        # User stakes
        vote_timestamp = 1_700_000_000 + 1000
        context.ledger.patch_global_fields(latest_timestamp=vote_timestamp)

        fry_asset = context.any.asset(asset_id=FRY_ASA_ID)

        mbr_payment = context.any.txn.payment(
            sender=user_account,
            receiver=app.address,
            amount=STAKE_BOX_MBR,
        )
        asset_transfer = context.any.txn.asset_transfer(
            sender=user_account,
            asset_receiver=app.address,
            xfer_asset=fry_asset,
            asset_amount=1_000_000,
        )

        user_app_call = context.any.txn.application_call(
            sender=user_account,
            app_id=app,
        )

        with context.txn.create_group([mbr_payment, asset_transfer, user_app_call], active_txn_index=2):
            contract.cast_vote(
                vote_id,
                arc4.UInt8(0),
                mbr_payment,
                asset_transfer,
            )

        # Try to withdraw 1 second before lock expires
        context.ledger.patch_global_fields(latest_timestamp=vote_timestamp + lock_duration - 1)

        user_app_call2 = context.any.txn.application_call(
            sender=user_account,
            app_id=app,
        )

        with context.txn.create_group([user_app_call2], active_txn_index=0):
            with pytest.raises(AssertionError, match="Lock period not expired"):
                contract.withdraw(vote_id)
