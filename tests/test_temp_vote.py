# Tests for cast_temp_vote method

from typing import Literal

import pytest
from algopy import arc4
from algopy_testing import AlgopyTestContext

from smart_contracts.fry_governance.constants import (
    STAKE_BOX_MBR,
    VOTE_BOX_MBR,
    VOTE_TYPE_FIP,
    VOTE_TYPE_TEMP_CHECK,
)
from smart_contracts.fry_governance.contract import FryGovernance
from tests.conftest import make_vote_id


class TestCastTempVote:
    """Test cases for the cast_temp_vote method."""

    def _create_temp_check_vote(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account,
        app,
        vote_id_bytes: bytes,
    ):
        """Helper to create a temp check vote."""
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

        end_date = 1_700_000_000 + 86400 * 7  # 7 days

        with context.txn.create_group([mbr_payment, app_call], active_txn_index=1):
            contract.create_vote(
                vote_id,
                arc4.UInt8(2),
                arc4.UInt64(end_date),
                arc4.UInt64(0),  # No lock for temp check
                arc4.UInt8(0),
                arc4.UInt8(VOTE_TYPE_TEMP_CHECK),
                mbr_payment,
            )

        return vote_id

    def test_cast_temp_vote_success(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account,
        user_account,
        app,
        fry_asset,
        vote_id_bytes: bytes,
    ):
        """Test successful temp vote casting."""
        # Setup min balance
        admin_app_call = context.any.txn.application_call(
            sender=admin_account,
            app_id=app,
        )
        with context.txn.create_group([admin_app_call], active_txn_index=0):
            contract.admin_set_min_balance(arc4.UInt64(1_000_000))

        # Create temp check vote
        vote_id = self._create_temp_check_vote(
            context, contract, admin_account, app, vote_id_bytes
        )

        # Setup user's FRY balance
        context.ledger.update_asset_holdings(fry_asset, user_account, balance=5_000_000)

        # Cast temp vote
        context.ledger.patch_global_fields(latest_timestamp=1_700_000_000 + 1000)

        mbr_payment = context.any.txn.payment(
            sender=user_account,
            receiver=app.address,
            amount=STAKE_BOX_MBR,
        )

        user_app_call = context.any.txn.application_call(
            sender=user_account,
            app_id=app,
        )

        with context.txn.create_group([mbr_payment, user_app_call], active_txn_index=1):
            contract.cast_temp_vote(
                vote_id,
                arc4.UInt8(0),
                mbr_payment,
            )

        # Verify vote recorded with weight = 1
        vote_record = contract.get_vote(vote_id)
        assert vote_record.total_voters[0].native == 1
        assert vote_record.total_tokens[0].native == 1

    def test_cast_temp_vote_wrong_group_size_fails(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account,
        user_account,
        app,
        fry_asset,
        vote_id_bytes: bytes,
    ):
        """Test wrong group size fails."""
        # Setup min balance
        admin_app_call = context.any.txn.application_call(
            sender=admin_account,
            app_id=app,
        )
        with context.txn.create_group([admin_app_call], active_txn_index=0):
            contract.admin_set_min_balance(arc4.UInt64(1_000_000))

        vote_id = self._create_temp_check_vote(
            context, contract, admin_account, app, vote_id_bytes
        )

        context.ledger.update_asset_holdings(fry_asset, user_account, balance=5_000_000)

        # Wrong group size - create 3 transactions
        context.ledger.patch_global_fields(latest_timestamp=1_700_000_000 + 1000)

        mbr_payment = context.any.txn.payment(
            sender=user_account,
            receiver=app.address,
            amount=STAKE_BOX_MBR,
        )

        extra_payment = context.any.txn.payment(
            sender=user_account,
            receiver=app.address,
            amount=1000,
        )

        user_app_call = context.any.txn.application_call(
            sender=user_account,
            app_id=app,
        )

        with pytest.raises(AssertionError, match="Group size must be 2"):
            with context.txn.create_group([mbr_payment, extra_payment, user_app_call], active_txn_index=2):
                contract.cast_temp_vote(
                    vote_id,
                    arc4.UInt8(0),
                    mbr_payment,
                )

    def test_cast_temp_vote_insufficient_mbr_fails(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account,
        user_account,
        app,
        fry_asset,
        vote_id_bytes: bytes,
    ):
        """Test insufficient MBR payment fails."""
        # Setup min balance
        admin_app_call = context.any.txn.application_call(
            sender=admin_account,
            app_id=app,
        )
        with context.txn.create_group([admin_app_call], active_txn_index=0):
            contract.admin_set_min_balance(arc4.UInt64(1_000_000))

        vote_id = self._create_temp_check_vote(
            context, contract, admin_account, app, vote_id_bytes
        )

        context.ledger.update_asset_holdings(fry_asset, user_account, balance=5_000_000)

        context.ledger.patch_global_fields(latest_timestamp=1_700_000_000 + 1000)

        mbr_payment = context.any.txn.payment(
            sender=user_account,
            receiver=app.address,
            amount=1000,  # Insufficient
        )

        user_app_call = context.any.txn.application_call(
            sender=user_account,
            app_id=app,
        )

        with pytest.raises(AssertionError, match="Insufficient MBR payment"):
            with context.txn.create_group([mbr_payment, user_app_call], active_txn_index=1):
                contract.cast_temp_vote(
                    vote_id,
                    arc4.UInt8(0),
                    mbr_payment,
                )

    def test_cast_temp_vote_on_fip_fails(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account,
        user_account,
        app,
        fry_asset,
        vote_id_bytes: bytes,
    ):
        """Test cast_temp_vote on FIP vote type fails."""
        # Setup min balance
        admin_app_call = context.any.txn.application_call(
            sender=admin_account,
            app_id=app,
        )
        with context.txn.create_group([admin_app_call], active_txn_index=0):
            contract.admin_set_min_balance(arc4.UInt64(1_000_000))

        # Create FIP vote (not temp check)
        vote_id = make_vote_id(vote_id_bytes)

        mbr_payment_vote = context.any.txn.payment(
            sender=admin_account,
            receiver=app.address,
            amount=VOTE_BOX_MBR,
        )

        admin_create_call = context.any.txn.application_call(
            sender=admin_account,
            app_id=app,
        )

        end_date = 1_700_000_000 + 86400 * 7

        with context.txn.create_group([mbr_payment_vote, admin_create_call], active_txn_index=1):
            contract.create_vote(
                vote_id,
                arc4.UInt8(2),
                arc4.UInt64(end_date),
                arc4.UInt64(15_768_000),
                arc4.UInt8(0),
                arc4.UInt8(VOTE_TYPE_FIP),  # FIP, not temp check
                mbr_payment_vote,
            )

        context.ledger.update_asset_holdings(fry_asset, user_account, balance=5_000_000)

        context.ledger.patch_global_fields(latest_timestamp=1_700_000_000 + 1000)

        mbr_payment = context.any.txn.payment(
            sender=user_account,
            receiver=app.address,
            amount=STAKE_BOX_MBR,
        )

        user_app_call = context.any.txn.application_call(
            sender=user_account,
            app_id=app,
        )

        with pytest.raises(AssertionError, match="Not a temp check vote"):
            with context.txn.create_group([mbr_payment, user_app_call], active_txn_index=1):
                contract.cast_temp_vote(
                    vote_id,
                    arc4.UInt8(0),
                    mbr_payment,
                )

    def test_cast_temp_vote_min_balance_not_configured_fails(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account,
        user_account,
        app,
        fry_asset,
        vote_id_bytes: bytes,
    ):
        """Test cast_temp_vote fails if min balance not configured."""
        # Create temp check vote without setting min balance
        vote_id = self._create_temp_check_vote(
            context, contract, admin_account, app, vote_id_bytes
        )

        context.ledger.update_asset_holdings(fry_asset, user_account, balance=5_000_000)

        context.ledger.patch_global_fields(latest_timestamp=1_700_000_000 + 1000)

        mbr_payment = context.any.txn.payment(
            sender=user_account,
            receiver=app.address,
            amount=STAKE_BOX_MBR,
        )

        user_app_call = context.any.txn.application_call(
            sender=user_account,
            app_id=app,
        )

        with pytest.raises(AssertionError, match="Min balance not configured"):
            with context.txn.create_group([mbr_payment, user_app_call], active_txn_index=1):
                contract.cast_temp_vote(
                    vote_id,
                    arc4.UInt8(0),
                    mbr_payment,
                )

    def test_cast_temp_vote_insufficient_fry_balance_fails(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account,
        user_account,
        app,
        fry_asset,
        vote_id_bytes: bytes,
    ):
        """Test cast_temp_vote fails if user has insufficient FRY balance."""
        # Setup min balance
        admin_app_call = context.any.txn.application_call(
            sender=admin_account,
            app_id=app,
        )
        with context.txn.create_group([admin_app_call], active_txn_index=0):
            contract.admin_set_min_balance(arc4.UInt64(1_000_000))

        vote_id = self._create_temp_check_vote(
            context, contract, admin_account, app, vote_id_bytes
        )

        # Set user's FRY balance below minimum
        context.ledger.update_asset_holdings(fry_asset, user_account, balance=500_000)

        context.ledger.patch_global_fields(latest_timestamp=1_700_000_000 + 1000)

        mbr_payment = context.any.txn.payment(
            sender=user_account,
            receiver=app.address,
            amount=STAKE_BOX_MBR,
        )

        user_app_call = context.any.txn.application_call(
            sender=user_account,
            app_id=app,
        )

        with pytest.raises(AssertionError, match="Insufficient FRY balance"):
            with context.txn.create_group([mbr_payment, user_app_call], active_txn_index=1):
                contract.cast_temp_vote(
                    vote_id,
                    arc4.UInt8(0),
                    mbr_payment,
                )

    def test_cast_temp_vote_duplicate_fails(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account,
        user_account,
        app,
        fry_asset,
        vote_id_bytes: bytes,
    ):
        """Test duplicate temp vote fails."""
        # Setup min balance
        admin_app_call = context.any.txn.application_call(
            sender=admin_account,
            app_id=app,
        )
        with context.txn.create_group([admin_app_call], active_txn_index=0):
            contract.admin_set_min_balance(arc4.UInt64(1_000_000))

        vote_id = self._create_temp_check_vote(
            context, contract, admin_account, app, vote_id_bytes
        )

        context.ledger.update_asset_holdings(fry_asset, user_account, balance=5_000_000)

        context.ledger.patch_global_fields(latest_timestamp=1_700_000_000 + 1000)

        mbr_payment = context.any.txn.payment(
            sender=user_account,
            receiver=app.address,
            amount=STAKE_BOX_MBR,
        )

        user_app_call = context.any.txn.application_call(
            sender=user_account,
            app_id=app,
        )

        # First vote
        with context.txn.create_group([mbr_payment, user_app_call], active_txn_index=1):
            contract.cast_temp_vote(
                vote_id,
                arc4.UInt8(0),
                mbr_payment,
            )

        # Create new transactions for second vote attempt
        mbr_payment_2 = context.any.txn.payment(
            sender=user_account,
            receiver=app.address,
            amount=STAKE_BOX_MBR,
        )

        user_app_call_2 = context.any.txn.application_call(
            sender=user_account,
            app_id=app,
        )

        # Second vote should fail
        with pytest.raises(AssertionError, match="Already voted"):
            with context.txn.create_group([mbr_payment_2, user_app_call_2], active_txn_index=1):
                contract.cast_temp_vote(
                    vote_id,
                    arc4.UInt8(1),
                    mbr_payment_2,
                )

    def test_cast_temp_vote_expired_fails(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account,
        user_account,
        app,
        fry_asset,
        vote_id_bytes: bytes,
    ):
        """Test cast_temp_vote on expired vote fails."""
        # Setup min balance
        admin_app_call = context.any.txn.application_call(
            sender=admin_account,
            app_id=app,
        )
        with context.txn.create_group([admin_app_call], active_txn_index=0):
            contract.admin_set_min_balance(arc4.UInt64(1_000_000))

        vote_id = self._create_temp_check_vote(
            context, contract, admin_account, app, vote_id_bytes
        )

        context.ledger.update_asset_holdings(fry_asset, user_account, balance=5_000_000)

        # Vote expires at 1_700_000_000 + 86400 * 7, set time after that
        context.ledger.patch_global_fields(latest_timestamp=1_700_000_000 + 86400 * 8)

        mbr_payment = context.any.txn.payment(
            sender=user_account,
            receiver=app.address,
            amount=STAKE_BOX_MBR,
        )

        user_app_call = context.any.txn.application_call(
            sender=user_account,
            app_id=app,
        )

        with pytest.raises(AssertionError, match="Vote has expired"):
            with context.txn.create_group([mbr_payment, user_app_call], active_txn_index=1):
                contract.cast_temp_vote(
                    vote_id,
                    arc4.UInt8(0),
                    mbr_payment,
                )

    def test_cast_temp_vote_stake_marked_withdrawn(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account,
        user_account,
        app,
        fry_asset,
        vote_id_bytes: bytes,
    ):
        """Test temp vote stake is marked as withdrawn (no tokens to withdraw)."""
        # Setup min balance
        admin_app_call = context.any.txn.application_call(
            sender=admin_account,
            app_id=app,
        )
        with context.txn.create_group([admin_app_call], active_txn_index=0):
            contract.admin_set_min_balance(arc4.UInt64(1_000_000))

        vote_id = self._create_temp_check_vote(
            context, contract, admin_account, app, vote_id_bytes
        )

        context.ledger.update_asset_holdings(fry_asset, user_account, balance=5_000_000)

        context.ledger.patch_global_fields(latest_timestamp=1_700_000_000 + 1000)

        mbr_payment = context.any.txn.payment(
            sender=user_account,
            receiver=app.address,
            amount=STAKE_BOX_MBR,
        )

        user_app_call = context.any.txn.application_call(
            sender=user_account,
            app_id=app,
        )

        with context.txn.create_group([mbr_payment, user_app_call], active_txn_index=1):
            contract.cast_temp_vote(
                vote_id,
                arc4.UInt8(0),
                mbr_payment,
            )

        # Verify stake record
        voter_bytes = arc4.StaticArray[arc4.Byte, Literal[32]].from_bytes(
            user_account.bytes
        )
        stake_record = contract.get_stake(vote_id, voter_bytes)

        # Token amount should be 0 (no tokens staked)
        assert stake_record.token_amount.native == 0
        # Should be marked as withdrawn
        assert stake_record.withdrawn.native == 1

    def test_cast_temp_vote_not_opted_in_fails(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account,
        user_account,
        app,
        vote_id_bytes: bytes,
    ):
        """Test cast_temp_vote fails if user not opted into FRY."""
        # Setup min balance
        admin_app_call = context.any.txn.application_call(
            sender=admin_account,
            app_id=app,
        )
        with context.txn.create_group([admin_app_call], active_txn_index=0):
            contract.admin_set_min_balance(arc4.UInt64(1_000_000))

        vote_id = self._create_temp_check_vote(
            context, contract, admin_account, app, vote_id_bytes
        )

        # Don't set any asset holding for user (not opted in)

        context.ledger.patch_global_fields(latest_timestamp=1_700_000_000 + 1000)

        mbr_payment = context.any.txn.payment(
            sender=user_account,
            receiver=app.address,
            amount=STAKE_BOX_MBR,
        )

        user_app_call = context.any.txn.application_call(
            sender=user_account,
            app_id=app,
        )

        with pytest.raises(AssertionError, match="Not opted into FRY"):
            with context.txn.create_group([mbr_payment, user_app_call], active_txn_index=1):
                contract.cast_temp_vote(
                    vote_id,
                    arc4.UInt8(0),
                    mbr_payment,
                )

    def test_multiple_voters_temp_check(
        self,
        context: AlgopyTestContext,
        contract: FryGovernance,
        admin_account,
        user_account,
        user_account_2,
        app,
        fry_asset,
        vote_id_bytes: bytes,
    ):
        """Test multiple voters each get 1 vote in temp check."""
        # Setup min balance
        admin_app_call = context.any.txn.application_call(
            sender=admin_account,
            app_id=app,
        )
        with context.txn.create_group([admin_app_call], active_txn_index=0):
            contract.admin_set_min_balance(arc4.UInt64(1_000_000))

        vote_id = self._create_temp_check_vote(
            context, contract, admin_account, app, vote_id_bytes
        )

        # Create a third user
        user_account_3 = context.any.account()

        # Setup FRY balances for all 3 users (different amounts)
        context.ledger.update_asset_holdings(fry_asset, user_account, balance=1_000_000)
        context.ledger.update_asset_holdings(fry_asset, user_account_2, balance=5_000_000)
        context.ledger.update_asset_holdings(fry_asset, user_account_3, balance=10_000_000)

        context.ledger.patch_global_fields(latest_timestamp=1_700_000_000 + 1000)

        # User 1 votes for option 0
        mbr_payment_1 = context.any.txn.payment(
            sender=user_account,
            receiver=app.address,
            amount=STAKE_BOX_MBR,
        )
        user_app_call_1 = context.any.txn.application_call(
            sender=user_account,
            app_id=app,
        )
        with context.txn.create_group([mbr_payment_1, user_app_call_1], active_txn_index=1):
            contract.cast_temp_vote(vote_id, arc4.UInt8(0), mbr_payment_1)

        # User 2 votes for option 0
        mbr_payment_2 = context.any.txn.payment(
            sender=user_account_2,
            receiver=app.address,
            amount=STAKE_BOX_MBR,
        )
        user_app_call_2 = context.any.txn.application_call(
            sender=user_account_2,
            app_id=app,
        )
        with context.txn.create_group([mbr_payment_2, user_app_call_2], active_txn_index=1):
            contract.cast_temp_vote(vote_id, arc4.UInt8(0), mbr_payment_2)

        # User 3 votes for option 1
        mbr_payment_3 = context.any.txn.payment(
            sender=user_account_3,
            receiver=app.address,
            amount=STAKE_BOX_MBR,
        )
        user_app_call_3 = context.any.txn.application_call(
            sender=user_account_3,
            app_id=app,
        )
        with context.txn.create_group([mbr_payment_3, user_app_call_3], active_txn_index=1):
            contract.cast_temp_vote(vote_id, arc4.UInt8(1), mbr_payment_3)

        # Verify vote counts: 1 vote per person regardless of FRY balance
        vote_record = contract.get_vote(vote_id)
        # Option 0: 2 voters, 2 tokens (1 each)
        assert vote_record.total_voters[0].native == 2
        assert vote_record.total_tokens[0].native == 2
        # Option 1: 1 voter, 1 token
        assert vote_record.total_voters[1].native == 1
        assert vote_record.total_tokens[1].native == 1
