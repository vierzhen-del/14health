from health14 import recommend


def test_classify_blood_pressure():
    assert recommend.classify("수축기혈압", 115)["status"] == "정상"
    assert recommend.classify("수축기혈압", 132)["status"] == "주의"
    assert recommend.classify("수축기혈압", 150)["status"] == "위험"


def test_classify_bmi_low_and_high():
    assert recommend.classify("BMI", 17.0)["label"] == "저체중"
    assert recommend.classify("BMI", 22.0)["status"] == "정상"
    assert recommend.classify("BMI", 26.5)["status"] == "위험"


def test_classify_higher_is_better():
    assert recommend.classify("HDL", 35)["status"] == "주의"
    assert recommend.classify("HDL", 55)["status"] == "정상"


def test_classify_waist_by_sex():
    assert recommend.classify("허리둘레", 88, sex="M")["status"] == "정상"
    assert recommend.classify("허리둘레", 88, sex="F")["status"] == "주의"


def test_recommended_checkups_by_age():
    recs = {r["name"] for r in recommend.recommended_checkups(45, "M")}
    assert "위내시경(위암검진)" in recs
    assert "대장내시경" not in recs  # 50세부터
    recs50 = {r["name"] for r in recommend.recommended_checkups(52, "M")}
    assert "대장내시경" in recs50


def test_recommended_checkups_female():
    recs = {r["name"] for r in recommend.recommended_checkups(42, "F")}
    assert "유방촬영(유방암검진)" in recs
    assert "자궁경부세포검사" in recs


def test_family_history_lowers_start_age():
    base = {r["name"] for r in recommend.recommended_checkups(36, "M")}
    assert "위내시경(위암검진)" not in base
    boosted = recommend.recommended_checkups(36, "M", family_diseases=["위암"])
    gastro = [r for r in boosted if r["name"] == "위내시경(위암검진)"]
    assert gastro and gastro[0]["family_history"] and gastro[0]["interval_years"] == 1


def test_quarterly_plan_vaccine_in_q4():
    recs = recommend.recommended_checkups(48, "M")
    quarters = recommend.quarterly_plan(recs)
    assert any("독감" in i for i in quarters["Q4"])


def test_lifecycle_stage():
    assert recommend.stage_of(3)["stage"] == "영유아기"
    assert recommend.stage_of(48)["stage"] == "중장년기"
    assert recommend.stage_of(80)["stage"] == "노년기"
