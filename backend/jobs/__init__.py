"""The jobs feature: a scrape request's whole life.

router.py   HTTP in and out          schemas.py  what the API accepts/returns
db.py       jobs + script_attempts   retry_loop.py  replay -> recon -> generate
                                     -> execute -> repair, capped at 3
"""
