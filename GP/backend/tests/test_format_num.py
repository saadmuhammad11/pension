"""SAP's trailing minus is a debit, not a positive figure (audit 6 Oct 2026, G3).

A re-calculation report or pay slip prints a debit as "1,234.00-". num() stripped the sign and
read 1,234, so an overdrawn balance passed as a credit. The rupee sign-off "1,234/-" stays positive.
"""
from gpf.format import num
from gpf.sap import parse_sap_text


def test_trailing_minus_is_negative_and_the_rupee_sign_off_is_not():
    assert num("1,234.00-") == -1234
    assert num("5-") == -5
    assert num("1,234/-") == 1234
    assert num("1,234.50") == 1234.5
    assert num(" 12 000 ") == 12000
    assert num("") is None
    assert num("-") is None
    assert num("abc") is None
    assert num(None) is None
    assert num(True) is None
    assert num(7) == 7


def test_a_debit_balance_in_an_extract_reads_as_negative():
    text = ("SAP EXTRACT: PAY SLIP\n"
            "Personnel No: 90000227\n"
            "GPF Balance: 12,345.00-\n"
            "GPF Subscription: 2,000\n"
            "GPF Loan Balance: 0\n")
    parsed = parse_sap_text(text)
    assert parsed["payslip"]["gpfBalance"] == -12345, parsed
    assert parsed["payslip"]["gpfSubscription"] == 2000
    assert parsed["payslip"]["loanBalance"] == 0
