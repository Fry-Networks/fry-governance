# FryGovernance Rescue Program
# Minimal recovery program deployed via admin_update to recover assets from orphan contracts
#
# Usage:
# 1. Use admin_update to deploy this program
# 2. Call delete_box() for each orphan box
# 3. Call recover_asset() for each ASA holding
# 4. Call delete_app() to close ALGO and delete application

from algopy import (
    Account,
    ARC4Contract,
    Asset,
    Global,
    Txn,
    arc4,
    itxn,
    log,
    op,
)

ADMIN_ADDRESS = "E2F2LT2INE75DBOYHQXTCTOP2PAP5MHAXQRXTTCCXFKHQTVG36DJONBQZE"


class RescueProgram(ARC4Contract):
    """Minimal rescue program for orphan contract recovery.
    
    Handles:
    - Deletion of orphan boxes to release MBR
    - Recovery of trapped ASA holdings
    - Closure of application
    """

    @arc4.abimethod
    def recover_asset(self, asset: Asset) -> None:
        """Close out an ASA holding to admin."""
        assert Txn.sender == Account(ADMIN_ADDRESS), "Only admin"
        itxn.AssetTransfer(
            xfer_asset=asset,
            asset_receiver=Account(ADMIN_ADDRESS),
            asset_close_to=Account(ADMIN_ADDRESS),
            asset_amount=0,
            fee=0,
        ).submit()
        log(b"asset_recovered")

    @arc4.abimethod
    def delete_box(self, key: arc4.Bytes) -> None:
        """Delete a box to release MBR."""
        assert Txn.sender == Account(ADMIN_ADDRESS), "Only admin"
        op.Box.delete(key.native)
        log(b"box_deleted")

    @arc4.baremethod(allow_actions=["DeleteApplication"])
    def delete_app(self) -> None:
        """Delete the application and close remaining ALGO to admin.
        Call LAST after all assets are recovered and boxes deleted."""
        assert Txn.sender == Account(ADMIN_ADDRESS), "Only admin"
        itxn.Payment(
            receiver=Account(ADMIN_ADDRESS),
            close_remainder_to=Account(ADMIN_ADDRESS),
            amount=0,
            fee=0,
        ).submit()
        log(b"app_deleted")
