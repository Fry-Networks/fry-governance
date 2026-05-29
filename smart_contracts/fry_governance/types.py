# FryGovernance Type Definitions
# ARC4 Struct definitions for box storage

from typing import Literal

from algopy import arc4


class VoteRecord(arc4.Struct):
    """
    Vote box storage structure (220 bytes total)
    Box key: "v_" + vote_id (32 bytes)
    """
    # Unique identifier for this vote (32 bytes, offset 0)
    vote_id: arc4.StaticArray[arc4.Byte, Literal[32]]
    # Number of voting options (1 byte, offset 32)
    options_count: arc4.UInt8
    # Unix timestamp when voting ends (8 bytes, offset 33)
    end_date: arc4.UInt64
    # Duration in seconds tokens are locked after voting (8 bytes, offset 41)
    lock_duration: arc4.UInt64
    # Whether super majority (>66%) is required (1 byte, offset 49)
    super_majority: arc4.UInt8
    # Vote type: 0=FIP, 1=cFIP, 2=temp_check (1 byte, offset 50)
    vote_type: arc4.UInt8
    # Whether vote is closed (1 byte, offset 51)
    closed: arc4.UInt8
    # Creator address (32 bytes, offset 52)
    created_by: arc4.StaticArray[arc4.Byte, Literal[32]]
    # Creation timestamp (8 bytes, offset 84)
    created_at: arc4.UInt64
    # Total tokens per option (8 options * 8 bytes = 64 bytes, offset 92)
    total_tokens: arc4.StaticArray[arc4.UInt64, Literal[8]]
    # Total voters per option (8 options * 8 bytes = 64 bytes, offset 156)
    total_voters: arc4.StaticArray[arc4.UInt64, Literal[8]]


class StakeRecord(arc4.Struct):
    """
    Stake box storage structure (82 bytes total)
    Box key: "s_" + vote_id (32 bytes) + voter (32 bytes)
    """
    # Voter address (32 bytes, offset 0)
    voter: arc4.StaticArray[arc4.Byte, Literal[32]]
    # Vote ID this stake is for (32 bytes, offset 32)
    vote_id: arc4.StaticArray[arc4.Byte, Literal[32]]
    # Which option was voted for (1 byte, offset 64)
    option_index: arc4.UInt8
    # Amount of FRY tokens staked (8 bytes, offset 65)
    token_amount: arc4.UInt64
    # Timestamp when vote was cast (8 bytes, offset 73)
    timestamp: arc4.UInt64
    # Whether tokens have been withdrawn (1 byte, offset 81)
    withdrawn: arc4.UInt8
