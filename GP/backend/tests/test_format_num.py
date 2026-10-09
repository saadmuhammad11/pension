"""SAP's trailing minus is a debit, not a positive figure (audit 6 Oct 2026, G3).

A re-calculation report or pay slip prints a debit as "1,234.00-". num() stripped the sign and
read 1,234, so an overdrawn balance passed as a credit. The rupee sign-off "1,234/-" stays positive.
"""
from gpf.format import amount, num
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


def test_the_sign_belongs_to_balances_only_and_a_double_sign_is_no_figure():
    """Review C1 (9 Oct 2026): "GPF Subscription 1,150.00-" in the deductions is Rs 1,150 deducted,
    not a negative subscription; "50,000-" where OCR lost the slash is Rs 50,000; "-1,234-" is nothing."""
    assert amount("1,150.00-") == 1150
    assert amount("50,000-") == 50000
    assert amount("-2,000") == 2000
    assert amount("") is None and amount(None) is None
    assert num("-1,234-") is None
    assert num("--5") is None
    assert num("-5") == -5
    text = ("SAP EXTRACT: PAY SLIP\n"
            "GPF Balance: 12,345.00-\n"
            "GPF Subscription: 1,150.00-\n"
            "GPF Loan Instalment: 2,000-\n"
            "GPF Loan Balance: 0\n"
            "SAP EXTRACT: RE-CALCULATION\n"
            "Start|End|Opening|Subscription|Adjustments|Temp Advance|Rec Temp Adv|Perm Adv|Interest|Closing\n"
            "01.07.2024|30.06.2025|100,000.00|1,150.00-|500.00-|50,000-|4,000.00-|0|1,200|147,850.00-\n")
    parsed = parse_sap_text(text)
    ps, row = parsed["payslip"], parsed["recalc"]["rows"][0]
    assert (ps["gpfBalance"], ps["gpfSubscription"], ps["loanInstalment"], ps["loanBalance"]) == (-12345, 1150, 2000, 0)
    assert (row["opening"], row["subscription"], row["adjustments"], row["tempAdvance"], row["recTempAdvance"], row["closing"]) \
        == (100000, 1150, -500, 50000, 4000, -147850)
