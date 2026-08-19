"""Online metadata lookup — the identity layer the app cannot compute.

Nothing in this package imports Qt, and nothing in it touches the network
unless a caller asks it to: the provider takes an injectable ``urlopen``-shaped
callable, so the tests run entirely on canned JSON.

What is deliberately absent: BPM, musical key and energy. Those are local
analysis only — an online source is never consulted for them.
"""
