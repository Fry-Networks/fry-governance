# Tests for create_vote method

from typing import Literal

import pytest
from algopy import UInt64, arc4
from algopy_testing import AlgopyTestContext

from smart_contracts.fry_governance.constants import (
    VOTE_BOX_MBR,
    VOTE_TYPE_FIP,
)
from smart_contracts.fry_governance.contract import FryGovernance
from tests.conftest import make_vote_id


class TestCreateVote:
    """Test cases for the create_vote method."""

    def test_create_vote_success(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account,
        app,
        vote_id_bytes: bytes,
    ):
        """Test successful vote creation by admin."""
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
                arc4.UInt8(3),
                arc4.UInt64(1_700_000_000 + 86400 * 30),
                arc4.UInt64(15_768_000),
                arc4.UInt8(0),
                arc4.UInt8(VOTE_TYPE_FIP),
                mbr_payment,
            )

        assert contract.total_active_votes == UInt64(1)

    def test_create_vote_non_admin_fails(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        user_account,
        app,
        vote_id_bytes: bytes,
    ):
        """Test that non-admin cannot create votes."""
        context.ledger.patch_global_fields(latest_timestamp=1_700_000_000)

        vote_id = make_vote_id(vote_id_bytes)

        mbr_payment = context.any.txn.payment(
            sender=user_account,
            receiver=app.address,
            amount=VOTE_BOX_MBR,
        )

        app_call = context.any.txn.application_call(
            sender=user_account,
            app_id=app,
        )

        with pytest.raises(AssertionError, match="Only admin can create vote"):
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

    def test_create_vote_wrong_group_size_fails(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account,
        app,
        vote_id_bytes: bytes,
    ):
        """Test that wrong group size fails."""
        context.ledger.patch_global_fields(latest_timestamp=1_700_000_000)

        vote_id = make_vote_id(vote_id_bytes)

        mbr_payment = context.any.txn.payment(
            sender=admin_account,
            receiver=app.address,
            amount=VOTE_BOX_MBR,
        )

        # Only one transaction in group (should be 2)
        app_call = context.any.txn.application_call(
            sender=admin_account,
            app_id=app,
        )

        with pytest.raises(AssertionError, match="Group size must be 2"):
            with context.txn.create_group([app_call], active_txn_index=0):
                contract.create_vote(
                    vote_id,
                    arc4.UInt8(3),
                    arc4.UInt64(1_700_000_000 + 86400 * 30),
                    arc4.UInt64(15_768_000),
                    arc4.UInt8(0),
                    arc4.UInt8(VOTE_TYPE_FIP),
                    mbr_payment,
                )

    def test_create_vote_insufficient_mbr_fails(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account,
        app,
        vote_id_bytes: bytes,
    ):
        """Test that insufficient MBR payment fails."""
        context.ledger.patch_global_fields(latest_timestamp=1_700_000_000)

        vote_id = make_vote_id(vote_id_bytes)

        # Insufficient MBR
        mbr_payment = context.any.txn.payment(
            sender=admin_account,
            receiver=app.address,
            amount=1000,  # Way less than required
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

    def test_create_vote_past_end_date_fails(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account,
        app,
        vote_id_bytes: bytes,
    ):
        """Test that past end date fails."""
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

        with pytest.raises(AssertionError, match="End date must be in future"):
            with context.txn.create_group([mbr_payment, app_call], active_txn_index=1):
                contract.create_vote(
                    vote_id,
                    arc4.UInt8(3),
                    arc4.UInt64(1_699_999_999),  # In the past
                    arc4.UInt64(15_768_000),
                    arc4.UInt8(0),
                    arc4.UInt8(VOTE_TYPE_FIP),
                    mbr_payment,
                )

    def test_create_vote_too_few_options_fails(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account,
        app,
        vote_id_bytes: bytes,
    ):
        """Test that less than 2 options fails."""
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

        with pytest.raises(AssertionError, match="Too few options"):
            with context.txn.create_group([mbr_payment, app_call], active_txn_index=1):
                contract.create_vote(
                    vote_id,
                    arc4.UInt8(1),  # Too few
                    arc4.UInt64(1_700_000_000 + 86400 * 30),
                    arc4.UInt64(15_768_000),
                    arc4.UInt8(0),
                    arc4.UInt8(VOTE_TYPE_FIP),
                    mbr_payment,
                )

    def test_create_vote_too_many_options_fails(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account,
        app,
        vote_id_bytes: bytes,
    ):
        """Test that more than 8 options fails."""
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

        with pytest.raises(AssertionError, match="Too many options"):
            with context.txn.create_group([mbr_payment, app_call], active_txn_index=1):
                contract.create_vote(
                    vote_id,
                    arc4.UInt8(9),  # Too many
                    arc4.UInt64(1_700_000_000 + 86400 * 30),
                    arc4.UInt64(15_768_000),
                    arc4.UInt8(0),
                    arc4.UInt8(VOTE_TYPE_FIP),
                    mbr_payment,
                )

    def test_create_vote_duplicate_fails(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account,
        app,
        vote_id_bytes: bytes,
    ):
        """Test that duplicate vote ID fails."""
        context.ledger.patch_global_fields(latest_timestamp=1_700_000_000)

        vote_id = make_vote_id(vote_id_bytes)

        # First creation succeeds
        mbr_payment1 = context.any.txn.payment(
            sender=admin_account,
            receiver=app.address,
            amount=VOTE_BOX_MBR,
        )
        app_call1 = context.any.txn.application_call(
            sender=admin_account,
            app_id=app,
        )

        with context.txn.create_group([mbr_payment1, app_call1], active_txn_index=1):
            contract.create_vote(
                vote_id,
                arc4.UInt8(3),
                arc4.UInt64(1_700_000_000 + 86400 * 30),
                arc4.UInt64(15_768_000),
                arc4.UInt8(0),
                arc4.UInt8(VOTE_TYPE_FIP),
                mbr_payment1,
            )

        # Second creation with same ID should fail
        mbr_payment2 = context.any.txn.payment(
            sender=admin_account,
            receiver=app.address,
            amount=VOTE_BOX_MBR,
        )
        app_call2 = context.any.txn.application_call(
            sender=admin_account,
            app_id=app,
        )

        with pytest.raises(AssertionError, match="Vote already exists"):
            with context.txn.create_group([mbr_payment2, app_call2], active_txn_index=1):
                contract.create_vote(
                    vote_id,
                    arc4.UInt8(3),
                    arc4.UInt64(1_700_000_000 + 86400 * 30),
                    arc4.UInt64(15_768_000),
                    arc4.UInt8(0),
                    arc4.UInt8(VOTE_TYPE_FIP),
                    mbr_payment2,
                )
