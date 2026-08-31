"""The directory feature: the broker list, and harvesting loan officers off it.

router.py   HTTP in and out          schemas.py  what the API accepts
db.py       companies + loan_officers, and the officer upsert
runner.py   the batch: per company -> jobs.retry_loop -> harvest -> upsert
seed.py     one-off import of the brokers CSV

Built on the jobs feature, never the other way round: a company's scrape is an
ordinary job, so recon, generation, the sandbox and the repair loop are reused
whole rather than reimplemented here.
"""
