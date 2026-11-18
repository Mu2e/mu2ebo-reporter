from mu2ebo_reporter.check import check, model_text

FACTS = {"board": {"rows": [{"config": "bpzq01R26_00", "values": {"sob": 1.41513, "flash_edep": 7.58519e-06}}]},
         "kb": "S/sqrt(B) 4.15 vs 3.26, rad. damage 1.10\u00d710\u22126"}


def test_supported_numbers_pass():
    r = check("Best **bpzq01R26_00**: sob = 1.41513, flash_edep = 7.58519e-6 (7.585 \u00d7 10\u207b\u2076).", FACTS)
    assert r["ok"], r


def test_invented_number_flagged():
    r = check("f_1 has a correlation of \u22120.89 with sob.", FACTS)
    assert [u["value"] for u in r["unsupported"]] == ["-0.89"]


def test_table_header_scale():
    report = "| config | flash_edep (\u00d710\u207b\u2076) |\n|---|---|\n| bpzq01R26_00 | 7.585 |\n"
    assert check(report, FACTS)["ok"]


def test_docdb_lines_reported_separately():
    r = check("DocDB 58092 quotes 4.15 vs 3.26 and 9.99.", FACTS)
    assert r["ok"] and [u["value"] for u in r["docdb_lines"]] == ["9.99"]


def test_small_integers_and_ids_ignored():
    assert check("1. Summary\n2. Setup with rOut_0 on 2026-10-15 in /exp/x/y2.tsv", FACTS)["ok"]


def test_spaced_exponent_and_log_axis():
    r = check("| bpzq01R26_00 | 7.58519 e\u201106 (\u2011log10 = 5.120) |", FACTS)
    assert r["ok"], r


def test_narrow_nbsp_before_exponent():
    assert check("flash_edep = 7.58519\u202fe\u201106", FACTS)["ok"]


DERIV = {"counts": {"scored": 10, "total": 22}, "sob": [1.41513, 1.31]}


def test_derived_ratio_and_percent_change_accepted():
    r = check("10 of 22 children scored (10 / 22 \u2248 45 %).\nsob 1.415 vs 1.31 (~7.4 % lower).", DERIV)
    assert r["ok"], r
    assert [(d["value"], d["from"]) for d in r["derived"]] == [("45", "100 * 10 / 22"),
                                                               ("7.4", "100 * (1.31 - 1.415) / 1.415")]


def test_invented_number_next_to_inputs_rejected():
    r = check("sob 1.41513 vs 1.31, a 45 % gain and correlation 0.37.\n10 / 22 \u2248 45 configs.", DERIV)
    assert [u["value"] for u in r["unsupported"]] == ["45", "0.37", "45"] and not r["derived"]


def test_derived_needs_inputs_on_same_line():
    assert not check("10 of 22 children scored.\nThat is 45 %.", DERIV)["ok"]


def test_model_text_drops_program_provenance():
    body = "Best: sob 1.41513."
    report = body + "\n\n## Provenance\n\n- Data root: `/x` (snapshot time unknown)\n- Model: `gpt-oss:120b`; ..."
    assert model_text(report) == body and check(model_text(report), FACTS)["ok"] and not check(report, FACTS)["ok"]
