# FryGovernance Constants

# FRY Token ASA ID on Algorand mainnet
FRY_ASA_ID = 2485314946

# Admin address for privileged operations
# Mainnet admin wallet
ADMIN_ADDRESS = "E2F2LT2INE75DBOYHQXTCTOP2PAP5MHAXQRXTTCCXFKHQTVG36DJONBQZE"

# Box storage prefixes
# Note: Stake box key is constructed as hash(vote_id + voter) to fit 64-byte limit
VOTE_BOX_PREFIX = b"v"
STAKE_BOX_PREFIX = b"s"

# Default lock duration: 6 months in seconds
DEFAULT_LOCK_DURATION = 15_768_000

# Minimum balance requirements for box storage (microAlgos)
VOTE_BOX_MBR = 104_100  # ~0.1 ALGO for vote box (220 bytes)
STAKE_BOX_MBR = 61_700  # ~0.06 ALGO for stake box (82 bytes)

# Vote types
VOTE_TYPE_FIP = 0  # Founder Improvement Proposal
VOTE_TYPE_CFIP = 1  # Community Improvement Proposal
VOTE_TYPE_TEMP_CHECK = 2  # Temperature check (uses V2 stake balance)

# Box sizes
VOTE_BOX_SIZE = 220
STAKE_BOX_SIZE = 82

# Options range
MIN_OPTIONS = 2
MAX_OPTIONS = 8

# Maximum temp check duration: 7 days in seconds
MAX_TEMP_CHECK_DURATION = 604_800

# Fix 1: Timelock for admin_update (HIGH-4) - Box Storage
UPDATE_TIMELOCK_SECONDS = 172_800  # 48 hours
UPDATE_PROPOSAL_BOX_KEY = b"upd"
UPDATE_PROPOSAL_BOX_MBR = 6_900   # 2,500 + 400 * (3 key + 8 value)

# Fix 2: Box Deletion + MBR Refund in withdraw
ACTUAL_STAKE_BOX_MBR = 48_500     # 2,500 + 400 * (33 key + 82 value)
