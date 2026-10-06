"""The evaluation harness. Build specification §17.

    Build before the pipeline, as in revision 1.

Everything here runs on the standard library, with no GPU, no network and no clock, because
that is what the decision layer is: a pure function from facts to results. Run it with

    python3 -m unittest discover -s GP/gpfund/tests -t GP
"""
