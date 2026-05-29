# Tests for edge cases

from typing import Literal

import pytest
from algopy import Application, UInt64, arc4
from algopy_testing import AlgopyTestContext

from smart_contracts.fry_governance.constants import (
    FRY_ASA_ID,
    MAX_OPTIONS,
    MIN_OPTIONS,
    STAKE_BOX_MBR,
    VOTE_BOX_MBR,
    VOTE_TYPE_FIP,
)
from smart_contracts.fry_governance.contract import FryGovernance
from tests.conftest import make_vote_id


class TestOverflow:
    """Test 128-bit overflow protection."""

    def _create_vote(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account,
        app: Application,
        vote_id_bytes: bytes,
    ):
        """Helper to create a test vote."""
        context.ledger.patch_global_fields(latest_timestamp=1_700_000_000)

        vote_id = make_vote_id(vote_id_bytes)
        end_date = 1_700_000_000 + 86400 * 30
        lock_duration = 3600
        vote_type = VOTE_TYPE_FIP

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
                arc4.UInt64(lock_duration),
                arc4.UInt8(0),
                arc4.UInt8(vote_type),
                mbr_payment,
            )

        return vote_id

    def test_large_token_amounts(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account,
        user_account,
        app: Application,
        vote_id_bytes: bytes,
    ):
        """Test large but valid token amounts don't overflow."""
        vote_id = self._create_vote(context, contract, admin_account, app, vote_id_bytes)

        context.ledger.patch_global_fields(latest_timestamp=1_700_000_000 + 1000)

        # Large amount: 10 billion tokens (within uint64 range)
        large_amount = 10_000_000_000_000_000  # 10^16

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
            asset_amount=large_amount,
        )

        app_call = context.any.txn.application_call(
            sender=user_account,
            app_id=app,
        )

        with context.txn.create_group(
            [mbr_payment, asset_transfer, app_call], active_txn_index=2
        ):
            contract.cast_vote(
                vote_id,
                arc4.UInt8(0),
                mbr_payment,
                asset_transfer,
            )

        # Verify
        vote_record = contract.get_vote(vote_id)
        assert vote_record.total_tokens[0].native == large_amount


class TestMaxOptions:
    """Test maximum options handling."""

    def test_max_options_vote(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account,
        app: Application,
        vote_id_bytes: bytes,
    ):
        """Test creating vote with maximum options."""
        context.ledger.patch_global_fields(latest_timestamp=1_700_000_000)

        vote_id = make_vote_id(vote_id_bytes)

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
                arc4.UInt8(MAX_OPTIONS),  # 8 options
                arc4.UInt64(1_700_000_000 + 86400 * 30),
                arc4.UInt64(15_768_000),
                arc4.UInt8(0),
                arc4.UInt8(VOTE_TYPE_FIP),
                mbr_payment,
            )

        vote_record = contract.get_vote(vote_id)
        assert vote_record.options_count.native == MAX_OPTIONS

    def test_min_options_vote(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account,
        app: Application,
        vote_id_bytes: bytes,
    ):
        """Test creating vote with minimum options."""
        context.ledger.patch_global_fields(latest_timestamp=1_700_000_000)

        vote_id = make_vote_id(vote_id_bytes)

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
                arc4.UInt8(MIN_OPTIONS),  # 2 options
                arc4.UInt64(1_700_000_000 + 86400 * 30),
                arc4.UInt64(15_768_000),
                arc4.UInt8(0),
                arc4.UInt8(VOTE_TYPE_FIP),
                mbr_payment,
            )

        vote_record = contract.get_vote(vote_id)
        assert vote_record.options_count.native == MIN_OPTIONS


class TestConcurrentVotes:
    """Test concurrent votes scenarios."""

    def test_multiple_active_votes(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account,
        app: Application,
        vote_id_bytes: bytes,
        vote_id_bytes_2: bytes,
    ):
        """Test multiple concurrent active votes."""
        context.ledger.patch_global_fields(latest_timestamp=1_700_000_000)

        # Create first vote
        vote_id_1 = make_vote_id(vote_id_bytes)
        mbr_payment_1 = context.any.txn.payment(
            sender=admin_account,
            receiver=app.address,
            amount=VOTE_BOX_MBR,
        )
        app_call_1 = context.any.txn.application_call(
            sender=admin_account,
            app_id=app,
        )

        with context.txn.create_group([mbr_payment_1, app_call_1], active_txn_index=1):
            contract.create_vote(
                vote_id_1,
                arc4.UInt8(3),
                arc4.UInt64(1_700_000_000 + 86400 * 30),
                arc4.UInt64(15_768_000),
                arc4.UInt8(0),
                arc4.UInt8(VOTE_TYPE_FIP),
                mbr_payment_1,
            )

        assert contract.total_active_votes == UInt64(1)

        # Create second vote
        vote_id_2 = make_vote_id(vote_id_bytes_2)
        mbr_payment_2 = context.any.txn.payment(
            sender=admin_account,
            receiver=app.address,
            amount=VOTE_BOX_MBR,
        )
        app_call_2 = context.any.txn.application_call(
            sender=admin_account,
            app_id=app,
        )

        with context.txn.create_group([mbr_payment_2, app_call_2], active_txn_index=1):
            contract.create_vote(
                vote_id_2,
                arc4.UInt8(2),
                arc4.UInt64(1_700_000_000 + 86400 * 14),
                arc4.UInt64(3600),
                arc4.UInt8(1),
                arc4.UInt8(VOTE_TYPE_FIP),
                mbr_payment_2,
            )

        assert contract.total_active_votes == UInt64(2)

        # Close first vote
        app_call_close = context.any.txn.application_call(
            sender=admin_account,
            app_id=app,
        )

        with context.txn.create_group([app_call_close], active_txn_index=0):
            contract.admin_close_vote(vote_id_1)

        assert contract.total_active_votes == UInt64(1)

    def test_user_votes_on_multiple_proposals(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account,
        user_account,
        app: Application,
        vote_id_bytes: bytes,
        vote_id_bytes_2: bytes,
    ):
        """Test user can vote on multiple proposals."""
        context.ledger.patch_global_fields(latest_timestamp=1_700_000_000)

        fry_asset = context.any.asset(asset_id=FRY_ASA_ID)

        # Create two votes
        vote_id_1 = make_vote_id(vote_id_bytes)
        vote_id_2 = make_vote_id(vote_id_bytes_2)

        for vid in [vote_id_1, vote_id_2]:
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
                    vid,
                    arc4.UInt8(2),
                    arc4.UInt64(1_700_000_000 + 86400 * 30),
                    arc4.UInt64(3600),
                    arc4.UInt8(0),
                    arc4.UInt8(VOTE_TYPE_FIP),
                    mbr_payment,
                )

        # User votes on first proposal
        context.ledger.patch_global_fields(latest_timestamp=1_700_000_000 + 1000)

        mbr_payment_stake_1 = context.any.txn.payment(
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

        with context.txn.create_group(
            [mbr_payment_stake_1, asset_transfer_1, app_call_1], active_txn_index=2
        ):
            contract.cast_vote(
                vote_id_1,
                arc4.UInt8(0),
                mbr_payment_stake_1,
                asset_transfer_1,
            )

        # User votes on second proposal
        mbr_payment_stake_2 = context.any.txn.payment(
            sender=user_account,
            receiver=app.address,
            amount=STAKE_BOX_MBR,
        )
        asset_transfer_2 = context.any.txn.asset_transfer(
            sender=user_account,
            asset_receiver=app.address,
            xfer_asset=fry_asset,
            asset_amount=2_000_000,
        )
        app_call_2 = context.any.txn.application_call(
            sender=user_account,
            app_id=app,
        )

        with context.txn.create_group(
            [mbr_payment_stake_2, asset_transfer_2, app_call_2], active_txn_index=2
        ):
            contract.cast_vote(
                vote_id_2,
                arc4.UInt8(1),
                mbr_payment_stake_2,
                asset_transfer_2,
            )

        # Verify both votes recorded
        vote_1 = contract.get_vote(vote_id_1)
        vote_2 = contract.get_vote(vote_id_2)

        assert vote_1.total_voters[0].native == 1
        assert vote_1.total_tokens[0].native == 1_000_000
        assert vote_2.total_voters[1].native == 1
        assert vote_2.total_tokens[1].native == 2_000_000


class TestMBRValidation:
    """Test MBR payment validation."""

    def test_exact_mbr_vote_box(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account,
        app: Application,
        vote_id_bytes: bytes,
    ):
        """Test exact MBR payment for vote box works."""
        context.ledger.patch_global_fields(latest_timestamp=1_700_000_000)

        vote_id = make_vote_id(vote_id_bytes)

        # Exact MBR
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
                arc4.UInt64(1_700_000_000 + 86400 * 30),
                arc4.UInt64(15_768_000),
                arc4.UInt8(0),
                arc4.UInt8(VOTE_TYPE_FIP),
                mbr_payment,
            )

        # Should succeed
        assert contract.total_active_votes == UInt64(1)

    def test_overpay_mbr_works(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account,
        app: Application,
        vote_id_bytes: bytes,
    ):
        """Test overpaying MBR works (excess stays with contract)."""
        context.ledger.patch_global_fields(latest_timestamp=1_700_000_000)

        vote_id = make_vote_id(vote_id_bytes)

        # Overpay MBR
        mbr_payment = context.any.txn.payment(
            sender=admin_account,
            receiver=app.address,
            amount=VOTE_BOX_MBR * 2,
        )

        app_call = context.any.txn.application_call(
            sender=admin_account,
            app_id=app,
        )

        with context.txn.create_group([mbr_payment, app_call], active_txn_index=1):
            contract.create_vote(
                vote_id,
                arc4.UInt8(3),
                arc4.UInt64(1_700_000_000 + 86400 * 30),
                arc4.UInt64(15_768_000),
                arc4.UInt8(0),
                arc4.UInt8(VOTE_TYPE_FIP),
                mbr_payment,
            )

        # Should succeed
        assert contract.total_active_votes == UInt64(1)

    def test_underpay_mbr_fails(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account,
        app: Application,
        vote_id_bytes: bytes,
    ):
        """Test underpaying MBR fails."""
        context.ledger.patch_global_fields(latest_timestamp=1_700_000_000)

        vote_id = make_vote_id(vote_id_bytes)

        # Underpay by 1 microAlgo
        mbr_payment = context.any.txn.payment(
            sender=admin_account,
            receiver=app.address,
            amount=VOTE_BOX_MBR - 1,
        )

        app_call = context.any.txn.application_call(
            sender=admin_account,
            app_id=app,
        )

        with pytest.raises(AssertionError, match="Insufficient MBR payment"):
            with context.txn.create_group([mbr_payment, app_call], active_txn_index=1):
                contract.create_vote(
                    vote_id,
                    arc4.UInt8(3),
                    arc4.UInt64(1_700_000_000 + 86400 * 30),
                    arc4.UInt64(15_768_000),
                    arc4.UInt8(0),
                    arc4.UInt8(VOTE_TYPE_FIP),
                    mbr_payment,
                )


class TestBoundaryConditions:
    """Test boundary conditions."""

    def test_vote_at_exact_end_time(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account,
        user_account,
        app: Application,
        vote_id_bytes: bytes,
    ):
        """Test voting at exact end time fails."""
        # Create vote
        context.ledger.patch_global_fields(latest_timestamp=1_700_000_000)

        end_time = 1_700_000_000 + 86400  # 1 day from now
        vote_id = make_vote_id(vote_id_bytes)

        mbr_payment_vote = context.any.txn.payment(
            sender=admin_account,
            receiver=app.address,
            amount=VOTE_BOX_MBR,
        )

        app_call_create = context.any.txn.application_call(
            sender=admin_account,
            app_id=app,
        )

        with context.txn.create_group(
            [mbr_payment_vote, app_call_create], active_txn_index=1
        ):
            contract.create_vote(
                vote_id,
                arc4.UInt8(2),
                arc4.UInt64(end_time),
                arc4.UInt64(3600),
                arc4.UInt8(0),
                arc4.UInt8(VOTE_TYPE_FIP),
                mbr_payment_vote,
            )

        # Try to vote at exact end time
        context.ledger.patch_global_fields(latest_timestamp=end_time)

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

        # Should fail - end_date must be > current time
        with pytest.raises(AssertionError, match="Vote has expired"):
            with context.txn.create_group(
                [mbr_payment, asset_transfer, app_call], active_txn_index=2
            ):
                contract.cast_vote(
                    vote_id,
                    arc4.UInt8(0),
                    mbr_payment,
                    asset_transfer,
                )

    def test_vote_one_second_before_end(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account,
        user_account,
        app: Application,
        vote_id_bytes: bytes,
    ):
        """Test voting one second before end works."""
        # Create vote
        context.ledger.patch_global_fields(latest_timestamp=1_700_000_000)

        end_time = 1_700_000_000 + 86400
        vote_id = make_vote_id(vote_id_bytes)

        mbr_payment_vote = context.any.txn.payment(
            sender=admin_account,
            receiver=app.address,
            amount=VOTE_BOX_MBR,
        )

        app_call_create = context.any.txn.application_call(
            sender=admin_account,
            app_id=app,
        )

        with context.txn.create_group(
            [mbr_payment_vote, app_call_create], active_txn_index=1
        ):
            contract.create_vote(
                vote_id,
                arc4.UInt8(2),
                arc4.UInt64(end_time),
                arc4.UInt64(3600),
                arc4.UInt8(0),
                arc4.UInt8(VOTE_TYPE_FIP),
                mbr_payment_vote,
            )

        # Vote 1 second before end
        context.ledger.patch_global_fields(latest_timestamp=end_time - 1)

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

        # Should succeed
        with context.txn.create_group(
            [mbr_payment, asset_transfer, app_call], active_txn_index=2
        ):
            contract.cast_vote(
                vote_id,
                arc4.UInt8(0),
                mbr_payment,
                asset_transfer,
            )

        vote_record = contract.get_vote(vote_id)
        assert vote_record.total_voters[0].native == 1
