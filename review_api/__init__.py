"""Review Agent HTTP/API layer (W5, Track B).

This package is the FastAPI/read half of the W5 Review Agent. It depends only on
the committed W4 snapshots and the shared ``ReviewStore`` contract; it needs no
database driver or credentials. Track A supplies a Postgres-backed
implementation of the same contract for the Friday convergence.
"""
