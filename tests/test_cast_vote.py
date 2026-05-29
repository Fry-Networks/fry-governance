# Tests for cast_vote method

from typing import Literal

import pytest
from algopy import Account, Application, arc4
from algopy_testing import AlgopyTestContext

from smart_contracts.fry_governance.constants import (
    FRY_ASA_ID,
    STAKE_BOX_MBR,
    VOTE_TYPE_FIP,
    VOTE_TYPE_TEMP_CHECK,
)
from smart_contracts.fry_governance.contract import FryGovernance
from tests.conftest import create_vote_helper, make_vote_id


class TestCastVote:
    """Test cases for the cast_vote method."""

    def test_cast_vote_success(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account: Account,
        app: Application,
        user_account: Account,
        vote_id_bytes: bytes,
    ):
        """Test successful vote casting."""
        # Create vote first
        create_vote_helper(context, contract, admin_account, app, vote_id_bytes)

        # Cast vote
        context.ledger.patch_global_fields(latest_timestamp=1_700_000_000 + 1000)

        vote_id = make_vote_id(vote_id_bytes)
        option_index = arc4.UInt8(1)
        stake_amount = 1_000_000

        mbr_payment = context.any.txn.payment(
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

        app_call = context.any.txn.application_call(
            sender=user_account,
            app_id=app,
        )

        # Group: [payment, asset_transfer, app_call], active_txn_index=2
        with context.txn.create_group([mbr_payment, asset_transfer, app_call], active_txn_index=2):
            contract.cast_vote(
                vote_id,  # positional
                option_index,  # positional
                mbr_payment,  # positional - gtxn reference
                asset_transfer,  # positional - gtxn reference
            )

        # Verify vote was recorded
        vote_record = contract.get_vote(vote_id)
        assert vote_record.total_voters[1].native == 1
        assert vote_record.total_tokens[1].native == stake_amount

    def test_cast_vote_wrong_group_size_fails(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account: Account,
        app: Application,
        user_account: Account,
        vote_id_bytes: bytes,
    ):
        """Test that wrong group size fails."""
        create_vote_helper(context, contract, admin_account, app, vote_id_bytes)

        context.ledger.patch_global_fields(latest_timestamp=1_700_000_000 + 1000)

        vote_id = make_vote_id(vote_id_bytes)
        option_index = arc4.UInt8(1)

        mbr_payment = context.any.txn.payment(
            sender=user_account,
            receiver=app.address,
            amount=STAKE_BOX_MBR,
        )

        fry_asset = context.any.asset(asset_id=FRY_ASA_ID)
        asset_transfer = context.any.txn.asset_transfer(
            sender=user_account,
            asset_receiver=app.address,
            xfer_asset=fry_asset,
            asset_amount=1_000_000,
        )

        # Create an app call so active_txn_index points to an app call
        app_call = context.any.txn.application_call(
            sender=user_account,
            app_id=app,
        )

        # Group has only 2 transactions (mbr_payment + app_call), missing asset_transfer
        # Contract expects group size of 3, so this will fail
        with pytest.raises(AssertionError, match="Group size must be 3"):
            with context.txn.create_group([mbr_payment, app_call], active_txn_index=1):
                contract.cast_vote(
                    vote_id,
                    option_index,
                    mbr_payment,
                    asset_transfer,
                )

    def test_cast_vote_insufficient_mbr_fails(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account: Account,
        app: Application,
        user_account: Account,
        vote_id_bytes: bytes,
    ):
        """Test that insufficient MBR payment fails."""
        create_vote_helper(context, contract, admin_account, app, vote_id_bytes)

        context.ledger.patch_global_fields(latest_timestamp=1_700_000_000 + 1000)

        vote_id = make_vote_id(vote_id_bytes)
        option_index = arc4.UInt8(1)

        mbr_payment = context.any.txn.payment(
            sender=user_account,
            receiver=app.address,
            amount=1000,  # Insufficient
        )

        fry_asset = context.any.asset(asset_id=FRY_ASA_ID)
        asset_transfer = context.any.txn.asset_transfer(
            sender=user_account,
            asset_receiver=app.address,
            xfer_asset=fry_asset,
            asset_amount=1_000_000,
        )

        app_call = context.any.txn.application_call(
            sender=user_account,
            app_id=app,
        )

        with pytest.raises(AssertionError, match="Insufficient MBR payment"):
            with context.txn.create_group([mbr_payment, asset_transfer, app_call], active_txn_index=2):
                contract.cast_vote(
                    vote_id,
                    option_index,
                    mbr_payment,
                    asset_transfer,
                )

    def test_cast_vote_zero_tokens_fails(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account: Account,
        app: Application,
        user_account: Account,
        vote_id_bytes: bytes,
    ):
        """Test that zero token stake fails."""
        create_vote_helper(context, contract, admin_account, app, vote_id_bytes)

        context.ledger.patch_global_fields(latest_timestamp=1_700_000_000 + 1000)

        vote_id = make_vote_id(vote_id_bytes)
        option_index = arc4.UInt8(1)

        mbr_payment = context.any.txn.payment(
            sender=user_account,
            receiver=app.address,
            amount=STAKE_BOX_MBR,
        )

        fry_asset = context.any.asset(asset_id=FRY_ASA_ID)
        asset_transfer = context.any.txn.asset_transfer(
            sender=user_account,
            asset_receiver=app.address,
            xfer_asset=fry_asset,
            asset_amount=0,  # Zero tokens
        )

        app_call = context.any.txn.application_call(
            sender=user_account,
            app_id=app,
        )

        with pytest.raises(AssertionError, match="Must stake some tokens"):
            with context.txn.create_group([mbr_payment, asset_transfer, app_call], active_txn_index=2):
                contract.cast_vote(
                    vote_id,
                    option_index,
                    mbr_payment,
                    asset_transfer,
                )

    def test_cast_vote_nonexistent_vote_fails(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        app: Application,
        user_account: Account,
    ):
        """Test voting on non-existent vote fails."""
        context.ledger.patch_global_fields(latest_timestamp=1_700_000_000 + 1000)

        vote_id = make_vote_id(b"nonexistent_vote_id_00000000000")
        option_index = arc4.UInt8(1)

        mbr_payment = context.any.txn.payment(
            sender=user_account,
            receiver=app.address,
            amount=STAKE_BOX_MBR,
        )

        fry_asset = context.any.asset(asset_id=FRY_ASA_ID)
        asset_transfer = context.any.txn.asset_transfer(
            sender=user_account,
            asset_receiver=app.address,
            xfer_asset=fry_asset,
            asset_amount=1_000_000,
        )

        app_call = context.any.txn.application_call(
            sender=user_account,
            app_id=app,
        )

        with pytest.raises(AssertionError, match="Vote does not exist"):
            with context.txn.create_group([mbr_payment, asset_transfer, app_call], active_txn_index=2):
                contract.cast_vote(
                    vote_id,
                    option_index,
                    mbr_payment,
                    asset_transfer,
                )

    def test_cast_vote_expired_vote_fails(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account: Account,
        app: Application,
        user_account: Account,
        vote_id_bytes: bytes,
    ):
        """Test voting on expired vote fails."""
        create_vote_helper(context, contract, admin_account, app, vote_id_bytes)

        # Set time after vote end date
        context.ledger.patch_global_fields(latest_timestamp=1_700_000_000 + 86400 * 31)

        vote_id = make_vote_id(vote_id_bytes)
        option_index = arc4.UInt8(1)

        mbr_payment = context.any.txn.payment(
            sender=user_account,
            receiver=app.address,
            amount=STAKE_BOX_MBR,
        )

        fry_asset = context.any.asset(asset_id=FRY_ASA_ID)
        asset_transfer = context.any.txn.asset_transfer(
            sender=user_account,
            asset_receiver=app.address,
            xfer_asset=fry_asset,
            asset_amount=1_000_000,
        )

        app_call = context.any.txn.application_call(
            sender=user_account,
            app_id=app,
        )

        with pytest.raises(AssertionError, match="Vote has expired"):
            with context.txn.create_group([mbr_payment, asset_transfer, app_call], active_txn_index=2):
                contract.cast_vote(
                    vote_id,
                    option_index,
                    mbr_payment,
                    asset_transfer,
                )

    def test_cast_vote_invalid_option_fails(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account: Account,
        app: Application,
        user_account: Account,
        vote_id_bytes: bytes,
    ):
        """Test voting with invalid option index fails."""
        create_vote_helper(context, contract, admin_account, app, vote_id_bytes)

        context.ledger.patch_global_fields(latest_timestamp=1_700_000_000 + 1000)

        vote_id = make_vote_id(vote_id_bytes)
        option_index = arc4.UInt8(10)  # Invalid - vote only has 3 options

        mbr_payment = context.any.txn.payment(
            sender=user_account,
            receiver=app.address,
            amount=STAKE_BOX_MBR,
        )

        fry_asset = context.any.asset(asset_id=FRY_ASA_ID)
        asset_transfer = context.any.txn.asset_transfer(
            sender=user_account,
            asset_receiver=app.address,
            xfer_asset=fry_asset,
            asset_amount=1_000_000,
        )

        app_call = context.any.txn.application_call(
            sender=user_account,
            app_id=app,
        )

        with pytest.raises(AssertionError, match="Invalid option index"):
            with context.txn.create_group([mbr_payment, asset_transfer, app_call], active_txn_index=2):
                contract.cast_vote(
                    vote_id,
                    option_index,
                    mbr_payment,
                    asset_transfer,
                )

    def test_cast_vote_duplicate_vote_fails(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account: Account,
        app: Application,
        user_account: Account,
        vote_id_bytes: bytes,
    ):
        """Test that user can only vote once per proposal."""
        create_vote_helper(context, contract, admin_account, app, vote_id_bytes)

        context.ledger.patch_global_fields(latest_timestamp=1_700_000_000 + 1000)

        vote_id = make_vote_id(vote_id_bytes)
        option_index = arc4.UInt8(1)
        fry_asset = context.any.asset(asset_id=FRY_ASA_ID)

        # First vote succeeds
        mbr_payment_1 = context.any.txn.payment(
            sender=user_account,
            receiver=app.address,
            amount=STAKE_BOX_MBR,
        )

        asset_transfer_1 = context.any.txn.asset_transfer(
            sender=user_account,
            asset_receiver=app.address,
            xfer_asset=fry_asset,
            asset_amount=1_000_000,
        )

        app_call_1 = context.any.txn.application_call(
            sender=user_account,
            app_id=app,
        )

        with context.txn.create_group([mbr_payment_1, asset_transfer_1, app_call_1], active_txn_index=2):
            contract.cast_vote(
                vote_id,
                option_index,
                mbr_payment_1,
                asset_transfer_1,
            )

        # Second vote fails
        mbr_payment_2 = context.any.txn.payment(
            sender=user_account,
            receiver=app.address,
            amount=STAKE_BOX_MBR,
        )

        asset_transfer_2 = context.any.txn.asset_transfer(
            sender=user_account,
            asset_receiver=app.address,
            xfer_asset=fry_asset,
            asset_amount=1_000_000,
        )

        app_call_2 = context.any.txn.application_call(
            sender=user_account,
            app_id=app,
        )

        with pytest.raises(AssertionError, match="Already voted"):
            with context.txn.create_group([mbr_payment_2, asset_transfer_2, app_call_2], active_txn_index=2):
                contract.cast_vote(
                    vote_id,
                    option_index,
                    mbr_payment_2,
                    asset_transfer_2,
                )

    def test_cast_vote_on_temp_check_fails(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account: Account,
        app: Application,
        user_account: Account,
        vote_id_bytes: bytes,
    ):
        """Test that cast_vote fails on temp_check vote type."""
        create_vote_helper(
            context, contract, admin_account, app, vote_id_bytes,
            vote_type=VOTE_TYPE_TEMP_CHECK
        )

        context.ledger.patch_global_fields(latest_timestamp=1_700_000_000 + 1000)

        vote_id = make_vote_id(vote_id_bytes)
        option_index = arc4.UInt8(1)

        mbr_payment = context.any.txn.payment(
            sender=user_account,
            receiver=app.address,
            amount=STAKE_BOX_MBR,
        )

        fry_asset = context.any.asset(asset_id=FRY_ASA_ID)
        asset_transfer = context.any.txn.asset_transfer(
            sender=user_account,
            asset_receiver=app.address,
            xfer_asset=fry_asset,
            asset_amount=1_000_000,
        )

        app_call = context.any.txn.application_call(
            sender=user_account,
            app_id=app,
        )

        with pytest.raises(AssertionError, match="Cannot stake on temp check votes"):
            with context.txn.create_group([mbr_payment, asset_transfer, app_call], active_txn_index=2):
                contract.cast_vote(
                    vote_id,
                    option_index,
                    mbr_payment,
                    asset_transfer,
                )

    def test_cast_vote_multiple_users(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account: Account,
        app: Application,
        user_account: Account,
        user_account_2: Account,
        vote_id_bytes: bytes,
    ):
        """Test multiple users voting on same proposal."""
        create_vote_helper(context, contract, admin_account, app, vote_id_bytes)

        vote_id = make_vote_id(vote_id_bytes)
        fry_asset = context.any.asset(asset_id=FRY_ASA_ID)

        # User 1 votes for option 0
        context.ledger.patch_global_fields(latest_timestamp=1_700_000_000 + 1000)

        mbr_payment_1 = context.any.txn.payment(
            sender=user_account,
            receiver=app.address,
            amount=STAKE_BOX_MBR,
        )
        asset_transfer_1 = context.any.txn.asset_transfer(
            sender=user_account,
            asset_receiver=app.address,
            xfer_asset=fry_asset,
            asset_amount=1_000_000,
        )
        app_call_1 = context.any.txn.application_call(
            sender=user_account,
            app_id=app,
        )

        with context.txn.create_group([mbr_payment_1, asset_transfer_1, app_call_1], active_txn_index=2):
            contract.cast_vote(
                vote_id,
                arc4.UInt8(0),
                mbr_payment_1,
                asset_transfer_1,
            )

        # User 2 votes for option 1
        mbr_payment_2 = context.any.txn.payment(
            sender=user_account_2,
            receiver=app.address,
            amount=STAKE_BOX_MBR,
        )
        asset_transfer_2 = context.any.txn.asset_transfer(
            sender=user_account_2,
            asset_receiver=app.address,
            xfer_asset=fry_asset,
            asset_amount=2_000_000,
        )
        app_call_2 = context.any.txn.application_call(
            sender=user_account_2,
            app_id=app,
        )

        with context.txn.create_group([mbr_payment_2, asset_transfer_2, app_call_2], active_txn_index=2):
            contract.cast_vote(
                vote_id,
                arc4.UInt8(1),
                mbr_payment_2,
                asset_transfer_2,
            )

        # Verify totals
        vote_record = contract.get_vote(vote_id)
        assert vote_record.total_voters[0].native == 1
        assert vote_record.total_tokens[0].native == 1_000_000
        assert vote_record.total_voters[1].native == 1
        assert vote_record.total_tokens[1].native == 2_000_000
