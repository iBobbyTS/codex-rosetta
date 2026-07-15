"""Emit the hidden facts used by the summary-quality fixture."""

import hashlib

print("project=Orchid")
print("stage=2 completed")
print("ledger_policy=do not modify ledger.csv")
print("timezone=UTC only")
print("endpoint=/v2/checkpoint")
print("predeploy_check=verify_delta")
print("reference_code=A7-KAPPA")
print(
    "FILLER:"
    + "".join(
        hashlib.sha256(f"fixture-{index}".encode()).hexdigest() for index in range(2000)
    )
)
