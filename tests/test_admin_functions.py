# Tests for admin functions

from typing import Literal

import pytest
from algopy import Account, Application, UInt64, arc4
from algopy_testing import AlgopyTestContext

from smart_contracts.fry_governance.constants import (
    UPDATE_PROPOSAL_BOX_MBR,
    UPDATE_TIMELOCK_SECONDS,
    FRY_ASA_ID,
    STAKE_BOX_MBR,
    VOTE_BOX_MBR,
    VOTE_TYPE_FIP,
)
from smart_contracts.fry_governance.contract import FryGovernance
from tests.conftest import make_vote_id


class TestAdminSetMinBalance:
    """Test cases for admin_set_min_balance method."""

    def test_set_min_balance_success(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account: Account,
        app: Application,
    ):
        """Test successful setting of min balance."""
        app_call = context.any.txn.application_call(
            sender=admin_account,
            app_id=app,
        )

        with context.txn.create_group([app_call], active_txn_index=0):
            contract.admin_set_min_balance(arc4.UInt64(1_000_000))

        assert contract.min_temp_check_balance == UInt64(1_000_000)

    def test_set_min_balance_non_admin_fails(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        user_account: Account,
        app: Application,
    ):
        """Test non-admin cannot set min balance."""
        app_call = context.any.txn.application_call(
            sender=user_account,
            app_id=app,
        )

        with pytest.raises(AssertionError, match="Only admin can set min balance"):
            with context.txn.create_group([app_call], active_txn_index=0):
                contract.admin_set_min_balance(arc4.UInt64(1_000_000))


class TestAdminSetPrice:
    """Test cases for admin_set_price method."""

    def test_set_price_success(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account: Account,
        app: Application,
    ):
        """Test successful price setting."""
        app_call = context.any.txn.application_call(
            sender=admin_account,
            app_id=app,
        )

        with context.txn.create_group([app_call], active_txn_index=0):
            contract.admin_set_price(arc4.UInt64(100), arc4.UInt8(1))

        assert contract.price_value == UInt64(100)
        assert contract.price_is_usd == UInt64(1)

    def test_set_price_non_admin_fails(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        user_account: Account,
        app: Application,
    ):
        """Test non-admin cannot set price."""
        app_call = context.any.txn.application_call(
            sender=user_account,
            app_id=app,
        )

        with pytest.raises(AssertionError, match="Only admin can set price"):
            with context.txn.create_group([app_call], active_txn_index=0):
                contract.admin_set_price(arc4.UInt64(100), arc4.UInt8(1))


class TestOptInFry:
    """Test cases for opt_in_fry method."""

    def test_opt_in_fry_success(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account: Account,
        app: Application,
    ):
        """Test successful FRY opt-in."""
        app_call = context.any.txn.application_call(
            sender=admin_account,
            app_id=app,
        )

        with context.txn.create_group([app_call], active_txn_index=0):
            contract.opt_in_fry()

    def test_opt_in_fry_non_admin_fails(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        user_account: Account,
        app: Application,
    ):
        """Test non-admin cannot opt in."""
        app_call = context.any.txn.application_call(
            sender=user_account,
            app_id=app,
        )

        with pytest.raises(AssertionError, match="Only admin can opt in"):
            with context.txn.create_group([app_call], active_txn_index=0):
                contract.opt_in_fry()


class TestAdminCloseVote:
    """Test cases for admin_close_vote method."""

    def _create_vote(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account: Account,
        app: Application,
        vote_id_bytes: bytes,
    ):
        """Helper to create a vote for testing."""
        vote_id = make_vote_id(vote_id_bytes)
        end_date = 1_700_000_000 + 86400 * 30

        mbr_payment = context.any.txn.payment(
            sender=admin_account,
            receiver=app.address,
            amount=VOTE_BOX_MBR,
        )
        app_call = context.any.txn.application_call(
            sender=admin_account,
            app_id=app,
        )

        with context.txn.create_group([mbr_payment, app_call], active_txn_index=1):
            contract.create_vote(
                vote_id,
                arc4.UInt8(3),
                arc4.UInt64(end_date),
                arc4.UInt64(15_768_000),
                arc4.UInt8(0),
                arc4.UInt8(VOTE_TYPE_FIP),
                mbr_payment,
            )

        return vote_id

    def test_close_vote_success(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account: Account,
        app: Application,
        vote_id_bytes: bytes,
    ):
        """Test successful vote closing."""
        context.ledger.patch_global_fields(latest_timestamp=1_700_000_000)

        vote_id = self._create_vote(context, contract, admin_account, app, vote_id_bytes)
        assert contract.total_active_votes == UInt64(1)

        app_call = context.any.txn.application_call(
            sender=admin_account,
            app_id=app,
        )

        with context.txn.create_group([app_call], active_txn_index=0):
            contract.admin_close_vote(vote_id)

        assert contract.total_active_votes == UInt64(0)

    def test_close_vote_non_admin_fails(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account: Account,
        user_account: Account,
        app: Application,
        vote_id_bytes: bytes,
    ):
        """Test non-admin cannot close vote."""
        context.ledger.patch_global_fields(latest_timestamp=1_700_000_000)

        vote_id = self._create_vote(context, contract, admin_account, app, vote_id_bytes)

        app_call = context.any.txn.application_call(
            sender=user_account,
            app_id=app,
        )

        with pytest.raises(AssertionError, match="Only admin can close vote"):
            with context.txn.create_group([app_call], active_txn_index=0):
                contract.admin_close_vote(vote_id)

    def test_close_vote_already_closed_fails(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account: Account,
        app: Application,
        vote_id_bytes: bytes,
    ):
        """Test cannot close already closed vote."""
        context.ledger.patch_global_fields(latest_timestamp=1_700_000_000)

        vote_id = self._create_vote(context, contract, admin_account, app, vote_id_bytes)

        # Close once
        app_call1 = context.any.txn.application_call(
            sender=admin_account,
            app_id=app,
        )
        with context.txn.create_group([app_call1], active_txn_index=0):
            contract.admin_close_vote(vote_id)

        # Try to close again
        app_call2 = context.any.txn.application_call(
            sender=admin_account,
            app_id=app,
        )
        with pytest.raises(AssertionError, match="Vote already closed"):
            with context.txn.create_group([app_call2], active_txn_index=0):
                contract.admin_close_vote(vote_id)

    def test_close_vote_nonexistent_fails(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account: Account,
        app: Application,
        vote_id_bytes: bytes,
    ):
        """Test cannot close nonexistent vote."""
        vote_id = make_vote_id(vote_id_bytes)

        app_call = context.any.txn.application_call(
            sender=admin_account,
            app_id=app,
        )

        with pytest.raises(AssertionError, match="Vote not found"):
            with context.txn.create_group([app_call], active_txn_index=0):
                contract.admin_close_vote(vote_id)


class TestAdminEmergencyRefund:
    """Test cases for admin_emergency_refund method."""

    def _create_vote_and_stake(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account: Account,
        user_account: Account,
        app: Application,
        vote_id_bytes: bytes,
        fry_asset,
    ):
        """Helper to create a vote and cast a stake."""
        context.ledger.patch_global_fields(latest_timestamp=1_700_000_000)

        vote_id = make_vote_id(vote_id_bytes)
        end_date = 1_700_000_000 + 86400 * 30

        # Create vote
        mbr_payment = context.any.txn.payment(
            sender=admin_account,
            receiver=app.address,
            amount=VOTE_BOX_MBR,
        )
        app_call = context.any.txn.application_call(
            sender=admin_account,
            app_id=app,
        )

        with context.txn.create_group([mbr_payment, app_call], active_txn_index=1):
            contract.create_vote(
                vote_id,
                arc4.UInt8(3),
                arc4.UInt64(end_date),
                arc4.UInt64(15_768_000),
                arc4.UInt8(0),
                arc4.UInt8(VOTE_TYPE_FIP),
                mbr_payment,
            )

        # Cast vote
        stake_payment = context.any.txn.payment(
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
        vote_app_call = context.any.txn.application_call(
            sender=user_account,
            app_id=app,
        )

        with context.txn.create_group(
            [stake_payment, asset_transfer, vote_app_call], active_txn_index=2
        ):
            contract.cast_vote(
                vote_id,
                arc4.UInt8(0),
                stake_payment,
                asset_transfer,
            )

        return vote_id

    def test_emergency_refund_success(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account: Account,
        user_account: Account,
        app: Application,
        vote_id_bytes: bytes,
        fry_asset,
    ):
        """Test successful emergency refund."""
        vote_id = self._create_vote_and_stake(
            context, contract, admin_account, user_account, app, vote_id_bytes, fry_asset
        )

        voter_bytes = arc4.StaticArray[arc4.Byte, Literal[32]].from_bytes(
            user_account.bytes
        )

        app_call = context.any.txn.application_call(
            sender=admin_account,
            app_id=app,
        )

        with context.txn.create_group([app_call], active_txn_index=0):
            contract.admin_emergency_refund(vote_id, voter_bytes)

    def test_emergency_refund_non_admin_fails(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account: Account,
        user_account: Account,
        app: Application,
        vote_id_bytes: bytes,
        fry_asset,
    ):
        """Test non-admin cannot emergency refund."""
        vote_id = self._create_vote_and_stake(
            context, contract, admin_account, user_account, app, vote_id_bytes, fry_asset
        )

        voter_bytes = arc4.StaticArray[arc4.Byte, Literal[32]].from_bytes(
            user_account.bytes
        )

        app_call = context.any.txn.application_call(
            sender=user_account,
            app_id=app,
        )

        with pytest.raises(AssertionError, match="Only admin can emergency refund"):
            with context.txn.create_group([app_call], active_txn_index=0):
                contract.admin_emergency_refund(vote_id, voter_bytes)

    def test_emergency_refund_already_withdrawn_fails(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account: Account,
        user_account: Account,
        app: Application,
        vote_id_bytes: bytes,
        fry_asset,
    ):
        """Test cannot emergency refund already withdrawn stake."""
        vote_id = self._create_vote_and_stake(
            context, contract, admin_account, user_account, app, vote_id_bytes, fry_asset
        )

        voter_bytes = arc4.StaticArray[arc4.Byte, Literal[32]].from_bytes(
            user_account.bytes
        )

        # First refund
        app_call1 = context.any.txn.application_call(
            sender=admin_account,
            app_id=app,
        )
        with context.txn.create_group([app_call1], active_txn_index=0):
            contract.admin_emergency_refund(vote_id, voter_bytes)

        # Second refund should fail
        app_call2 = context.any.txn.application_call(
            sender=admin_account,
            app_id=app,
        )
        with pytest.raises(AssertionError, match="Stake not found"):
            with context.txn.create_group([app_call2], active_txn_index=0):
                contract.admin_emergency_refund(vote_id, voter_bytes)

    def test_emergency_refund_nonexistent_stake_fails(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account: Account,
        user_account: Account,
        app: Application,
        vote_id_bytes: bytes,
    ):
        """Test cannot refund nonexistent stake."""
        vote_id = make_vote_id(vote_id_bytes)
        voter_bytes = arc4.StaticArray[arc4.Byte, Literal[32]].from_bytes(
            user_account.bytes
        )

        app_call = context.any.txn.application_call(
            sender=admin_account,
            app_id=app,
        )

        with pytest.raises(AssertionError, match="Stake not found"):
            with context.txn.create_group([app_call], active_txn_index=0):
                contract.admin_emergency_refund(vote_id, voter_bytes)


class TestAdminUpdate:
    """Test cases for admin_update method."""

    def test_update_with_timelock(
        self,
        context: AlgopyTestContext,
        admin_account: Account,
    ):
        """Test admin can update after 48-hour timelock."""
        from algopy import OnCompleteAction

        contract = FryGovernance()
        context.ledger.patch_global_fields(latest_timestamp=1_700_000_000)

        app = context.ledger.get_app(contract.__app_id__)

        # Set admin_account as the creator of this app
        context.ledger.update_app(app, creator=admin_account)

        # Create contract first
        create_call = context.any.txn.application_call(
            sender=admin_account,
            app_id=app,
            on_completion=OnCompleteAction.NoOp,
        )
        with context.txn.create_group([create_call], active_txn_index=0):
            contract.create(arc4.UInt64(FRY_ASA_ID))

        # Step 1: Propose update with MBR payment
        mbr_payment = context.any.txn.payment(
            sender=admin_account,
            receiver=app.address,
            amount=UPDATE_PROPOSAL_BOX_MBR,
        )
        propose_call = context.any.txn.application_call(
            sender=admin_account,
            app_id=app,
            on_completion=OnCompleteAction.NoOp,
        )
        with context.txn.create_group([mbr_payment, propose_call], active_txn_index=1):
            contract.admin_propose_update(mbr_payment)

        # Step 2: Advance time past 48-hour timelock
        context.ledger.patch_global_fields(
            latest_timestamp=1_700_000_000 + UPDATE_TIMELOCK_SECONDS + 1
        )

        # Step 3: Execute update
        update_call = context.any.txn.application_call(
            sender=admin_account,
            app_id=app,
            on_completion=OnCompleteAction.UpdateApplication,
        )
        with context.txn.create_group([update_call], active_txn_index=0):
            contract.admin_update()

    def test_update_by_non_creator_fails(
        self,
        context: AlgopyTestContext,
        admin_account: Account,
        user_account: Account,
    ):
        """Test non-creator cannot update."""
        from algopy import OnCompleteAction

        contract = FryGovernance()
        context.ledger.patch_global_fields(latest_timestamp=1_700_000_000)

        app = context.ledger.get_app(contract.__app_id__)

        # Set admin_account as the creator of this app
        context.ledger.update_app(app, creator=admin_account)

        # Create contract first
        create_call = context.any.txn.application_call(
            sender=admin_account,
            app_id=app,
            on_completion=OnCompleteAction.NoOp,
        )
        with context.txn.create_group([create_call], active_txn_index=0):
            contract.create(arc4.UInt64(FRY_ASA_ID))

        # Non-creator tries to update
        update_call = context.any.txn.application_call(
            sender=user_account,
            app_id=app,
            on_completion=OnCompleteAction.UpdateApplication,
        )
        with pytest.raises(AssertionError, match="Only admin can update"):
            with context.txn.create_group([update_call], active_txn_index=0):
                contract.admin_update()
