# FryGovernance Smart Contract
# On-chain governance system for FIP and cFIP voting

from typing import Literal

from algopy import (
    Account,
    ARC4Contract,
    Application,
    Asset,
    Bytes,
    Global,
    Txn,
    UInt64,
    arc4,
    gtxn,
    itxn,
    log,
    op,
    subroutine,
)

from smart_contracts.fry_governance.constants import (
    ACTUAL_STAKE_BOX_MBR,
    ADMIN_ADDRESS,
    FRY_ASA_ID,
    MAX_OPTIONS,
    MAX_TEMP_CHECK_DURATION,
    MIN_OPTIONS,
    STAKE_BOX_MBR,
    STAKE_BOX_PREFIX,
    STAKE_BOX_SIZE,
    UPDATE_PROPOSAL_BOX_KEY,
    UPDATE_PROPOSAL_BOX_MBR,
    UPDATE_TIMELOCK_SECONDS,
    VOTE_BOX_MBR,
    VOTE_BOX_PREFIX,
    VOTE_BOX_SIZE,
    VOTE_TYPE_TEMP_CHECK,
)
from smart_contracts.fry_governance.types import StakeRecord, VoteRecord


@subroutine
def box_exists(key: Bytes) -> bool:
    """Check if a box exists."""
    _length, exists = op.Box.length(key)
    return exists


class FryGovernance(ARC4Contract):
    """
    FryGovernance: On-chain voting system for Fry Networks

    Features:
    - FIP/cFIP voting with token staking and 6-month lock
    - Temperature checks using FryStaking V2 balances
    - Self-service withdrawal (no hot wallet)
    - Admin-upgradeable for bug fixes
    """

    def __init__(self) -> None:
        # Admin address for privileged operations
        self.admin = op.Global.zero_address.bytes
        # FRY token ASA ID
        self.fry_asa_id = UInt64(0)
        # Minimum FRY balance for temp check voting
        self.min_temp_check_balance = UInt64(0)
        # Count of open votes
        self.total_active_votes = UInt64(0)
        # Vote weight multiplier
        self.price_value = UInt64(1)
        # 0=fixed, 1=USD-pegged
        self.price_is_usd = UInt64(0)

    @arc4.abimethod(create="require")
    def create(self, fry_asa_id: arc4.UInt64) -> None:
        """Initialize the contract with admin and FRY ASA ID."""
        self.admin = Account(ADMIN_ADDRESS).bytes
        self.fry_asa_id = fry_asa_id.native
        self.min_temp_check_balance = UInt64(0)
        self.total_active_votes = UInt64(0)
        self.price_value = UInt64(1)
        self.price_is_usd = UInt64(0)

    @arc4.abimethod
    def admin_propose_update(self, mbr_payment: gtxn.PaymentTransaction) -> None:
        """Propose a contract update. Must wait 48 hours before executing."""
        assert Txn.sender == Account(ADMIN_ADDRESS), "Only admin can propose updates"
        assert Global.group_size == UInt64(2), "Group size must be 2"
        assert mbr_payment.receiver == Global.current_application_address, "Payment must be to contract"
        assert mbr_payment.amount >= UInt64(UPDATE_PROPOSAL_BOX_MBR), "Insufficient MBR"
        
        # Check no existing proposal
        _length, exists = op.Box.length(UPDATE_PROPOSAL_BOX_KEY)
        assert not exists, "Update already proposed"
        
        # Create proposal box with current timestamp
        op.Box.create(UPDATE_PROPOSAL_BOX_KEY, UInt64(8))
        op.Box.put(UPDATE_PROPOSAL_BOX_KEY, op.itob(Global.latest_timestamp))
        log(b"update_proposed")

    @arc4.baremethod(allow_actions=["UpdateApplication"])
    def admin_update(self) -> None:
        """Execute a proposed contract update after 48-hour timelock."""
        assert Txn.sender == Account(ADMIN_ADDRESS), "Only admin can update"
        
        # Read proposal box
        proposal_data, exists = op.Box.get(UPDATE_PROPOSAL_BOX_KEY)
        assert exists, "No update proposed"
        
        # Check 48-hour timelock
        proposed_at = op.btoi(proposal_data)
        assert Global.latest_timestamp >= proposed_at + UPDATE_TIMELOCK_SECONDS, "48-hour timelock not elapsed"
        
        # Delete proposal box (cleanup)
        op.Box.delete(UPDATE_PROPOSAL_BOX_KEY)
        log(b"update_executed")

    @arc4.abimethod
    def admin_cancel_update(self) -> None:
        """Cancel a pending update proposal."""
        assert Txn.sender == Account(ADMIN_ADDRESS), "Only admin can cancel"
        _length, exists = op.Box.length(UPDATE_PROPOSAL_BOX_KEY)
        assert exists, "No update pending"
        op.Box.delete(UPDATE_PROPOSAL_BOX_KEY)
        log(b"update_cancelled")

    @arc4.abimethod
    def opt_in_fry(self) -> None:
        """Opt contract into FRY ASA (admin only)."""
        assert Txn.sender == Account(ADMIN_ADDRESS), "Only admin can opt in"

        itxn.AssetTransfer(
            xfer_asset=self.fry_asa_id,
            asset_receiver=Global.current_application_address,
            asset_amount=0,
            fee=0,
        ).submit()

    @arc4.abimethod
    def admin_set_min_balance(self, min_balance: arc4.UInt64) -> None:
        """Set minimum FRY balance for temp check voting (admin only)."""
        assert Txn.sender == Account(ADMIN_ADDRESS), "Only admin can set min balance"
        self.min_temp_check_balance = min_balance.native

    @arc4.abimethod
    def admin_set_price(
        self, price_value: arc4.UInt64, price_is_usd: arc4.UInt8
    ) -> None:
        """Update price value and USD flag (admin only)."""
        assert Txn.sender == Account(ADMIN_ADDRESS), "Only admin can set price"
        self.price_value = price_value.native
        self.price_is_usd = price_is_usd.native

    @arc4.abimethod
    def create_vote(
        self,
        vote_id: arc4.StaticArray[arc4.Byte, Literal[32]],
        options_count: arc4.UInt8,
        end_date: arc4.UInt64,
        lock_duration: arc4.UInt64,
        super_majority: arc4.UInt8,
        vote_type: arc4.UInt8,
        mbr_payment: gtxn.PaymentTransaction,
    ) -> None:
        """
        Create a new vote (admin only).

        Atomic group: [Payment, AppCall]
        """
        # Auth check
        assert Txn.sender == Account(ADMIN_ADDRESS), "Only admin can create vote"

        # Atomic group validation
        assert Global.group_size == UInt64(2), "Group size must be 2"
        assert (
            mbr_payment.receiver == Global.current_application_address
        ), "Payment must be to contract"
        assert mbr_payment.amount >= UInt64(VOTE_BOX_MBR), "Insufficient MBR payment"

        # Parameter validation
        assert end_date.native > Global.latest_timestamp, "End date must be in future"
        assert options_count.native >= MIN_OPTIONS, "Too few options"
        assert options_count.native <= MAX_OPTIONS, "Too many options"

        # Build vote box key
        vote_box_key = VOTE_BOX_PREFIX + vote_id.bytes

        # Check vote doesn't already exist
        assert not box_exists(vote_box_key), "Vote already exists"

        # Create vote box
        op.Box.create(vote_box_key, UInt64(VOTE_BOX_SIZE))

        # Initialize vote record
        zero_totals = arc4.StaticArray[arc4.UInt64, Literal[8]](
            arc4.UInt64(0),
            arc4.UInt64(0),
            arc4.UInt64(0),
            arc4.UInt64(0),
            arc4.UInt64(0),
            arc4.UInt64(0),
            arc4.UInt64(0),
            arc4.UInt64(0),
        )

        vote_record = VoteRecord(
            vote_id=vote_id.copy(),
            options_count=options_count,
            end_date=end_date,
            lock_duration=lock_duration,
            super_majority=super_majority,
            vote_type=vote_type,
            closed=arc4.UInt8(0),
            created_by=arc4.StaticArray[arc4.Byte, Literal[32]].from_bytes(
                Txn.sender.bytes
            ),
            created_at=arc4.UInt64(Global.latest_timestamp),
            total_tokens=zero_totals.copy(),
            total_voters=zero_totals.copy(),
        )

        op.Box.put(vote_box_key, vote_record.bytes)
        self.total_active_votes += UInt64(1)

    @arc4.abimethod
    def cast_vote(
        self,
        vote_id: arc4.StaticArray[arc4.Byte, Literal[32]],
        option_index: arc4.UInt8,
        mbr_payment: gtxn.PaymentTransaction,
        asset_transfer: gtxn.AssetTransferTransaction,
    ) -> None:
        """
        Cast a vote with FRY token staking.

        Atomic group: [Payment, AssetTransfer, AppCall]
        """
        # Atomic group validation
        assert Global.group_size == UInt64(3), "Group size must be 3"

        # MBR payment validation
        assert (
            mbr_payment.receiver == Global.current_application_address
        ), "Payment must be to contract"
        assert mbr_payment.amount >= UInt64(STAKE_BOX_MBR), "Insufficient MBR payment"

        # Asset transfer validation
        assert (
            asset_transfer.asset_receiver == Global.current_application_address
        ), "Asset must be sent to contract"
        assert (
            asset_transfer.xfer_asset == Asset(self.fry_asa_id)
        ), "Must transfer FRY tokens"
        assert asset_transfer.sender == Txn.sender, "Asset sender must match caller"
        assert asset_transfer.asset_amount > UInt64(0), "Must stake some tokens"

        # Get vote record
        vote_box_key = VOTE_BOX_PREFIX + vote_id.bytes
        assert box_exists(vote_box_key), "Vote does not exist"

        vote_content, _exists = op.Box.get(vote_box_key)
        vote_record = VoteRecord.from_bytes(vote_content)

        # Vote status validation
        assert vote_record.closed.native == 0, "Vote is closed"
        assert (
            vote_record.end_date.native > Global.latest_timestamp
        ), "Vote has expired"
        assert (
            vote_record.vote_type.native != VOTE_TYPE_TEMP_CHECK
        ), "Cannot stake on temp check votes"
        assert (
            option_index.native < vote_record.options_count.native
        ), "Invalid option index"

        # Check user hasn't voted (stake box doesn't exist)
        # Use hash of vote_id + voter to fit 64-byte box name limit (1 + 32 = 33 bytes)
        stake_box_key = STAKE_BOX_PREFIX + op.sha256(vote_id.bytes + Txn.sender.bytes)
        assert not box_exists(stake_box_key), "Already voted"

        # Create stake box
        op.Box.create(stake_box_key, UInt64(STAKE_BOX_SIZE))

        stake_record = StakeRecord(
            voter=arc4.StaticArray[arc4.Byte, Literal[32]].from_bytes(
                Txn.sender.bytes
            ),
            vote_id=vote_id.copy(),
            option_index=option_index,
            token_amount=arc4.UInt64(asset_transfer.asset_amount),
            timestamp=arc4.UInt64(Global.latest_timestamp),
            withdrawn=arc4.UInt8(0),
        )

        op.Box.put(stake_box_key, stake_record.bytes)

        # Update vote totals with 128-bit safe math
        idx = option_index.native
        current_tokens = vote_record.total_tokens[idx].native
        current_voters = vote_record.total_voters[idx].native

        # Safe addition with overflow check
        new_tokens_high, new_tokens_low = op.addw(
            current_tokens, asset_transfer.asset_amount
        )
        assert new_tokens_high == UInt64(0), "Token overflow"

        new_voters_high, new_voters_low = op.addw(current_voters, UInt64(1))
        assert new_voters_high == UInt64(0), "Voter count overflow"

        # Update totals in vote record
        vote_record.total_tokens[idx] = arc4.UInt64(new_tokens_low)
        vote_record.total_voters[idx] = arc4.UInt64(new_voters_low)

        op.Box.put(vote_box_key, vote_record.bytes)

    @arc4.abimethod
    def cast_temp_vote(
        self,
        vote_id: arc4.StaticArray[arc4.Byte, Literal[32]],
        option_index: arc4.UInt8,
        mbr_payment: gtxn.PaymentTransaction,
    ) -> None:
        """
        Cast a temperature check vote (no token movement).
        One person = one vote. Requires minimum FRY balance.

        Atomic group: [Payment, AppCall]

        NOTE: The app call must include:
        - Foreign assets: [fry_asa_id]
        """
        # Atomic group validation
        assert Global.group_size == UInt64(2), "Group size must be 2"

        # MBR payment validation
        assert (
            mbr_payment.receiver == Global.current_application_address
        ), "Payment must be to contract"
        assert mbr_payment.amount >= UInt64(STAKE_BOX_MBR), "Insufficient MBR payment"

        # Get vote record
        vote_box_key = VOTE_BOX_PREFIX + vote_id.bytes
        assert box_exists(vote_box_key), "Vote does not exist"

        vote_content, _exists = op.Box.get(vote_box_key)
        vote_record = VoteRecord.from_bytes(vote_content)

        # Vote type validation
        assert (
            vote_record.vote_type.native == VOTE_TYPE_TEMP_CHECK
        ), "Not a temp check vote"
        assert vote_record.closed.native == 0, "Vote is closed"
        assert (
            vote_record.end_date.native > Global.latest_timestamp
        ), "Vote has expired"
        assert (
            option_index.native < vote_record.options_count.native
        ), "Invalid option index"

        # Check minimum balance is configured
        min_balance = self.min_temp_check_balance
        assert min_balance > UInt64(0), "Min balance not configured"

        # Check voter's FRY balance using native asset holding
        fry_balance, has_asset = op.AssetHoldingGet.asset_balance(
            Txn.sender, self.fry_asa_id
        )
        assert has_asset, "Not opted into FRY"
        assert fry_balance >= min_balance, "Insufficient FRY balance"

        # Check user hasn't voted
        # Use hash of vote_id + voter to fit 64-byte box name limit (1 + 32 = 33 bytes)
        stake_box_key = STAKE_BOX_PREFIX + op.sha256(vote_id.bytes + Txn.sender.bytes)
        assert not box_exists(stake_box_key), "Already voted"

        # Create stake box (token_amount=0, withdrawn=1 since no tokens to withdraw)
        op.Box.create(stake_box_key, UInt64(STAKE_BOX_SIZE))

        stake_record = StakeRecord(
            voter=arc4.StaticArray[arc4.Byte, Literal[32]].from_bytes(
                Txn.sender.bytes
            ),
            vote_id=vote_id.copy(),
            option_index=option_index,
            token_amount=arc4.UInt64(0),  # No tokens staked for temp check
            timestamp=arc4.UInt64(Global.latest_timestamp),
            withdrawn=arc4.UInt8(1),  # Mark as withdrawn since nothing to withdraw
        )

        op.Box.put(stake_box_key, stake_record.bytes)

        # Update vote totals (1 vote per person)
        idx = option_index.native
        current_tokens = vote_record.total_tokens[idx].native
        current_voters = vote_record.total_voters[idx].native

        # Safe addition with overflow check
        new_tokens_high, new_tokens_low = op.addw(current_tokens, UInt64(1))
        assert new_tokens_high == UInt64(0), "Token overflow"

        new_voters_high, new_voters_low = op.addw(current_voters, UInt64(1))
        assert new_voters_high == UInt64(0), "Voter count overflow"

        vote_record.total_tokens[idx] = arc4.UInt64(new_tokens_low)
        vote_record.total_voters[idx] = arc4.UInt64(new_voters_low)

        op.Box.put(vote_box_key, vote_record.bytes)

    @arc4.abimethod
    def request_temp_check(
        self,
        vote_id: arc4.StaticArray[arc4.Byte, Literal[32]],
        end_date: arc4.UInt64,
        mbr_payment: gtxn.PaymentTransaction,
    ) -> None:
        """
        Create a temperature check vote (any eligible user).

        Requirements:
        - Caller must have minimum FRY balance (same as voting)
        - Payment covers vote box MBR
        - End date must be in future and within 7-day max duration

        Atomic group: [Payment, AppCall]
        Foreign assets: [fry_asa_id]
        """
        # Atomic group validation
        assert Global.group_size == UInt64(2), "Group size must be 2"
        assert (
            mbr_payment.receiver == Global.current_application_address
        ), "Payment must be to contract"
        assert mbr_payment.amount >= UInt64(VOTE_BOX_MBR), "Insufficient MBR payment"

        # Check caller's FRY balance (same requirement as casting temp vote)
        min_balance = self.min_temp_check_balance
        assert min_balance > UInt64(0), "Min balance not configured"

        fry_balance, has_asset = op.AssetHoldingGet.asset_balance(
            Txn.sender, self.fry_asa_id
        )
        assert has_asset, "Not opted into FRY"
        assert fry_balance >= min_balance, "Insufficient FRY balance"

        # End date validation
        assert end_date.native > Global.latest_timestamp, "End date must be in future"

        # Enforce 7-day max duration
        max_end = Global.latest_timestamp + UInt64(MAX_TEMP_CHECK_DURATION)
        assert end_date.native <= max_end, "Duration exceeds 7-day maximum"

        # Build vote box key
        vote_box_key = VOTE_BOX_PREFIX + vote_id.bytes

        # Check vote doesn't already exist
        assert not box_exists(vote_box_key), "Vote already exists"

        # Create vote box
        op.Box.create(vote_box_key, UInt64(VOTE_BOX_SIZE))

        # Initialize vote record with temp check defaults
        zero_totals = arc4.StaticArray[arc4.UInt64, Literal[8]](
            arc4.UInt64(0),
            arc4.UInt64(0),
            arc4.UInt64(0),
            arc4.UInt64(0),
            arc4.UInt64(0),
            arc4.UInt64(0),
            arc4.UInt64(0),
            arc4.UInt64(0),
        )

        vote_record = VoteRecord(
            vote_id=vote_id.copy(),
            options_count=arc4.UInt8(2),  # Fixed: yes/no
            end_date=end_date,
            lock_duration=arc4.UInt64(0),  # No lock for temp checks
            super_majority=arc4.UInt8(0),  # Simple majority
            vote_type=arc4.UInt8(VOTE_TYPE_TEMP_CHECK),
            closed=arc4.UInt8(0),
            created_by=arc4.StaticArray[arc4.Byte, Literal[32]].from_bytes(
                Txn.sender.bytes
            ),
            created_at=arc4.UInt64(Global.latest_timestamp),
            total_tokens=zero_totals.copy(),
            total_voters=zero_totals.copy(),
        )

        op.Box.put(vote_box_key, vote_record.bytes)
        self.total_active_votes += UInt64(1)

    @arc4.abimethod
    def withdraw(
        self,
        vote_id: arc4.StaticArray[arc4.Byte, Literal[32]],
    ) -> None:
        """
        Withdraw staked FRY tokens after lock period expires.
        Self-service - caller must be the original voter.
        Deletes stake box and refunds MBR.
        """
        # Get stake record
        # Use hash of vote_id + voter to fit 64-byte box name limit (1 + 32 = 33 bytes)
        stake_box_key = STAKE_BOX_PREFIX + op.sha256(vote_id.bytes + Txn.sender.bytes)
        assert box_exists(stake_box_key), "Stake not found"

        stake_content, _exists = op.Box.get(stake_box_key)
        stake_record = StakeRecord.from_bytes(stake_content)

        # Verify caller is the voter
        assert (
            stake_record.voter.bytes == Txn.sender.bytes
        ), "Only voter can withdraw"

        # Get vote record for lock duration
        vote_box_key = VOTE_BOX_PREFIX + vote_id.bytes
        assert box_exists(vote_box_key), "Vote not found"

        vote_content, _exists = op.Box.get(vote_box_key)
        vote_record = VoteRecord.from_bytes(vote_content)

        # Check lock period has passed
        unlock_time = stake_record.timestamp.native + vote_record.lock_duration.native
        assert Global.latest_timestamp >= unlock_time, "Lock period not expired"

        # Extract token amount BEFORE deleting the box
        token_amount = stake_record.token_amount.native

        # Delete the stake box (replaces marking as withdrawn)
        op.Box.delete(stake_box_key)

        # Return FRY tokens if any
        if token_amount > UInt64(0):
            itxn.AssetTransfer(
                xfer_asset=self.fry_asa_id,
                asset_receiver=Txn.sender,
                asset_amount=token_amount,
                fee=0,
            ).submit()

        # Refund MBR to voter (always)
        itxn.Payment(
            receiver=Txn.sender,
            amount=UInt64(ACTUAL_STAKE_BOX_MBR),
            fee=0,
        ).submit()

    @arc4.abimethod
    def admin_close_vote(
        self,
        vote_id: arc4.StaticArray[arc4.Byte, Literal[32]],
    ) -> None:
        """Close a vote (admin only)."""
        assert Txn.sender == Account(ADMIN_ADDRESS), "Only admin can close vote"

        vote_box_key = VOTE_BOX_PREFIX + vote_id.bytes
        assert box_exists(vote_box_key), "Vote not found"

        vote_content, _exists = op.Box.get(vote_box_key)
        vote_record = VoteRecord.from_bytes(vote_content)
        assert vote_record.closed.native == 0, "Vote already closed"

        vote_record.closed = arc4.UInt8(1)
        op.Box.put(vote_box_key, vote_record.bytes)

        self.total_active_votes -= UInt64(1)

    @arc4.abimethod
    def admin_emergency_refund(
        self,
        vote_id: arc4.StaticArray[arc4.Byte, Literal[32]],
        voter: arc4.StaticArray[arc4.Byte, Literal[32]],
    ) -> None:
        """
        Emergency refund of staked tokens and MBR (admin only).
        Use case: Bug recovery, disputes.
        Deletes stake box.
        """
        assert Txn.sender == Account(ADMIN_ADDRESS), "Only admin can emergency refund"

        # Get stake record
        # Use hash of vote_id + voter to fit 64-byte box name limit
        stake_box_key = STAKE_BOX_PREFIX + op.sha256(vote_id.bytes + voter.bytes)
        assert box_exists(stake_box_key), "Stake not found"

        stake_content, _exists = op.Box.get(stake_box_key)
        stake_record = StakeRecord.from_bytes(stake_content)

        # Extract token amount BEFORE deleting the box
        token_amount = stake_record.token_amount.native

        # Delete the stake box
        op.Box.delete(stake_box_key)

        # Return FRY tokens if any
        if token_amount > UInt64(0):
            # Decode voter address from bytes
            voter_account = Account(voter.bytes)

            itxn.AssetTransfer(
                xfer_asset=self.fry_asa_id,
                asset_receiver=voter_account,
                asset_amount=token_amount,
                fee=0,
            ).submit()

        # Refund MBR to voter (not admin)
        voter_account = Account(voter.bytes)
        itxn.Payment(
            receiver=voter_account,
            amount=UInt64(ACTUAL_STAKE_BOX_MBR),
            fee=0,
        ).submit()

    @arc4.abimethod(readonly=True)
    def get_vote(
        self,
        vote_id: arc4.StaticArray[arc4.Byte, Literal[32]],
    ) -> VoteRecord:
        """Get vote record by ID."""
        vote_box_key = VOTE_BOX_PREFIX + vote_id.bytes
        assert box_exists(vote_box_key), "Vote not found"

        vote_content, _exists = op.Box.get(vote_box_key)
        return VoteRecord.from_bytes(vote_content)

    @arc4.abimethod(readonly=True)
    def get_stake(
        self,
        vote_id: arc4.StaticArray[arc4.Byte, Literal[32]],
        voter: arc4.StaticArray[arc4.Byte, Literal[32]],
    ) -> StakeRecord:
        """Get stake record for a voter on a specific vote."""
        # Use hash of vote_id + voter to fit 64-byte box name limit
        stake_box_key = STAKE_BOX_PREFIX + op.sha256(vote_id.bytes + voter.bytes)
        assert box_exists(stake_box_key), "Stake not found"

        stake_content, _exists = op.Box.get(stake_box_key)
        return StakeRecord.from_bytes(stake_content)
