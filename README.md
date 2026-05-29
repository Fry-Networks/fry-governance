# FryGovernance

On-chain governance system for Fry Networks built on Algorand.

## Features

- Create governance votes with multiple options
- Cast votes with FRY token staking
- Temporary check votes using FryStaking V2 balance
- Admin functions for vote management
- 128-bit overflow protection
- Atomic transaction group validation

## Development

```bash
poetry install
poetry run pytest tests/ -v
```

## Compile to TEAL

```bash
poetry run python -m algopy compile smart_contracts/fry_governance/contract.py --out-dir artifacts/
```
